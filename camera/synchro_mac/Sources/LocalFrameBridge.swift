import Darwin
import Foundation

/// Localhost handoff for a JPEG the viewer has already received.
/// This process does not open a radio and does not speak the camera command protocol.
enum LocalBridge {
    static let port: UInt16 = 8765
    static let maxAge: TimeInterval = 4
    static let wait: TimeInterval = 2.5
}

struct PublishedFrame: Equatable {
    var jpeg: Data
    var width: Int
    var height: Int
    var capturedAt: TimeInterval
}

struct BridgeSnapshot: Equatable {
    var live = false
    var frame: PublishedFrame?
}

enum BridgeBody: Equatable {
    case json(status: Int, text: String)
    case jpeg(Data)
}

func localBridgeDecision(
    method: String,
    path: String,
    now: TimeInterval,
    snapshot: BridgeSnapshot,
    maxAge: TimeInterval
) -> BridgeBody {
    let target = path.split(separator: "?", maxSplits: 1).first.map(String.init) ?? "/"
    guard method.uppercased() == "GET" else {
        return .json(status: 405, text: #"{"error":"method_not_allowed"}"#)
    }
    switch target {
    case "/status":
        return .json(status: 200, text: bridgeStatusJSON(now: now, snapshot: snapshot))
    case "/frame.jpg":
        guard snapshot.live, let frame = snapshot.frame else {
            return .json(
                status: 503,
                text: #"{"error":"camera_unavailable","message":"The native viewer has no live JPEG from its existing Bluetooth session."}"#
            )
        }
        if now - frame.capturedAt > maxAge {
            return .json(
                status: 503,
                text: #"{"error":"stale_frame","message":"The latest JPEG from the existing Bluetooth session is too old."}"#
            )
        }
        return .jpeg(frame.jpeg)
    default:
        return .json(status: 404, text: #"{"error":"not_found"}"#)
    }
}

func bridgeStatusJSON(now: TimeInterval, snapshot: BridgeSnapshot) -> String {
    let hasFrame = snapshot.live && snapshot.frame != nil
    let age: String
    if let frame = snapshot.frame, snapshot.live {
        age = String(Int(max(0, (now - frame.capturedAt) * 1000)))
    } else {
        age = "null"
    }
    let width = hasFrame ? (snapshot.frame?.width ?? 0) : 0
    let height = hasFrame ? (snapshot.frame?.height ?? 0) : 0
    return """
    {"service":"synchro-camera-bridge","available":true,"connected":\(snapshot.live),"has_frame":\(hasFrame),"age_ms":\(age),"width":\(width),"height":\(height),"transport":"bluetooth-classic-rfcomm","simulated":false}
    """
}

func encodeBridgeHTTP(_ body: BridgeBody) -> Data {
    switch body {
    case .json(let status, let text):
        return bridgeHTTP(status: status, type: "application/json; charset=utf-8", payload: Data(text.utf8))
    case .jpeg(let data):
        return bridgeHTTP(status: 200, type: "image/jpeg", payload: data)
    }
}

func bridgeHTTP(status: Int, type: String, payload: Data) -> Data {
    let reason: String
    switch status {
    case 200: reason = "OK"
    case 404: reason = "Not Found"
    case 405: reason = "Method Not Allowed"
    case 503: reason = "Service Unavailable"
    default: reason = "Error"
    }
    let header = "HTTP/1.1 \(status) \(reason)\r\nContent-Type: \(type)\r\nContent-Length: \(payload.count)\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n"
    var out = Data(header.utf8)
    out.append(payload)
    return out
}

final class FramePublisher {
    private let condition = NSCondition()
    private var snapshot = BridgeSnapshot()

    func setLive(_ live: Bool) {
        condition.lock()
        snapshot.live = live
        if !live {
            snapshot.frame = nil
        }
        condition.broadcast()
        condition.unlock()
    }

    func publish(jpeg: Data, width: Int, height: Int, at time: TimeInterval) {
        condition.lock()
        defer {
            condition.broadcast()
            condition.unlock()
        }
        guard snapshot.live else { return }
        snapshot.frame = PublishedFrame(jpeg: jpeg, width: width, height: height, capturedAt: time)
    }

    func current() -> BridgeSnapshot {
        condition.lock()
        defer { condition.unlock() }
        return snapshot
    }

    func waitForFreshFrame(maxAge: TimeInterval, timeout: TimeInterval) -> (snapshot: BridgeSnapshot, now: TimeInterval) {
        condition.lock()
        let deadline = Date().addingTimeInterval(max(0, timeout))
        while true {
            let now = Date.timeIntervalSinceReferenceDate
            if let frame = snapshot.frame, snapshot.live, now - frame.capturedAt <= maxAge {
                let copy = snapshot
                condition.unlock()
                return (copy, now)
            }
            if !snapshot.live || !condition.wait(until: deadline) {
                let copy = snapshot
                let ended = Date.timeIntervalSinceReferenceDate
                condition.unlock()
                return (copy, ended)
            }
        }
    }
}

final class LocalFrameServer {
    let publisher = FramePublisher()
    var maxAge = LocalBridge.maxAge
    var wait = LocalBridge.wait
    private(set) var port: UInt16 = 0
    private var listenFD: Int32 = -1
    private var exited: DispatchSemaphore?

    func setLive(_ live: Bool) {
        publisher.setLive(live)
    }

    func publish(jpeg: Data, width: Int, height: Int, at time: TimeInterval) {
        publisher.publish(jpeg: jpeg, width: width, height: height, at: time)
    }

    func start(port requested: UInt16) -> String? {
        stop()
        let fd = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        if fd < 0 {
            return "Could not open the local camera bridge socket."
        }
        var reuse: Int32 = 1
        _ = Darwin.setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = requested.bigEndian
        let converted = withUnsafeMutablePointer(to: &addr.sin_addr) { pointer in
            inet_pton(AF_INET, "127.0.0.1", pointer)
        }
        if converted != 1 {
            Darwin.close(fd)
            return "Could not bind the local camera bridge to localhost."
        }
        let bound = withUnsafePointer(to: &addr) { pointer -> Int32 in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { raw in
                Darwin.bind(fd, raw, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        if bound != 0 || Darwin.listen(fd, 8) != 0 {
            Darwin.close(fd)
            return "Could not listen on 127.0.0.1:\(requested) for the local camera bridge."
        }
        var actual = sockaddr_in()
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let named = withUnsafeMutablePointer(to: &actual) { pointer -> Int32 in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { raw in
                Darwin.getsockname(fd, raw, &length)
            }
        }
        if named != 0 {
            Darwin.close(fd)
            return "Could not read the local camera bridge port."
        }
        listenFD = fd
        port = UInt16(bigEndian: actual.sin_port)
        let done = DispatchSemaphore(value: 0)
        exited = done
        let thread = Thread { [weak self] in
            self?.acceptLoop(fd: fd)
            done.signal()
        }
        thread.name = "org.synchro.camera.bridge"
        thread.start()
        return nil
    }

    func stop() {
        let fd = listenFD
        listenFD = -1
        if fd >= 0 {
            Darwin.close(fd)
        }
        if let exited {
            _ = exited.wait(timeout: .now() + 2)
            self.exited = nil
        }
    }

    private func acceptLoop(fd: Int32) {
        while listenFD == fd {
            var clientAddr = sockaddr_in()
            var length = socklen_t(MemoryLayout<sockaddr_in>.size)
            let client = withUnsafeMutablePointer(to: &clientAddr) { pointer -> Int32 in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { raw in
                    Darwin.accept(fd, raw, &length)
                }
            }
            if listenFD != fd {
                if client >= 0 { Darwin.close(client) }
                return
            }
            if client < 0 {
                return
            }
            if !isLoopback(clientAddr) {
                Darwin.close(client)
                continue
            }
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                self?.handle(client)
            }
        }
    }

    private func handle(_ client: Int32) {
        defer { Darwin.close(client) }
        var noSignal: Int32 = 1
        _ = Darwin.setsockopt(client, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size))
        var timeout = timeval(tv_sec: 2, tv_usec: 0)
        _ = Darwin.setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        var buffer = [UInt8](repeating: 0, count: 2048)
        let count = Darwin.recv(client, &buffer, buffer.count, 0)
        if count <= 0 { return }
        let text = String(decoding: Data(buffer.prefix(count)), as: UTF8.self)
        let first = text.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        let parts = first.split(separator: " ")
        let method = parts.first.map(String.init) ?? ""
        let path = parts.dropFirst().first.map(String.init) ?? "/"
        let body = response(method: method, path: path)
        let payload = encodeBridgeHTTP(body)
        payload.withUnsafeBytes { raw in
            guard let base = raw.baseAddress else { return }
            _ = Darwin.send(client, base, payload.count, 0)
        }
    }

    private func response(method: String, path: String) -> BridgeBody {
        let target = path.split(separator: "?", maxSplits: 1).first.map(String.init) ?? "/"
        if target == "/frame.jpg" && method.uppercased() == "GET" {
            let waited = publisher.waitForFreshFrame(maxAge: maxAge, timeout: wait)
            return localBridgeDecision(
                method: method,
                path: path,
                now: waited.now,
                snapshot: waited.snapshot,
                maxAge: maxAge
            )
        }
        return localBridgeDecision(
            method: method,
            path: path,
            now: Date.timeIntervalSinceReferenceDate,
            snapshot: publisher.current(),
            maxAge: maxAge
        )
    }

    private func isLoopback(_ addr: sockaddr_in) -> Bool {
        var loopback = in_addr()
        guard withUnsafeMutablePointer(to: &loopback, { inet_pton(AF_INET, "127.0.0.1", $0) }) == 1 else {
            return false
        }
        let copy = addr
        return copy.sin_addr.s_addr == loopback.s_addr
    }
}

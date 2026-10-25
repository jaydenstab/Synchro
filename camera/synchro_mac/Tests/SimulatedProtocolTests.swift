import CoreGraphics
import Darwin
import Foundation
import ImageIO

// SIMULATED protocol tests. Every byte in this file is synthetic.
// Nothing here is an ESP32-CAM measurement.

var checks = 0
var failures: [String] = []

func check(_ condition: Bool, _ message: String, file: StaticString = #fileID, line: UInt = #line) {
    checks += 1
    if !condition {
        failures.append("\(file):\(line) \(message)")
    }
}

func checkClose(_ actual: Double, _ expected: Double, _ message: String, file: StaticString = #fileID, line: UInt = #line) {
    check(abs(actual - expected) < 0.000_001, "\(message) actual=\(actual) expected=\(expected)", file: file, line: line)
}

func markerJPEG(width: Int, height: Int, tag: UInt8) -> Data {
    var data = Data([0xFF, 0xD8, 0xFF, 0xFE, 0x00, 0x03, tag])
    data.append(contentsOf: [0xFF, 0xC0, 0x00, 0x0B, 0x08])
    data.append(UInt8((height >> 8) & 0xFF))
    data.append(UInt8(height & 0xFF))
    data.append(UInt8((width >> 8) & 0xFF))
    data.append(UInt8(width & 0xFF))
    data.append(contentsOf: [0x01, 0x01, 0x11, 0x00, 0xFF, 0xD9])
    return data
}

func statusPacket(firmware: String = "bluetooth-2", ready: Bool = true) -> Data {
    Data("{\"firmware\":\"\(firmware)\",\"camera_ready\":\(ready ? "true" : "false")}\n".utf8)
}

func framePacket(jpeg: Data, width: Int, height: Int, trailer: String = "\nJPEG_END\n") -> Data {
    var data = Data("JPEG_BEGIN \(jpeg.count) \(width) \(height)\n".utf8)
    data.append(jpeg)
    data.append(Data(trailer.utf8))
    return data
}

func feed(_ assembler: inout FrameAssembler, _ data: Data, chunkSize: Int) -> [AssemblerEvent] {
    var events: [AssemblerEvent] = []
    var index = data.startIndex
    while index < data.endIndex {
        let end = data.index(index, offsetBy: chunkSize, limitedBy: data.endIndex) ?? data.endIndex
        events.append(contentsOf: assembler.append(Data(data[index..<end])))
        index = end
    }
    return events
}

func testJPEGHeaders() {
    let jpeg = markerJPEG(width: 320, height: 240, tag: 7)
    check(inspectJpeg(jpeg, declaredWidth: 320, declaredHeight: 240) == .accepted, "marker JPEG should pass SOF check")
    check(inspectJpeg(jpeg, declaredWidth: 640, declaredHeight: 480) == .rejected("JPEG dimensions do not match JPEG_BEGIN."), "SOF mismatch")
    var missingSOI = jpeg
    missingSOI[0] = 0x00
    check(inspectJpeg(missingSOI, declaredWidth: 320, declaredHeight: 240) == .rejected("JPEG missing SOI."), "missing SOI")
    var missingEOI = jpeg
    missingEOI.removeLast(2)
    missingEOI.append(contentsOf: [0x00, 0x00])
    check(inspectJpeg(missingEOI, declaredWidth: 320, declaredHeight: 240) == .rejected("JPEG missing EOI."), "missing EOI")
    let truncated = Data([0xFF, 0xD8, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0xFF, 0xD9])
    if case .rejected(let reason) = inspectJpeg(truncated, declaredWidth: 320, declaredHeight: 240) {
        check(reason == "Invalid JPEG marker length.", "truncated marker reason \(reason)")
    } else {
        check(false, "truncated marker should be rejected")
    }
    check(SynchroImage.decode(Data([0x00, 0x01, 0x02, 0x03])) == nil, "corrupt bytes are not a JPEG")
    check(SynchroImage.decode(jpeg) == nil, "header-only JPEG is not a displayable image")
}

func testImageIORoundTrip() {
    let width = 320
    let height = 240
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: width * 4,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        check(false, "could not allocate a synthetic bitmap")
        return
    }
    context.setFillColor(CGColor(red: 0.1, green: 0.2, blue: 0.3, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    guard let painted = context.makeImage() else {
        check(false, "could not paint a synthetic bitmap")
        return
    }
    let storage = NSMutableData()
    guard let destination = CGImageDestinationCreateWithData(storage, "public.jpeg" as CFString, 1, nil) else {
        check(false, "could not create a synthetic JPEG destination")
        return
    }
    CGImageDestinationAddImage(destination, painted, [kCGImageDestinationLossyCompressionQuality: 0.4] as CFDictionary)
    check(CGImageDestinationFinalize(destination), "synthetic JPEG finalize")
    let jpeg = storage as Data
    check(inspectJpeg(jpeg, declaredWidth: width, declaredHeight: height) == .accepted, "ImageIO JPEG failed SOF inspection prefix=\(jpeg.prefix(8).map { String(format: "%02X", $0) }.joined())")
    guard let decoded = SynchroImage.decode(jpeg) else {
        check(false, "ImageIO JPEG did not decode")
        return
    }
    check(decoded.width == width && decoded.height == height, "decoded synthetic JPEG size")
}

func testFragmentedSession() {
    var assembler = FrameAssembler()
    let first = markerJPEG(width: 320, height: 240, tag: 1)
    let second = markerJPEG(width: 640, height: 480, tag: 2)
    var blob = statusPacket()
    blob.append(framePacket(jpeg: first, width: 320, height: 240))
    blob.append(framePacket(jpeg: second, width: 640, height: 480))
    let partial = feed(&assembler, blob.prefix(5), chunkSize: 1)
    check(partial.isEmpty, "incomplete header must not emit a frame")
    let events = feed(&assembler, blob.suffix(from: 5), chunkSize: 3)
    check(events.count == 3, "status plus two frames, got \(events.count)")
    check(events.first == .statusReady(firmware: "bluetooth-2"), "firmware status")
    if case .frameReady(let jpeg, let width, let height) = events.dropFirst().first {
        check(jpeg == first && width == 320 && height == 240, "first frame order")
    } else {
        check(false, "missing first frame")
    }
    if case .frameReady(let jpeg, let width, let height) = events.last {
        check(jpeg == second && width == 640 && height == 480, "second frame order")
    } else {
        check(false, "missing second frame")
    }
    check(assembler.waitingForStatus == false, "status consumed")
}

func testInvalidLengthsAndCorruptPayload() {
    var assembler = FrameAssembler()
    check(feed(&assembler, statusPacket(), chunkSize: 4) == [.statusReady(firmware: "bluetooth-2")], "ready status")
    let badLengths = [
        "JPEG_BEGIN 3 640 480\n",
        "JPEG_BEGIN 1000001 640 480\n",
        "JPEG_BEGIN 100 800 600\n",
        "JPEG_BEGIN 100 640 480 extra\n",
        "JPEG_BEGIN no 640 480\n"
    ]
    for line in badLengths {
        var one = FrameAssembler()
        _ = one.append(statusPacket())
        let events = one.append(Data(line.utf8))
        check(events == [.fatal("Unexpected camera response. Press Start to reconnect.")], "invalid begin \(line)")
        check(one.waitingForStatus, "fatal begin resets the assembler")
    }
    var stream = FrameAssembler()
    _ = stream.append(statusPacket())
    let garbage = Data(repeating: 0x11, count: 32)
    let good = markerJPEG(width: 320, height: 240, tag: 9)
    var mixed = framePacket(jpeg: garbage, width: 320, height: 240)
    mixed.append(framePacket(jpeg: good, width: 320, height: 240))
    let events = feed(&stream, mixed, chunkSize: 7)
    check(events.count == 2, "corrupt payload then a good frame, got \(events)")
    if case .rejected = events[0] {
        check(true, "corrupt payload rejected")
    } else {
        check(false, "corrupt payload should be rejected")
    }
    if case .frameReady(let jpeg, _, _) = events[1] {
        check(jpeg == good, "good frame survived the rejected one")
    } else {
        check(false, "good frame missing after rejection")
    }
    check(stream.waitingForStatus == false, "rejection keeps the session")
}

func testBadTrailerAndOversizedBuffer() {
    var assembler = FrameAssembler()
    _ = assembler.append(statusPacket())
    let jpeg = markerJPEG(width: 320, height: 240, tag: 4)
    let events = assembler.append(framePacket(jpeg: jpeg, width: 320, height: 240, trailer: "\nNOPE_END\n"))
    check(events == [.fatal("Invalid camera image. Press Start to reconnect.")], "bad trailer")
    check(assembler.readableBytes == 0, "fatal trailer drops the buffer")

    var huge = FrameAssembler()
    _ = huge.append(statusPacket())
    _ = huge.append(Data("JPEG_BEGIN 1000000 640 480\n".utf8))
    let overflow = huge.append(Data(repeating: 0xAB, count: SynchroLimits.maxBufferedBytes + 1))
    check(overflow == [.fatal("Camera response exceeded the allowed size.")], "oversized buffer got \(overflow)")
    check(huge.readableBytes == 0, "overflow resets the buffer")
}

func testStatusRejectionAndHeaderLimits() {
    var wrongFirmware = FrameAssembler()
    let firmwareEvents = wrongFirmware.append(statusPacket(firmware: "bluetooth-9"))
    check(firmwareEvents == [.fatal("Camera firmware is not ready.")], "unknown firmware")
    var notReady = FrameAssembler()
    check(notReady.append(statusPacket(ready: false)) == [.fatal("Camera firmware is not ready.")], "camera_ready false")
    var blank = FrameAssembler()
    let padding = Data(repeating: 0x41, count: SynchroLimits.maxHeaderBytes + 1)
    check(blank.append(padding) == [.fatal("Invalid camera response header.")], "header without newline")
}

func testBufferCursor() {
    var buffer = SynchroByteBuffer()
    for index in 0..<30 {
        buffer.append(Data(repeating: UInt8(index & 0xFF), count: 20_000))
        buffer.dropFirst(19_990)
    }
    check(buffer.count == 300, "readable tail count")
    check(buffer.allocatedCount < 80_000, "cursor compacted the prefix, allocated=\(buffer.allocatedCount)")
    buffer.dropFirst(300)
    check(buffer.count == 0 && buffer.allocatedCount == 0, "full drop clears storage")
    buffer.append(Data([0x0A, 0x01]))
    check(buffer.firstIndex(of: 10) == 0, "newline at the cursor")
}

func testTimingStatistics() {
    var tracker = PerformanceTracker()
    tracker.recordFrame(at: 0, jpegBytes: 20_480, width: 640, height: 480, latency: 0.1, decodeSeconds: 0.002)
    tracker.recordFrame(at: 1, jpegBytes: 20_480, width: 640, height: 480, latency: 0.2, decodeSeconds: 0.004)
    tracker.recordFrame(at: 2, jpegBytes: 10_240, width: 320, height: 240, latency: 0.4, decodeSeconds: 0.006)
    checkClose(tracker.lastInstantFPS, 1, "instant FPS")
    checkClose(tracker.averageFPS, 1, "average FPS inside the 3s window")
    checkClose(tracker.averageLatency, (0.1 + 0.2 + 0.4) / 3, "average latency")
    checkClose(tracker.maxLatency, 0.4, "session max latency")
    check(tracker.lastJPEGBytes == 10_240 && tracker.lastWidth == 320 && tracker.lastHeight == 240, "last frame metadata")
    tracker.recordFrame(at: 10, jpegBytes: 1000, width: 320, height: 240, latency: 0.05, decodeSeconds: 0.001)
    checkClose(tracker.lastInstantFPS, 1.0 / 8.0, "instant FPS across a gap")
    checkClose(tracker.averageFPS, 0, "average FPS drops samples outside the window")
    checkClose(tracker.averageLatency, 0.05, "latency window follows the FPS window")
    checkClose(tracker.maxLatency, 0.4, "session max survives the rolling window")
    tracker.recordRejection()
    tracker.recordTimeout()
    tracker.recordConnectionError()
    check(tracker.rejectedFrames == 1 && tracker.timeoutErrors == 1 && tracker.connectionErrors == 1, "error counters")
    let text = dashboardText(tracker)
    check(text.contains("Current FPS"), "dashboard current FPS")
    check(text.contains("Rejected / invalid frames"), "dashboard rejects")
    check(text.contains("Timeout errors"), "dashboard timeouts")
    check(text.contains("Connection errors"), "dashboard connection errors")
    check(text.contains("640") == false && text.contains("320 × 240"), "dashboard shows the latest resolution")
    tracker.maxSamples = 2
    tracker.reset()
    check(tracker.receivedFrames == 0 && tracker.maxLatency == 0 && tracker.samples.isEmpty, "reset clears the session")
    check(tracker.maxSamples == 2, "reset keeps the sample cap")
    tracker.recordFrame(at: 1, jpegBytes: 10, width: 320, height: 240, latency: 0.1, decodeSeconds: 0)
    tracker.recordFrame(at: 2, jpegBytes: 10, width: 320, height: 240, latency: 0.1, decodeSeconds: 0)
    tracker.recordFrame(at: 3, jpegBytes: 10, width: 320, height: 240, latency: 0.1, decodeSeconds: 0)
    check(tracker.samples.map(\.sequence) == [2, 3], "sample log drops the oldest row")
    check(legacyLiveStatus(averageFPS: 12.34, width: 640, height: 480, frames: 8) == "Bluetooth live · 12.3 fps · 640 × 480 · 8 frames", "legacy status line")
}

func testPacingWatchdogAndCSV() {
    checkClose(nextCaptureDelay(now: 10, requestSentAt: 10), 1.0 / 15.0, "15 Hz pace from a fresh CAPTURE")
    checkClose(nextCaptureDelay(now: 10.1, requestSentAt: 10), 0, "late frame requests the next CAPTURE immediately")
    check(shouldFireWatchdog(running: true, deadline: 5, now: 5.1), "watchdog after the deadline")
    check(!shouldFireWatchdog(running: true, deadline: 0, now: 100), "cleared deadline does not time out")
    check(!shouldFireWatchdog(running: false, deadline: 5, now: 9), "stopped viewer does not time out")
    check(disconnectDisposition(running: true, callbackMatchesOpenChannel: true) == .unexpectedClose, "unexpected disconnect")
    check(disconnectDisposition(running: false, callbackMatchesOpenChannel: true) == .ignore, "close after Stop")
    check(disconnectDisposition(running: true, callbackMatchesOpenChannel: false) == .ignore, "stale channel callback")

    var tracker = PerformanceTracker()
    tracker.recordFrame(at: 100, jpegBytes: 4096, width: 320, height: 240, latency: 0.1, decodeSeconds: 0.003)
    let simulated = renderPerformanceCSV(samples: tracker.samples, origin: .simulated)
    check(simulated.contains("# origin: simulated"), "CSV marks simulated origin")
    check(simulated.contains("# simulated: true"), "CSV simulated flag")
    check(simulated.contains("not the image sensor exposure time"), "CSV distinguishes exposure time")
    check(simulated.contains("request_to_frame_ms"), "CSV latency column")
    check(simulated.contains(",320,240,4096,100.000,"), "CSV frame row \(simulated)")
    let live = renderPerformanceCSV(samples: [], origin: .macViewer)
    check(live.contains("# origin: mac-viewer"), "viewer CSV origin")
    check(live.contains("# simulated: false"), "viewer CSV is not marked simulated")
    check(live.contains("not the image sensor exposure time"), "viewer CSV keeps the exposure warning")
}

func testLocalBridgeServesOnlyAnExistingFrame() {
    let jpeg = Data([0xFF, 0xD8, 0xFF, 0xD9])
    let publisher = FramePublisher()
    publisher.publish(jpeg: jpeg, width: 640, height: 480, at: 10)
    let ignored = publisher.current()
    check(ignored.frame == nil, "a frame is not published before the viewer session is live")

    let offline = localBridgeDecision(
        method: "GET",
        path: "/frame.jpg",
        now: 10,
        snapshot: BridgeSnapshot(live: false, frame: nil),
        maxAge: 4
    )
    guard case .json(let offlineStatus, let offlineText) = offline else {
        check(false, "offline bridge returns JSON")
        return
    }
    check(offlineStatus == 503, "offline bridge refuses a frame")
    check(offlineText.contains("camera_unavailable"), "offline bridge names the missing session")

    let staleFrame = PublishedFrame(jpeg: jpeg, width: 320, height: 240, capturedAt: 1)
    let stale = localBridgeDecision(
        method: "GET",
        path: "/frame.jpg",
        now: 10,
        snapshot: BridgeSnapshot(live: true, frame: staleFrame),
        maxAge: 4
    )
    guard case .json(let staleStatus, let staleText) = stale else {
        check(false, "stale bridge returns JSON")
        return
    }
    check(staleStatus == 503 && staleText.contains("stale_frame"), "an old JPEG is not served as fresh")

    let fresh = localBridgeDecision(
        method: "GET",
        path: "/frame.jpg",
        now: 10,
        snapshot: BridgeSnapshot(live: true, frame: PublishedFrame(jpeg: jpeg, width: 640, height: 480, capturedAt: 9)),
        maxAge: 4
    )
    guard case .jpeg(let served) = fresh else {
        check(false, "fresh bridge returns the JPEG")
        return
    }
    check(served == jpeg, "fresh bridge returns the viewer JPEG unchanged")

    let status = localBridgeDecision(
        method: "GET",
        path: "/status",
        now: 10,
        snapshot: BridgeSnapshot(live: true, frame: PublishedFrame(jpeg: jpeg, width: 640, height: 480, capturedAt: 9.5)),
        maxAge: 4
    )
    guard case .json(let statusCode, let statusText) = status else {
        check(false, "status is JSON")
        return
    }
    check(statusCode == 200, "status is OK")
    check(statusText.contains("\"service\":\"synchro-camera-bridge\""), "status identifies this bridge")
    check(statusText.contains("\"simulated\":false"), "bridge status is not marked simulated")
    check(!statusText.contains("FFD8"), "status JSON does not include image bytes")

    let rejected = localBridgeDecision(method: "POST", path: "/frame.jpg", now: 10, snapshot: BridgeSnapshot(), maxAge: 4)
    guard case .json(let rejectedStatus, _) = rejected else {
        check(false, "post is rejected")
        return
    }
    check(rejectedStatus == 405, "bridge accepts only GET")

    let bridgeURL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("Sources/LocalFrameBridge.swift")
    let bridgeSource = (try? String(contentsOf: bridgeURL, encoding: .utf8)) ?? ""
    check(bridgeSource.contains("127.0.0.1"), "bridge binds to localhost")
    check(!bridgeSource.contains("openRFCOMM"), "bridge source does not open a radio channel")
    check(!bridgeSource.contains("IOBluetooth"), "bridge source does not import Bluetooth")

    let server = LocalFrameServer()
    server.maxAge = 4
    server.wait = 0.2
    let started = server.start(port: 0)
    check(started == nil, started ?? "bridge socket started")
    check(server.port > 0, "bridge chose a port")
    let down = readBridgeSoon(port: server.port, path: "/frame.jpg")
    check(down?.0 == 503, "socket refuses a frame before the session is live")
    server.publisher.setLive(true)
    server.publisher.publish(jpeg: jpeg, width: 640, height: 480, at: Date.timeIntervalSinceReferenceDate)
    let up = readBridgeSoon(port: server.port, path: "/frame.jpg")
    check(up?.0 == 200, "socket returns the published JPEG")
    check(up?.1 == jpeg, "socket body is the JPEG and nothing else")
    let listed = readBridgeSoon(port: server.port, path: "/status")
    check(listed?.0 == 200, "socket status responds")
    let listedText = String(decoding: listed?.1 ?? Data(), as: UTF8.self)
    check(listedText.contains("\"simulated\":false"), "socket status is a real-viewer contract, simulated test data aside")
    server.stop()
}

func readBridgeSoon(port: UInt16, path: String) -> (Int, Data)? {
    for _ in 0..<20 {
        if let response = readBridge(port: port, path: path) {
            return response
        }
        Thread.sleep(forTimeInterval: 0.02)
    }
    return nil
}

func readBridge(port: UInt16, path: String) -> (Int, Data)? {
    let fd = Darwin.socket(AF_INET, SOCK_STREAM, 0)
    if fd < 0 { return nil }
    var addr = sockaddr_in()
    addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = port.bigEndian
    let converted = withUnsafeMutablePointer(to: &addr.sin_addr) { inet_pton(AF_INET, "127.0.0.1", $0) }
    if converted != 1 {
        Darwin.close(fd)
        return nil
    }
    let connected = withUnsafePointer(to: &addr) { pointer -> Int32 in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { raw in
            Darwin.connect(fd, raw, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    if connected != 0 {
        Darwin.close(fd)
        return nil
    }
    let request = "GET \(path) HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    _ = request.withCString { Darwin.send(fd, $0, strlen($0), 0) }
    var collected = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while true {
        let count = Darwin.recv(fd, &buffer, buffer.count, 0)
        if count <= 0 { break }
        collected.append(contentsOf: buffer.prefix(count))
    }
    Darwin.close(fd)
    guard let headerEnd = collected.range(of: Data("\r\n\r\n".utf8)) else { return nil }
    let header = String(decoding: collected[..<headerEnd.lowerBound], as: UTF8.self)
    let status = Int(header.split(separator: " ").dropFirst().first ?? "0") ?? 0
    return (status, Data(collected[headerEnd.upperBound...]))
}

func testCommandsStayWithinProtocol() {
    let sourceURL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("SynchroCamera.swift")
    let source = (try? String(contentsOf: sourceURL, encoding: .utf8)) ?? ""
    check(source.contains("send(\"STATUS\\n\""), "viewer still sends STATUS")
    check(source.contains("send(\"CAPTURE\\n\""), "viewer still sends CAPTURE")
    check(!source.contains("AUTOFOCUS"), "no autofocus command")
    check(!source.contains("SET_RESOLUTION"), "no invented resolution command")
    check(source.contains("JPEG_BEGIN") == false, "viewer does not fabricate JPEG_BEGIN")
}

@main
struct SimulatedTestRunner {
    static func main() {
        print("SIMULATED Synchro camera protocol tests")
        print("These tests use synthetic RFCOMM bytes. They are not ESP32-CAM measurements.")
        testJPEGHeaders()
        testImageIORoundTrip()
        testFragmentedSession()
        testInvalidLengthsAndCorruptPayload()
        testBadTrailerAndOversizedBuffer()
        testStatusRejectionAndHeaderLimits()
        testBufferCursor()
        testTimingStatistics()
        testPacingWatchdogAndCSV()
        testLocalBridgeServesOnlyAnExistingFrame()
        testCommandsStayWithinProtocol()

        if failures.isEmpty {
            print("passed: \(checks)")
            print("failed: 0")
        } else {
            for failure in failures {
                print(failure)
            }
            print("passed: \(checks - failures.count)")
            print("failed: \(failures.count)")
            exit(1)
        }
    }
}

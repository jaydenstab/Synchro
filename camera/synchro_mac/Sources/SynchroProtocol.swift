import Foundation

/// Limits copied from the original Mac viewer so framing stays compatible
/// with the existing Synchro-Cam firmware.
enum SynchroLimits {
    static let maxBufferedBytes = 1_001_024
    static let maxHeaderBytes = 512
    static let minJpegBytes = 4
    static let maxJpegBytes = 1_000_000
    static let trailer = Data("\nJPEG_END\n".utf8)
    static let readyFirmware: Set<String> = ["bluetooth-1", "bluetooth-2"]
}

enum AssemblerEvent: Equatable {
    case statusReady(firmware: String)
    case frameReady(jpeg: Data, width: Int, height: Int)
    case rejected(String)
    case fatal(String)
}

enum DisconnectDisposition: Equatable {
    /// Close happened after Stop, or the callback is for an older channel.
    case ignore
    /// The open channel dropped while the viewer still expected frames.
    case unexpectedClose
}

func disconnectDisposition(running: Bool, callbackMatchesOpenChannel: Bool) -> DisconnectDisposition {
    if running && callbackMatchesOpenChannel { return .unexpectedClose }
    return .ignore
}

func isAllowedCameraResolution(width: Int, height: Int) -> Bool {
    (width == 640 && height == 480) || (width == 320 && height == 240)
}

enum JpegCheck: Equatable {
    case accepted
    case rejected(String)
}

/// Checks SOI, a SOF0/SOF1/SOF2 size that matches `JPEG_BEGIN`, and a trailing EOI.
/// This does not decode pixels. ImageIO does that later, off the main thread.
func inspectJpeg(_ data: Data, declaredWidth: Int, declaredHeight: Int) -> JpegCheck {
    guard data.count >= 4 else { return .rejected("JPEG too small.") }
    guard data[0] == 0xFF, data[1] == 0xD8 else { return .rejected("JPEG missing SOI.") }
    guard data[data.count - 2] == 0xFF, data[data.count - 1] == 0xD9 else {
        return .rejected("JPEG missing EOI.")
    }

    var index = 2
    while index < data.count {
        guard data[index] == 0xFF else { return .rejected("JPEG marker misaligned.") }
        index += 1
        while index < data.count && data[index] == 0xFF { index += 1 }
        guard index < data.count else { break }
        let marker = data[index]
        index += 1
        if marker == 0xD9 { break }
        if marker == 0x01 || (marker >= 0xD0 && marker <= 0xD7) { continue }
        guard index + 1 < data.count else { return .rejected("Truncated JPEG marker.") }
        let length = (Int(data[index]) << 8) | Int(data[index + 1])
        guard length >= 2, index + length <= data.count else {
            return .rejected("Invalid JPEG marker length.")
        }
        if marker == 0xC0 || marker == 0xC1 || marker == 0xC2 {
            guard length >= 7 else { return .rejected("Truncated SOF marker.") }
            let height = (Int(data[index + 3]) << 8) | Int(data[index + 4])
            let width = (Int(data[index + 5]) << 8) | Int(data[index + 6])
            guard width == declaredWidth, height == declaredHeight else {
                return .rejected("JPEG dimensions do not match JPEG_BEGIN.")
            }
            return .accepted
        }
        if marker == 0xDA {
            return .rejected("JPEG missing SOF dimensions.")
        }
        index += length
    }
    return .rejected("JPEG missing SOF dimensions.")
}

enum StatusParse: Equatable {
    case ready(String)
    case notReady
}

func parseStatusLine(_ line: Data) -> StatusParse {
    let trimmed = trimASCII(line)
    guard !trimmed.isEmpty,
          let object = try? JSONSerialization.jsonObject(with: trimmed) as? [String: Any] else {
        return .notReady
    }
    let firmware = object["firmware"] as? String ?? ""
    guard SynchroLimits.readyFirmware.contains(firmware), object["camera_ready"] as? Bool == true else {
        return .notReady
    }
    return .ready(firmware)
}

enum JPEGBeginParse: Equatable {
    case ready(length: Int, width: Int, height: Int)
    case invalid
}

func parseJPEGBegin(_ line: Data) -> JPEGBeginParse {
    let words = String(decoding: trimASCII(line), as: UTF8.self)
        .split(separator: " ")
        .map(String.init)
    guard words.count == 4,
          words[0] == "JPEG_BEGIN",
          let length = Int(words[1]),
          let width = Int(words[2]),
          let height = Int(words[3]),
          (SynchroLimits.minJpegBytes...SynchroLimits.maxJpegBytes).contains(length),
          isAllowedCameraResolution(width: width, height: height) else {
        return .invalid
    }
    return .ready(length: length, width: width, height: height)
}

/// Reassembles RFCOMM fragments into status lines and one JPEG at a time.
struct FrameAssembler {
    private var buffer = SynchroByteBuffer()
    var waitingForStatus = true
    private var pending: (length: Int, width: Int, height: Int)?

    var readableBytes: Int { buffer.count }
    var allocatedBytes: Int { buffer.allocatedCount }

    mutating func reset() {
        buffer.reset()
        waitingForStatus = true
        pending = nil
    }

    mutating func append(_ chunk: Data) -> [AssemblerEvent] {
        buffer.append(chunk)
        if buffer.count > SynchroLimits.maxBufferedBytes {
            reset()
            return [.fatal("Camera response exceeded the allowed size.")]
        }

        var events: [AssemblerEvent] = []
        while true {
            if let spec = pending {
                let need = spec.length + SynchroLimits.trailer.count
                guard buffer.count >= need else { return events }
                let jpeg = buffer.copyPrefix(spec.length)
                let trailerOK = buffer.matches(SynchroLimits.trailer, at: spec.length)
                buffer.dropFirst(need)
                pending = nil
                if !trailerOK {
                    events.append(.fatal("Invalid camera image. Press Start to reconnect."))
                    reset()
                    return events
                }
                switch inspectJpeg(jpeg, declaredWidth: spec.width, declaredHeight: spec.height) {
                case .accepted:
                    events.append(.frameReady(jpeg: jpeg, width: spec.width, height: spec.height))
                case .rejected(let reason):
                    events.append(.rejected(reason))
                }
                continue
            }

            guard let newline = buffer.firstIndex(of: 10) else {
                if buffer.count > SynchroLimits.maxHeaderBytes {
                    reset()
                    events.append(.fatal("Invalid camera response header."))
                }
                return events
            }
            if newline > SynchroLimits.maxHeaderBytes {
                reset()
                events.append(.fatal("Oversized camera response header."))
                return events
            }
            let line = buffer.copyPrefix(newline)
            buffer.dropFirst(newline + 1)
            if waitingForStatus {
                switch parseStatusLine(line) {
                case .ready(let firmware):
                    waitingForStatus = false
                    events.append(.statusReady(firmware: firmware))
                case .notReady:
                    events.append(.fatal("Camera firmware is not ready."))
                    reset()
                    return events
                }
            } else {
                switch parseJPEGBegin(line) {
                case .ready(let length, let width, let height):
                    pending = (length, width, height)
                case .invalid:
                    events.append(.fatal("Unexpected camera response. Press Start to reconnect."))
                    reset()
                    return events
                }
            }
        }
    }
}

private func trimASCII(_ data: Data) -> Data {
    let ignored: Set<UInt8> = [0x20, 0x09, 0x0D, 0x0A]
    var bytes = [UInt8](data)
    while let first = bytes.first, ignored.contains(first) { bytes.removeFirst() }
    while let last = bytes.last, ignored.contains(last) { bytes.removeLast() }
    return Data(bytes)
}

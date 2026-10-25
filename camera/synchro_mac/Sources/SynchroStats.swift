import Foundation

enum SynchroTiming {
    /// Same rolling window the original viewer used for its single FPS number.
    static let fpsWindow: TimeInterval = 3
    /// The existing firmware path is one CAPTURE at a time, at most 15 per second.
    static let maxRequestRate = 15.0
    static let connectTimeout: TimeInterval = 20
    static let responseTimeout: TimeInterval = 8
    static let watchdogInterval: TimeInterval = 0.5
    static let latencyExplanation = "Request-to-frame is the time from sending CAPTURE until JPEG_END is validated. It includes firmware capture, JPEG compression, and Bluetooth transfer. It is not the image sensor exposure time. Mac JPEG decode is local and is timed separately."
}

enum MeasurementOrigin: String {
    case simulated
    case macViewer = "mac-viewer"
}

struct PerformanceSample: Equatable {
    var sequence: Int
    var completedAt: TimeInterval
    var jpegBytes: Int
    var width: Int
    var height: Int
    var latency: TimeInterval
    var instantaneousFPS: Double
    var averageFPS: Double
    var averageLatency: TimeInterval
    var maxLatency: TimeInterval
    var decodeSeconds: TimeInterval
    var receivedFrames: Int
    var rejectedFrames: Int
    var timeoutErrors: Int
    var connectionErrors: Int
}

struct PerformanceTracker {
    var window: TimeInterval = SynchroTiming.fpsWindow
    var maxSamples = 20_000
    private(set) var receivedFrames = 0
    private(set) var rejectedFrames = 0
    private(set) var timeoutErrors = 0
    private(set) var connectionErrors = 0
    private(set) var lastJPEGBytes = 0
    private(set) var lastWidth = 0
    private(set) var lastHeight = 0
    private(set) var lastLatency = 0.0
    private(set) var maxLatency = 0.0
    private(set) var lastInstantFPS = 0.0
    private(set) var lastDecode = 0.0
    private(set) var decodeTotal = 0.0
    private(set) var decodeCount = 0
    private(set) var frameTimes: [TimeInterval] = []
    private(set) var latencies: [TimeInterval] = []
    private(set) var samples: [PerformanceSample] = []

    var averageFPS: Double {
        guard let first = frameTimes.first, let last = frameTimes.last, last > first else { return 0 }
        return Double(frameTimes.count - 1) / (last - first)
    }

    var averageLatency: Double {
        guard !latencies.isEmpty else { return 0 }
        return latencies.reduce(0, +) / Double(latencies.count)
    }

    var averageDecode: Double {
        guard decodeCount > 0 else { return 0 }
        return decodeTotal / Double(decodeCount)
    }

    mutating func reset() {
        let keptWindow = window
        let keptMax = maxSamples
        self = PerformanceTracker()
        window = keptWindow
        maxSamples = keptMax
    }

    mutating func recordRejection() { rejectedFrames += 1 }
    mutating func recordTimeout() { timeoutErrors += 1 }
    mutating func recordConnectionError() { connectionErrors += 1 }

    mutating func recordFrame(at time: TimeInterval, jpegBytes: Int, width: Int, height: Int, latency: TimeInterval, decodeSeconds: TimeInterval) {
        receivedFrames += 1
        lastJPEGBytes = jpegBytes
        lastWidth = width
        lastHeight = height
        lastLatency = latency
        if latency > maxLatency { maxLatency = latency }
        lastDecode = decodeSeconds
        decodeTotal += decodeSeconds
        decodeCount += 1
        frameTimes.append(time)
        latencies.append(latency)
        if frameTimes.count >= 2 {
            let delta = frameTimes[frameTimes.count - 1] - frameTimes[frameTimes.count - 2]
            lastInstantFPS = delta > 0 ? 1.0 / delta : 0
        } else {
            lastInstantFPS = 0
        }
        let cutoff = time - window
        while frameTimes.count > 1, let first = frameTimes.first, first < cutoff {
            frameTimes.removeFirst()
            latencies.removeFirst()
        }
        samples.append(PerformanceSample(
            sequence: receivedFrames,
            completedAt: time,
            jpegBytes: jpegBytes,
            width: width,
            height: height,
            latency: latency,
            instantaneousFPS: lastInstantFPS,
            averageFPS: averageFPS,
            averageLatency: averageLatency,
            maxLatency: maxLatency,
            decodeSeconds: decodeSeconds,
            receivedFrames: receivedFrames,
            rejectedFrames: rejectedFrames,
            timeoutErrors: timeoutErrors,
            connectionErrors: connectionErrors
        ))
        if samples.count > maxSamples {
            samples.removeFirst(samples.count - maxSamples)
        }
    }
}

func nextCaptureDelay(now: TimeInterval, requestSentAt: TimeInterval, maxHz: Double = SynchroTiming.maxRequestRate) -> TimeInterval {
    guard maxHz > 0, requestSentAt > 0 else { return 0 }
    return max(0, (1.0 / maxHz) - (now - requestSentAt))
}

func shouldFireWatchdog(running: Bool, deadline: TimeInterval, now: TimeInterval) -> Bool {
    running && deadline > 0 && now > deadline
}

func formatFixed(_ value: Double, digits: Int) -> String {
    String(format: "%.\(digits)f", locale: Locale(identifier: "en_US_POSIX"), arguments: [value])
}

func legacyLiveStatus(averageFPS: Double, width: Int, height: Int, frames: Int) -> String {
    "Bluetooth live · \(formatFixed(averageFPS, digits: 1)) fps · \(width) × \(height) · \(frames) frames"
}

func dashboardText(_ stats: PerformanceTracker) -> String {
    func row(_ name: String, _ value: String) -> String {
        name.padding(toLength: 28, withPad: " ", startingAt: 0) + value
    }
    let fps: (Double) -> String = { value in
        stats.receivedFrames >= 2 ? formatFixed(value, digits: 1) : "—"
    }
    let size: String = {
        guard stats.lastJPEGBytes > 0 else { return "—" }
        let kb = Double(stats.lastJPEGBytes) / 1024
        let digits = kb >= 10 ? 1 : 2
        return formatFixed(kb, digits: digits) + " KB"
    }()
    let resolution = stats.lastWidth > 0 ? "\(stats.lastWidth) × \(stats.lastHeight)" : "—"
    let latency: (Double, Bool) -> String = { value, known in
        known ? formatFixed(value * 1000, digits: 1) + " ms" : "—"
    }
    let known = stats.receivedFrames > 0
    return [
        row("Current FPS", fps(stats.lastInstantFPS)),
        row("Average FPS (\(Int(stats.window))s)", fps(stats.averageFPS)),
        row("JPEG size", size),
        row("Resolution", resolution),
        row("Request-to-frame", latency(stats.lastLatency, known)),
        row("Average request-to-frame", latency(stats.averageLatency, known)),
        row("Maximum request-to-frame", latency(stats.maxLatency, known)),
        row("Mac JPEG decode", latency(stats.lastDecode, known)),
        row("Average Mac decode", latency(stats.averageDecode, known)),
        row("Frames received", "\(stats.receivedFrames)"),
        row("Rejected / invalid frames", "\(stats.rejectedFrames)"),
        row("Timeout errors", "\(stats.timeoutErrors)"),
        row("Connection errors", "\(stats.connectionErrors)")
    ].joined(separator: "\n")
}

func renderPerformanceCSV(samples: [PerformanceSample], origin: MeasurementOrigin) -> String {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime]
    var lines = [
        "# origin: \(origin.rawValue)",
        "# simulated: \(origin == .simulated ? "true" : "false")",
        "# request_to_frame_ms is the time from sending CAPTURE until JPEG_END was validated.",
        "# That duration includes firmware capture, JPEG compression, and Bluetooth transfer.",
        "# It is not the image sensor exposure time. The Mac viewer cannot measure exposure by itself.",
        "# average_fps uses a \(Int(SynchroTiming.fpsWindow))s rolling window of completed frames.",
        "frame,completed_at_iso,width,height,jpeg_bytes,request_to_frame_ms,instant_fps,average_fps,average_request_to_frame_ms,max_request_to_frame_ms,mac_decode_ms,received_frames,rejected_frames,timeout_errors,connection_errors"
    ]
    for sample in samples {
        let stamp = formatter.string(from: Date(timeIntervalSinceReferenceDate: sample.completedAt))
        let fields = [
            String(sample.sequence),
            stamp,
            String(sample.width),
            String(sample.height),
            String(sample.jpegBytes),
            formatFixed(sample.latency * 1000, digits: 3),
            formatFixed(sample.instantaneousFPS, digits: 3),
            formatFixed(sample.averageFPS, digits: 3),
            formatFixed(sample.averageLatency * 1000, digits: 3),
            formatFixed(sample.maxLatency * 1000, digits: 3),
            formatFixed(sample.decodeSeconds * 1000, digits: 3),
            String(sample.receivedFrames),
            String(sample.rejectedFrames),
            String(sample.timeoutErrors),
            String(sample.connectionErrors)
        ]
        lines.append(fields.joined(separator: ","))
    }
    return lines.joined(separator: "\n") + "\n"
}

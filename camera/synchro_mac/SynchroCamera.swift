import AppKit
import CoreGraphics
import IOBluetooth
import IOKit
import QuartzCore
import UniformTypeIdentifiers

// Native macOS viewer for the existing Synchro-Cam Bluetooth Classic firmware.
// Framing and statistics live in Sources/ so they can be tested without a radio.
// JPEG decode runs off the main thread. Status text and the image view stay on main.
final class CameraApp: NSObject, NSApplicationDelegate, IOBluetoothRFCOMMChannelDelegate {
    let address = "70:4B:CA:46:52:22"
    let rfcommChannelID: BluetoothRFCOMMChannelID = 1
    var window: NSWindow!
    var surface: MonitorSurface!
    var shell: SynchroShell!
    var device: IOBluetoothDevice?
    var channel: IOBluetoothRFCOMMChannel?
    var assembler = FrameAssembler()
    var stats = PerformanceTracker()
    var lastJPEG: Data?
    var running = false
    var generation = 0
    var captureToken = 0
    var deadline: TimeInterval = 0
    var requestTime: TimeInterval = 0
    var watchdog: Timer?
    let decodeQueue = DispatchQueue(label: "org.synchro.camera.jpeg-decode", qos: .userInitiated)
    /// Serves the latest JPEG from this process. It does not open another radio session.
    let frameBridge = LocalFrameServer()
    var motionTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit Synchro", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)
        NSApp.mainMenu = menu

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1380, height: 920),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Synchro"
        window.minSize = NSSize(width: 1220, height: 820)
        window.appearance = NSAppearance(named: .darkAqua)
        window.isReleasedWhenClosed = false
        surface = MonitorSurface.make(address: address)
        shell = SynchroShell()
        shell.install(in: window.contentView!)
        shell.onPageChange = { [weak self] page in
            self?.surface.startButton.keyEquivalent = page == .camera ? "\r" : ""
        }
        surface.install(in: shell.cameraPage)
        surface.startButton.target = self
        surface.startButton.action = #selector(start)
        surface.stopButton.target = self
        surface.stopButton.action = #selector(stop)
        surface.rotateButton.target = self
        surface.rotateButton.action = #selector(rotationChanged)
        surface.saveButton.target = self
        surface.saveButton.action = #selector(saveJPEG)
        surface.exportButton.target = self
        surface.exportButton.action = #selector(exportCSV)
        surface.resetButton.target = self
        surface.resetButton.action = #selector(resetStatistics)
        surface.glove.calibrateButton.target = self
        surface.glove.calibrateButton.action = #selector(calibrateMotion)
        shell.startService()
        motionTimer = Timer.scheduledTimer(withTimeInterval: 0.3, repeats: true) { [weak self] _ in
            self?.pollMotion()
        }
        pollMotion()
        applyRotation()
        refreshDashboard(message: nil)
        if let screen = NSScreen.main ?? NSScreen.screens.first {
            let visible = screen.visibleFrame.insetBy(dx: 20, dy: 16)
            let frame = NSRect(
                x: visible.midX - min(1360, visible.width) / 2,
                y: visible.minY,
                width: min(1360, visible.width),
                height: min(visible.height, 980)
            )
            window.setFrame(frame, display: true)
        } else {
            window.center()
        }
        window.makeKeyAndOrderFront(nil)
        if #available(macOS 14.0, *) {
            NSApp.activate()
        } else {
            NSApp.activate(ignoringOtherApps: true)
        }
        if let problem = frameBridge.start(port: LocalBridge.port) {
            FileHandle.standardError.write(Data("Synchro camera bridge: \(problem)\n".utf8))
            surface.messageLabel.stringValue = problem
        }
        watchdog = Timer.scheduledTimer(withTimeInterval: SynchroTiming.watchdogInterval, repeats: true) { [weak self] _ in
            guard let self else { return }
            let now = Date.timeIntervalSinceReferenceDate
            guard shouldFireWatchdog(running: self.running, deadline: self.deadline, now: now) else { return }
            self.fail("Timed out. Check camera power, Bluetooth pairing, and that the Windows viewer is stopped. Press Start to retry.", kind: .timeout)
        }
    }

    func pollMotion() {
        guard let url = URL(string: "http://127.0.0.1:8000/api/motion") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, response, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                guard let data,
                      let http = response as? HTTPURLResponse, http.statusCode == 200,
                      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    self.surface.glove.showOffline("Backend offline")
                    return
                }
                self.surface.glove.apply(object)
            }
        }.resume()
    }

    @objc func calibrateMotion() {
        guard let url = URL(string: "http://127.0.0.1:8000/api/motion/calibrate") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        URLSession.shared.dataTask(with: request) { [weak self] data, response, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                guard let data, let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    self.surface.glove.noteLabel.stringValue = "Calibration did not start."
                    return
                }
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    self.surface.glove.apply(object)
                } else if let detail = object["detail"] as? String {
                    self.surface.glove.noteLabel.stringValue = detail
                }
            }
        }.resume()
    }

    @objc func start() {
        releaseLink(status: nil, link: .unchanged)
        generation += 1
        running = true
        frameBridge.setLive(true)
        requestTime = 0
        stats.reset()
        assembler.reset()
        lastJPEG = nil
        surface.setPreview(image: nil)
        surface.startButton.isEnabled = false
        surface.stopButton.isEnabled = true
        setLink("Connecting", color: .systemOrange)
        refreshDashboard(message: "Connecting over Bluetooth…")
        deadline = Date.timeIntervalSinceReferenceDate + SynchroTiming.connectTimeout
        device = IOBluetoothDevice(addressString: address)
        guard let device else {
            fail("Could not create the camera Bluetooth connection.", kind: .connection)
            return
        }
        var opened: IOBluetoothRFCOMMChannel?
        let result = device.openRFCOMMChannelAsync(&opened, withChannelID: rfcommChannelID, delegate: self)
        channel = opened
        if result != kIOReturnSuccess {
            fail("Bluetooth open failed (\(result)). Pair Synchro-Cam-BT in System Settings, then retry.", kind: .connection)
            return
        }
        if opened == nil {
            fail("Bluetooth channel was not created. Pair Synchro-Cam-BT in System Settings, then retry.", kind: .connection)
        }
    }

    @objc func stop() {
        releaseLink(status: "Stopped. Bluetooth released for another laptop.", link: .stopped)
    }

    func releaseLink(status: String?, link: LinkState) {
        frameBridge.setLive(false)
        running = false
        generation += 1
        captureToken += 1
        deadline = 0
        let previous = channel
        channel = nil
        previous?.setDelegate(nil)
        previous?.close()
        device = nil
        assembler.reset()
        surface.startButton.isEnabled = true
        surface.stopButton.isEnabled = false
        if let status {
            surface.messageLabel.stringValue = status
            surface.messageLabel.textColor = link == .error ? .systemRed : .labelColor
        }
        switch link {
        case .stopped:
            setLink("Stopped", color: .systemGray)
        case .error:
            setLink("Error", color: .systemRed)
        case .unchanged:
            break
        }
        surface.apply(stats: stats)
    }

    func fail(_ message: String, kind: FailureKind) {
        switch kind {
        case .timeout:
            stats.recordTimeout()
        case .connection:
            stats.recordConnectionError()
        }
        releaseLink(status: message, link: .error)
    }

    /// Commands are short ASCII lines and stay under the RFCOMM MTU.
    /// writeSync blocks until the controller accepts those few bytes, so it stays on main.
    func send(_ text: String, isCapture: Bool) {
        guard running, let channel else { return }
        var bytes = Array(text.utf8)
        guard bytes.count <= Int(UInt16.max) else { return }
        let count = UInt16(bytes.count)
        let now = Date.timeIntervalSinceReferenceDate
        if isCapture { requestTime = now }
        deadline = now + SynchroTiming.responseTimeout
        let result = bytes.withUnsafeMutableBytes { raw -> IOReturn in
            guard let base = raw.baseAddress else { return kIOReturnError }
            return channel.writeSync(base, length: count)
        }
        if result != kIOReturnSuccess {
            fail("Bluetooth write failed (\(result)). Press Start to reconnect.", kind: .connection)
        }
    }

    func requestCapture(after delay: TimeInterval) {
        guard running else { return }
        captureToken += 1
        let token = captureToken
        let activeGeneration = generation
        let fire = { [weak self] in
            guard let self, self.running, self.generation == activeGeneration, self.captureToken == token else { return }
            self.send("CAPTURE\n", isCapture: true)
        }
        if delay <= 0 {
            fire()
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: fire)
        }
    }

    func rfcommChannelOpenComplete(_ rfcommChannel: IOBluetoothRFCOMMChannel!, status error: IOReturn) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.running, self.channel === rfcommChannel else { return }
            if error != kIOReturnSuccess {
                self.fail("Bluetooth connection failed (\(error)). Check pairing and stop other viewers.", kind: .connection)
                return
            }
            self.setLink("Connected", color: .systemGreen)
            self.refreshDashboard(message: "Connected. Checking camera…")
            self.send("STATUS\n", isCapture: false)
        }
    }

    func rfcommChannelClosed(_ rfcommChannel: IOBluetoothRFCOMMChannel!) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            let disposition = disconnectDisposition(
                running: self.running,
                callbackMatchesOpenChannel: self.channel === rfcommChannel
            )
            guard disposition == .unexpectedClose else { return }
            self.fail("Camera disconnected. Check its power, then press Start.", kind: .connection)
        }
    }

    func rfcommChannelData(_ rfcommChannel: IOBluetoothRFCOMMChannel!, data dataPointer: UnsafeMutableRawPointer!, length dataLength: Int) {
        guard let dataPointer, dataLength > 0 else { return }
        let received = Data(bytes: dataPointer, count: dataLength)
        DispatchQueue.main.async { [weak self] in
            guard let self, self.running, self.channel === rfcommChannel else { return }
            self.ingest(received)
        }
    }

    func ingest(_ data: Data) {
        let events = assembler.append(data)
        for event in events {
            let completedAt = Date.timeIntervalSinceReferenceDate
            switch event {
            case .statusReady:
                setLink("Connected", color: .systemGreen)
                refreshDashboard(message: "Camera ready. Requesting frames…")
                requestCapture(after: 0)
            case .frameReady(let jpeg, let width, let height):
                deadline = 0
                let latency = requestTime > 0 ? max(0, completedAt - requestTime) : 0
                submitDecode(jpeg: jpeg, width: width, height: height, latency: latency, completedAt: completedAt)
                let delay = nextCaptureDelay(now: completedAt, requestSentAt: requestTime)
                requestCapture(after: delay)
            case .rejected(let reason):
                stats.recordRejection()
                deadline = 0
                refreshDashboard(message: "Rejected a frame (\(reason)). Continuing.")
                let delay = nextCaptureDelay(now: completedAt, requestSentAt: requestTime)
                requestCapture(after: delay)
            case .fatal(let reason):
                fail(reason, kind: .connection)
                return
            }
        }
    }

    func submitDecode(jpeg: Data, width: Int, height: Int, latency: TimeInterval, completedAt: TimeInterval) {
        let generationAtSubmit = generation
        decodeQueue.async { [weak self] in
            let started = Date.timeIntervalSinceReferenceDate
            let image = SynchroImage.decode(jpeg)
            let decodeSeconds = max(0, Date.timeIntervalSinceReferenceDate - started)
            DispatchQueue.main.async {
                guard let self, self.generation == generationAtSubmit else { return }
                guard let image, image.width == width, image.height == height else {
                    self.stats.recordRejection()
                    self.refreshDashboard(message: "JPEG failed local decode. Continuing.")
                    return
                }
                self.lastJPEG = jpeg
                self.frameBridge.publish(jpeg: jpeg, width: width, height: height, at: completedAt)
                self.stats.recordFrame(
                    at: completedAt,
                    jpegBytes: jpeg.count,
                    width: width,
                    height: height,
                    latency: latency,
                    decodeSeconds: decodeSeconds
                )
                let picture = NSImage(cgImage: image, size: NSSize(width: width, height: height))
                self.surface.setPreview(image: picture)
                self.applyRotation()
                self.setLink("Live", color: .systemGreen)
                let line = legacyLiveStatus(
                    averageFPS: self.stats.averageFPS > 0 ? self.stats.averageFPS : self.stats.lastInstantFPS,
                    width: width,
                    height: height,
                    frames: self.stats.receivedFrames
                )
                self.refreshDashboard(message: line)
            }
        }
    }

    @objc func rotationChanged() {
        applyRotation()
    }

    func applyRotation() {
        surface.imageView.wantsLayer = true
        surface.imageView.layer?.transform = surface.rotateButton.state == .on
            ? CATransform3DMakeRotation(.pi, 0, 0, 1)
            : CATransform3DIdentity
    }

    @objc func saveJPEG() {
        guard let jpeg = lastJPEG else {
            surface.messageLabel.stringValue = "No original JPEG yet. Start the camera and wait for a frame."
            return
        }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.jpeg]
        panel.nameFieldStringValue = "synchro-frame-\(max(stats.receivedFrames, 1)).jpg"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self, response == .OK, let url = panel.url else { return }
            do {
                try jpeg.write(to: url)
                self.surface.messageLabel.stringValue = "Saved original JPEG (\(jpeg.count) bytes), before display rotation."
            } catch {
                self.surface.messageLabel.stringValue = "Could not save JPEG: \(error.localizedDescription)"
            }
        }
    }

    @objc func exportCSV() {
        let csv = renderPerformanceCSV(samples: stats.samples, origin: .macViewer)
        let rows = stats.samples.count
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "synchro-performance.csv"
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self, response == .OK, let url = panel.url else { return }
            do {
                try csv.write(to: url, atomically: true, encoding: .utf8)
                self.surface.messageLabel.stringValue = "Exported \(rows) mac-viewer frame rows. This file is not a simulated test."
            } catch {
                self.surface.messageLabel.stringValue = "Could not export CSV: \(error.localizedDescription)"
            }
        }
    }

    @objc func resetStatistics() {
        stats.reset()
        refreshDashboard(message: "Statistics reset. Bluetooth was left unchanged.")
    }

    func setLink(_ text: String, color: NSColor) {
        surface.setStatus(title: text, color: color)
    }

    func refreshDashboard(message: String?) {
        if let message {
            surface.messageLabel.stringValue = message
            surface.messageLabel.textColor = SynchroTheme.muted
        }
        surface.apply(stats: stats)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        frameBridge.setLive(false)
        frameBridge.stop()
        releaseLink(status: nil, link: .unchanged)
        watchdog?.invalidate()
    }
}

enum FailureKind {
    case timeout
    case connection
}

enum LinkState {
    case stopped
    case error
    case unchanged
}

@main
struct SynchroMain {
    static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        let delegate = CameraApp()
        application.delegate = delegate
        application.run()
    }
}

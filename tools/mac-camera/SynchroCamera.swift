import AppKit
import IOBluetooth
import IOKit

// Native macOS Bluetooth Classic viewer for the existing Synchro-Cam firmware.
// All connection and UI work runs on the application's main run loop.
final class CameraApp: NSObject, NSApplicationDelegate, IOBluetoothRFCOMMChannelDelegate {
    let address = "70:4B:CA:46:52:22"
    var window: NSWindow!
    let imageView = NSImageView()
    let statusLabel = NSTextField(wrappingLabelWithString: "Power the camera, close the Windows viewer, then press Start.")
    let startButton = NSButton(title: "Start", target: nil, action: nil)
    let stopButton = NSButton(title: "Stop", target: nil, action: nil)
    let rotateButton = NSButton(checkboxWithTitle: "Rotate 180°", target: nil, action: nil)
    var device: IOBluetoothDevice?
    var channel: IOBluetoothRFCOMMChannel?
    var buffer = Data()
    var pendingFrame: (length: Int, width: Int, height: Int)?
    var waitingForStatus = true
    var running = false
    var generation = 0
    var deadline: TimeInterval = 0
    var requestTime: TimeInterval = 0
    var frameTimes: [TimeInterval] = []
    var frames = 0
    var sourceImage: NSImage?
    var watchdog: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit Synchro Camera", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)
        NSApp.mainMenu = menu

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 820, height: 690),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Synchro | Bluetooth Camera"
        window.minSize = NSSize(width: 560, height: 480)
        window.isReleasedWhenClosed = false
        let title = NSTextField(labelWithString: "SYNCHRO / BLUETOOTH")
        title.font = .boldSystemFont(ofSize: 21)
        let subtitle = NSTextField(labelWithString: "Synchro-Cam-BT · \(address)")
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.wantsLayer = true
        imageView.layer?.backgroundColor = NSColor.black.cgColor
        imageView.setContentHuggingPriority(.defaultLow, for: .vertical)
        statusLabel.alignment = .center
        startButton.target = self
        startButton.action = #selector(start)
        stopButton.target = self
        stopButton.action = #selector(stop)
        stopButton.isEnabled = false
        rotateButton.target = self
        rotateButton.action = #selector(render)
        rotateButton.state = .on
        let controls = NSStackView(views: [startButton, stopButton, rotateButton])
        controls.orientation = .horizontal
        controls.spacing = 14
        let stack = NSStackView(views: [title, subtitle, imageView, statusLabel, controls])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        let content = window.contentView!
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -20),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 20),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -20),
            imageView.widthAnchor.constraint(equalTo: stack.widthAnchor),
            imageView.heightAnchor.constraint(greaterThanOrEqualToConstant: 260),
            statusLabel.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        watchdog = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            guard let self = self, self.running, self.deadline > 0,
                  Date.timeIntervalSinceReferenceDate > self.deadline else { return }
            self.fail("Timed out. Check camera power, Bluetooth pairing, and that the Windows viewer is stopped. Press Start to retry.")
        }
    }

    @objc func start() {
        stop()
        generation += 1
        running = true
        waitingForStatus = true
        frames = 0
        frameTimes.removeAll()
        buffer.removeAll()
        pendingFrame = nil
        sourceImage = nil
        imageView.image = nil
        startButton.isEnabled = false
        stopButton.isEnabled = true
        statusLabel.stringValue = "Connecting over Bluetooth…"
        deadline = Date.timeIntervalSinceReferenceDate + 20
        device = IOBluetoothDevice(addressString: address)
        guard let device = device else { fail("Could not create the camera Bluetooth connection."); return }
        var opened: IOBluetoothRFCOMMChannel?
        let result = device.openRFCOMMChannelAsync(&opened, withChannelID: 1, delegate: self)
        channel = opened
        if result != kIOReturnSuccess { fail("Bluetooth open failed (\(result)). Pair Synchro-Cam-BT in System Settings, then retry.") }
    }

    @objc func stop() {
        running = false
        generation += 1
        deadline = 0
        let previous = channel
        channel = nil
        previous?.setDelegate(nil)
        previous?.close()
        device = nil
        buffer.removeAll()
        pendingFrame = nil
        startButton.isEnabled = true
        stopButton.isEnabled = false
        statusLabel.stringValue = "Stopped. Bluetooth released for another laptop."
    }

    func fail(_ message: String) {
        stop()
        statusLabel.stringValue = message
    }

    func send(_ text: String) {
        guard running, let channel = channel else { return }
        var bytes = Array(text.utf8)
        let count = UInt16(bytes.count)
        requestTime = Date.timeIntervalSinceReferenceDate
        deadline = requestTime + 8
        let result = bytes.withUnsafeMutableBytes { channel.writeSync($0.baseAddress, length: count) }
        if result != kIOReturnSuccess { fail("Bluetooth write failed (\(result)). Press Start to reconnect.") }
    }

    func rfcommChannelOpenComplete(_ rfcommChannel: IOBluetoothRFCOMMChannel!, status error: IOReturn) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.running, self.channel === rfcommChannel else { return }
            if error != kIOReturnSuccess { self.fail("Bluetooth connection failed (\(error)). Check pairing and stop other viewers."); return }
            self.statusLabel.stringValue = "Connected. Checking camera…"
            self.send("STATUS\n")
        }
    }

    func rfcommChannelClosed(_ rfcommChannel: IOBluetoothRFCOMMChannel!) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.running, self.channel === rfcommChannel else { return }
            self.fail("Camera disconnected. Check its power, then press Start.")
        }
    }

    func rfcommChannelData(_ rfcommChannel: IOBluetoothRFCOMMChannel!, data dataPointer: UnsafeMutableRawPointer!, length dataLength: Int) {
        guard let dataPointer = dataPointer, dataLength > 0 else { return }
        let received = Data(bytes: dataPointer, count: dataLength)
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.running, self.channel === rfcommChannel else { return }
            self.buffer.append(received)
            self.consume()
        }
    }

    func consume() {
        if buffer.count > 1_001_024 { fail("Camera response exceeded the allowed size."); return }
        while running {
            if let spec = pendingFrame {
                let trailer = Data("\nJPEG_END\n".utf8)
                guard buffer.count >= spec.length + trailer.count else { return }
                let jpeg = Data(buffer.prefix(spec.length))
                let ending = Data(buffer.dropFirst(spec.length).prefix(trailer.count))
                buffer.removeFirst(spec.length + trailer.count)
                pendingFrame = nil
                guard ending == trailer, jpeg.starts(with: [0xff, 0xd8]), jpeg.suffix(2) == Data([0xff, 0xd9]),
                      let bitmap = NSBitmapImageRep(data: jpeg), bitmap.pixelsWide == spec.width,
                      bitmap.pixelsHigh == spec.height else { fail("Invalid camera image. Press Start to reconnect."); return }
                let size = NSSize(width: CGFloat(spec.width), height: CGFloat(spec.height))
                let picture = NSImage(size: size)
                picture.addRepresentation(bitmap)
                sourceImage = picture
                render()
                frames += 1
                let now = Date.timeIntervalSinceReferenceDate
                frameTimes.append(now)
                frameTimes.removeAll { $0 < now - 3 }
                let span = now - (frameTimes.first ?? now)
                let fps = span > 0 ? Double(frameTimes.count - 1) / span : 0
                statusLabel.stringValue = String(format: "Bluetooth live · %.1f fps · %d × %d · %d frames", fps, spec.width, spec.height, frames)
                deadline = 0
                let activeGeneration = generation
                DispatchQueue.main.asyncAfter(deadline: .now() + max(0, 1.0 / 15.0 - (now - requestTime))) { [weak self] in
                    guard let self = self, self.running, self.generation == activeGeneration else { return }
                    self.send("CAPTURE\n")
                }
                continue
            }
            guard let newline = buffer.firstIndex(of: 10) else {
                if buffer.count > 512 { fail("Invalid camera response header.") }
                return
            }
            let lineData = Data(buffer[..<newline])
            guard lineData.count <= 512 else { fail("Oversized camera response header."); return }
            buffer.removeFirst(buffer.distance(from: buffer.startIndex, to: newline) + 1)
            if waitingForStatus {
                guard let status = (try? JSONSerialization.jsonObject(with: lineData)) as? [String: Any],
                      ["bluetooth-1", "bluetooth-2"].contains(status["firmware"] as? String ?? ""),
                      status["camera_ready"] as? Bool == true else { fail("Camera firmware is not ready."); return }
                waitingForStatus = false
                send("CAPTURE\n")
            } else {
                let words = String(decoding: lineData, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines).split(separator: " ")
                guard words.count == 4, words[0] == "JPEG_BEGIN", let length = Int(words[1]),
                      let width = Int(words[2]), let height = Int(words[3]), (4...1_000_000).contains(length),
                      (width == 640 && height == 480) || (width == 320 && height == 240) else {
                    fail("Unexpected camera response. Press Start to reconnect."); return
                }
                pendingFrame = (length, width, height)
            }
        }
    }

    @objc func render() {
        guard let source = sourceImage else { return }
        if rotateButton.state != .on { imageView.image = source; return }
        imageView.image = NSImage(size: source.size, flipped: false) { rect in
            NSGraphicsContext.saveGraphicsState()
            defer { NSGraphicsContext.restoreGraphicsState() }
            let transform = NSAffineTransform()
            transform.translateX(by: rect.width, yBy: rect.height)
            transform.rotate(byDegrees: 180)
            transform.concat()
            source.draw(in: rect)
            return true
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { stop(); watchdog?.invalidate() }
}

let application = NSApplication.shared
application.setActivationPolicy(.regular)
let delegate = CameraApp()
application.delegate = delegate
application.run()

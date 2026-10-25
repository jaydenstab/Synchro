import AppKit
import QuartzCore

enum SynchroTheme {
    static let bg = NSColor(srgbRed: 0x0d / 255, green: 0x0f / 255, blue: 0x11 / 255, alpha: 1)
    static let panel = NSColor(srgbRed: 0x15 / 255, green: 0x18 / 255, blue: 0x1b / 255, alpha: 1)
    static let panel2 = NSColor(srgbRed: 0x10 / 255, green: 0x12 / 255, blue: 0x14 / 255, alpha: 1)
    static let line = NSColor(white: 1, alpha: 0.10)
    static let text = NSColor(srgbRed: 0xf3 / 255, green: 0xf6 / 255, blue: 0xf4 / 255, alpha: 1)
    static let muted = NSColor(srgbRed: 0x9a / 255, green: 0xa3 / 255, blue: 0x9c / 255, alpha: 1)
    static let mint = NSColor(srgbRed: 0x3d / 255, green: 0xdc / 255, blue: 0x97 / 255, alpha: 1)
    static let ink = NSColor(srgbRed: 0x06 / 255, green: 0x28 / 255, blue: 0x1a / 255, alpha: 1)
    static let danger = NSColor(srgbRed: 1, green: 0x6b / 255, blue: 0x6b / 255, alpha: 1)
    static let warn = NSColor(srgbRed: 0xf0 / 255, green: 0xb4 / 255, blue: 0x29 / 255, alpha: 1)
}

enum SynchroButtonKind { case primary, ghost, danger, plain, nav }

final class SynchroButton: NSButton {
    var kind: SynchroButtonKind = .ghost { didSet { refreshFace() } }
    var chosen = false { didSet { refreshFace() } }
    var showsCheck = false

    static func make(_ title: String, symbol: String?, kind: SynchroButtonKind) -> SynchroButton {
        let button = SynchroButton()
        let cell = SynchroButtonCell(textCell: title)
        cell.padX = kind == .nav ? 12 : 14
        cell.alignment = kind == .nav ? .left : .center
        button.cell = cell
        button.kind = kind
        button.title = title
        button.isBordered = false
        button.focusRingType = .none
        button.wantsLayer = true
        button.imagePosition = .imageLeading
        button.imageScaling = .scaleProportionallyDown
        if let symbol, let image = NSImage(systemSymbolName: symbol, accessibilityDescription: title) {
            button.image = image.withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 12, weight: .semibold))
        }
        button.refreshFace()
        return button
    }

    override var state: NSControl.StateValue {
        didSet { if showsCheck { refreshFace() } }
    }

    override var alignmentRectInsets: NSEdgeInsets { NSEdgeInsets() }

    override var intrinsicContentSize: NSSize {
        guard let cell else { return super.intrinsicContentSize }
        return cell.cellSize(forBounds: NSRect(x: 0, y: 0, width: 4_000, height: 36))
    }

    override var isEnabled: Bool {
        didSet { refreshFace() }
    }

    func refreshFace() {
        let selected = kind == .nav && chosen
        let emphasized = kind == .primary || selected || (kind == .danger && isEnabled)
        let font = NSFont.systemFont(ofSize: 13, weight: emphasized ? .semibold : .medium)
        let color: NSColor
        switch kind {
        case .primary:
            color = SynchroTheme.ink
        case .danger:
            color = isEnabled ? SynchroTheme.danger : SynchroTheme.muted
        case .plain:
            color = showsCheck && state == .on ? SynchroTheme.text : SynchroTheme.muted
        case .nav:
            color = selected ? SynchroTheme.ink : SynchroTheme.muted
        case .ghost:
            color = isEnabled ? SynchroTheme.text : SynchroTheme.muted
        }
        attributedTitle = NSAttributedString(string: title, attributes: [
            .font: font,
            .foregroundColor: color,
            .baselineOffset: 0
        ])
        if showsCheck {
            let symbol = state == .on ? "checkmark.square.fill" : "square"
            image = NSImage(systemSymbolName: symbol, accessibilityDescription: title)?
                .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 13, weight: .medium))
            contentTintColor = state == .on ? SynchroTheme.mint : SynchroTheme.muted
        } else {
            contentTintColor = color
        }
        wantsLayer = true
        layer?.masksToBounds = true
        layer?.cornerRadius = 10
        switch kind {
        case .primary:
            layer?.backgroundColor = SynchroTheme.mint.cgColor
            layer?.borderWidth = 0
        case .nav:
            layer?.backgroundColor = (selected ? SynchroTheme.mint : NSColor.clear).cgColor
            layer?.borderWidth = 0
        case .plain:
            layer?.backgroundColor = NSColor.clear.cgColor
            layer?.borderWidth = 0
        case .danger where isEnabled:
            layer?.backgroundColor = SynchroTheme.danger.withAlphaComponent(0.12).cgColor
            layer?.borderWidth = 1
            layer?.borderColor = SynchroTheme.danger.withAlphaComponent(0.55).cgColor
        case .ghost, .danger:
            layer?.backgroundColor = NSColor.clear.cgColor
            layer?.borderWidth = 1
            layer?.borderColor = SynchroTheme.line.cgColor
        }
        invalidateIntrinsicContentSize()
    }
}

final class SynchroButtonCell: NSButtonCell {
    var padX: CGFloat = 14
    private let iconGap: CGFloat = 6

    override func cellSize(forBounds rect: NSRect) -> NSSize {
        let titleWidth = ceil(attributedTitle.size().width)
        let iconWidth = image == nil ? 0 : ceil(image!.size.width) + iconGap
        return NSSize(width: padX + iconWidth + titleWidth + padX, height: 36)
    }

    override func imageRect(forBounds rect: NSRect) -> NSRect {
        guard let image else { return .zero }
        let size = image.size
        let titleWidth = attributedTitle.size().width
        let content = size.width + iconGap + titleWidth
        let originX = alignment == .left ? rect.minX + padX : rect.midX - content / 2
        return NSRect(x: originX, y: rect.midY - size.height / 2, width: size.width, height: size.height)
    }

    override func titleRect(forBounds rect: NSRect) -> NSRect {
        let titleSize = attributedTitle.size()
        let icon = imageRect(forBounds: rect)
        let originX = icon.width > 0 ? icon.maxX + iconGap : (alignment == .left ? rect.minX + padX : rect.midX - titleSize.width / 2)
        return NSRect(x: originX, y: rect.midY - titleSize.height / 2, width: titleSize.width, height: titleSize.height)
    }

    override func drawInterior(withFrame cellFrame: NSRect, in controlView: NSView) {
        let iconFrame = imageRect(forBounds: cellFrame)
        if let image, iconFrame.width > 0 {
            let tint = (controlView as? NSButton)?.contentTintColor ?? SynchroTheme.text
            let painted = NSImage(size: iconFrame.size, flipped: false) { destination in
                image.draw(in: NSRect(origin: .zero, size: destination.size))
                tint.set()
                destination.fill(using: .sourceAtop)
                return true
            }
            painted.draw(in: iconFrame, from: .zero, operation: .sourceOver, fraction: 1)
        }
        let titleSize = attributedTitle.size()
        let titleX = iconFrame.width > 0
            ? iconFrame.maxX + iconGap
            : (alignment == .left ? cellFrame.minX + padX : cellFrame.midX - titleSize.width / 2)
        let titleRect = NSRect(
            x: titleX,
            y: cellFrame.midY - titleSize.height / 2,
            width: ceil(titleSize.width),
            height: ceil(titleSize.height)
        )
        attributedTitle.draw(in: titleRect)
    }
}

/// Presentation for the camera monitor. Packet handling stays in CameraApp.
struct MonitorSurface {
    let imageView: NSImageView
    let emptyState: NSView
    let messageLabel: NSTextField
    let noteLabel: NSTextField
    let statusDot: NSView
    let statusLabel: NSTextField
    let currentFPS: Readout
    let averageFPS: Readout
    let jpegSize: Readout
    let resolution: Readout
    let requestLatency: Readout
    let averageLatency: Readout
    let maxLatency: Readout
    let decodeLatency: Readout
    let received: Readout
    let rejected: Readout
    let timeouts: Readout
    let connectionErrors: Readout
    let startButton: NSButton
    let stopButton: NSButton
    let rotateButton: NSButton
    let saveButton: NSButton
    let exportButton: NSButton
    let resetButton: NSButton
    let glove: GloveMetricsBar
    let root: NSStackView

    static func make(address: String) -> MonitorSurface {
        let imageView = NSImageView()
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.imageAlignment = .alignCenter
        imageView.wantsLayer = true
        imageView.layer?.backgroundColor = NSColor.clear.cgColor

        let emptyTitle = tracked("No signal", size: 28, weight: .semibold, color: SynchroTheme.text, kern: -1.1)
        let emptyDetail = NSTextField(wrappingLabelWithString: "The picture appears with the first frame.")
        emptyDetail.font = .systemFont(ofSize: 15, weight: .regular)
        emptyDetail.textColor = NSColor(white: 1, alpha: 0.62)
        emptyDetail.alignment = .center
        emptyDetail.preferredMaxLayoutWidth = 320
        let emptyState = NSStackView(views: [emptyTitle, emptyDetail])
        emptyState.orientation = .vertical
        emptyState.alignment = .centerX
        emptyState.spacing = 8

        let well = NSView()
        well.wantsLayer = true
        well.layer?.backgroundColor = NSColor.black.cgColor
        well.layer?.cornerRadius = 18
        well.layer?.masksToBounds = true
        well.layer?.borderWidth = 1
        well.layer?.borderColor = SynchroTheme.line.cgColor
        imageView.translatesAutoresizingMaskIntoConstraints = false
        emptyState.translatesAutoresizingMaskIntoConstraints = false
        well.addSubview(imageView)
        well.addSubview(emptyState)
        NSLayoutConstraint.activate([
            imageView.leadingAnchor.constraint(equalTo: well.leadingAnchor),
            imageView.trailingAnchor.constraint(equalTo: well.trailingAnchor),
            imageView.topAnchor.constraint(equalTo: well.topAnchor),
            imageView.bottomAnchor.constraint(equalTo: well.bottomAnchor),
            emptyState.centerXAnchor.constraint(equalTo: well.centerXAnchor),
            emptyState.centerYAnchor.constraint(equalTo: well.centerYAnchor),
            emptyState.widthAnchor.constraint(lessThanOrEqualTo: well.widthAnchor, constant: -48)
        ])

        let currentFPS = Readout(caption: "Current fps", valueSize: 22)
        let averageFPS = Readout(caption: "3 s average", valueSize: 22)
        let jpegSize = Readout(caption: "JPEG size", valueSize: 22)
        let resolution = Readout(caption: "Resolution", valueSize: 22)
        let requestLatency = Readout(caption: "Request to frame", valueSize: 22)
        let averageLatency = Readout(caption: "Average", valueSize: 22)
        let maxLatency = Readout(caption: "Maximum", valueSize: 22)
        let decodeLatency = Readout(caption: "Mac decode", valueSize: 22)
        let received = Readout(caption: "Received", valueSize: 22)
        let rejected = Readout(caption: "Rejected", valueSize: 22)
        let timeouts = Readout(caption: "Timeouts", valueSize: 22)
        let connectionErrors = Readout(caption: "Connection", valueSize: 22)
        requestLatency.valueLabel.toolTip = SynchroTiming.latencyExplanation
        averageLatency.valueLabel.toolTip = SynchroTiming.latencyExplanation
        maxLatency.valueLabel.toolTip = SynchroTiming.latencyExplanation
        decodeLatency.valueLabel.toolTip = "Local ImageIO time after JPEG_END. This is not camera exposure."
        connectionErrors.valueLabel.toolTip = "Connection errors"

        let name = NSTextField(labelWithString: "Synchro-Cam-BT")
        name.font = .systemFont(ofSize: 16, weight: .semibold)
        name.textColor = SynchroTheme.text
        let addressLabel = NSTextField(labelWithString: "\(address)  ·  RFCOMM 1")
        addressLabel.font = .monospacedDigitSystemFont(ofSize: 12, weight: .regular)
        addressLabel.textColor = SynchroTheme.muted
        let statusDot = NSView()
        statusDot.wantsLayer = true
        statusDot.layer?.cornerRadius = 4
        statusDot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            statusDot.widthAnchor.constraint(equalToConstant: 8),
            statusDot.heightAnchor.constraint(equalToConstant: 8)
        ])
        let statusLabel = NSTextField(labelWithString: "Idle")
        statusLabel.font = .systemFont(ofSize: 13, weight: .regular)
        statusLabel.textColor = SynchroTheme.muted
        let pill = NSStackView(views: [statusDot, statusLabel])
        pill.orientation = .horizontal
        pill.alignment = .centerY
        pill.spacing = 8
        pill.edgeInsets = NSEdgeInsets(top: 6, left: 10, bottom: 6, right: 10)
        pill.wantsLayer = true
        pill.layer?.cornerRadius = 14
        pill.layer?.borderWidth = 1
        pill.layer?.borderColor = SynchroTheme.line.cgColor
        pill.layer?.backgroundColor = NSColor.clear.cgColor

        let identity = NSStackView(views: [sectionLabel("Device"), name, addressLabel])
        identity.orientation = .vertical
        identity.alignment = .leading
        identity.spacing = 4
        identity.setCustomSpacing(8, after: name)

        let column = NSStackView(views: [
            identity,
            hairline(),
            group("Rate", row(currentFPS, averageFPS)),
            group("Frame", row(jpegSize, resolution)),
            group("Transfer", grid(requestLatency, averageLatency, maxLatency, decodeLatency)),
            group("Session", grid(received, rejected, timeouts, connectionErrors))
        ])
        column.orientation = .vertical
        column.alignment = .leading
        column.spacing = 12
        column.translatesAutoresizingMaskIntoConstraints = false

        let rail = InspectorPanel()
        rail.addSubview(column)
        NSLayoutConstraint.activate([
            column.leadingAnchor.constraint(equalTo: rail.leadingAnchor, constant: 14),
            column.trailingAnchor.constraint(equalTo: rail.trailingAnchor, constant: -14),
            column.topAnchor.constraint(equalTo: rail.topAnchor, constant: 14),
            column.bottomAnchor.constraint(lessThanOrEqualTo: rail.bottomAnchor, constant: -14),
            rail.widthAnchor.constraint(equalToConstant: 336)
        ])
        for item in column.arrangedSubviews {
            item.widthAnchor.constraint(equalTo: column.widthAnchor).isActive = true
        }

        let body = NSView()
        well.translatesAutoresizingMaskIntoConstraints = false
        rail.translatesAutoresizingMaskIntoConstraints = false
        body.addSubview(well)
        body.addSubview(rail)
        NSLayoutConstraint.activate([
            well.leadingAnchor.constraint(equalTo: body.leadingAnchor),
            well.topAnchor.constraint(equalTo: body.topAnchor),
            well.bottomAnchor.constraint(equalTo: body.bottomAnchor),
            rail.leadingAnchor.constraint(equalTo: well.trailingAnchor, constant: 16),
            rail.trailingAnchor.constraint(equalTo: body.trailingAnchor),
            rail.topAnchor.constraint(equalTo: body.topAnchor),
            rail.bottomAnchor.constraint(equalTo: body.bottomAnchor),
            well.widthAnchor.constraint(greaterThanOrEqualToConstant: 520),
            body.heightAnchor.constraint(greaterThanOrEqualToConstant: 360)
        ])

        let pageTitle = tracked("Camera", size: 28, weight: .semibold, color: SynchroTheme.text, kern: -1.12)
        let messageLabel = NSTextField(wrappingLabelWithString: "Power the camera, close the Windows viewer, then press Start.")
        messageLabel.font = .systemFont(ofSize: 13)
        messageLabel.textColor = SynchroTheme.muted
        messageLabel.maximumNumberOfLines = 2
        messageLabel.preferredMaxLayoutWidth = 640
        let headerSpacer = NSView()
        headerSpacer.setContentHuggingPriority(.fittingSizeCompression, for: .horizontal)
        let titleRow = NSStackView(views: [pageTitle, headerSpacer, pill])
        titleRow.orientation = .horizontal
        titleRow.alignment = .centerY
        titleRow.spacing = 16
        let heading = NSStackView(views: [titleRow, messageLabel])
        heading.orientation = .vertical
        heading.alignment = .leading
        heading.spacing = 6
        titleRow.widthAnchor.constraint(equalTo: heading.widthAnchor).isActive = true
        let header = heading

        let startButton = SynchroButton.make("Start", symbol: "play.fill", kind: .primary)
        let stopButton = SynchroButton.make("Stop", symbol: "stop.fill", kind: .danger)
        stopButton.isEnabled = false
        let rotateButton = SynchroButton.make("Rotate 180°", symbol: "checkmark.square.fill", kind: .plain)
        rotateButton.showsCheck = true
        rotateButton.setButtonType(.toggle)
        rotateButton.state = .on
        (rotateButton.cell as? SynchroButtonCell)?.padX = 2
        rotateButton.invalidateIntrinsicContentSize()
        rotateButton.toolTip = "Turns the preview 180°. The saved JPEG stays in the camera's orientation."
        let saveButton = SynchroButton.make("Save Original JPEG", symbol: "square.and.arrow.down", kind: .ghost)
        saveButton.toolTip = "Write the latest JPEG bytes, before display rotation."
        let exportButton = SynchroButton.make("Export Performance CSV", symbol: "tablecells", kind: .ghost)
        exportButton.toolTip = "Save this session. The file origin is mac-viewer."
        let resetButton = SynchroButton.make("Reset Statistics", symbol: "arrow.counterclockwise", kind: .ghost)
        resetButton.toolTip = "Clear the counters and the export log. Bluetooth stays as it is."
        startButton.keyEquivalent = "\r"

        let controls = [startButton, stopButton, rotateButton, saveButton, exportButton, resetButton]
        for button in controls {
            button.translatesAutoresizingMaskIntoConstraints = false
            button.heightAnchor.constraint(equalToConstant: 36).isActive = true
            button.setContentHuggingPriority(.required, for: .vertical)
            button.setContentHuggingPriority(.required, for: .horizontal)
            button.setContentCompressionResistancePriority(.required, for: .vertical)
            button.setContentCompressionResistancePriority(.required, for: .horizontal)
        }

        let divider = NSView()
        divider.wantsLayer = true
        divider.layer?.backgroundColor = SynchroTheme.line.cgColor
        divider.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            divider.widthAnchor.constraint(equalToConstant: 1),
            divider.heightAnchor.constraint(equalToConstant: 16)
        ])

        let transport = NSStackView(views: [startButton, stopButton, divider, rotateButton])
        transport.orientation = .horizontal
        transport.alignment = .centerY
        transport.spacing = 8
        transport.setCustomSpacing(12, after: stopButton)
        transport.setCustomSpacing(12, after: divider)

        let actions = NSStackView(views: [saveButton, exportButton, resetButton])
        actions.orientation = .vertical
        actions.alignment = .leading
        actions.spacing = 8
        actions.translatesAutoresizingMaskIntoConstraints = false
        for button in [saveButton, exportButton, resetButton] {
            button.setContentHuggingPriority(.defaultLow, for: .horizontal)
            button.widthAnchor.constraint(equalTo: actions.widthAnchor).isActive = true
        }

        let noteLabel = NSTextField(labelWithString: "Request-to-frame includes capture, compression, and Bluetooth. It is not sensor exposure time. Decode time is measured on the Mac.")
        noteLabel.font = .systemFont(ofSize: 12, weight: .regular)
        noteLabel.textColor = SynchroTheme.muted
        noteLabel.lineBreakMode = .byTruncatingTail
        noteLabel.maximumNumberOfLines = 1
        noteLabel.toolTip = SynchroTiming.latencyExplanation
        noteLabel.setContentHuggingPriority(.required, for: .vertical)
        noteLabel.setContentCompressionResistancePriority(.required, for: .vertical)

        let footer = NSView()
        transport.translatesAutoresizingMaskIntoConstraints = false
        noteLabel.translatesAutoresizingMaskIntoConstraints = false
        footer.addSubview(transport)
        footer.addSubview(actions)
        footer.addSubview(noteLabel)
        footer.setContentCompressionResistancePriority(.required, for: .vertical)
        footer.setContentHuggingPriority(.required, for: .vertical)

        let glove = GloveMetricsBar()
        let root = NSStackView(views: [header, body, glove, footer])
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 16
        root.translatesAutoresizingMaskIntoConstraints = false
        let notePull = noteLabel.topAnchor.constraint(equalTo: footer.topAnchor)
        notePull.priority = .defaultLow
        NSLayoutConstraint.activate([
            transport.leadingAnchor.constraint(equalTo: well.leadingAnchor),
            transport.topAnchor.constraint(equalTo: footer.topAnchor),
            transport.trailingAnchor.constraint(lessThanOrEqualTo: actions.leadingAnchor, constant: -16),
            actions.leadingAnchor.constraint(equalTo: rail.leadingAnchor),
            actions.trailingAnchor.constraint(equalTo: rail.trailingAnchor),
            actions.topAnchor.constraint(equalTo: transport.topAnchor),
            noteLabel.leadingAnchor.constraint(equalTo: footer.leadingAnchor),
            noteLabel.trailingAnchor.constraint(equalTo: footer.trailingAnchor),
            noteLabel.topAnchor.constraint(greaterThanOrEqualTo: transport.bottomAnchor, constant: 10),
            noteLabel.topAnchor.constraint(greaterThanOrEqualTo: actions.bottomAnchor, constant: 10),
            notePull,
            footer.bottomAnchor.constraint(equalTo: noteLabel.bottomAnchor)
        ])
        body.setContentHuggingPriority(.defaultLow, for: .vertical)
        body.setContentCompressionResistancePriority(NSLayoutConstraint.Priority(200), for: .vertical)
        messageLabel.setContentCompressionResistancePriority(.required, for: .vertical)
        noteLabel.setContentCompressionResistancePriority(.required, for: .vertical)

        let surface = MonitorSurface(
            imageView: imageView,
            emptyState: emptyState,
            messageLabel: messageLabel,
            noteLabel: noteLabel,
            statusDot: statusDot,
            statusLabel: statusLabel,
            currentFPS: currentFPS,
            averageFPS: averageFPS,
            jpegSize: jpegSize,
            resolution: resolution,
            requestLatency: requestLatency,
            averageLatency: averageLatency,
            maxLatency: maxLatency,
            decodeLatency: decodeLatency,
            received: received,
            rejected: rejected,
            timeouts: timeouts,
            connectionErrors: connectionErrors,
            startButton: startButton,
            stopButton: stopButton,
            rotateButton: rotateButton,
            saveButton: saveButton,
            exportButton: exportButton,
            resetButton: resetButton,
            glove: glove,
            root: root
        )
        surface.apply(stats: PerformanceTracker())
        surface.setStatus(title: "Idle", color: .systemGray)
        return surface
    }

    func install(in content: NSView) {
        content.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            root.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            root.topAnchor.constraint(equalTo: content.topAnchor, constant: 22),
            root.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -20)
        ])
        for view in root.arrangedSubviews {
            view.widthAnchor.constraint(equalTo: root.widthAnchor).isActive = true
        }
    }

    func setPreview(image: NSImage?) {
        guard let image else {
            imageView.image = nil
            imageView.alphaValue = 0
            emptyState.alphaValue = 1
            emptyState.isHidden = false
            return
        }
        let firstFrame = imageView.image == nil
        imageView.image = image
        guard firstFrame else { return }
        imageView.alphaValue = 0
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.22
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            imageView.animator().alphaValue = 1
            emptyState.animator().alphaValue = 0
        } completionHandler: {
            self.emptyState.isHidden = true
        }
    }

    func setStatus(title: String, color: NSColor) {
        statusLabel.stringValue = title
        statusLabel.textColor = SynchroTheme.muted
        let dot: NSColor
        switch title {
        case "Live", "Connected": dot = SynchroTheme.mint
        case "Connecting": dot = SynchroTheme.warn
        case "Error": dot = SynchroTheme.danger
        default: dot = SynchroTheme.muted
        }
        statusDot.layer?.backgroundColor = dot.cgColor
        statusDot.layer?.removeAnimation(forKey: "pulse")
        if title == "Live" || title == "Connecting" {
            let pulse = CABasicAnimation(keyPath: "opacity")
            pulse.fromValue = 1
            pulse.toValue = 0.35
            pulse.duration = title == "Connecting" ? 0.7 : 1.1
            pulse.autoreverses = true
            pulse.repeatCount = .infinity
            pulse.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            statusDot.layer?.add(pulse, forKey: "pulse")
        }
    }

    func apply(stats: PerformanceTracker) {
        let fpsReady = stats.receivedFrames >= 2
        currentFPS.set(fpsReady ? formatFixed(stats.lastInstantFPS, digits: 1) : "—", placeholder: !fpsReady)
        averageFPS.set(fpsReady ? formatFixed(stats.averageFPS, digits: 1) : "—", placeholder: !fpsReady)
        if stats.lastJPEGBytes > 0 {
            let kb = Double(stats.lastJPEGBytes) / 1024
            jpegSize.set(formatFixed(kb, digits: kb >= 10 ? 1 : 2) + " KB", placeholder: false)
        } else {
            jpegSize.set("—", placeholder: true)
        }
        if stats.lastWidth > 0 {
            resolution.set("\(stats.lastWidth) × \(stats.lastHeight)", placeholder: false)
        } else {
            resolution.set("—", placeholder: true)
        }
        let timed = stats.receivedFrames > 0
        requestLatency.set(milliseconds(stats.lastLatency, known: timed), placeholder: !timed)
        averageLatency.set(milliseconds(stats.averageLatency, known: timed), placeholder: !timed)
        maxLatency.set(milliseconds(stats.maxLatency, known: timed), placeholder: !timed)
        decodeLatency.set(milliseconds(stats.lastDecode, known: timed), placeholder: !timed)
        received.set("\(stats.receivedFrames)", placeholder: false)
        rejected.set("\(stats.rejectedFrames)", placeholder: false)
        timeouts.set("\(stats.timeoutErrors)", placeholder: false)
        connectionErrors.set("\(stats.connectionErrors)", placeholder: false)
        rejected.valueLabel.textColor = stats.rejectedFrames > 0 ? SynchroTheme.warn : SynchroTheme.text
        timeouts.valueLabel.textColor = stats.timeoutErrors > 0 ? SynchroTheme.danger : SynchroTheme.text
        connectionErrors.valueLabel.textColor = stats.connectionErrors > 0 ? SynchroTheme.danger : SynchroTheme.text
    }
}

final class Readout: NSView {
    let valueLabel: NSTextField
    let captionLabel: NSTextField

    init(caption: String, valueSize: CGFloat) {
        valueLabel = NSTextField(labelWithString: "—")
        captionLabel = NSTextField(wrappingLabelWithString: caption)
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 12
        layer?.borderWidth = 1
        layer?.borderColor = SynchroTheme.line.cgColor
        layer?.backgroundColor = SynchroTheme.panel2.cgColor
        valueLabel.font = .monospacedDigitSystemFont(ofSize: valueSize, weight: .semibold)
        valueLabel.textColor = SynchroTheme.muted
        valueLabel.lineBreakMode = .byTruncatingTail
        captionLabel.font = .systemFont(ofSize: 12, weight: .medium)
        captionLabel.textColor = SynchroTheme.muted
        captionLabel.maximumNumberOfLines = 1
        captionLabel.lineBreakMode = .byTruncatingTail
        let stack = NSStackView(views: [captionLabel, valueLabel])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 4
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 10),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -10),
            stack.topAnchor.constraint(equalTo: topAnchor, constant: 8),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -8),
            heightAnchor.constraint(equalToConstant: 58)
        ])
    }

    required init?(coder: NSCoder) { nil }

    func set(_ value: String, placeholder: Bool) {
        valueLabel.stringValue = value
        valueLabel.textColor = placeholder ? SynchroTheme.muted : SynchroTheme.text
        valueLabel.setAccessibilityLabel("\(captionLabel.stringValue): \(value)")
    }
}

private func milliseconds(_ seconds: Double, known: Bool) -> String {
    guard known else { return "—" }
    return formatFixed(seconds * 1000, digits: 0) + " ms"
}

private func tracked(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor, kern: CGFloat) -> NSTextField {
    let label = NSTextField(labelWithString: "")
    label.attributedStringValue = NSAttributedString(string: text, attributes: [
        .font: NSFont.systemFont(ofSize: size, weight: weight),
        .foregroundColor: color,
        .kern: kern
    ])
    return label
}

private func sectionLabel(_ text: String) -> NSTextField {
    let label = NSTextField(labelWithString: text)
    label.font = .systemFont(ofSize: 16, weight: .semibold)
    label.textColor = SynchroTheme.text
    return label
}

private func row(_ leading: NSView, _ trailing: NSView) -> NSStackView {
    let stack = NSStackView(views: [leading, trailing])
    stack.orientation = .horizontal
    stack.distribution = .fillEqually
    stack.spacing = 10
    return stack
}

private func grid(_ first: NSView, _ second: NSView, _ third: NSView, _ fourth: NSView) -> NSStackView {
    let top = row(first, second)
    let bottom = row(third, fourth)
    let stack = NSStackView(views: [top, bottom])
    stack.orientation = .vertical
    stack.alignment = .leading
    stack.spacing = 10
    top.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
    bottom.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
    return stack
}

private func group(_ title: String, _ body: NSView) -> NSStackView {
    let stack = NSStackView(views: [sectionLabel(title), body])
    stack.orientation = .vertical
    stack.alignment = .leading
    stack.spacing = 8
    body.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
    return stack
}

private func hairline() -> NSView {
    Hairline()
}

final class InspectorPanel: NSView {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.cornerRadius = 16
        layer?.borderWidth = 1
        layer?.borderColor = SynchroTheme.line.cgColor
        layer?.masksToBounds = true
    }

    required init?(coder: NSCoder) { nil }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        refreshFill()
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        refreshFill()
    }

    private func refreshFill() {
        layer?.backgroundColor = SynchroTheme.panel.cgColor
        layer?.borderColor = SynchroTheme.line.cgColor
    }
}

final class Hairline: NSView {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        translatesAutoresizingMaskIntoConstraints = false
        heightAnchor.constraint(equalToConstant: 1).isActive = true
    }

    required init?(coder: NSCoder) { nil }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        layer?.backgroundColor = SynchroTheme.line.cgColor
    }

    override func viewDidChangeEffectiveAppearance() {
        super.viewDidChangeEffectiveAppearance()
        layer?.backgroundColor = SynchroTheme.line.cgColor
    }
}

/// Same glove readouts as the browser panel: angles, contacts, link line, calibration.
final class GloveMetricsBar: NSView {
    let angleValues: [NSTextField]
    let contacts: [NSTextField]
    let lineLabel = NSTextField(labelWithString: "Looking for Nano USB...")
    let noteLabel = NSTextField(labelWithString: "Not calibrated. Yaw can drift.")
    let calibrateButton = SynchroButton.make("Calibrate — hold still 15 s", symbol: nil, kind: .ghost)
    let progress = NSProgressIndicator()
    private var flashUntil = [0.0, 0.0]
    private var seenPresses: [Int?] = [nil, nil]

    override init(frame frameRect: NSRect) {
        let captions = ["ROLL / X", "PITCH / Y", "YAW / RELATIVE"]
        angleValues = captions.map { _ in NSTextField(labelWithString: "—") }
        let angleColumns: [NSView] = zip(captions, angleValues).map { caption, value in
            let title = NSTextField(labelWithString: caption)
            title.font = .systemFont(ofSize: 11, weight: .medium)
            title.textColor = SynchroTheme.muted
            value.font = .monospacedDigitSystemFont(ofSize: 22, weight: .semibold)
            value.textColor = SynchroTheme.muted
            let column = NSStackView(views: [title, value])
            column.orientation = .vertical
            column.alignment = .leading
            column.spacing = 2
            return column
        }
        let names = ["Index / LEFT CLICK", "Middle / RIGHT CLICK"]
        contacts = names.map { name in
            let chip = NSTextField(labelWithString: "\(name): NO SIGNAL  ·  0 taps")
            chip.font = .systemFont(ofSize: 13, weight: .semibold)
            chip.textColor = SynchroTheme.muted
            chip.lineBreakMode = .byTruncatingTail
            chip.wantsLayer = true
            chip.layer?.cornerRadius = 10
            chip.layer?.backgroundColor = NSColor(srgbRed: 0x25 / 255, green: 0x35 / 255, blue: 0x3a / 255, alpha: 1).cgColor
            return chip
        }
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.cornerRadius = 16
        layer?.borderWidth = 1
        layer?.borderColor = SynchroTheme.line.cgColor
        layer?.backgroundColor = SynchroTheme.panel.cgColor
        translatesAutoresizingMaskIntoConstraints = false
        setContentCompressionResistancePriority(.required, for: .vertical)
        setContentHuggingPriority(.required, for: .vertical)

        let angles = NSStackView(views: angleColumns)
        angles.orientation = .horizontal
        angles.distribution = .fillEqually
        angles.spacing = 8
        let chips = NSStackView(views: contacts)
        chips.orientation = .horizontal
        chips.distribution = .fillEqually
        chips.spacing = 8
        lineLabel.font = .systemFont(ofSize: 13)
        lineLabel.textColor = SynchroTheme.muted
        lineLabel.lineBreakMode = .byTruncatingTail
        noteLabel.font = .systemFont(ofSize: 12)
        noteLabel.textColor = SynchroTheme.muted
        noteLabel.lineBreakMode = .byTruncatingTail
        calibrateButton.isEnabled = false
        progress.isIndeterminate = false
        progress.minValue = 0
        progress.maxValue = 100
        progress.doubleValue = 0
        progress.controlSize = .small
        let actions = NSStackView(views: [calibrateButton, progress])
        actions.orientation = .horizontal
        actions.alignment = .centerY
        actions.spacing = 10
        progress.widthAnchor.constraint(greaterThanOrEqualToConstant: 120).isActive = true
        let column = NSStackView(views: [angles, chips, lineLabel, actions, noteLabel])
        column.orientation = .vertical
        column.alignment = .leading
        column.spacing = 8
        column.translatesAutoresizingMaskIntoConstraints = false
        addSubview(column)
        NSLayoutConstraint.activate([
            column.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 14),
            column.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -14),
            column.topAnchor.constraint(equalTo: topAnchor, constant: 12),
            column.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -12),
            angles.widthAnchor.constraint(equalTo: column.widthAnchor),
            chips.widthAnchor.constraint(equalTo: column.widthAnchor),
            actions.widthAnchor.constraint(equalTo: column.widthAnchor),
            lineLabel.widthAnchor.constraint(equalTo: column.widthAnchor),
            noteLabel.widthAnchor.constraint(equalTo: column.widthAnchor)
        ])
    }

    required init?(coder: NSCoder) { nil }

    func showOffline(_ message: String) {
        lineLabel.stringValue = message
        noteLabel.stringValue = "Not calibrated. Yaw can drift."
        calibrateButton.isEnabled = false
        for value in angleValues {
            value.stringValue = "—"
            value.textColor = SynchroTheme.muted
        }
        let names = ["Index / LEFT CLICK", "Middle / RIGHT CLICK"]
        for (index, chip) in contacts.enumerated() {
            chip.stringValue = "\(names[index]): NO SIGNAL  ·  0 taps"
            chip.textColor = SynchroTheme.muted
            chip.layer?.backgroundColor = NSColor(srgbRed: 0x25 / 255, green: 0x35 / 255, blue: 0x3a / 255, alpha: 1).cgColor
        }
    }

    func apply(_ body: [String: Any]) {
        let fresh = (body["fresh"] as? NSNumber)?.boolValue ?? (body["fresh"] as? Bool ?? false)
        let angles = (body["angles"] as? [Any])?.compactMap { ($0 as? NSNumber)?.doubleValue }
        for index in 0..<3 {
            let value = (angles?.count ?? 0) > index ? angles?[index] : nil
            angleValues[index].stringValue = Self.formatAngle(value)
            angleValues[index].textColor = value == nil ? SynchroTheme.muted : SynchroTheme.text
        }
        let counts = [
            (body["left_presses"] as? NSNumber)?.intValue ?? 0,
            (body["right_presses"] as? NSNumber)?.intValue ?? 0
        ]
        let downs: [Bool?] = ["left_down", "right_down"].map { key in
            if body[key] is NSNull || body[key] == nil { return nil }
            return (body[key] as? NSNumber)?.boolValue
        }
        let names = ["Index / LEFT CLICK", "Middle / RIGHT CLICK"]
        let now = Date().timeIntervalSince1970
        let idle = NSColor(srgbRed: 0x25 / 255, green: 0x35 / 255, blue: 0x3a / 255, alpha: 1)
        let live = NSColor(srgbRed: 0x28 / 255, green: 0x5d / 255, blue: 0x46 / 255, alpha: 1)
        let liveText = NSColor(srgbRed: 0xd2 / 255, green: 1, blue: 0xe3 / 255, alpha: 1)
        for index in 0..<2 {
            if let previous = seenPresses[index], counts[index] > previous {
                flashUntil[index] = now + 0.25
            }
            seenPresses[index] = counts[index]
            let down = downs[index]
            let text: String
            let active: Bool
            if !fresh || down == nil {
                text = "NO SIGNAL"
                active = false
            } else if down == true {
                text = "HELD"
                active = true
            } else if now < flashUntil[index] {
                text = "TAP"
                active = true
            } else {
                text = "released"
                active = false
            }
            contacts[index].stringValue = "\(names[index]): \(text)  ·  \(counts[index]) taps"
            contacts[index].textColor = active ? liveText : SynchroTheme.muted
            contacts[index].layer?.backgroundColor = (active ? live : idle).cgColor
        }
        lineLabel.stringValue = body["line"] as? String ?? "Looking for Nano USB..."
        noteLabel.stringValue = body["calibration_note"] as? String ?? "Not calibrated. Yaw can drift."
        progress.doubleValue = ((body["calibration_progress"] as? NSNumber)?.doubleValue ?? 0) * 100
        let enabled = (body["calibrate_enabled"] as? NSNumber)?.boolValue ?? false
        calibrateButton.isEnabled = enabled
    }

    private static func formatAngle(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return String(format: "%+.2f°", value)
    }
}


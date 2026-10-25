import AppKit
import WebKit

enum SynchroPage: Int {
    case camera, gestures, test, settings

    var path: String {
        switch self {
        case .camera: return "/"
        case .gestures: return "/gestures"
        case .test: return "/test"
        case .settings: return "/settings"
        }
    }

    var title: String {
        switch self {
        case .camera: return "Camera"
        case .gestures: return "Gestures"
        case .test: return "Test"
        case .settings: return "Settings"
        }
    }
}

/// Local FastAPI process used by Gestures, Test, and Settings.
/// The camera page does not need it. An already running service is left alone.
final class SynchroService {
    private var process: Process?
    private var logHandle: FileHandle?
    private var starting = false

    func ensureRunning(_ done: @escaping (String?) -> Void) {
        probe { up in
            if up {
                done(nil)
                return
            }
            if let failure = self.launch() {
                done(failure)
                return
            }
            self.wait(attempts: 40, done: done)
        }
    }

    private func probe(_ done: @escaping (Bool) -> Void) {
        guard let url = URL(string: "http://127.0.0.1:8000/api/status") else {
            done(false)
            return
        }
        URLSession.shared.dataTask(with: url) { data, response, _ in
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            done(code == 200 && data != nil)
        }.resume()
    }

    private func launch() -> String? {
        if starting || process?.isRunning == true { return nil }
        starting = true
        guard let root = Self.projectRoot() else {
            starting = false
            return "The Synchro project folder was not found next to this app."
        }
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            starting = false
            return "The local Python environment is missing. In the project folder, run python3 -m venv .venv and install requirements.txt."
        }
        let proc = Process()
        proc.executableURL = python
        proc.arguments = ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"]
        proc.currentDirectoryURL = root
        let logURL = URL(fileURLWithPath: "/tmp/synchro-api.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let handle = try? FileHandle(forWritingTo: logURL) {
            handle.seekToEndOfFile()
            logHandle = handle
            proc.standardOutput = handle
            proc.standardError = handle
        }
        do {
            try proc.run()
        } catch {
            starting = false
            return error.localizedDescription
        }
        process = proc
        starting = true
        return nil
    }

    private func wait(attempts: Int, done: @escaping (String?) -> Void) {
        probe { up in
            if up {
                self.starting = false
                done(nil)
                return
            }
            if attempts <= 0 {
                self.starting = false
                done("The local service did not answer on port 8000. See /tmp/synchro-api.log.")
                return
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + 0.25) {
                self.wait(attempts: attempts - 1, done: done)
            }
        }
    }

    static func projectRoot() -> URL? {
        let args = CommandLine.arguments
        if let flag = args.firstIndex(of: "--root"), flag + 1 < args.count {
            let url = URL(fileURLWithPath: args[flag + 1], isDirectory: true)
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("app.py").path) {
                return url
            }
        }
        var url = Bundle.main.bundleURL
        for _ in 0..<4 {
            url.deleteLastPathComponent()
            if FileManager.default.fileExists(atPath: url.appendingPathComponent("app.py").path) {
                return url
            }
        }
        return nil
    }
}

final class SynchroShell: NSObject {
    let cameraPage = NSView()
    var onPageChange: ((SynchroPage) -> Void)?
    private let webView: WKWebView
    private let webWrap = NSView()
    private let offline = NSTextField(wrappingLabelWithString: "")
    private let retry = SynchroButton.make("Retry", symbol: nil, kind: .primary)
    private var buttons: [SynchroPage: SynchroButton] = [:]
    private let service = SynchroService()
    private var page: SynchroPage = .camera
    private var loadedPath: String?

    override init() {
        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()
        webView.translatesAutoresizingMaskIntoConstraints = false
        webView.underPageBackgroundColor = SynchroTheme.bg
        retry.target = self
        retry.action = #selector(retryService)
        retry.kind = .primary
        retry.refreshFace()
    }

    func install(in content: NSView) {
        content.wantsLayer = true
        content.layer?.backgroundColor = SynchroTheme.bg.cgColor

        let sidebar = NSStackView()
        sidebar.orientation = .vertical
        sidebar.alignment = .leading
        sidebar.spacing = 4
        sidebar.edgeInsets = NSEdgeInsets(top: 22, left: 16, bottom: 28, right: 16)
        sidebar.translatesAutoresizingMaskIntoConstraints = false
        sidebar.wantsLayer = true
        sidebar.layer?.backgroundColor = SynchroTheme.panel2.cgColor

        let brand = NSTextField(labelWithString: "")
        brand.attributedStringValue = NSAttributedString(string: "Synchro", attributes: [
            .font: NSFont.systemFont(ofSize: 18, weight: .semibold),
            .foregroundColor: SynchroTheme.text,
            .kern: -0.54
        ])
        let caption = NSTextField(labelWithString: "Camera, glove, and speech")
        caption.font = .systemFont(ofSize: 12, weight: .regular)
        caption.textColor = SynchroTheme.muted
        let brandBlock = NSStackView(views: [brand, caption])
        brandBlock.orientation = .vertical
        brandBlock.alignment = .leading
        brandBlock.spacing = 2
        brandBlock.edgeInsets = NSEdgeInsets(top: 0, left: 8, bottom: 0, right: 8)
        sidebar.addArrangedSubview(brandBlock)
        sidebar.setCustomSpacing(22, after: brandBlock)

        for item in [SynchroPage.camera, .gestures, .test] {
            sidebar.addArrangedSubview(navButton(item))
        }
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .vertical)
        sidebar.addArrangedSubview(spacer)
        sidebar.addArrangedSubview(navButton(.settings))

        cameraPage.translatesAutoresizingMaskIntoConstraints = false
        webWrap.translatesAutoresizingMaskIntoConstraints = false
        offline.translatesAutoresizingMaskIntoConstraints = false
        offline.font = .systemFont(ofSize: 15, weight: .regular)
        offline.textColor = SynchroTheme.muted
        offline.alignment = .center
        offline.maximumNumberOfLines = 6
        offline.preferredMaxLayoutWidth = 460
        offline.isHidden = true
        retry.translatesAutoresizingMaskIntoConstraints = false
        retry.isHidden = true
        webWrap.addSubview(webView)
        webWrap.addSubview(offline)
        webWrap.addSubview(retry)
        webWrap.isHidden = true

        let rule = NSView()
        rule.wantsLayer = true
        rule.layer?.backgroundColor = SynchroTheme.line.cgColor
        rule.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(sidebar)
        content.addSubview(rule)
        content.addSubview(cameraPage)
        content.addSubview(webWrap)
        NSLayoutConstraint.activate([
            sidebar.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            sidebar.topAnchor.constraint(equalTo: content.topAnchor),
            sidebar.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            sidebar.widthAnchor.constraint(equalToConstant: 208),
            rule.widthAnchor.constraint(equalToConstant: 1),
            rule.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor),
            rule.topAnchor.constraint(equalTo: content.topAnchor),
            rule.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            cameraPage.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor),
            cameraPage.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            cameraPage.topAnchor.constraint(equalTo: content.topAnchor),
            cameraPage.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            webWrap.leadingAnchor.constraint(equalTo: cameraPage.leadingAnchor),
            webWrap.trailingAnchor.constraint(equalTo: cameraPage.trailingAnchor),
            webWrap.topAnchor.constraint(equalTo: cameraPage.topAnchor),
            webWrap.bottomAnchor.constraint(equalTo: cameraPage.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: webWrap.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: webWrap.trailingAnchor),
            webView.topAnchor.constraint(equalTo: webWrap.topAnchor),
            webView.bottomAnchor.constraint(equalTo: webWrap.bottomAnchor),
            offline.centerXAnchor.constraint(equalTo: webWrap.centerXAnchor),
            offline.centerYAnchor.constraint(equalTo: webWrap.centerYAnchor, constant: -20),
            offline.widthAnchor.constraint(lessThanOrEqualToConstant: 480),
            retry.topAnchor.constraint(equalTo: offline.bottomAnchor, constant: 14),
            retry.centerXAnchor.constraint(equalTo: offline.centerXAnchor)
        ])
        show(.camera)
    }

    func startService() {
        service.ensureRunning { _ in }
    }

    func show(_ next: SynchroPage) {
        page = next
        styleButtons()
        onPageChange?(next)
        if next == .camera {
            webWrap.isHidden = true
            cameraPage.isHidden = false
            return
        }
        cameraPage.isHidden = true
        webWrap.isHidden = false
        webView.isHidden = true
        offline.stringValue = "Starting the local gesture service."
        offline.isHidden = false
        retry.isHidden = true
        service.ensureRunning { [weak self] result in
            DispatchQueue.main.async {
                self?.finish(next, result)
            }
        }
    }

    private func finish(_ next: SynchroPage, _ failure: String?) {
        guard page == next else { return }
        if let failure {
            loadedPath = nil
            webView.isHidden = true
            offline.stringValue = failure
            offline.isHidden = false
            retry.isHidden = false
            return
        }
        offline.isHidden = true
        retry.isHidden = true
        webView.isHidden = false
        let path = next.path
        guard loadedPath != path, let url = URL(string: "http://127.0.0.1:8000\(path)?embed=1") else { return }
        loadedPath = path
        webView.load(URLRequest(url: url))
    }

    @objc private func retryService() {
        loadedPath = nil
        show(page)
    }

    @objc private func selectPage(_ sender: NSButton) {
        guard let next = SynchroPage(rawValue: sender.tag) else { return }
        show(next)
    }

    private func navButton(_ item: SynchroPage) -> SynchroButton {
        let button = SynchroButton.make(item.title, symbol: nil, kind: .nav)
        button.tag = item.rawValue
        button.target = self
        button.action = #selector(selectPage(_:))
        button.translatesAutoresizingMaskIntoConstraints = false
        button.widthAnchor.constraint(equalToConstant: 176).isActive = true
        button.heightAnchor.constraint(equalToConstant: 38).isActive = true
        buttons[item] = button
        return button
    }

    private func styleButtons() {
        for (item, button) in buttons {
            button.chosen = item == page
        }
    }
}

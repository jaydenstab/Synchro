"""Windows Bluetooth Classic camera, published on the Mac viewer's localhost bridge.

The React camera page reads `127.0.0.1:8765` on both operating systems.
macOS keeps using `camera/synchro_mac` because Python cannot open RFCOMM there.
This module does not open a Tk window.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADDRESS = '70:4B:CA:46:52:22'


def camera_target() -> tuple[str, int]:
    data: dict = {}
    for path in (ROOT / 'bluetooth-camera.example.json', ROOT / '.local' / 'bluetooth-camera.json'):
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            data.update(loaded)
    address = os.environ.get('SYNCHRO_BT_ADDRESS', '').strip() or str(data.get('bt_address') or DEFAULT_ADDRESS)
    raw_channel = os.environ.get('SYNCHRO_BT_CHANNEL', '').strip() or data.get('bt_channel') or 1
    try:
        channel = int(raw_channel)
    except (TypeError, ValueError):
        channel = 1
    return address, channel


class WindowsCameraBridge:
    def __init__(self, address: str, channel: int, port: int = 8765) -> None:
        self.address = address
        self.channel = channel
        self.port = port
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._server: ThreadingHTTPServer | None = None
        self._connected = False
        self._status = 'Windows camera idle'
        self._jpeg: bytes | None = None
        self._width = 0
        self._height = 0
        self._captured_at = 0.0

    @classmethod
    def from_env(cls) -> 'WindowsCameraBridge':
        address, channel = camera_target()
        port = int(os.environ.get('SYNCHRO_CAMERA_BRIDGE_PORT', '8765') or '8765')
        return cls(address, channel, port)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        try:
            self._server = ThreadingHTTPServer(('127.0.0.1', self.port), self._handler())
        except OSError as exc:
            self._status = f'Camera bridge port {self.port} is already in use: {exc}'
            return
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, name='synchro-camera-http', daemon=True).start()
        self._thread = threading.Thread(target=self._capture_loop, name='synchro-camera-bt', daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:
                return

            def do_GET(self) -> None:
                path = self.path.split('?', 1)[0]
                now = time.time()
                if path == '/status':
                    payload = json.dumps(bridge.status_body(now)).encode()
                    self._send(200, 'application/json; charset=utf-8', payload)
                    return
                if path == '/frame.jpg':
                    frame = bridge.frame(now)
                    if frame is None:
                        body = b'{"error":"camera_unavailable","message":"The Windows camera service has no live JPEG."}'
                        self._send(503, 'application/json; charset=utf-8', body)
                        return
                    self._send(200, 'image/jpeg', frame)
                    return
                self._send(404, 'application/json; charset=utf-8', b'{"error":"not_found"}')

            def _send(self, status: int, content_type: str, payload: bytes) -> None:
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(payload)

        return Handler

    def status_body(self, now: float | None = None) -> dict:
        moment = time.time() if now is None else now
        with self._lock:
            age = moment - self._captured_at if self._jpeg else None
            fresh = self._connected and self._jpeg is not None and age is not None and age <= 4
            return {
                'service': 'synchro-camera-bridge',
                'available': True,
                'connected': self._connected,
                'has_frame': fresh,
                'age_ms': None if age is None else int(max(0, age * 1000)),
                'width': self._width if fresh else 0,
                'height': self._height if fresh else 0,
                'transport': 'bluetooth-classic-rfcomm',
                'simulated': False,
                'viewer': 'windows',
                'status': self._status,
            }

    def frame(self, now: float | None = None) -> bytes | None:
        moment = time.time() if now is None else now
        with self._lock:
            if not self._connected or self._jpeg is None:
                return None
            if moment - self._captured_at > 4:
                return None
            return self._jpeg

    def _capture_loop(self) -> None:
        from motion.host import ensure_tools_path
        ensure_tools_path()
        try:
            from bluetooth_viewer import Camera
        except Exception as exc:
            with self._lock:
                self._status = f'Windows camera dependencies are missing: {exc}'
            return
        camera = None
        while not self._stop.is_set():
            try:
                if camera is None:
                    with self._lock:
                        self._connected = False
                        self._status = f'Connecting to Synchro-Cam-BT {self.address}'
                    camera = Camera(self.address, self.channel)
                    camera.connect()
                    with self._lock:
                        self._connected = True
                        self._status = 'Bluetooth camera connected'
                began = time.perf_counter()
                shot = camera.capture()
                with self._lock:
                    self._jpeg = shot.jpeg
                    self._width, self._height = shot.image.size
                    self._captured_at = time.time()
                    self._connected = True
                    self._status = 'Live Bluetooth camera'
                wait = max(0.0, (1 / 15) - (time.perf_counter() - began))
                self._stop.wait(wait)
            except Exception as exc:
                with self._lock:
                    self._connected = False
                    self._jpeg = None
                    self._status = str(exc)
                if camera is not None:
                    try:
                        camera.close()
                    except Exception:
                        pass
                    camera = None
                self._stop.wait(1.5)
        if camera is not None:
            try:
                camera.close()
            except Exception:
                pass

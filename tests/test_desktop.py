"""Shared desktop window. Camera bytes are synthetic. No radio is opened."""
import json

import pytest

from desktop.camera_link import (
    ProtocolError,
    Reader,
    bluetooth_available,
    camera_limitation,
    capture_frame,
    handshake,
    open_bluetooth,
)
from desktop.present import contact_line, format_angle, format_axis
from desktop.window import SynchroWindow
from motion.service import MotionService


class FakeSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)
        self.sent = b''

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, _size: int) -> bytes:
        if not self.chunks:
            return b''
        return self.chunks.pop(0)

    def settimeout(self, _seconds: float) -> None:
        return None

    def close(self) -> None:
        return None


def jpeg_frame(width: int = 640, height: int = 480) -> bytes:
    jpeg = b'\xff\xd8' + b'\x00' * 16 + b'\xff\xd9'
    header = f'JPEG_BEGIN {len(jpeg)} {width} {height}\n'.encode()
    return header + jpeg + b'\nJPEG_END\n'


def test_bluetooth_socket_follows_the_operating_system():
    if bluetooth_available():
        assert camera_limitation() is None
        return
    assert camera_limitation()
    with pytest.raises(OSError, match='Bluetooth Classic'):
        open_bluetooth()


def test_status_and_capture_parse_one_frame():
    status = json.dumps({'firmware': 'bluetooth-2', 'camera_ready': True}).encode() + b'\n'
    sock = FakeSocket([status, jpeg_frame()])
    parsed, reader = handshake(sock)
    assert sock.sent == b'STATUS\n'
    assert parsed['camera_ready'] is True
    jpeg, width, height, seconds = capture_frame(sock, reader)
    assert jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
    assert (width, height) == (640, 480)
    assert seconds >= 0
    assert sock.sent.endswith(b'CAPTURE\n')


def test_bad_firmware_and_bad_trailer_are_rejected():
    status = b'{"firmware":"other","camera_ready":true}\n'
    with pytest.raises(ProtocolError):
        handshake(FakeSocket([status]))
    good = json.dumps({'firmware': 'bluetooth-2', 'camera_ready': True}).encode() + b'\n'
    sock = FakeSocket([good, b'JPEG_BEGIN 6 640 480\n\xff\xd8\x00\x00\xff\xd9NOT_END!!!'])
    _status, reader = handshake(sock)
    with pytest.raises(ProtocolError):
        capture_frame(sock, reader)


def test_data_page_shows_windows_glove_readings(tmp_path):
    tkinter = pytest.importorskip('tkinter')
    root = tkinter.Tk()
    root.withdraw()
    try:
        motion = MotionService(tmp_path)
        window = SynchroWindow(motion, root)
        window.show('data')
        assert window.page == 'data'
        assert window.angle_values[0].cget('text') == '—'
        assert 'NO SIGNAL' in window.contact_values[0].cget('text')
        assert window.calibration_note.cget('text') == 'Not calibrated. Yaw can drift.'
        assert 'Packet errors 0' in window.test_line.cget('text')
        if not bluetooth_available():
            window.start_camera()
            assert window._camera['running'] is False
            assert 'Bluetooth Classic' in window._camera['message']
    finally:
        root.destroy()


def test_reader_rejects_a_missing_header():
    reader = Reader(FakeSocket([b'x' * 600]))
    with pytest.raises(ProtocolError):
        reader.line()


def test_present_matches_the_windows_labels():
    assert format_angle(None) == '—'
    assert format_angle(1.2) == '+1.20°'
    assert format_axis(-0.5) == '-0.500'
    text, active = contact_line('Index / LEFT CLICK', True, True, 2, False)
    assert text == 'Index / LEFT CLICK: HELD  ·  2 taps'
    assert active is True

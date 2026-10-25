"""Bluetooth Classic camera session used by the desktop window.

The command stream is the same STATUS / CAPTURE protocol as the Mac viewer
and the Windows viewer. Python exposes RFCOMM sockets on Windows. It does not
on macOS, so this module refuses to pretend a radio is open there.
"""
from __future__ import annotations

import json
import re
import socket
import time

ADDRESS = '70:4B:CA:46:52:22'
CHANNEL = 1
FRAME_SIZES = {(320, 240), (640, 480)}


class ProtocolError(Exception):
    pass


def bluetooth_available() -> bool:
    return hasattr(socket, 'AF_BLUETOOTH') and hasattr(socket, 'BTPROTO_RFCOMM')


def camera_limitation() -> str | None:
    if bluetooth_available():
        return None
    return (
        'Python on this operating system cannot open Bluetooth Classic. '
        'The Data page still reads the glove over USB. '
        'On a Mac, the camera radio stays in the Synchro window.'
    )


class Reader:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.buffer = bytearray()

    def receive(self) -> None:
        block = self.connection.recv(8192)
        if not block:
            raise ConnectionError('Camera disconnected')
        self.buffer.extend(block)

    def line(self) -> bytes:
        while True:
            end = self.buffer.find(b'\n')
            if end >= 0:
                if end > 512:
                    raise ProtocolError('Oversized response header')
                result = bytes(self.buffer[:end]).rstrip(b'\r')
                del self.buffer[:end + 1]
                return result
            if len(self.buffer) > 512:
                raise ProtocolError('Missing response header')
            self.receive()

    def exact(self, length: int) -> bytes:
        while len(self.buffer) < length:
            self.receive()
        result = bytes(self.buffer[:length])
        del self.buffer[:length]
        return result


def open_bluetooth(address: str = ADDRESS, channel: int = CHANNEL):
    limitation = camera_limitation()
    if limitation:
        raise OSError(limitation)
    connection = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    connection.settimeout(12)
    connection.connect((address, channel))
    connection.settimeout(6)
    return connection


def handshake(connection) -> tuple[dict, Reader]:
    reader = Reader(connection)
    connection.sendall(b'STATUS\n')
    status = json.loads(reader.line())
    if status.get('firmware') not in ('bluetooth-1', 'bluetooth-2') or not status.get('camera_ready'):
        raise ProtocolError('The Bluetooth camera firmware is not ready')
    return status, reader


def capture_frame(connection, reader: Reader) -> tuple[bytes, int, int, float]:
    began = time.perf_counter()
    connection.sendall(b'CAPTURE\n')
    header = reader.line()
    match = re.fullmatch(rb'JPEG_BEGIN (\d+) (\d+) (\d+)', header)
    if not match:
        raise ProtocolError('Camera did not return a photo')
    length, width, height = (int(part) for part in match.groups())
    if not 4 <= length <= 1_000_000 or (width, height) not in FRAME_SIZES:
        raise ProtocolError('Invalid frame size')
    jpeg = reader.exact(length)
    if reader.exact(10) != b'\nJPEG_END\n':
        raise ProtocolError('Incomplete frame trailer')
    if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
        raise ProtocolError('Invalid JPEG markers')
    return jpeg, width, height, time.perf_counter() - began

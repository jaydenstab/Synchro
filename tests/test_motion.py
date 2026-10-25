"""Glove metrics. Packets are synthetic bytes, not a claim about a physical MPU."""
import math
import struct
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from motion.synimu import HEADER, MAGIC, SAMPLE, Orientation, PacketReader, calibration_report, scaled


def make_packet(rows=((0, 0, 8192, 0, 0, 0),), contacts=0, left=0, right=0, ready=1, count=None):
    body = HEADER.pack(
        1, 0, 12345678, len(rows) if count is None else count,
        0, contacts, ready, left, right, 0, 0, 0,
    )
    body += b''.join(SAMPLE.pack(*row) for row in rows)
    return MAGIC + struct.pack('<H', len(body)) + body + struct.pack('<I', zlib.crc32(body))


def test_fragmented_packet_reports_level_angles_and_index_contact(tmp_path: Path):
    client_app = create_app(tmp_path)
    motion = client_app.state.motion
    blob = b'boot text\r\n' + make_packet(contacts=1, left=4, right=2)
    for size in (1, 7, 20):
        step = PacketReader()
        packets = []
        for start in range(0, len(blob), size):
            packets.extend(step.feed(blob[start:start + size]))
        assert len(packets) == 1
        assert scaled(packets[0].samples[0])[:3] == (0, 0, 1)

    motion.ingest_bytes(blob, now=50, transport='USB')
    motion.ingest_bytes(make_packet(contacts=1, left=4, right=2), now=50.4, transport='USB')
    body = motion.snapshot(now=50.4)
    assert body['simulated'] is False
    assert body['fresh'] is True
    assert body['ready'] is True
    assert body['left_down'] is True
    assert body['right_down'] is False
    assert body['left_presses'] == 4
    assert body['right_presses'] == 2
    assert body['angles'] is not None
    assert abs(body['angles'][0]) < 0.01
    assert abs(body['angles'][1]) < 0.01
    assert 'USB' in body['line']
    assert 'samples/s' in body['line']
    assert '°C' in body['line']
    assert body['packet_errors'] == 0
    assert body['axes'] is not None
    assert abs(body['axes'][2] - 1) < 1e-9
    assert body['calibration_note'] == 'Not calibrated. Yaw can drift.'
    assert body['calibrate_enabled'] is True


def test_corrupt_packet_is_dropped_and_idle_panel_stays_empty(tmp_path: Path):
    motion = create_app(tmp_path).state.motion
    bad = bytearray(make_packet())
    bad[25] ^= 0xFF
    motion.ingest_bytes(bytes(bad), now=10, transport='USB')
    body = motion.snapshot(now=10)
    assert body['angles'] is None
    assert body['fresh'] is False
    assert body['line'] == 'Looking for Nano USB...'

    with TestClient(create_app(tmp_path)) as client:
        idle = client.get('/api/motion')
        assert idle.status_code == 200
        payload = idle.json()
        assert payload['angles'] is None
        assert payload['left_down'] is None
        assert payload['calibration_note'] == 'Not calibrated. Yaw can drift.'
        assert payload['simulated'] is False
        refused = client.post('/api/motion/calibrate')
        assert refused.status_code == 400
        assert 'No fresh MPU data' in refused.json()['detail']


def test_stale_link_hides_angles_but_keeps_tap_counts(tmp_path: Path):
    motion = create_app(tmp_path).state.motion
    motion.ingest_bytes(make_packet(contacts=2, left=1, right=9), now=5, transport='USB')
    hidden = motion.snapshot(now=6)
    assert hidden['fresh'] is False
    assert hidden['angles'] is None
    assert hidden['left_down'] is None
    assert hidden['right_presses'] == 9


def test_known_tilt_and_stationary_bias_report():
    roll, pitch = 30, -25
    r, p = math.radians(roll), math.radians(pitch)
    gravity = (-math.sin(p), math.sin(r) * math.cos(p), math.cos(r) * math.cos(p))
    filt = Orientation()
    for _ in range(200):
        filt.update((*gravity, 0, 0, 0))
    actual = filt.angles()
    assert actual is not None
    assert abs(abs(actual[0]) - abs(roll)) < 1e-6
    assert abs(actual[1] - pitch) < 1e-6

    rows = [(0, 0, 1, -1.0, 0.1, -0.2, 30.0) for _ in range(15000)]
    report = calibration_report(rows, 15)
    assert report['passed'] is True
    assert abs(report['bias_dps'][0] + 1.0) < 1e-9

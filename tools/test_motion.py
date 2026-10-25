"""Synthetic numerical/protocol regressions; these do NOT calibrate hardware."""
import math
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zlib

from motion_core import (MAGIC, HEADER, SAMPLE, Orientation, PacketReader,
                         calibration_report, scaled)
from motion_sensor import MotionSensor


def make_packet(rows=((0, 0, 8192, 0, 0, 0),), contacts=0, left=0, right=0, count=None):
    body = HEADER.pack(1, 0, 12345678, len(rows) if count is None else count,
                       0, contacts, 1, left, right, 1, 0, 0)
    body += b''.join(SAMPLE.pack(*row) for row in rows)
    return MAGIC + struct.pack('<H', len(body)) + body + struct.pack('<I', zlib.crc32(body))


class ProtocolTests(unittest.TestCase):
    def test_fragmentation_and_coalescing(self):
        data = b'ESP32 boot text\r\n' + make_packet(contacts=3, left=17, right=42) * 2
        for chunk in (1, 7, 64, 4096):
            decoder = PacketReader()
            packets = []
            for start in range(0, len(data), chunk):
                packets.extend(decoder.feed(data[start:start + chunk]))
            self.assertEqual(len(packets), 2)
            self.assertEqual(packets[0].contacts, 3)
            self.assertEqual(packets[0].right_presses, 42)
            self.assertEqual(scaled(packets[0].samples[0]), (0, 0, 1, 0, 0, 0))

    def test_corruption_resynchronizes(self):
        bad = bytearray(make_packet())
        bad[25] ^= 0xFF
        decoder = PacketReader()
        packets = decoder.feed(bad + make_packet())
        self.assertEqual(len(packets), 1)
        self.assertEqual(decoder.errors, 1)

    def test_bad_count_and_length(self):
        decoder = PacketReader()
        self.assertEqual(decoder.feed(make_packet(count=17)), [])
        self.assertEqual(decoder.feed(MAGIC + b'\xff\xff' + b'noise' + make_packet())[0].count, 1)
        self.assertEqual(decoder.errors, 2)

    def test_signed_axes_and_latched_tap_counts(self):
        row = (-8192, 4096, 0, -655, 6550, -32768)
        p = PacketReader().feed(make_packet((row,), left=4, right=8))[0]
        self.assertEqual(p.samples[0], row)
        self.assertEqual(p.contacts, 0)  # Tap counts survive release before next UI refresh.
        self.assertEqual(p.left_presses, 4)
        self.assertAlmostEqual(scaled(row)[3], -10)

    def test_bounded_garbage(self):
        decoder = PacketReader()
        self.assertEqual(decoder.feed(b'x' * 100000), [])
        self.assertLess(len(decoder.buffer), len(MAGIC))


class OrientationTests(unittest.TestCase):
    def test_known_tilts_and_upside_down(self):
        for roll, pitch in ((0, 0), (30, -25), (-60, 45), (180, 0)):
            r, p = math.radians(roll), math.radians(pitch)
            gravity = (-math.sin(p), math.sin(r) * math.cos(p), math.cos(r) * math.cos(p))
            f = Orientation()
            for _ in range(1000):
                f.update((*gravity, 0, 0, 0))
            actual = f.angles()
            self.assertAlmostEqual(abs(actual[0]), abs(roll), places=8)
            self.assertAlmostEqual(actual[1], pitch, places=8)

    def test_yaw_rotation_and_double_precision_norm(self):
        f = Orientation()
        for _ in range(1000):
            f.update((0, 0, 1, 0, 0, 90))
        self.assertAlmostEqual(f.angles()[2], 90, places=8)
        self.assertAlmostEqual(sum(v * v for v in f.q), 1, places=14)

    def test_roll_rotation_uses_body_axis_gyro(self):
        f = Orientation()
        f.update((0, 0, 1, 0, 0, 0))
        for i in range(1000):
            angle = math.radians(45 * i / 1000)
            f.update((0, math.sin(angle), math.cos(angle), 45, 0, 0))
        self.assertAlmostEqual(f.angles()[0], 45, places=7)

    def test_bias_removed_but_uncalibrated_yaw_not_hidden(self):
        f = Orientation(bias=(-4.4, 0.1, 0.2))
        uncorrected = Orientation()
        for _ in range(15000):
            f.update((0, 0, 1, -4.4, 0.1, 0.2))
            uncorrected.update((0, 0, 1, 0, 0, 0.2))
        self.assertAlmostEqual(max(abs(a) for a in f.angles()), 0, places=10)
        self.assertAlmostEqual(uncorrected.angles()[2], 3, places=9)

    def test_linear_acceleration_gate(self):
        f = Orientation()
        f.update((0, 0, 1, 0, 0, 0))
        for _ in range(1000):
            f.update((1, 0, 1, 0, 0, 0))
        self.assertEqual(f.angles(), (0, 0, 0))

    def test_freefall_does_not_create_an_angle(self):
        f = Orientation()
        f.update((0, 0, 0, 0, 0, 0))
        self.assertIsNone(f.angles())


class CalibrationTests(unittest.TestCase):
    def stationary(self):
        return [(0, 0, 1, -4.4 + (i % 2) * 0.02, 0.1, -0.2, 30) for i in range(15000)]

    def test_stationary_bias_and_holdout(self):
        report = calibration_report(self.stationary(), 15)
        self.assertTrue(report['passed'])
        self.assertAlmostEqual(report['bias_dps'][0], -4.39)
        self.assertLess(max(abs(v) for v in report['validation_last_3s_residual_dps']), 1e-10)

    def test_movement_rejected(self):
        rows = self.stationary()
        rows[7500] = (0.5, 0, 0.8, 40, 0, 0, 30)
        self.assertFalse(calibration_report(rows, 15)['passed'])

    def test_drifting_bias_rejected(self):
        rows = [(0, 0, 1, -4.4 + i * 0.0001, 0, 0, 30) for i in range(15000)]
        report = calibration_report(rows, 15)
        self.assertFalse(report['passed'])
        self.assertTrue(any('Bias changed' in s for s in report['failures']))

    def test_missing_samples_and_bad_timing(self):
        with self.assertRaises(ValueError):
            calibration_report(self.stationary()[:-1], 15)
        self.assertFalse(calibration_report(self.stationary(), 25)['passed'])

    def test_request_refuses_missing_or_stale_hardware(self):
        sensor = MotionSensor()
        with self.assertRaises(ValueError):
            sensor.request_calibration()
        sensor._set(ready=True, angles=(1, 2, 3), left_down=True, received_at=1.0)
        self.assertIsNone(sensor.snapshot()['angles'])
        self.assertIsNone(sensor.snapshot()['left_down'])
        with self.assertRaises(ValueError):
            sensor.request_calibration()


class ClippingTests(unittest.TestCase):
    def test_clipping_resets_once_per_episode_then_valid_samples_recover(self):
        sensor = MotionSensor()
        normal = PacketReader().feed(make_packet())[0]
        clipped = PacketReader().feed(make_packet(((0, 0, 8192, 32767, 0, 0),) * 10))[0]
        self.assertFalse(sensor._consume_samples(normal))
        for _ in range(20):
            self.assertTrue(sensor._consume_samples(clipped))
        self.assertIsNone(sensor.filter.angles())
        self.assertEqual(sensor.state['orientation_version'], 1)
        self.assertEqual(sensor.state['clipped_samples'], 200)
        self.assertEqual(sensor.state['last_orientation_reset'], 'Sensor measurement range exceeded')
        self.assertFalse(sensor._consume_samples(normal))
        self.assertEqual(sensor.filter.angles(), (0, 0, 0))
        self.assertFalse(sensor.state['range_exceeded'])
        sensor._consume_samples(clipped)
        self.assertEqual(sensor.state['orientation_version'], 2)

    def test_clipping_still_rejects_stationary_calibration(self):
        sensor = MotionSensor()
        sensor.cal = {'id': 'test', 'rows': []}
        packet = PacketReader().feed(make_packet(((0, 0, 32767, 0, 0, 0),)))[0]
        self.assertTrue(sensor._consume_samples(packet))
        self.assertIsNone(sensor.cal)
        self.assertEqual(sensor.state['calibration']['state'], 'failed')


class ControlTests(unittest.TestCase):
    def test_readiness_is_read_only_and_stale_start_rejected(self):
        # Separate in-process test server: never accesses real serial hardware.
        with tempfile.TemporaryDirectory() as folder:
            sensor = MotionSensor()
            with patch('motion_sensor.CONTROL_FILE', Path(folder) / 'control.json'):
                sensor._start_control_server()
                try:
                    base = f'http://127.0.0.1:{sensor.server.server_port}'
                    headers = {'X-Synchro-Token': sensor.token}
                    with urlopen(Request(base + '/status', headers=headers)) as response:
                        self.assertEqual(json.load(response)['calibration']['state'], 'idle')
                    self.assertTrue(sensor.commands.empty())
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/calibrate', headers=headers, method='POST'))
                    self.assertEqual(error.exception.code, 409)
                    self.assertTrue(sensor.commands.empty())
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/status'))
                    self.assertEqual(error.exception.code, 403)
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/status', headers={**headers, 'Origin': 'https://example.org'}))
                    self.assertEqual(error.exception.code, 403)
                finally:
                    sensor.server.shutdown()
                    sensor.server.server_close()


if __name__ == '__main__':
    unittest.main()

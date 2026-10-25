"""MPU packet decoding, float64 orientation, and stationary bias validation.

Python floats are IEEE-754 doubles. Orientation is body-to-world; +Z is up.
The six-axis IMU has no absolute yaw reference. See firmware/MOTION.md.
"""
from dataclasses import dataclass
import math
import statistics
import struct
import zlib

MAGIC = b'SYNIMU1\n'
HEADER = struct.Struct('<IIQHhBBIIIII')
SAMPLE = struct.Struct('<6h')
SAMPLE_HZ = 1000
CALIBRATION_SAMPLES = 15 * SAMPLE_HZ


@dataclass(frozen=True)
class Packet:
    sequence: int
    first_sample: int
    time_us: int
    count: int
    temperature_raw: int
    contacts: int
    ready: int
    left_presses: int
    right_presses: int
    fifo_resets: int
    i2c_errors: int
    reserved: int
    samples: tuple

    @property
    def temperature_c(self):
        return self.temperature_raw / 340.0 + 36.53


class PacketReader:
    def __init__(self):
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, data):
        self.buffer.extend(data)
        packets = []
        while True:
            start = self.buffer.find(MAGIC)
            if start < 0:
                # Keep a possible fragmented magic prefix, discard boot text.
                self.buffer[:] = self.buffer[-(len(MAGIC) - 1):]
                break
            del self.buffer[:start]
            if len(self.buffer) < 10:
                break
            size, = struct.unpack_from('<H', self.buffer, 8)
            if not HEADER.size <= size <= HEADER.size + 16 * SAMPLE.size:
                self.errors += 1
                del self.buffer[0]
                continue
            total = 10 + size + 4
            if len(self.buffer) < total:
                break
            body = bytes(self.buffer[10:10 + size])
            crc, = struct.unpack_from('<I', self.buffer, 10 + size)
            if zlib.crc32(body) != crc:
                self.errors += 1
                del self.buffer[0]
                continue
            values = HEADER.unpack_from(body)
            count = values[3]
            if (count > 16 or size != HEADER.size + count * SAMPLE.size or
                    values[5] > 3 or values[6] not in (0, 1)):
                self.errors += 1
                del self.buffer[:total]
                continue
            rows = tuple(SAMPLE.iter_unpack(body[HEADER.size:]))
            packets.append(Packet(*values, rows))
            del self.buffer[:total]
        return packets


def scaled(raw):
    return tuple(v / 8192.0 for v in raw[:3]) + tuple(v / 65.5 for v in raw[3:])


def gravity_angles(accel):
    ax, ay, az = accel
    return math.atan2(ay, az), math.atan2(-ax, math.hypot(ay, az))


class Orientation:
    """Quaternion complementary filter; no hidden yaw zero-velocity clamp.

    Fixed dt follows FIFO sample order, not USB delivery jitter. Acceleration
    correction fades between 0.05g and 0.20g deviation from gravity. This
    cannot distinguish all sustained linear accelerations from tilt.
    """
    def __init__(self, bias=(0.0, 0.0, 0.0), kp=2.0):
        self.bias = tuple(bias)
        self.kp = kp
        self.q = None

    def reset(self):
        self.q = None

    def update(self, values, dt=1.0 / SAMPLE_HZ):
        ax, ay, az, gx, gy, gz = values
        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if self.q is None:
            if norm < 0.5:
                return
            roll, pitch = gravity_angles((ax, ay, az))
            cr, sr = math.cos(roll / 2), math.sin(roll / 2)
            cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
            self.q = (cr * cp, sr * cp, cr * sp, -sr * sp)
        w, x, y, z = self.q
        wx, wy, wz = (math.radians(g - b) for g, b in zip((gx, gy, gz), self.bias))
        trust = max(0.0, min(1.0, (0.20 - abs(norm - 1.0)) / 0.15))
        if trust and norm > 0:
            ax, ay, az = ax / norm, ay / norm, az / norm
            vx, vy, vz = 2 * (x * z - w * y), 2 * (w * x + y * z), 1 - 2 * (x * x + y * y)
            gain = self.kp * trust
            wx += gain * (ay * vz - az * vy)
            wy += gain * (az * vx - ax * vz)
            wz += gain * (ax * vy - ay * vx)
        speed = math.sqrt(wx * wx + wy * wy + wz * wz)
        half = 0.5 * speed * dt
        factor = math.sin(half) / speed if speed > 1e-12 else 0.5 * dt
        dw, dx, dy, dz = math.cos(half), wx * factor, wy * factor, wz * factor
        q = (w * dw - x * dx - y * dy - z * dz,
             w * dx + x * dw + y * dz - z * dy,
             w * dy - x * dz + y * dw + z * dx,
             w * dz + x * dy - y * dx + z * dw)
        length = math.sqrt(sum(v * v for v in q))
        self.q = tuple(v / length for v in q)

    def angles(self):
        if self.q is None:
            return None
        w, x, y, z = self.q
        return tuple(math.degrees(v) for v in (
            math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)),
            math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))),
            math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))))


def calibration_report(rows, elapsed_seconds):
    """rows: ax,ay,az,gx,gy,gz,temp. Final 3s validate first 12s bias.

    If accepted, all 15s estimate the saved bias. The held-out result is
    explicitly a check of the 12s provisional bias, not an independent test
    of the final 15s fit. Slow constant yaw rotation is unobservable here.
    """
    if len(rows) < CALIBRATION_SAMPLES:
        raise ValueError('Need 15,000 uninterrupted samples for calibration')
    rows = rows[:CALIBRATION_SAMPLES]
    columns = list(zip(*rows))
    means = [statistics.fmean(c) for c in columns]
    std = [statistics.stdev(c) for c in columns]
    ranges = [max(c) - min(c) for c in columns]
    norms = [math.sqrt(sum(v * v for v in row[:3])) for row in rows]
    provisional = [statistics.fmean(c[:12000]) for c in columns[3:6]]
    held_out = [statistics.fmean(c[12000:]) for c in columns[3:6]]
    residual = [a - b for a, b in zip(held_out, provisional)]
    failures = []
    if not 13.5 <= elapsed_seconds <= 17.0:
        failures.append('Sample timing is outside the expected 1 kHz range')
    if not 0.85 <= statistics.fmean(norms) <= 1.15:
        failures.append('Acceleration magnitude is not close to 1 g')
    if max(std[:3]) > 0.02 or max(ranges[:3]) > 0.15:
        failures.append('Accelerometer detected movement or vibration')
    if max(std[3:6]) > 0.35 or max(ranges[3:6]) > 3.0:
        failures.append('Gyroscope detected movement or excessive noise')
    if max(abs(v) for v in means[3:6]) > 20:
        failures.append('Angular rate is too large for a stationary bias')
    if max(abs(v) for v in residual) > 0.15:
        failures.append('Bias changed between the first 12s and final 3s')
    if ranges[6] > 2:
        failures.append('Temperature changed more than 2 C; warm up and retry')
    return {
        'passed': not failures, 'failures': failures,
        'samples': len(rows), 'elapsed_seconds': elapsed_seconds,
        'bias_dps': means[3:6], 'gyro_std_dps': std[3:6],
        'accel_std_g': std[:3], 'gravity_norm_g': statistics.fmean(norms),
        'temperature_c': means[6], 'temperature_span_c': ranges[6],
        'uncorrected_axis_drift_deg_per_min': [v * 60 for v in means[3:6]],
        'validation_bias_first_12s_dps': provisional,
        'validation_last_3s_residual_dps': residual,
        'validation_axis_drift_deg_per_min': [v * 60 for v in residual],
        'note': 'Stationary gyro bias only. No absolute yaw or six-pose accelerometer calibration.',
    }

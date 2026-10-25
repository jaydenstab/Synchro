"""SYNIMU1 decode and orientation. Matches NanoMotionAngles on the glove.

Python floats are IEEE-754 doubles. Orientation is body-to-world; +Z is up.
The six-axis IMU has no absolute yaw reference. Acceleration counts are
±4 g (8192 per g). Gyro counts are ±500 deg/s (65.5 per deg/s).
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
PROFILE_SCHEMA = 'mpu6050-4g-500dps-98hz-1000hz-v1'


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
    def temperature_c(self) -> float:
        return self.temperature_raw / 340.0 + 36.53


class PacketReader:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.errors = 0

    def feed(self, data: bytes) -> list[Packet]:
        self.buffer.extend(data)
        packets: list[Packet] = []
        while True:
            start = self.buffer.find(MAGIC)
            if start < 0:
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


def scaled(raw: tuple) -> tuple[float, float, float, float, float, float]:
    return tuple(v / 8192.0 for v in raw[:3]) + tuple(v / 65.5 for v in raw[3:])


def gravity_angles(accel: tuple[float, float, float]) -> tuple[float, float]:
    ax, ay, az = accel
    return math.atan2(ay, az), math.atan2(-ax, math.hypot(ay, az))


class Orientation:
    """Quaternion complementary filter. Yaw is not clamped to hide drift."""

    def __init__(self, bias: tuple[float, float, float] = (0.0, 0.0, 0.0), kp: float = 2.0) -> None:
        self.bias = tuple(bias)
        self.kp = kp
        self.q: tuple[float, float, float, float] | None = None

    def reset(self) -> None:
        self.q = None

    def update(self, values: tuple[float, ...], dt: float = 1.0 / SAMPLE_HZ) -> None:
        ax, ay, az, gx, gy, gz = values
        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if self.q is None:
            if norm < 0.5:
                return
            roll, pitch = gravity_angles((ax, ay, az))
            cr, sr = math.cos(roll / 2), math.sin(roll / 2)
            cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
            self.q = (cr * cp, sr * cp, cr * sp, -sr * sp)
        assert self.q is not None
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

    def angles(self) -> tuple[float, float, float] | None:
        if self.q is None:
            return None
        w, x, y, z = self.q
        return tuple(math.degrees(v) for v in (
            math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)),
            math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))),
            math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)),
        ))


def calibration_report(rows: list[tuple], elapsed_seconds: float) -> dict:
    """rows: ax, ay, az in g, gx, gy, gz in deg/s, temp C. Final 3s check the first 12s."""
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
        'passed': not failures,
        'failures': failures,
        'samples': len(rows),
        'elapsed_seconds': elapsed_seconds,
        'bias_dps': means[3:6],
        'temperature_c': means[6],
        'note': 'Stationary gyro bias only. No absolute yaw or six-pose accelerometer calibration.',
    }

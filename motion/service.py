"""Live glove metrics shared by the Mac window and the browser on either OS.

The running service uses the teammate stack in tools/: USB or Bluetooth LE,
stationary calibration, the Windows pointer, and local speech. Packet injection
below is for tests. Angles stay empty until a real packet arrives.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path

from motion.synimu import (
    CALIBRATION_SAMPLES,
    PROFILE_SCHEMA,
    Orientation,
    Packet,
    PacketReader,
    calibration_report,
    scaled,
)

FRESH_SECONDS = 0.5
CLIP = 32760


class MotionService:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.profile_path = self.data_dir / 'mpu-calibration.json'
        self._lock = threading.Lock()
        self._reader = PacketReader()
        self._filter = Orientation()
        self._status = 'Looking for Nano USB...'
        self._transport: str | None = None
        self._connected = False
        self._ready = False
        self._last_rx = 0.0
        self._link_started: float | None = None
        self._temperature: float | None = None
        self._left_down = False
        self._right_down = False
        self._left_presses = 0
        self._right_presses = 0
        self._tracking_restarts = 0
        self._seen_packet = False
        self._fifo_resets = 0
        self._i2c_errors = 0
        self._range_exceeded = False
        self._calibrated = False
        self._calibration: dict = {'state': 'idle', 'progress': 0.0, 'message': None}
        self._rows: list[tuple] | None = None
        self._cal_started = 0.0
        self._marks: deque[tuple[float, int]] = deque()
        self._sample_total = 0
        self._sample_hz = 0.0
        self._packet_errors = 0
        self._axes: tuple[float, float, float, float, float, float] | None = None
        self._hardware = None
        self._speech = None
        self._load_profile()

    def start_usb(self) -> None:
        """Open the glove over USB or BLE and start pointer control."""
        if self._hardware is not None:
            return
        from motion.host import session_from_env
        self._hardware = session_from_env()
        self._speech = self._hardware.speech
        self._hardware.start()

    def close(self) -> None:
        hardware = self._hardware
        self._hardware = None
        if hardware is not None:
            hardware.close()
        if self._speech is not None and hardware is None:
            self._speech.stop()

    def ingest_bytes(self, data: bytes, *, now: float | None = None, transport: str | None = None) -> None:
        moment = time.monotonic() if now is None else now
        packets = self._reader.feed(data)
        with self._lock:
            self._packet_errors = self._reader.errors
            if transport:
                self._transport = transport
                self._connected = True
                if self._link_started is None:
                    self._link_started = moment
            for packet in packets:
                self._apply(packet, moment)

    def request_calibration(self, now: float | None = None) -> None:
        if self._hardware is not None:
            self._hardware.sensor.request_calibration()
            return
        moment = time.monotonic() if now is None else now
        with self._lock:
            fresh = self._connected and moment - self._last_rx < FRESH_SECONDS
            if not fresh or not self._ready:
                raise ValueError('No fresh MPU data. Connect the Nano and check its wiring.')
            if self._calibration['state'] in ('queued', 'running', 'saving'):
                raise ValueError('Calibration is already running.')
            if self._link_started is None or moment - self._link_started < 10:
                raise ValueError('Let the MPU warm up for at least 10 seconds, then retry.')
            self._rows = []
            self._cal_started = moment
            self._calibration = {'state': 'running', 'progress': 0.0, 'message': None}

    def snapshot(self, now: float | None = None) -> dict:
        if self._hardware is not None:
            return self._hardware.snapshot()
        moment = time.monotonic() if now is None else now
        with self._lock:
            fresh = self._connected and moment - self._last_rx < FRESH_SECONDS
            ready = fresh and self._ready
            angles = self._filter.angles() if ready else None
            note = self._note_locked()
            state = self._calibration['state']
            return {
                'connected': self._connected and fresh,
                'ready': ready,
                'fresh': fresh,
                'transport': self._transport if fresh else None,
                'status': self._status,
                'line': self._line_locked(fresh, ready),
                'angles': list(angles) if angles is not None else None,
                'sample_hz': self._sample_hz if fresh else 0.0,
                'temperature_c': self._temperature if fresh else None,
                'left_down': self._left_down if fresh else None,
                'right_down': self._right_down if fresh else None,
                'left_presses': self._left_presses,
                'right_presses': self._right_presses,
                'tracking_restarts': self._tracking_restarts,
                'calibrated': self._calibrated,
                'calibration_state': state,
                'calibration_progress': float(self._calibration.get('progress') or 0.0),
                'calibration_note': note,
                'calibrate_enabled': ready and state not in ('queued', 'running', 'saving'),
                'packet_errors': self._packet_errors,
                'axes': list(self._axes) if fresh and self._axes is not None else None,
                'simulated': False,
                'pointer': self._idle_pointer(),
                'speech': self.speech_snapshot(),
            }

    def update_pointer(
        self,
        *,
        enabled: bool | None = None,
        recenter: bool = False,
        speed: float | None = None,
        invert_x: bool | None = None,
        invert_y: bool | None = None,
        auto_enable: bool | None = None,
        stabilize: bool | None = None,
        sideways_axis: str | None = None,
    ) -> None:
        if self._hardware is None:
            raise ValueError('The glove link is not running.')
        pointer = self._hardware.pointer
        current = pointer.snapshot()
        axis_index = None
        if sideways_axis is not None:
            if sideways_axis not in ('X', 'Y'):
                raise ValueError('Choose sideways axis X or Y.')
            axis_index = 0 if sideways_axis == 'X' else 1
        if any(value is not None for value in (speed, invert_x, invert_y, auto_enable, stabilize, sideways_axis)):
            pointer.configure(
                current['speed'] if speed is None else speed,
                current['invert_x'] if invert_x is None else invert_x,
                current['invert_y'] if invert_y is None else invert_y,
                auto_enable=current['auto_enable'] if auto_enable is None else auto_enable,
                stabilize=current['stabilized'] if stabilize is None else stabilize,
                sideways_axis=axis_index,
            )
        if recenter:
            pointer.recenter()
        if enabled is True:
            pointer.enable()
        elif enabled is False:
            pointer.disable()

    def speech_snapshot(self) -> dict:
        controller = self._speech_controller()
        if controller is None:
            from motion.host import idle_speech
            return idle_speech()
        return controller.snapshot(include_text=True)

    def speech_devices(self) -> dict:
        from motion.host import speech_devices
        return speech_devices()

    def speech_start(self, device: int | None = None) -> None:
        controller = self._speech_controller()
        if controller is None:
            raise ValueError('Local speech is not available.')
        try:
            controller.start(device)
        except Exception as exc:
            raise ValueError(str(exc)) from exc

    def speech_stop(self) -> None:
        controller = self._speech_controller()
        if controller is not None:
            controller.stop()

    def speech_clear(self) -> None:
        controller = self._speech_controller()
        if controller is not None:
            controller.clear()

    def _speech_controller(self):
        if self._hardware is not None:
            return self._hardware.speech
        if self._speech is None:
            from motion.host import speech_controller
            self._speech = speech_controller()
        return self._speech

    def _idle_pointer(self) -> dict:
        from motion.host import idle_pointer
        return idle_pointer()

    def _apply(self, packet: Packet, now: float) -> None:
        if self._seen_packet and (
            packet.fifo_resets > self._fifo_resets or packet.i2c_errors > self._i2c_errors
        ):
            self._tracking_restarts += 1
            self._filter.reset()
        self._seen_packet = True
        self._fifo_resets = packet.fifo_resets
        self._i2c_errors = packet.i2c_errors
        self._last_rx = now
        self._ready = bool(packet.ready)
        self._temperature = packet.temperature_c
        self._left_down = bool(packet.contacts & 1)
        self._right_down = bool(packet.contacts & 2)
        self._left_presses = packet.left_presses
        self._right_presses = packet.right_presses
        self._connected = True
        if self._link_started is None:
            self._link_started = now
        if not packet.ready or not packet.samples:
            return
        clipped = any(any(abs(value) >= CLIP for value in raw) for raw in packet.samples)
        if clipped:
            if not self._range_exceeded:
                self._filter.reset()
                self._tracking_restarts += 1
                self._fail_locked('Sensor range exceeded. Calibration was not saved.')
            self._range_exceeded = True
            return
        self._range_exceeded = False
        for raw in packet.samples:
            values = scaled(raw)
            self._axes = values
            self._filter.update(values)
            self._sample_total += 1
            if self._rows is not None:
                self._rows.append((*values, packet.temperature_c))
        self._marks.append((now, self._sample_total))
        cutoff = now - 1.0
        while len(self._marks) > 1 and self._marks[0][0] < cutoff:
            self._marks.popleft()
        span = now - self._marks[0][0]
        self._sample_hz = (self._sample_total - self._marks[0][1]) / span if span >= 0.2 else 0.0
        if self._rows is not None:
            self._calibration = {
                'state': 'running',
                'progress': min(1.0, len(self._rows) / CALIBRATION_SAMPLES),
                'message': None,
            }
            if len(self._rows) >= CALIBRATION_SAMPLES:
                self._finish_locked(now)

    def _finish_locked(self, now: float) -> None:
        rows = self._rows or []
        self._rows = None
        elapsed = now - self._cal_started
        try:
            report = calibration_report(rows, elapsed)
        except ValueError as exc:
            self._calibration = {'state': 'failed', 'progress': 1.0, 'message': str(exc)}
            return
        if not report['passed']:
            self._calibration = {
                'state': 'failed',
                'progress': 1.0,
                'message': '; '.join(report['failures']),
            }
            return
        bias = tuple(float(value) for value in report['bias_dps'])
        self._filter.bias = bias
        self._filter.reset()
        self._calibrated = True
        self._calibration = {
            'state': 'passed',
            'progress': 1.0,
            'message': 'Calibration saved. Heading restarted at zero.',
        }
        payload = {
            'schema': PROFILE_SCHEMA,
            'bias_dps': list(bias),
            'temperature_c': report['temperature_c'],
        }
        try:
            self.profile_path.write_text(json.dumps(payload), encoding='utf-8')
        except OSError as exc:
            self._calibration['message'] = f'Calibration applied, but it could not be saved: {exc}'

    def _fail_locked(self, message: str) -> None:
        if self._rows is None and self._calibration['state'] not in ('queued', 'running'):
            return
        self._rows = None
        self._calibration = {'state': 'failed', 'progress': 0.0, 'message': message}

    def _line_locked(self, fresh: bool, ready: bool) -> str:
        if fresh and ready and self._temperature is not None and self._transport:
            return (
                f'{self._transport}  ·  {self._sample_hz:.0f} samples/s  ·  '
                f'{self._temperature:.1f} °C  ·  {self._tracking_restarts} tracking restarts'
            )
        return self._status

    def _note_locked(self) -> str:
        state = self._calibration['state']
        if state in ('queued', 'running', 'saving'):
            progress = float(self._calibration.get('progress') or 0.0)
            return f'KEEP STILL — {15 * progress:.1f} / 15 seconds'
        if state == 'failed' and self._calibration.get('message'):
            return str(self._calibration['message'])
        if state == 'passed' and self._calibration.get('message'):
            return str(self._calibration['message'])
        if self._calibrated:
            return 'Calibrated. Yaw can still drift.'
        return 'Not calibrated. Yaw can drift.'

    def _load_profile(self) -> None:
        if not self.profile_path.is_file():
            return
        try:
            profile = json.loads(self.profile_path.read_text(encoding='utf-8'))
            bias = profile['bias_dps']
            if profile.get('schema') != PROFILE_SCHEMA or len(bias) != 3:
                raise ValueError('schema')
            if not all(isinstance(value, (int, float)) and abs(float(value)) <= 20 for value in bias):
                raise ValueError('bias')
            self._filter.bias = tuple(float(value) for value in bias)
            self._calibrated = True
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._calibrated = False

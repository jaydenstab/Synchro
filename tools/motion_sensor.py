"""Single USB owner shared by the camera UI and calibration command-line tool."""
from collections import deque
import csv
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import queue
import secrets
import threading
import time
import uuid

from motion_core import (CALIBRATION_SAMPLES, Orientation, PacketReader,
                         calibration_report, scaled)
from motion_translation import InertialTranslation

PROJECT = Path(__file__).resolve().parents[1]
CONTROL_FILE = PROJECT / '.local' / 'motion-control.json'
PROFILE_SCHEMA = 'mpu6050-4g-500dps-98hz-1000hz-v1'


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


class MotionSensor:
    def __init__(self, port=None, transport='auto', ble_address=None):
        self.requested_port = port
        self.transport = transport
        self.ble_address = ble_address
        self.stop_event = threading.Event()
        self.commands = queue.Queue()
        self.lock = threading.Lock()
        self.state = {'connected': False, 'ready': False, 'status': 'Looking for Nano USB...',
                      'angles': None, 'sample_hz': 0.0, 'temperature_c': None,
                      'left_down': False, 'right_down': False,
                      'left_presses': 0, 'right_presses': 0,
                      'calibrated': False, 'bias_dps': [0.0] * 3,
                      'calibration': {'state': 'idle', 'progress': 0.0},
                      'tracking_restarts': 0, 'orientation_version': 0, 'received_at': 0.0,
                      'last_orientation_reset': None, 'range_exceeded': False, 'clipped_samples': 0}
        self.pointer = None
        self.speech = None
        self.assistant = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.filter = Orientation()
        self.translation = InertialTranslation()
        self.cal = None
        self.profile_path = None
        self.sensor_id = None
        self.server = None
        self.token = secrets.token_urlsafe(32)

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def snapshot(self):
        with self.lock:
            result = dict(self.state)
        result['age_seconds'] = time.monotonic() - result.pop('received_at')
        result['fresh'] = result['age_seconds'] < 0.5
        if not result['fresh']:
            result.update(ready=False, angles=None, left_down=None, right_down=None)
        if self.pointer is not None:
            result['pointer'] = self.pointer.snapshot()
        if self.speech is not None:
            result['speech'] = self.speech.snapshot(include_text=False)
        if self.assistant is not None:
            result['assistant'] = self.assistant.snapshot(include_text=False)
        return result

    def _reset_orientation(self, reason='Tracking reset'):
        self.filter.reset()
        self.translation.reset()
        with self.lock:
            self.state['orientation_version'] += 1
            self.state['last_orientation_reset'] = reason
            self.state['translation'] = self.translation.snapshot()
            self.state['orientation_quaternion'] = None

    def _consume_samples(self, packet):
        clipped = sum(any(abs(v) >= 32760 for v in raw) for raw in packet.samples)
        if clipped:
            # One reset per clipping episode, not hundreds of resets in a fast
            # motion. Reject the whole batch; clipped rates cannot be recovered.
            if not self.state['range_exceeded']:
                self._reset_orientation('Sensor measurement range exceeded')
            self._set(range_exceeded=True, clipped_samples=self.state['clipped_samples'] + clipped)
            self._fail_calibration('Sensor range exceeded; calibration was not saved.')
            return True
        self._set(range_exceeded=False)
        for raw in packet.samples:
            values = scaled(raw)
            self.filter.update(values)
            self.translation.update(values, self.filter.q, self.filter.bias)
            if self.cal is not None:
                self.cal['rows'].append((*values, packet.temperature_c))
                if len(self.cal['rows']) == CALIBRATION_SAMPLES:
                    self._finish_calibration()
        return False

    def start(self):
        self.thread.start()
        self._start_control_server()

    def request_calibration(self):
        with self.lock:
            if not self.state['ready'] or time.monotonic() - self.state['received_at'] >= 0.5:
                raise ValueError('No fresh MPU data. Connect the Nano and check its wiring.')
            if self.state['calibration']['state'] in ('queued', 'running', 'saving'):
                raise ValueError('Calibration is already running.')
            if self.state.get('uptime_seconds', 0) < 10:
                raise ValueError('Let the MPU warm up for at least 10 seconds, then retry.')
            run_id = uuid.uuid4().hex
            self.state['calibration'] = {'state': 'queued', 'progress': 0.0, 'id': run_id}
        self.commands.put(('calibrate', run_id))
        return run_id

    def _fail_calibration(self, message):
        if self.cal is not None:
            self._set(calibration={'state': 'failed', 'progress': 0.0,
                                   'id': self.cal['id'], 'message': message})
            self.cal = None
        with self.lock:
            if self.state['calibration']['state'] == 'queued':
                self.state['calibration'] = {**self.state['calibration'], 'state': 'failed', 'message': message}

    def _load_profile(self, port_info):
        self.sensor_id = getattr(port_info, 'serial_number', None)
        if self.sensor_id:
            self.sensor_id = self.sensor_id.upper()
        key = self.sensor_id or port_info.device
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        self.profile_path = PROJECT / '.local' / f'mpu-calibration-{digest}.json'
        self.filter = Orientation()
        self._reset_orientation('Connection/profile loaded')
        self._set(range_exceeded=False)
        self._set(ready=False, angles=None)
        self._set(calibrated=False, bias_dps=[0.0] * 3, profile_warning=None,
                  calibration_temperature_c=None)
        if self.profile_path.exists():
            try:
                profile = json.loads(self.profile_path.read_text(encoding='utf-8'))
                bias = profile['bias_dps']
                if (profile['schema'] != PROFILE_SCHEMA or len(bias) != 3 or
                        not all(math.isfinite(v) and abs(v) <= 20 for v in bias)):
                    raise ValueError('Invalid calibration profile')
                self.filter.bias = tuple(bias)
                self._set(calibrated=True, bias_dps=list(bias), calibration_temperature_c=profile['temperature_c'])
            except (KeyError, ValueError, TypeError, OSError) as error:
                self._set(profile_warning=f'Calibration not loaded: {error}')

    def _finish_calibration(self):
        cal = self.cal
        self.cal = None
        elapsed = time.monotonic() - cal['started']
        profile_path, sensor_id = self.profile_path, self.sensor_id
        self._set(calibration={'state': 'saving', 'progress': 1.0, 'id': cal['id']})

        def save():
            # Statistics and disk writes must not stall acquisition / fill FIFO.
            try:
                report = calibration_report(cal['rows'], elapsed)
                report.update(id=cal['id'], schema=PROFILE_SCHEMA, usb_serial=sensor_id,
                              created_utc=datetime.now(timezone.utc).isoformat())
                folder = PROJECT / '.local' / 'motion-calibrations' / cal['id']
                folder.mkdir(parents=True, exist_ok=True)
                with (folder / 'samples.csv').open('w', newline='', encoding='utf-8') as output:
                    writer = csv.writer(output)
                    writer.writerow(('ax_g', 'ay_g', 'az_g', 'gx_dps', 'gy_dps', 'gz_dps', 'temp_c'))
                    writer.writerows(cal['rows'])
                atomic_json(folder / 'report.json', report)
                if report['passed']:
                    atomic_json(profile_path, report)
                result = {'state': 'passed' if report['passed'] else 'failed',
                          'progress': 1.0, 'id': cal['id'], 'report': report,
                          'report_path': str(folder / 'report.json'),
                          'message': 'Calibration saved; heading restarted at zero.' if report['passed']
                          else '; '.join(report['failures'])}
                self.commands.put(('calibration_result', (profile_path, result)))
            except (OSError, ValueError) as error:
                self._set(calibration={'state': 'failed', 'id': cal['id'], 'progress': 1.0,
                                       'message': f'Could not save calibration: {error}'})

        threading.Thread(target=save, daemon=True).start()

    def _run(self):
        try:
            import serial
            from serial.tools import list_ports
        except ImportError:
            self._set(status='Install pyserial to read the Nano: python -m pip install pyserial')
            return
        while not self.stop_event.is_set():
            connection = None
            try:
                ports = list(list_ports.comports())
                matches = [p for p in ports if p.device == self.requested_port] if self.requested_port else [
                    p for p in ports if p.vid == 0x2341 and p.pid in (0x0070, 0x0071)]
                use_usb = self.transport != 'ble' and bool(matches)
                if use_usb:
                    if len(matches) != 1:
                        raise ValueError('Multiple Nanos found; select one with --mpu-port COMx.')
                    info = matches[0]
                    connection = serial.Serial(port=None, baudrate=115200, timeout=0.1)
                    connection.dtr = False
                    connection.rts = False
                    connection.port = info.device
                    connection.open()
                    # TinyUSB reboot handshake requires DTR before RTS.
                    connection.dtr = True
                    connection.rts = True
                    connection.reset_input_buffer()
                    transport_name = 'USB'
                else:
                    if self.transport == 'usb' or self.requested_port:
                        raise ValueError('Connect the Nano directly to laptop USB.')
                    from motion_ble import BleStream
                    self._set(status='Looking for Synchro-Glove over Bluetooth LE...')
                    connection = BleStream(self.stop_event, self.ble_address, self.sensor_id)
                    info = connection.info
                    transport_name = 'Bluetooth LE'
                    # Pin reconnections to this glove, including after USB is unplugged.
                    self.ble_address = info.device
                self._load_profile(info)
                self._set(connected=True, port=info.device, transport=transport_name,
                          status='Waiting for angle firmware...')
                reader = PacketReader()
                previous = None
                timing = deque()
                last_packet = time.monotonic()
                parse_errors = 0
                while not self.stop_event.is_set():
                    while not self.commands.empty():
                        command, run_id = self.commands.get_nowait()
                        if command == 'calibration_result':
                            profile_path, result = run_id
                            if profile_path == self.profile_path:
                                if result['state'] == 'passed':
                                    report = result['report']
                                    self.filter.bias = tuple(report['bias_dps'])
                                    self._reset_orientation('Calibration applied')
                                    self._set(calibrated=True, bias_dps=report['bias_dps'],
                                              calibration_temperature_c=report['temperature_c'])
                                self._set(calibration=result)
                            else:
                                self._set(calibration={'state': 'failed', 'progress': 1.0,
                                                       'id': result['id'], 'message': 'Nano changed; profile not applied.'})
                        if command == 'calibrate':
                            with self.lock:
                                queued = self.state['calibration']['state'] == 'queued'
                            if queued:
                                self.cal = {'id': run_id, 'started': time.monotonic(), 'rows': []}
                                self._set(calibration={'state': 'running', 'progress': 0.0, 'id': run_id})
                    data = connection.read(max(1, min(4096, connection.in_waiting)))
                    packets = reader.feed(data)
                    if reader.errors != parse_errors:
                        parse_errors = reader.errors
                        self._fail_calibration('USB packet corruption; calibration was not saved.')
                        self._reset_orientation('Packet corruption')
                    for packet in packets:
                        last_packet = time.monotonic()
                        discontinuity = previous is not None and (
                            packet.sequence != (previous.sequence + 1) & 0xFFFFFFFF or
                            packet.first_sample != (previous.first_sample + previous.count) & 0xFFFFFFFF or
                            packet.fifo_resets != previous.fifo_resets or
                            packet.i2c_errors != previous.i2c_errors or
                            packet.time_us <= previous.time_us)
                        if discontinuity:
                            self._fail_calibration('Sensor data gap or reset; retry while connected.')
                            self._reset_orientation('Sensor data gap or reset')
                            timing.clear()
                            with self.lock:
                                self.state['tracking_restarts'] += 1
                        previous = packet
                        if not packet.ready:
                            self._fail_calibration('MPU disconnected or I2C failed.')
                            self._reset_orientation('MPU disconnected or I2C failed')
                        saturated = self._consume_samples(packet)
                        timing.append((packet.time_us, packet.first_sample + packet.count))
                        while len(timing) > 2 and timing[0][0] < packet.time_us - 2_000_000:
                            timing.popleft()
                        hz = ((timing[-1][1] - timing[0][1]) * 1e6 / (timing[-1][0] - timing[0][0])
                              if len(timing) > 1 and timing[-1][0] > timing[0][0] else 0.0)
                        status = ('Live MPU angles' if packet.ready else 'MPU missing: check A4/A5, 3V3 and GND')
                        if saturated:
                            status = 'Motion exceeded sensor range; orientation restarted'
                        self._set(ready=bool(packet.ready and packet.count and not saturated),
                                  angles=self.filter.angles() if packet.ready and not saturated else None,
                                  sample_hz=hz, temperature_c=packet.temperature_c,
                                  translation=self.translation.snapshot(), orientation_quaternion=self.filter.q,
                                  uptime_seconds=packet.time_us / 1e6,
                                  left_down=bool(packet.contacts & 1), right_down=bool(packet.contacts & 2),
                                  left_presses=packet.left_presses, right_presses=packet.right_presses,
                                  fifo_resets=packet.fifo_resets, i2c_errors=packet.i2c_errors,
                                  ble_dropped_frames=packet.reserved,
                                  packet_errors=reader.errors, status=status, received_at=last_packet)
                        self._set(sample_sequence=(packet.first_sample + packet.count) & 0xFFFFFFFF)
                        if self.cal is not None:
                            self._set(calibration={'state': 'running', 'id': self.cal['id'],
                                                   'progress': len(self.cal['rows']) / CALIBRATION_SAMPLES})
                    if time.monotonic() - last_packet > 1:
                        self._set(ready=False, angles=None,
                                  status='No MPU packets. Upload NanoMotionAngles, or reconnect USB.')
                    if self.cal and time.monotonic() - self.cal['started'] > 20:
                        self._fail_calibration('Calibration timed out; check USB and the sensor.')
            except (OSError, ValueError, serial.SerialException) as error:
                self._fail_calibration(str(error))
                self._set(connected=False, ready=False, angles=None, status=str(error), received_at=0.0)
            finally:
                if connection is not None:
                    connection.close()
            self.stop_event.wait(1)

    def _start_control_server(self):
        sensor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, code, body):
                payload = json.dumps(body, allow_nan=False).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def authorized(self):
                return (not self.headers.get('Origin') and
                        secrets.compare_digest(self.headers.get('X-Synchro-Token', ''), sensor.token))

            def do_GET(self):
                if not self.authorized():
                    self.respond(403, {'error': 'Local tool authentication required'})
                elif self.path == '/status':
                    self.respond(200, sensor.snapshot())
                else:
                    self.respond(404, {'error': 'Unknown endpoint'})

            def do_POST(self):
                if not self.authorized():
                    self.respond(403, {'error': 'Local tool authentication required'})
                    return
                if self.path.startswith('/pointer/') and sensor.pointer is not None:
                    actions = {'/pointer/enable': sensor.pointer.enable,
                               '/pointer/disable': sensor.pointer.disable,
                               '/pointer/recenter': sensor.pointer.recenter}
                    if self.path not in actions:
                        self.respond(404, {'error': 'Unknown pointer action'})
                        return
                    try:
                        actions[self.path]()
                        self.respond(200, sensor.pointer.snapshot())
                    except ValueError as error:
                        self.respond(409, {'error': str(error)})
                    return
                if self.path != '/calibrate':
                    self.respond(404, {'error': 'Unknown endpoint'})
                    return
                try:
                    self.respond(202, {'id': sensor.request_calibration()})
                except ValueError as error:
                    self.respond(409, {'error': str(error)})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        atomic_json(CONTROL_FILE, {'port': self.server.server_port, 'token': self.token})

    def close(self):
        self.stop_event.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.thread.join(timeout=2)
        try:
            if json.loads(CONTROL_FILE.read_text())['token'] == self.token:
                CONTROL_FILE.unlink()
        except (OSError, ValueError, KeyError):
            pass

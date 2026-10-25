"""Automatic glove pointer with stabilized sideways swipes and finger clicks.

X uses experimental inertial displacement; Y uses pitch relative to neutral.
Legacy roll/pitch mapping remains available to the isolated mapping tests.
"""
import math
import sys
import threading
import time
from motion_translation import CursorStabilizer, horizontal_axis


def angle_difference(value, reference):
    return (value - reference + 180.0) % 360.0 - 180.0


class TiltMapping:
    def __init__(self, dead_zone=0.5, pixels_per_degree=25.0):
        self.dead_zone, self.pixels_per_degree = dead_zone, pixels_per_degree
        self.neutral = None
        # Keep the existing configuration key for compatibility with the UI/API.
        # This is now a distance sensitivity multiplier, never a velocity.
        self.speed = 1.0
        self.invert_x = False
        self.invert_y = False

    def center(self, angles):
        if angles is None or len(angles) != 3 or not all(math.isfinite(a) for a in angles):
            raise ValueError('No valid angles to use as neutral.')
        if abs(angles[1]) >= 75:
            raise ValueError('Lower the hand from the vertical pose before setting neutral.')
        self.neutral = tuple(angles[:2])

    def offset(self, angles):
        if (self.neutral is None or angles is None or len(angles) != 3 or
                not all(math.isfinite(v) for v in angles) or abs(angles[1]) >= 80):
            return None
        # Positive roll -> right. Positive pitch -> up (screen Y decreases).
        delta = [angle_difference(angles[0], self.neutral[0]),
                 angle_difference(angles[1], self.neutral[1])]
        # Soft dead zone: continuous at its edge and linear beyond it. No dt,
        # integration, acceleration, or dependence on how long a pose is held.
        offsets = [math.copysign(max(0.0, abs(a) - self.dead_zone), a) *
                   self.pixels_per_degree * self.speed for a in delta]
        return (round(offsets[0] * (-1 if self.invert_x else 1)),
                round(offsets[1] * (1 if self.invert_y else -1)))


class WindowsPointer:
    """Explicitly typed Win32 calls; absolute updates avoid pointer acceleration."""
    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('Pointer control is currently implemented for Windows.')
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.point_type = wintypes.POINT
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user32.GetCursorPos.restype = wintypes.BOOL
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = wintypes.BOOL
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int
        # MOUSEINPUT is the largest INPUT union member on both Win32 and Win64.
        # ULONG_PTR must follow the Python process pointer size.
        class MouseInput(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                        ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

        class InputUnion(ctypes.Union):
            _fields_ = [('mi', MouseInput)]

        class Input(ctypes.Structure):
            _anonymous_ = ('value',)
            _fields_ = [('type', wintypes.DWORD), ('value', InputUnion)]

        self.input_type = Input
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT

    def escape_down(self):
        return bool(self.user32.GetAsyncKeyState(0x1B) & 0x8000)

    def position(self):
        point = self.point_type()
        if not self.user32.GetCursorPos(self.ctypes.byref(point)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return point.x, point.y

    def center_position(self):
        # Neutral is the primary screen center, not the Enable/Pause button
        # that was just clicked. This also leaves room for tilt in every direction.
        return (self.user32.GetSystemMetrics(0) // 2, self.user32.GetSystemMetrics(1) // 2)

    def set_position(self, x, y):
        # Virtual desktop supports displays to the left/above the primary.
        left, top, width, height = (self.user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))
        target = (max(left, min(left + width - 1, x)),
                  max(top, min(top + height - 1, y)))
        if self.position() != target and not self.user32.SetCursorPos(*target):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return self.position()

    def click(self, button):
        down, up = {'left': (0x0002, 0x0004), 'right': (0x0008, 0x0010)}[button]
        events = (self.input_type * 2)()
        events[0].mi.dwFlags, events[1].mi.dwFlags = down, up
        # Submit press/release together: holding a contact never holds a button.
        inserted = self.user32.SendInput(2, events, self.ctypes.sizeof(self.input_type))
        if inserted != 2:
            if inserted == 1:
                # Best-effort release if Windows accepted only the press.
                self.user32.SendInput(1, self.ctypes.byref(events[1]),
                                      self.ctypes.sizeof(self.input_type))
            raise OSError('Windows could not send the mouse click. Pointer paused.')


class PointerController:
    def __init__(self, sensor, backend=None, *, auto_enable=True, sideways=True, stabilize=True):
        self.sensor = sensor
        self.backend = backend
        self.mapping = TiltMapping()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.enabled = False
        self.message = 'Auto cursor: waiting for glove. Hold a comfortable pose briefly after connecting.'
        self.auto_enable = auto_enable
        self.manual_pause = False
        self.auto_candidate = None
        self.sideways = sideways
        self.sideways_axis = 0
        self.sideways_basis = None
        self.translation_reference = None
        self.translation_rebase_pending = False
        self.pixels_per_meter = 5000.0
        self.stabilize = stabilize
        self.stabilizer = CursorStabilizer()
        self.click_freeze_until = 0.0
        self.reference_version = None
        self.last_time = None
        self.last_sequence = None
        self.last_sequence_time = None
        self.last_position = None
        self.origin = None
        self.moves = 0
        self.distance = 0.0
        self.contact_counts = {}
        self.contact_blocked = {}
        self.clicks = {'left': 0, 'right': 0}
        self.suspended = False
        self.resume_since = None
        self.vertical_hold = False
        self.pause_events = 0
        self.recovery_events = 0
        self.last_pause_reason = None
        self.on_message = 'Cursor ON · sideways swipe: left/right (approx.) · pitch: up/down · Esc pauses.'

    def _prime_contacts(self, data):
        # Never replay touches made while paused; an already-held pad must be
        # released before it can click. Counters also catch short taps between ticks.
        for side in ('left', 'right'):
            self.contact_counts[side] = data.get(f'{side}_presses')
            self.contact_blocked[side] = data.get(f'{side}_down') is not False

    def start(self):
        try:
            if self.backend is None:
                self.backend = WindowsPointer()
        except OSError as error:
            self.message = str(error)
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @staticmethod
    def unavailable(data):
        if not data.get('ready') or not data.get('fresh') or data.get('age_seconds', 0) > 0.2:
            return 'Pointer off: sensor data stopped. Re-enable when connected.'
        if not data.get('calibrated'):
            return 'Run the stationary gyro calibration before enabling the pointer.'
        if data.get('calibration', {}).get('state') in ('queued', 'running', 'saving'):
            return 'Pointer off during calibration. Re-enable afterward.'
        angles = data.get('angles')
        if angles is None or len(angles) != 3 or not all(math.isfinite(a) for a in angles):
            return 'Pointer off: no valid angle readings.'
        return None

    def enable(self):
        data = self.sensor.snapshot()
        reason = self._control_unavailable(data)
        if reason:
            raise ValueError(reason)
        if self.backend is None:
            raise ValueError(self.message)
        with self.lock:
            self._enable_locked(data, time.monotonic())

    def _control_unavailable(self, data):
        reason = self.unavailable(data)
        if reason:
            return reason
        if self.sideways and (not data.get('translation', {}).get('ready') or
                              data.get('orientation_quaternion') is None):
            return 'Hold the glove still briefly to initialize sideways motion.'
        return None

    def _capture_translation(self, data):
        if self.sideways:
            self.sideways_basis = horizontal_axis(data['orientation_quaternion'], self.sideways_axis)
            self.translation_reference = tuple(data['translation']['position_m'])
        self.translation_rebase_pending = False

    def _enable_locked(self, data, now):
        self.mapping.center(data['angles'])
        self._capture_translation(data)
        self.origin = self.backend.center_position()
        self.last_position = self.backend.position()
        self.stabilizer.reset(self.last_position)
        self.reference_version = data.get('orientation_version', 0)
        self.enabled = True
        self.manual_pause = False
        self.auto_candidate = None
        self.last_time = now
        self.last_sequence = data.get('sample_sequence')
        self.last_sequence_time = now
        self._prime_contacts(data)
        self.suspended = self.vertical_hold = False
        self.resume_since = None
        self.message = self.on_message

    def _try_auto_locked(self, data, now):
        if not self.auto_enable or self.manual_pause or self.backend is None:
            return
        if self._control_unavailable(data) or abs(data['angles'][1]) >= 75:
            self.auto_candidate = None
            self.message = 'Auto cursor waiting — connect glove and hold it still briefly.'
            return
        if self.sideways and not data['translation']['stationary']:
            self.auto_candidate = None
            self.message = 'Auto cursor ready — hold your resting pose for a moment.'
            return
        if (self.auto_candidate is None or
            self.auto_candidate[2] != data.get('orientation_version', 0) or
            any(abs(angle_difference(a, b)) > 2 for a, b in zip(data['angles'][:2], self.auto_candidate[1]))):
            self.auto_candidate = (now, tuple(data['angles'][:2]), data.get('orientation_version', 0), data.get('sample_sequence'))
            return
        if now - self.auto_candidate[0] >= .45 and data.get('sample_sequence') != self.auto_candidate[3]:
            try:
                self._enable_locked(data, now)
            except ValueError as error:
                self.message = str(error)
                self.auto_candidate = None

    def _disable_locked(self, message, manual=False):
        self.enabled = False
        self.suspended = self.vertical_hold = False
        self.resume_since = None
        self.auto_candidate = None
        if manual:
            self.manual_pause = True
        self.message = message

    def disable(self, message='Pointer off. Hold a comfortable pose, then Enable.'):
        with self.lock:
            self._disable_locked(message, manual=True)

    def recenter(self):
        data = self.sensor.snapshot()
        reason = self._control_unavailable(data)
        if reason:
            raise ValueError(reason)
        with self.lock:
            self.mapping.center(data['angles'])
            self._capture_translation(data)
            self.origin = self.backend.center_position()
            self.last_position = self.backend.position()
            self.stabilizer.reset(self.last_position)
            self.reference_version = data.get('orientation_version', 0)
            self._prime_contacts(data)
            self.message = 'Neutral position set. Esc stops the pointer.' if self.enabled else 'Neutral position set; pointer is off.'

    def configure(self, speed=1.0, invert_x=False, invert_y=False, *, auto_enable=None, stabilize=None, sideways_axis=None):
        if not math.isfinite(speed) or not 0.25 <= speed <= 2.0:
            raise ValueError('Sensitivity must be 0.25–2.0.')
        with self.lock:
            self.mapping.speed = speed
            self.mapping.invert_x, self.mapping.invert_y = bool(invert_x), bool(invert_y)
            if auto_enable is not None and bool(auto_enable) != self.auto_enable:
                self.auto_enable = bool(auto_enable)
                if self.auto_enable:
                    self.manual_pause = False
                    self.auto_candidate = None
            if stabilize is not None:
                self.stabilize = bool(stabilize)
            if sideways_axis is not None and sideways_axis != self.sideways_axis:
                if sideways_axis not in (0, 1):
                    raise ValueError('Choose sideways axis X or Y.')
                self.sideways_axis = sideways_axis
                self._disable_locked('Sideways axis changed. Hold still to resume automatically.')

    def snapshot(self):
        with self.lock:
            return {'enabled': self.enabled, 'available': self.backend is not None,
                    'message': self.message, 'neutral': self.mapping.neutral,
                    'control_mode': 'approximate_swipe_x_pitch_y' if self.sideways else 'position', 'origin': self.origin,
                    'auto_enable': self.auto_enable, 'manual_pause': self.manual_pause,
                    'stabilized': self.stabilize, 'sideways_axis': 'XY'[self.sideways_axis],
                    'pixels_per_estimated_cm': self.pixels_per_meter * self.mapping.speed / 100,
                    'pixels_per_degree': self.mapping.pixels_per_degree * self.mapping.speed,
                    'speed': self.mapping.speed, 'invert_x': self.mapping.invert_x,
                    'invert_y': self.mapping.invert_y, 'move_events': self.moves,
                    'left_clicks': self.clicks['left'], 'right_clicks': self.clicks['right'],
                    'suspended': self.suspended, 'pause_events': self.pause_events,
                    'recovery_events': self.recovery_events, 'last_pause_reason': self.last_pause_reason,
                    'requested_distance_px': self.distance, 'last_position': self.last_position}

    def _click_contacts(self, data):
        for side in ('left', 'right'):
            count, down = data.get(f'{side}_presses'), data.get(f'{side}_down')
            previous = self.contact_counts.get(side)
            self.contact_counts[side] = count
            if not isinstance(count, int) or not isinstance(previous, int) or down is None:
                self.contact_blocked[side] = True
                continue
            if self.contact_blocked[side]:
                if not down:
                    self.contact_blocked[side] = False
                continue
            # uint32 wrap is a single press. Resets or queued bursts are rebased,
            # never replayed as a burst of clicks at a possibly different target.
            if ((count - previous) & 0xFFFFFFFF) == 1:
                self.backend.click(side)
                self.clicks[side] += 1

    def tick(self, data, now):
        with self.lock:
            if self.backend is not None and self.backend.escape_down():
                self._disable_locked('Pointer stopped with Esc. Click Enable to resume.', manual=True)
                return
            if not self.enabled:
                self._try_auto_locked(data, now)
                return
            if data.get('calibration', {}).get('state') in ('queued', 'running', 'saving'):
                self._disable_locked('Pointer off during calibration. Re-enable afterward.')
                return
            if not data.get('calibrated'):
                self._disable_locked('Pointer off: calibration unavailable. Re-enable when calibrated.')
                return
            reason = self._control_unavailable(data)
            version = data.get('orientation_version', 0)
            if version != self.reference_version:
                self.reference_version = version
                self.translation_rebase_pending = self.sideways
                reason = 'Tracking restarted; waiting for reliable angles.'
            dt = now - self.last_time
            self.last_time = now
            if dt > 0.2:
                reason = 'Processing delay; waiting for fresh readings.'
            sequence = data.get('sample_sequence')
            if sequence != self.last_sequence:
                self.last_sequence, self.last_sequence_time = sequence, now
            elif now - self.last_sequence_time > 0.2:
                reason = 'Waiting for new sensor samples.'
            # Disconnects re-arm automatic connection handling. Esc/Pause remain
            # latched off until the user explicitly enables control again.
            if data.get('age_seconds', 0) > 2 or now - self.last_sequence_time > 2 or dt > 2:
                self._disable_locked('Connection stopped. Auto cursor will resume after reconnecting.')
                return
            angles = data.get('angles')
            if angles is not None and len(angles) == 3 and math.isfinite(angles[1]):
                if abs(angles[1]) >= 80:
                    self.vertical_hold = True
                elif abs(angles[1]) < 75:
                    self.vertical_hold = False
            if self.vertical_hold:
                reason = 'Hand near vertical; lower it to resume automatically.'
            if reason:
                if not self.suspended:
                    self.pause_events += 1
                self.suspended = True
                self.resume_since = None
                self.last_pause_reason = reason
                self._prime_contacts(data)
                self.message = 'Pointer waiting — ' + reason.replace('Pointer off: ', '').replace(' Re-enable when connected.', '')
                return
            if self.suspended:
                # Preserve the user's gravity-referenced roll/pitch neutral.
                # Do not silently make the current tilted hand the new neutral.
                self._prime_contacts(data)
                if self.resume_since is None:
                    self.resume_since = now
                if now - self.resume_since < 0.15:
                    self.message = 'Pointer waiting — readings recovering; resumes automatically.'
                    return
                self.suspended = False
                self.resume_since = None
                if self.translation_rebase_pending:
                    try:
                        self._capture_translation(data)
                    except ValueError:
                        self.suspended = True
                        return
                    self.origin = (self.last_position[0], self.origin[1])
                self.stabilizer.reset(self.backend.position())
                self.recovery_events += 1
                self.message = self.on_message
                return  # Discard touches made during the interruption.
            offset = self.mapping.offset(data['angles'])
            if offset is None:
                return
            previous = self.backend.position()
            if self.sideways:
                displacement = sum((v-r)*a for v, r, a in zip(
                    data['translation']['position_m'], self.translation_reference, self.sideways_basis))
                offset = (round(displacement * self.pixels_per_meter * self.mapping.speed *
                                (-1 if self.mapping.invert_x else 1)), offset[1])
            target = (self.origin[0] + offset[0], self.origin[1] + offset[1])
            if self.stabilize:
                if any(not self.contact_blocked.get(side, True) and
                       ((data.get(f'{side}_presses', 0) - self.contact_counts.get(side, 0)) & 0xFFFFFFFF) == 1
                       for side in ('left', 'right')):
                    self.click_freeze_until = now + .12
                if now < self.click_freeze_until:
                    self.stabilizer.reset(previous)
                    self._click_contacts(data)
                    return
                target = self.stabilizer.step(target, dt)
            self.last_position = self.backend.set_position(*target)
            if self.sideways and self.last_position[0] != target[0]:
                # Discard displacement beyond the screen edge instead of
                # requiring the user to undo an invisible off-screen swipe.
                self.translation_reference = tuple(data['translation']['position_m'])
                self.origin = (self.last_position[0], self.origin[1])
                self.stabilizer.reset(self.last_position)
            if self.last_position != previous:
                self.moves += 1
                self.distance += math.hypot(self.last_position[0] - previous[0],
                                            self.last_position[1] - previous[1])
            self._click_contacts(data)

    def _run(self):
        while not self.stop_event.is_set():
            began = time.monotonic()
            try:
                self.tick(self.sensor.snapshot(), began)
            except Exception as error:
                self.disable(f'Pointer stopped: {error}')
            self.stop_event.wait(max(0.001, 0.01 - (time.monotonic() - began)))

    def close(self):
        self.disable()
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)

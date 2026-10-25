"""Tilt-to-pointer controller with held finger buttons for clicking and dragging.

Roll and pitch map directly to screen offsets from a user-selected neutral pose.
Holding a tilt holds a position; returning to neutral returns to the anchor.
"""
import math
import sys
import threading
import time

CHORD_GRACE_SECONDS = .08
SCROLL_DEGREES_PER_NOTCH = 3.0

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
        # A complete tap may occur between received samples.
        inserted = self.user32.SendInput(2, events, self.ctypes.sizeof(self.input_type))
        if inserted != 2:
            if inserted == 1:
                # Best-effort release if Windows accepted only the press.
                self.user32.SendInput(1, self.ctypes.byref(events[1]),
                                      self.ctypes.sizeof(self.input_type))
            raise OSError('Windows could not send the mouse click. Pointer paused.')

    def _button(self, button, down):
        flags = {'left': (0x0002, 0x0004), 'right': (0x0008, 0x0010)}[button]
        event = self.input_type()
        event.mi.dwFlags = flags[0 if down else 1]
        if self.user32.SendInput(1, self.ctypes.byref(event), self.ctypes.sizeof(self.input_type)) != 1:
            raise OSError('Windows could not update the mouse button. Pointer paused.')

    def button_down(self, button):
        self._button(button, True)

    def button_up(self, button):
        self._button(button, False)

    def scroll(self, notches):
        event = self.input_type()
        event.mi.dwFlags = 0x0800  # MOUSEEVENTF_WHEEL; positive scrolls up.
        event.mi.mouseData = (int(notches) * 120) & 0xFFFFFFFF
        if self.user32.SendInput(1, self.ctypes.byref(event), self.ctypes.sizeof(self.input_type)) != 1:
            raise OSError('Windows could not scroll. Pointer paused.')


class PointerController:
    def __init__(self, sensor, backend=None):
        self.sensor = sensor
        self.backend = backend
        self.mapping = TiltMapping()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.enabled = False
        self.message = 'Pointer off. Hold a comfortable pose, then Enable.'
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
        self.held = {'left': False, 'right': False}
        self.pending_press = {'left': None, 'right': None}
        self.scrolling = self.scroll_wait_release = False
        self.scroll_pitch = None
        self.scroll_remainder = 0.0
        self.wheel_events = self.wheel_notches = 0
        self.suspended = False
        self.resume_since = None
        self.vertical_hold = False
        self.pause_events = 0
        self.recovery_events = 0
        self.last_pause_reason = None
        self.on_message = 'Tilt ON · one contact: click/hold to drag · both: tilt up/down to scroll · Pause pointer stops.'

    def _release_button(self, side):
        if self.held[side]:
            self.backend.button_up(side)
            self.held[side] = False

    def _release_buttons(self):
        success = True
        for side in ('left', 'right'):
            try:
                self._release_button(side)
            except OSError:
                success = False  # Retain held state and retry on the next loop.
        return success

    def _prime_contacts(self, data):
        self.pending_press = {'left': None, 'right': None}
        self.scrolling = self.scroll_wait_release = False
        self.scroll_pitch = None
        self.scroll_remainder = 0.0
        if not self._release_buttons():
            self.enabled = False
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
        reason = self.unavailable(data)
        if reason:
            raise ValueError(reason)
        if self.backend is None:
            raise ValueError(self.message)
        with self.lock:
            self.mapping.center(data['angles'])
            self.origin = self.backend.center_position()
            self.last_position = self.backend.position()
            self.reference_version = data.get('orientation_version', 0)
            self.enabled = True
            self.last_time = time.monotonic()
            self.last_sequence = data.get('sample_sequence')
            self.last_sequence_time = self.last_time
            self._prime_contacts(data)
            self.suspended = self.vertical_hold = False
            self.resume_since = None
            self.message = self.on_message

    def _disable_locked(self, message):
        self.enabled = False
        self.suspended = self.vertical_hold = False
        self.resume_since = None
        self.message = message
        self.pending_press = {'left': None, 'right': None}
        self.scrolling = self.scroll_wait_release = False
        if not self._release_buttons():
            self.message = 'Pointer paused; retrying mouse-button release.'

    def disable(self, message='Pointer off. Hold a comfortable pose, then Enable.'):
        with self.lock:
            self._disable_locked(message)

    def recenter(self):
        data = self.sensor.snapshot()
        reason = self.unavailable(data)
        if reason:
            raise ValueError(reason)
        with self.lock:
            self.mapping.center(data['angles'])
            self.origin = self.backend.center_position()
            self.last_position = self.backend.position()
            self.reference_version = data.get('orientation_version', 0)
            self._prime_contacts(data)
            self.message = 'Neutral position set. Use Pause pointer to stop.' if self.enabled else 'Neutral position set; pointer is off.'

    def configure(self, speed=1.0, invert_x=False, invert_y=False):
        if not math.isfinite(speed) or not 0.25 <= speed <= 2.0:
            raise ValueError('Sensitivity must be 0.25–2.0.')
        with self.lock:
            self.mapping.speed = speed
            self.mapping.invert_x, self.mapping.invert_y = bool(invert_x), bool(invert_y)

    def snapshot(self):
        with self.lock:
            return {'enabled': self.enabled, 'available': self.backend is not None,
                    'message': self.message, 'neutral': self.mapping.neutral,
                    'control_mode': 'position', 'origin': self.origin,
                    'escape_stops_pointer': False,
                    'pixels_per_degree': self.mapping.pixels_per_degree * self.mapping.speed,
                    'speed': self.mapping.speed, 'invert_x': self.mapping.invert_x,
                    'invert_y': self.mapping.invert_y, 'move_events': self.moves,
                    'left_clicks': self.clicks['left'], 'right_clicks': self.clicks['right'],
                    'left_held': self.held['left'], 'right_held': self.held['right'],
                    'button_mode': 'hold_to_drag',
                    'scroll_mode': 'two_finger_tilt', 'scrolling': self.scrolling,
                    'wheel_events': self.wheel_events, 'wheel_notches': self.wheel_notches,
                    'suspended': self.suspended, 'pause_events': self.pause_events,
                    'recovery_events': self.recovery_events, 'last_pause_reason': self.last_pause_reason,
                    'requested_distance_px': self.distance, 'last_position': self.last_position}

    def _scroll_contacts(self, data):
        left, right = data.get('left_down'), data.get('right_down')
        both = left is True and right is True
        counts_valid = all(isinstance(data.get(f'{side}_presses'), int) and
                           isinstance(self.contact_counts.get(side), int) and
                           ((data[f'{side}_presses'] - self.contact_counts[side]) & 0xFFFFFFFF) in (0, 1)
                           for side in ('left', 'right'))
        if not self.scrolling:
            if not both:
                return False
            if not counts_valid or any(self.contact_blocked.values()):
                self._prime_contacts(data)
                return True
            if not self._release_buttons():
                self._disable_locked('Pointer paused; retrying mouse-button release.')
                return True
            self.pending_press = {'left': None, 'right': None}
            self.scrolling = True
            self.scroll_pitch = data['angles'][1]
            self.scroll_remainder = 0.0
            self.message = 'Scrolling · tilt up/down · release both contacts to return to the pointer.'
        if not both or not counts_valid:
            self.scroll_wait_release = True
        if self.scroll_wait_release:
            if left is False and right is False:
                # Keep the original neutral and screen anchor. Apply the current
                # tilt immediately, as if pointing had continued during scrolling.
                self._prime_contacts(data)
                self.message = self.on_message
                return False
            return True
        pitch = data['angles'][1]
        delta = angle_difference(pitch, self.scroll_pitch)
        self.scroll_pitch = pitch
        self.scroll_remainder += delta * self.mapping.speed * (-1 if self.mapping.invert_y else 1)
        raw_steps = math.trunc(self.scroll_remainder / SCROLL_DEGREES_PER_NOTCH)
        if raw_steps:
            steps = max(-4, min(4, raw_steps))
            self.backend.scroll(steps)
            self.scroll_remainder -= raw_steps * SCROLL_DEGREES_PER_NOTCH
            self.wheel_events += 1
            self.wheel_notches += steps
        for side in ('left', 'right'):
            self.contact_counts[side] = data.get(f'{side}_presses')
        return True

    def _click_contacts(self, data, now):
        for side in ('left', 'right'):
            count, down = data.get(f'{side}_presses'), data.get(f'{side}_down')
            previous = self.contact_counts.get(side)
            self.contact_counts[side] = count
            if not isinstance(count, int) or not isinstance(previous, int) or not isinstance(down, bool):
                self._release_button(side)
                self.pending_press[side] = None
                self.contact_blocked[side] = True
                continue
            if self.contact_blocked[side]:
                self._release_button(side)
                self.pending_press[side] = None
                if not down:
                    self.contact_blocked[side] = False
                continue
            delta = (count - previous) & 0xFFFFFFFF
            if delta not in (0, 1):
                self._release_button(side)
                self.pending_press[side] = None
                self.contact_blocked[side] = down
                continue
            # A new press while already held means a release/re-press happened
            # between packets. Release the old hold before starting the new one.
            if self.held[side] and (not down or delta == 1):
                self._release_button(side)
            if self.pending_press[side] is not None and (not down or delta == 1):
                self.backend.click(side)
                self.clicks[side] += 1
                self.pending_press[side] = None
            if delta == 1:
                if down:
                    # Allow nearly simultaneous fingers to form a scroll chord
                    # without briefly clicking the content under the cursor.
                    self.pending_press[side] = now
                else:
                    self.backend.click(side)
                    self.clicks[side] += 1
            if (down and self.pending_press[side] is not None and
                    now - self.pending_press[side] >= CHORD_GRACE_SECONDS):
                self.held[side] = True
                self.backend.button_down(side)
                self.pending_press[side] = None
                self.clicks[side] += 1

    def tick(self, data, now):
        with self.lock:
            if not self.enabled:
                self._release_buttons()
                return
            if data.get('calibration', {}).get('state') in ('queued', 'running', 'saving'):
                self._disable_locked('Pointer off during calibration. Re-enable afterward.')
                return
            if not data.get('calibrated'):
                self._disable_locked('Pointer off: calibration unavailable. Re-enable when calibrated.')
                return
            reason = self.unavailable(data)
            version = data.get('orientation_version', 0)
            if version != self.reference_version:
                self.reference_version = version
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
            # Brief radio/host delays freeze output. A sustained outage still
            # needs an explicit enable, as do Pause and calibration.
            if data.get('age_seconds', 0) > 2 or now - self.last_sequence_time > 2 or dt > 2:
                self._disable_locked('Pointer off: connection stopped for 2 seconds. Re-enable when connected.')
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
                self.recovery_events += 1
                self.message = self.on_message
                return  # Discard touches made during the interruption.
            if self._scroll_contacts(data):
                return
            offset = self.mapping.offset(data['angles'])
            if offset is None:
                return
            previous = self.backend.position()
            target = (self.origin[0] + offset[0], self.origin[1] + offset[1])
            self.last_position = self.backend.set_position(*target)
            if self.last_position != previous:
                self.moves += 1
                self.distance += math.hypot(self.last_position[0] - previous[0],
                                            self.last_position[1] - previous[1])
            self._click_contacts(data, now)

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

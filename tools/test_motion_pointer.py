"""Pointer regressions use a fake desktop; tests never move the real mouse."""
import math
import sys
import time
from types import SimpleNamespace
import unittest

from motion_pointer import PointerController, TiltMapping, WindowsPointer


def live(angles=(170.0, -15.0, 0.0), **changes):
    return {'ready': True, 'fresh': True, 'age_seconds': 0.01,
            'calibrated': True, 'calibration': {'state': 'passed'},
            'orientation_version': 1, 'sample_sequence': 100,
            'left_presses': 8, 'right_presses': 13, 'left_down': False, 'right_down': False,
            'angles': angles, **changes}


class Sensor:
    def __init__(self):
        self.data = live()

    def snapshot(self):
        return dict(self.data)


class Desktop:
    def __init__(self):
        self.escape = False
        self.moves = []
        self.clicks = []
        self.current_position = (500, 500)

    def escape_down(self):
        return self.escape

    def position(self):
        return self.current_position

    def center_position(self):
        return (500, 500)

    def set_position(self, x, y):
        # Simulate screen edges as well as absolute cursor placement.
        target = (max(0, min(1919, x)), max(0, min(1079, y)))
        if target != self.current_position:
            self.moves.append(target)
        self.current_position = target
        return target

    def click(self, button):
        self.clicks.append(button)


class MappingTests(unittest.TestCase):
    def mapping(self, neutral=(170, -15, 0)):
        mapping = TiltMapping()
        mapping.center(neutral)
        return mapping

    def test_neutral_and_noise_do_not_move(self):
        mapping = self.mapping()
        for i in range(1000):
            self.assertEqual(mapping.offset((170 + .4 * math.sin(i), -15 + .4 * math.cos(i), 90)), (0, 0))

    def test_roll_and_pitch_directions_independent_of_yaw(self):
        for angles, signs in (((-178, -15, 80), (1, 0)), ((158, -15, -80), (-1, 0)),
                              ((170, -3, 80), (0, -1)), ((170, -27, -80), (0, 1))):
            dx, dy = self.mapping().offset(angles)
            self.assertEqual(((dx > 0) - (dx < 0), (dy > 0) - (dy < 0)), signs)

    def test_roll_wrap_is_short_distance(self):
        mapping = self.mapping((179, 0, 0))
        self.assertEqual(mapping.offset((-179, 0, 0)), (38, 0))
        self.assertEqual(mapping.offset((-175, 0, 0)), (138, 0))

    def test_same_angle_same_offset_without_integration_or_creep(self):
        mapping = self.mapping()
        for _ in range(1000):
            self.assertEqual(mapping.offset((-170, 5, 0)), (488, -488))
        self.assertEqual(mapping.offset((170, -15, 0)), (0, 0))

    def test_distance_is_linear_in_degrees_and_sensitivity(self):
        mapping = self.mapping((0, 0, 0))
        self.assertEqual(mapping.offset((10.5, 0, 0)), (250, 0))
        self.assertEqual(mapping.offset((20.5, 0, 0)), (500, 0))
        mapping.speed = 2
        self.assertEqual(mapping.offset((10.5, 0, 0)), (500, 0))

    def test_reversal_and_vertical_guard(self):
        mapping = self.mapping()
        mapping.invert_x = mapping.invert_y = True
        dx, dy = mapping.offset((-170, 5, 0))
        self.assertLess(dx, 0)
        self.assertGreater(dy, 0)
        self.assertIsNone(mapping.offset((-170, 89, 0)))
        with self.assertRaises(ValueError):
            mapping.center((0, 90, 0))

    def test_recenter_changes_zero_reference(self):
        mapping = self.mapping()
        mapping.center((-170, 5, 10))
        self.assertEqual(mapping.offset((-170, 5, 10)), (0, 0))


class ControllerTests(unittest.TestCase):
    def controller(self):
        sensor, desktop = Sensor(), Desktop()
        return PointerController(sensor, desktop, auto_enable=False, sideways=False, stabilize=False), sensor, desktop

    def test_disabled_by_default_and_enable_captures_neutral(self):
        pointer, sensor, desktop = self.controller()
        pointer.tick(live((-170, 5, 0)), time.monotonic())
        self.assertEqual(desktop.moves, [])
        pointer.enable()
        self.assertEqual(pointer.snapshot()['neutral'], (170, -15))
        t = pointer.last_time
        for i in range(1, 101):
            pointer.tick(live((-170, 5, 0), sample_sequence=100 + i), t + i / 100)
        self.assertEqual(desktop.position(), (988, 12))
        self.assertEqual(len(desktop.moves), 1)  # Held tilt cannot keep moving.
        self.assertGreater(pointer.snapshot()['move_events'], 0)

    def test_returning_to_neutral_restores_anchor_even_after_screen_edge(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        pointer.tick(live((-100, -15, 0), sample_sequence=101), t+.01)
        self.assertEqual(desktop.position(), (1919, 500))
        pointer.tick(live(sample_sequence=102), t+.02)
        self.assertEqual(desktop.position(), (500, 500))

    def test_recenter_maps_current_hand_pose_to_screen_center(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        desktop.current_position = (700, 600)
        sensor.data = live((-170, 5, 0), sample_sequence=101)
        pointer.recenter()
        pointer.tick(sensor.data, pointer.last_time+.01)
        self.assertEqual(desktop.position(), (500, 500))
        self.assertEqual(pointer.snapshot()['origin'], (500, 500))

    def test_escape_and_connection_failures_stop_and_stay_off(self):
        variants = [dict(age_seconds=2.1), dict(calibration={'state': 'running'}),
                    dict(calibrated=False)]
        for changes in variants:
            pointer, sensor, desktop = self.controller()
            pointer.enable()
            pointer.tick(live(**changes), pointer.last_time + .01)
            self.assertFalse(pointer.snapshot()['enabled'], changes)
            pointer.tick(live((-170, 5, 0)), pointer.last_time + .01)
            self.assertEqual(desktop.moves, [])
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        desktop.escape = True
        pointer.tick(live(), pointer.last_time + .01)
        self.assertFalse(pointer.snapshot()['enabled'])
        self.assertEqual(desktop.moves, [])

    def test_no_motion_from_backlog_after_pause(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        pointer.tick(live((-170, 5, 0)), pointer.last_time + 1)
        self.assertTrue(pointer.snapshot()['suspended'])
        self.assertEqual(desktop.moves, [])

    def test_frozen_sequence_pauses_then_stops_even_if_fresh_flag_is_wrong(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        for i in range(1, 26):
            pointer.tick(live(), t + i / 100)
        self.assertTrue(pointer.snapshot()['suspended'])
        for i in range(26, 210):
            pointer.tick(live(), t + i / 100)
        self.assertFalse(pointer.snapshot()['enabled'])

    def test_transient_errors_resume_without_changing_neutral_or_replaying_clicks(self):
        variants = [dict(ready=False), dict(fresh=False), dict(age_seconds=.21),
                    dict(orientation_version=2), dict(angles=(float('nan'), 0, 0))]
        for changes in variants:
            pointer, sensor, desktop = self.controller()
            pointer.enable()
            neutral = pointer.mapping.neutral
            t = pointer.last_time
            pointer.tick(live(left_presses=9, **changes), t+.01)
            self.assertTrue(pointer.snapshot()['enabled'], changes)
            self.assertTrue(pointer.snapshot()['suspended'], changes)
            self.assertEqual(desktop.moves, [])
            self.assertEqual(desktop.clicks, [])
            version = changes.get('orientation_version', 1)
            for i in range(2, 30):
                pointer.tick(live((-170, 5, 0), orientation_version=version,
                                  sample_sequence=100+i, left_presses=10), t+i/100)
            self.assertTrue(pointer.snapshot()['enabled'], changes)
            self.assertFalse(pointer.snapshot()['suspended'], changes)
            self.assertEqual(pointer.mapping.neutral, neutral)
            self.assertGreater(len(desktop.moves), 0)
            self.assertEqual(desktop.clicks, [])
            self.assertEqual(pointer.snapshot()['recovery_events'], 1)
            pointer.tick(live(orientation_version=version, sample_sequence=131,
                              left_presses=11), t+.30)
            self.assertEqual(desktop.clicks, ['left'])

    def test_vertical_hold_has_hysteresis_and_resumes(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        for i in range(1, 50):
            pitch = 81 if i < 20 else 78
            pointer.tick(live((170, pitch, 0), sample_sequence=100+i), t+i/100)
        self.assertTrue(pointer.snapshot()['enabled'])
        self.assertTrue(pointer.snapshot()['suspended'])
        self.assertEqual(desktop.moves, [])
        for i in range(50, 75):
            pointer.tick(live(sample_sequence=100+i), t+i/100)
        self.assertFalse(pointer.snapshot()['suspended'])
        self.assertEqual(desktop.moves, [])

    def test_repeated_resets_extend_recovery_without_disable(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        for i in range(1, 100):
            pointer.tick(live(orientation_version=i+1, sample_sequence=100+i), t+i/100)
        self.assertTrue(pointer.snapshot()['enabled'])
        self.assertTrue(pointer.snapshot()['suspended'])
        self.assertEqual(desktop.moves, [])
        for i in range(100, 125):
            pointer.tick(live(orientation_version=100, sample_sequence=100+i), t+i/100)
        self.assertFalse(pointer.snapshot()['suspended'])

    def test_manual_pause_and_escape_during_recovery_remain_off(self):
        for escape in (False, True):
            pointer, sensor, desktop = self.controller()
            pointer.enable()
            t = pointer.last_time
            pointer.tick(live(ready=False), t+.01)
            if escape:
                desktop.escape = True
                pointer.tick(live(), t+.02)
                desktop.escape = False
            else:
                pointer.disable()
            for i in range(3, 50):
                pointer.tick(live((-170, 5, 0), left_presses=10, sample_sequence=100+i), t+i/100)
            self.assertFalse(pointer.snapshot()['enabled'])
            self.assertEqual(desktop.moves, [])
            self.assertEqual(desktop.clicks, [])

    def test_missing_calibration_cannot_enable(self):
        pointer, sensor, desktop = self.controller()
        sensor.data['calibrated'] = False
        with self.assertRaises(ValueError):
            pointer.enable()
        self.assertFalse(pointer.snapshot()['enabled'])

    def test_each_finger_clicks_correct_button_once_while_held(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        for i in range(1, 30):
            pointer.tick(live(left_presses=9, left_down=True, sample_sequence=100+i), t+i/100)
        self.assertEqual(desktop.clicks, ['left'])
        for i in range(30, 60):
            pointer.tick(live(left_presses=9, right_presses=14, right_down=True,
                              sample_sequence=100+i), t+i/100)
        self.assertEqual(desktop.clicks, ['left', 'right'])
        self.assertEqual(pointer.snapshot()['left_clicks'], 1)
        self.assertEqual(pointer.snapshot()['right_clicks'], 1)

    def test_short_taps_between_ticks_and_double_taps_are_received(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        for i, count in enumerate((9, 9, 10), 1):
            pointer.tick(live(left_presses=count, sample_sequence=100+i), t+i/20)
        self.assertEqual(desktop.clicks, ['left', 'left'])

    def test_disabled_contacts_are_not_replayed_after_enable(self):
        pointer, sensor, desktop = self.controller()
        sensor.data = live(left_presses=20, right_presses=30)
        pointer.tick(sensor.data, time.monotonic())
        pointer.enable()
        pointer.tick(sensor.data, pointer.last_time+.01)
        self.assertEqual(desktop.clicks, [])
        pointer.disable()
        sensor.data = live(left_presses=21, right_presses=31)
        pointer.enable()
        pointer.tick(sensor.data, pointer.last_time+.01)
        self.assertEqual(desktop.clicks, [])

    def test_held_contact_on_enable_requires_release_then_new_touch(self):
        pointer, sensor, desktop = self.controller()
        sensor.data = live(left_down=True)
        pointer.enable()
        t = pointer.last_time
        pointer.tick(live(left_down=True, left_presses=9), t+.01)
        pointer.tick(live(left_down=False, left_presses=9), t+.02)
        self.assertEqual(desktop.clicks, [])
        pointer.tick(live(left_down=True, left_presses=10), t+.03)
        self.assertEqual(desktop.clicks, ['left'])

    def test_stale_reset_calibration_and_escape_never_click(self):
        variants = [dict(fresh=False), dict(age_seconds=.21), dict(ready=False),
                    dict(orientation_version=2), dict(calibration={'state': 'running'}),
                    dict(angles=(170, 81, 0))]
        for changes in variants:
            pointer, sensor, desktop = self.controller()
            pointer.enable()
            pointer.tick(live(left_presses=9, right_presses=14, **changes), pointer.last_time+.01)
            self.assertEqual(desktop.clicks, [], changes)
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        desktop.escape = True
        pointer.tick(live(left_presses=9), pointer.last_time+.01)
        self.assertEqual(desktop.clicks, [])

    def test_counter_reset_or_backlog_is_discarded_then_new_touch_works(self):
        for count in (0, 50):
            pointer, sensor, desktop = self.controller()
            pointer.enable()
            pointer.tick(live(left_presses=count), pointer.last_time+.01)
            self.assertEqual(desktop.clicks, [])
            pointer.tick(live(left_presses=count+1), pointer.last_time+.01)
            self.assertEqual(desktop.clicks, ['left'])

    def test_uint32_counter_wrap_is_one_click(self):
        pointer, sensor, desktop = self.controller()
        sensor.data = live(right_presses=0xFFFFFFFF)
        pointer.enable()
        pointer.tick(live(right_presses=0), pointer.last_time+.01)
        self.assertEqual(desktop.clicks, ['right'])

    def test_both_contacts_emit_one_click_each(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        pointer.tick(live(left_presses=9, right_presses=14, left_down=True, right_down=True),
                     pointer.last_time+.01)
        self.assertEqual(desktop.clicks, ['left', 'right'])


@unittest.skipUnless(sys.platform == 'win32', 'Win32 ABI checks')
class WindowsClickTests(unittest.TestCase):
    def backend(self, results=(2,)):
        backend = WindowsPointer()
        calls = []
        answers = iter(results)

        def send(count, events, size):
            values = backend.ctypes.cast(events, backend.ctypes.POINTER(backend.input_type))
            calls.append([(values[i].type, values[i].mi.dwFlags) for i in range(count)])
            self.assertEqual(size, 40 if backend.ctypes.sizeof(backend.ctypes.c_void_p) == 8 else 28)
            return next(answers)

        # No real input injection: verify the exact native structures passed.
        backend.user32 = SimpleNamespace(SendInput=send)
        return backend, calls

    def test_left_and_right_press_release_pairs(self):
        for button, flags in (('left', (2, 4)), ('right', (8, 16))):
            backend, calls = self.backend()
            backend.click(button)
            self.assertEqual(calls, [[(0, flags[0]), (0, flags[1])]])

    def test_partial_send_releases_button_before_reporting_error(self):
        backend, calls = self.backend((1, 1))
        with self.assertRaises(OSError):
            backend.click('left')
        self.assertEqual(calls, [[(0, 2), (0, 4)], [(0, 4)]])

    def test_rejected_send_reports_error_without_retrying_click(self):
        backend, calls = self.backend((0,))
        with self.assertRaises(OSError):
            backend.click('right')
        self.assertEqual(calls, [[(0, 8), (0, 16)]])


if __name__ == '__main__':
    unittest.main()

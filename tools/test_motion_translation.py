import math
import time
import unittest
from motion_translation import InertialTranslation, CursorStabilizer, horizontal_axis, rotate_vector
from motion_pointer import PointerController
from test_motion_pointer import Sensor, Desktop, live


def swipe_live(position=(0, 0, 0), **changes):
    return live(translation={'ready': True, 'stationary': True, 'position_m': position},
                orientation_quaternion=(1, 0, 0, 0), **changes)


class TranslationTests(unittest.TestCase):
    def initialized(self):
        model = InertialTranslation()
        for _ in range(800): model.update((0, 0, .98, 0, 0, 0), (1, 0, 0, 0))
        self.assertTrue(model.ready)
        return model

    def test_bias_and_rest_do_not_integrate_forever(self):
        model = self.initialized()
        for i in range(10000):
            model.update((.001*math.sin(i), 0, .98, 0, 0, 0), (1, 0, 0, 0))
        self.assertEqual(model.position, [0, 0, 0])
        self.assertEqual(model.velocity, [0, 0, 0])

    def test_short_translation_moves_then_holds(self):
        model = self.initialized()
        for acceleration in (.2, -.2):
            for _ in range(200): model.update((acceleration, 0, .98, 0, 0, 0), (1, 0, 0, 0))
        for _ in range(700): model.update((0, 0, .98, 0, 0, 0), (1, 0, 0, 0))
        position = model.position[:]
        self.assertGreater(position[0], .005)
        self.assertLess(position[0], .2)
        for _ in range(1000): model.update((0, 0, .98, 0, 0, 0), (1, 0, 0, 0))
        self.assertEqual(model.position, position)

    def test_pure_rotation_gravity_is_not_sideways_translation(self):
        model = InertialTranslation()
        for _ in range(800): model.update((0, 0, 1, 0, 0, 0), (1, 0, 0, 0))
        for i in range(1000):
            angle = math.radians(30*i/1000)
            q = (math.cos(angle/2), 0, math.sin(angle/2), 0)
            gravity = (-math.sin(angle), 0, math.cos(angle))
            model.update((*gravity, 0, 30, 0), q)
        self.assertAlmostEqual(model.position[0], 0)

    def test_invalid_data_resets_readiness(self):
        model = self.initialized()
        model.update((0, 0, 1, 0, 0, 0), None)
        self.assertFalse(model.ready)
        self.assertEqual(model.velocity, [0, 0, 0])

    def test_horizontal_reference_follows_neutral_orientation(self):
        q = (math.sqrt(.5), 0, 0, math.sqrt(.5))
        axis = horizontal_axis(q)
        self.assertAlmostEqual(axis[0], 0)
        self.assertAlmostEqual(axis[1], 1)


class StabilizerTests(unittest.TestCase):
    def test_tremor_frequency_is_attenuated(self):
        filt = CursorStabilizer()
        output = []
        for i in range(400):
            point = filt.step((20*math.sin(2*math.pi*8*i*.01), 0), .01)
            if i > 100: output.append(point[0])
        self.assertLess(max(output)-min(output), 10)  # Input is 40 px peak-to-peak.

    def test_large_intentional_move_settles_quickly(self):
        filt = CursorStabilizer()
        for _ in range(40): point = filt.step((300, 200), .01)
        self.assertLess(math.hypot(point[0]-300, point[1]-200), 4)


class AutoSwipeTests(unittest.TestCase):
    def controller(self):
        sensor, desktop = Sensor(), Desktop()
        sensor.data = swipe_live()
        return PointerController(sensor, desktop), sensor, desktop

    def test_auto_connect_after_rest_and_no_click_replay(self):
        pointer, sensor, desktop = self.controller()
        t = time.monotonic()
        for i in range(80):
            pointer.tick(swipe_live(sample_sequence=100+i, left_presses=25), t+i*.01)
        self.assertTrue(pointer.enabled)
        self.assertEqual(desktop.clicks, [])

    def test_esc_survives_disconnect_and_reconnect(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        desktop.escape = True
        pointer.tick(swipe_live(), t+.01)
        desktop.escape = False
        pointer.tick(live(ready=False, age_seconds=3), t+3)
        for i in range(100): pointer.tick(swipe_live(sample_sequence=100+i), t+4+i*.01)
        self.assertFalse(pointer.enabled)
        self.assertTrue(pointer.manual_pause)

    def test_reconnect_automatically_recaptures_reference(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        pointer.tick(live(ready=False, age_seconds=3), t+.01)
        for i in range(100): pointer.tick(swipe_live(sample_sequence=100+i), t+.1+i*.01)
        self.assertTrue(pointer.enabled)

    def test_roll_does_not_move_x_but_translation_does(self):
        pointer, sensor, desktop = self.controller()
        pointer.enable()
        t = pointer.last_time
        for i in range(1, 60):
            pointer.tick(swipe_live(angles=(-160, -15, 0), sample_sequence=100+i), t+i*.01)
        self.assertEqual(desktop.position()[0], 500)
        for i in range(60, 120):
            pointer.tick(swipe_live((.05, 0, 0), sample_sequence=100+i), t+i*.01)
        self.assertAlmostEqual(desktop.position()[0], 750, delta=3)

    def test_uninitialized_translation_never_auto_activates(self):
        pointer, sensor, desktop = self.controller()
        t = time.monotonic()
        for i in range(100): pointer.tick(live(sample_sequence=100+i), t+i*.01)
        self.assertFalse(pointer.enabled)


if __name__ == '__main__': unittest.main()

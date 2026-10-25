import math
import unittest
from motion_translation import InertialTranslation, CursorStabilizer, horizontal_axis, rotate_vector


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


if __name__ == '__main__': unittest.main()

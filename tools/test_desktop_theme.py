"""Glove tab and preview banner colors come from desktop_theme. No hardware."""
from pathlib import Path
import unittest


TOOLS = Path(__file__).resolve().parent
PALETTE = ('#15181b', '#25353a', '#285d46', '#9aa39c', '#f0b429', '#f3f6f4', '#d2ffe3')
BANNER_HEX = ('#1b2822', '#b7cbbc')


def sensor_view(**overrides):
    data = {
        'ready': True,
        'angles': (1.25, -2.5, 0.5),
        'fresh': True,
        'status': 'connected',
        'left_presses': 0,
        'right_presses': 0,
        'left_down': False,
        'right_down': False,
        'transport': 'USB',
        'sample_hz': 1000.0,
        'temperature_c': 25.0,
        'tracking_restarts': 0,
        'calibration': {'state': 'idle', 'progress': 0.0},
        'calibrated': False,
    }
    data.update(overrides)
    return data


class ThemeSourceTests(unittest.TestCase):
    def test_glove_tab_and_preview_banner_use_theme_names(self):
        motion = (TOOLS / 'motion_panel.py').read_text(encoding='utf-8')
        viewer = (TOOLS / 'bluetooth_viewer.py').read_text(encoding='utf-8')
        theme = (TOOLS / 'desktop_theme.py').read_text(encoding='utf-8')
        for color in PALETTE:
            self.assertNotIn(color, motion, color)
        for color in BANNER_HEX:
            self.assertNotIn(color, viewer, color)
        for color in ('#25353a', '#285d46', '#d2ffe3', *BANNER_HEX):
            self.assertIn(color, theme, color)
        self.assertIn('bg=BANNER', viewer)
        self.assertIn('fg=BANNER_TEXT', viewer)


class GloveThemeTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except Exception as exc:
            self.skipTest(f'Tk unavailable: {exc}')
        self.tk = tk
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk desktop unavailable: {exc}')
        self.root.withdraw()
        from desktop_theme import (PANEL, INSET, TEXT, MUTED, WARN, DANGER, MINT,
                                   CHIP, SELECT, SELECT_TEXT)
        from motion_panel import MotionPanel
        self.colors = {
            'PANEL': PANEL, 'INSET': INSET, 'TEXT': TEXT, 'MUTED': MUTED, 'WARN': WARN,
            'DANGER': DANGER, 'MINT': MINT, 'CHIP': CHIP, 'SELECT': SELECT,
            'SELECT_TEXT': SELECT_TEXT,
        }
        self.panel = MotionPanel(self.root, connect=False)

    def tearDown(self):
        panel = getattr(self, 'panel', None)
        if panel is not None:
            panel.close()
        root = getattr(self, 'root', None)
        if root is not None:
            root.destroy()

    def paint(self, widget, option):
        return widget.cget(option)

    def test_resting_glove_tab_uses_shared_surfaces(self):
        panel = self.panel
        self.assertEqual(self.paint(panel.frame, 'bg'), self.colors['PANEL'])
        self.assertEqual(self.paint(panel.clicks, 'bg'), self.colors['PANEL'])
        self.assertEqual(self.paint(panel.status, 'bg'), self.colors['PANEL'])
        self.assertEqual(self.paint(panel.status, 'fg'), self.colors['MUTED'])
        self.assertEqual(self.paint(panel.cal_status, 'fg'), self.colors['WARN'])
        self.assertEqual(self.paint(panel.pointer_status, 'fg'), self.colors['WARN'])
        self.assertEqual(self.paint(panel.sensitivity_label, 'fg'), self.colors['MUTED'])
        for label in panel.angle_labels:
            self.assertEqual(self.paint(label, 'bg'), self.colors['INSET'])
            self.assertEqual(self.paint(label, 'fg'), self.colors['MUTED'])
        for label in panel.contact_labels:
            self.assertEqual(label.cget('text'), 'Waiting for contacts')
            self.assertEqual(self.paint(label, 'bg'), self.colors['CHIP'])
            self.assertEqual(self.paint(label, 'fg'), self.colors['MUTED'])

    def test_live_contacts_and_angles_follow_theme_states(self):
        panel = self.panel
        panel.sensor.snapshot = lambda: sensor_view(left_down=True, left_presses=1)
        panel.update()
        self.assertEqual(panel.angle_labels[0].cget('text'), '+1.25°')
        self.assertEqual(self.paint(panel.angle_labels[0], 'fg'), self.colors['TEXT'])
        self.assertEqual(self.paint(panel.contact_labels[0], 'bg'), self.colors['SELECT'])
        self.assertEqual(self.paint(panel.contact_labels[0], 'fg'), self.colors['SELECT_TEXT'])
        self.assertIn('HELD', panel.contact_labels[0].cget('text'))
        self.assertEqual(self.paint(panel.contact_labels[1], 'bg'), self.colors['CHIP'])
        self.assertEqual(self.paint(panel.contact_labels[1], 'fg'), self.colors['MUTED'])
        self.assertEqual(self.paint(panel.cal_status, 'fg'), self.colors['MUTED'])
        self.assertEqual(self.paint(panel.pointer_status, 'fg'), self.colors['MUTED'])

        panel.sensor.snapshot = lambda: sensor_view(left_down=False, left_presses=2)
        panel.update()
        self.assertEqual(self.paint(panel.contact_labels[0], 'bg'), self.colors['SELECT'])
        self.assertEqual(self.paint(panel.contact_labels[0], 'fg'), self.colors['SELECT_TEXT'])
        self.assertIn('TAP', panel.contact_labels[0].cget('text'))

        panel.sensor.snapshot = lambda: sensor_view(
            fresh=False, ready=False, angles=None, left_down=None, right_down=None,
            calibration={'state': 'running', 'progress': 0.2})
        panel.update()
        self.assertEqual(self.paint(panel.angle_labels[0], 'fg'), self.colors['MUTED'])
        self.assertEqual(self.paint(panel.contact_labels[0], 'bg'), self.colors['CHIP'])
        self.assertEqual(self.paint(panel.contact_labels[0], 'fg'), self.colors['MUTED'])
        self.assertIn('NO SIGNAL', panel.contact_labels[0].cget('text'))
        self.assertEqual(self.paint(panel.cal_status, 'fg'), self.colors['WARN'])

        panel.error = 'Calibration failed in this test double.'
        panel.sensor.snapshot = lambda: sensor_view(calibration={'state': 'failed', 'progress': 1})
        panel.update()
        self.assertEqual(self.paint(panel.cal_status, 'fg'), self.colors['DANGER'])

        panel.pointer_error = None
        panel.pointer.enabled = True
        panel.pointer.suspended = False
        panel.sensor.snapshot = lambda: sensor_view()
        panel.update()
        self.assertEqual(self.paint(panel.pointer_status, 'fg'), self.colors['MINT'])

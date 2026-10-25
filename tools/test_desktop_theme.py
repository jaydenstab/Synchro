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
        self.assertNotIn('BLE MTU', panel.status.cget('text'))
        panel.sensor.snapshot = lambda: sensor_view(transport='Bluetooth LE', ble_mtu=23)
        panel.update()
        self.assertIn('BLE MTU 23', panel.status.cget('text'))
        panel.sensor.snapshot = lambda: sensor_view(transport='Bluetooth LE', ble_mtu=247)
        panel.update()
        self.assertNotIn('BLE MTU', panel.status.cget('text'))
        panel.sensor.snapshot = lambda: sensor_view(left_down=True, left_presses=1)
        panel.update()
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


class InputLevelTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            self.skipTest(f'Tk unavailable: {exc}')
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk desktop unavailable: {exc}')
        self.ttk = ttk
        from desktop_theme import MUTED, MINT, MINT_BRIGHT, LINE, install_theme
        from speech_panel import SpeechPanel
        self.root.geometry('480x640')
        install_theme(self.root)
        self.colors = {'MUTED': MUTED, 'MINT': MINT, 'MINT_BRIGHT': MINT_BRIGHT, 'LINE': LINE}
        self.panel = SpeechPanel(self.root, preview=True)
        self.panel.frame.pack(fill='both', expand=True)
        self.root.update()
        self.root.withdraw()

    def tearDown(self):
        panel = getattr(self, 'panel', None)
        if panel is not None:
            panel.close()
        root = getattr(self, 'root', None)
        if root is not None:
            root.destroy()

    def show(self, **overrides):
        data = {
            'listening': False, 'error': None, 'status': 'Mic off',
            'noise_suppression': False, 'latency_ms': None, 'dropped': 0,
            'level': 0.0, 'voice': False, 'revision': 0, 'text': '',
        }
        data.update(overrides)
        self.panel.controller.snapshot = lambda include_text=True: data
        self.panel.update()

    def test_meter_is_a_full_row_and_tracks_speech(self):
        panel = self.panel
        style = self.ttk.Style(self.root)
        self.assertEqual(panel.level_caption.cget('text'), 'Input level')
        self.assertEqual(panel.level_caption.cget('fg'), self.colors['MUTED'])
        self.assertEqual(panel.level.cget('style'), 'Level.Horizontal.TProgressbar')
        self.assertEqual(int(style.lookup('Level.Horizontal.TProgressbar', 'thickness')), 12)
        self.assertEqual(style.lookup('Level.Horizontal.TProgressbar', 'troughcolor'), self.colors['LINE'])
        self.assertEqual(style.lookup('Level.Horizontal.TProgressbar', 'background'), self.colors['MINT'])
        self.assertEqual(style.lookup('Level.Voice.Horizontal.TProgressbar', 'background'), self.colors['MINT_BRIGHT'])
        self.assertEqual(int(style.lookup('Horizontal.TProgressbar', 'thickness')), 5)
        self.assertGreater(panel.level.winfo_width(), 200)
        self.assertGreater(panel.level.winfo_rooty(), panel.button.winfo_rooty())
        bar_mid = panel.level.winfo_rooty() + panel.level.winfo_height() / 2
        caption_mid = panel.level_caption.winfo_rooty() + panel.level_caption.winfo_height() / 2
        self.assertLess(abs(bar_mid - caption_mid), 8)

        self.show(listening=True, level=0.4, voice=False)
        self.assertEqual(panel.level.cget('style'), 'Level.Horizontal.TProgressbar')
        self.assertAlmostEqual(panel.level['value'], 40)
        self.assertEqual(panel.level_caption.cget('fg'), self.colors['MINT'])

        self.show(listening=True, level=0.8, voice=True)
        self.assertEqual(panel.level.cget('style'), 'Level.Voice.Horizontal.TProgressbar')
        self.assertAlmostEqual(panel.level['value'], 80)
        self.assertEqual(panel.level_caption.cget('fg'), self.colors['MINT_BRIGHT'])

        self.show(listening=False, level=0, voice=True)
        self.assertEqual(panel.level.cget('style'), 'Level.Horizontal.TProgressbar')
        self.assertEqual(panel.level_caption.cget('fg'), self.colors['MUTED'])

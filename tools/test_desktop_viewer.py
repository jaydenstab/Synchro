"""Opt-in native layout and control smoke test. Requires a desktop session."""
import os
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace


@unittest.skipUnless(os.environ.get('SYNCHRO_TEST_DESKTOP') == '1', 'requires an interactive Tk desktop')
class DesktopViewerTests(unittest.TestCase):
    def test_tabs_fit_and_camera_controls_follow_connection_lifecycle(self):
        self.check_viewer(preview=False)

    def test_preview_opens_no_hardware_and_has_the_same_tabs(self):
        self.check_viewer(preview=True)

    def test_voice_test_launch_keeps_glove_tab_visible(self):
        self.check_viewer(preview=True, pause_pointer=True)

    def test_camera_frame_is_displayed_with_tk_work_on_main_thread(self):
        self.check_viewer(preview=False, live_camera=True)

    def check_viewer(self, preview, pause_pointer=False, live_camera=False):
        import threading
        import time
        from PIL import Image, ImageTk
        from bluetooth_viewer import ReceivedJPEG
        import tkinter as tk
        from tkinter import ttk
        from bluetooth_viewer import launch_viewer, FrameRate
        from motion_sensor import MotionSensor
        from motion_pointer import PointerController
        import speech_stream  # Load optional compiled dependencies before the module sandbox.

        errors = []
        observations = []
        rate_changes = []
        original_set_rate = FrameRate.set
        def set_rate(rate, value):
            original_set_rate(rate, value)
            rate_changes.append(rate.get())

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        def run_checks(root):
            try:
                root.update()
                notebook = next(w for w in walk(root) if isinstance(w, ttk.Notebook))
                if pause_pointer:
                    self.assertEqual(notebook.tab(notebook.select(), 'text'), 'Speech & Jarvis')
                for geometry in ('980x720', '1280x860'):
                    root.geometry(geometry)
                    root.update()
                    for tab in notebook.tabs():
                        notebook.select(tab)
                        root.update()
                        for widget in walk(root):
                            if isinstance(widget, (ttk.Button, ttk.Combobox, ttk.Scale, tk.Text, tk.Label)) and widget.winfo_ismapped():
                                right = widget.winfo_rootx() + widget.winfo_width()
                                bottom = widget.winfo_rooty() + widget.winfo_height()
                                self.assertGreaterEqual(widget.winfo_rootx(), root.winfo_rootx(), str(widget))
                                self.assertLessEqual(right, root.winfo_rootx() + root.winfo_width(), str(widget))
                                self.assertLessEqual(bottom, root.winfo_rooty() + root.winfo_height(), str(widget))
                cap = next(w for w in walk(root) if isinstance(w, ttk.Combobox)
                           and '30' in w.cget('values'))
                self.assertEqual(cap.get(), '15')
                cap.set('30')
                cap.event_generate('<<ComboboxSelected>>')
                root.update()
                self.assertEqual(rate_changes[-1], 30)
                observations.extend(notebook.tab(tab, 'text') for tab in notebook.tabs())
                from desktop_theme import BANNER, BANNER_TEXT, CHIP, MUTED, PANEL
                motion_frame = root.nametowidget(notebook.tabs()[0])
                self.assertEqual(notebook.tab(notebook.tabs()[0], 'text'), 'Glove')
                self.assertEqual(motion_frame.cget('bg'), PANEL)
                contacts = [w for w in walk(motion_frame) if isinstance(w, tk.Label) and (
                    'CLICK' in str(w.cget('text')) or w.cget('text') == 'Waiting for contacts')]
                self.assertEqual([w.cget('bg') for w in contacts], [CHIP, CHIP])
                self.assertEqual([w.cget('fg') for w in contacts], [MUTED, MUTED])
                banners = [w for w in walk(root) if isinstance(w, tk.Label)
                           and str(w.cget('text')).startswith('PREVIEW MODE')]
                if preview:
                    self.assertEqual([(w.cget('bg'), w.cget('fg')) for w in banners], [(BANNER, BANNER_TEXT)])
                else:
                    self.assertEqual(banners, [])
                levels = [w for w in walk(root) if isinstance(w, ttk.Progressbar) and str(w.cget('style')).startswith('Level.')]
                captions = [w for w in walk(root) if isinstance(w, tk.Label) and w.cget('text') == 'Input level']
                self.assertEqual(len(levels), 1)
                self.assertEqual(len(captions), 1)
                self.assertGreater(levels[0].winfo_width(), 160)
                bar_mid = levels[0].winfo_rooty() + levels[0].winfo_height() / 2
                caption_mid = captions[0].winfo_rooty() + captions[0].winfo_height() / 2
                self.assertLess(abs(bar_mid - caption_mid), 8)
                # Both transcript/conversation views and every screenshot control must survive the redesign.
                inner = next(w for w in walk(root) if isinstance(w, ttk.Notebook) and w is not notebook)
                self.assertEqual([inner.tab(t, 'text') for t in inner.tabs()], ['Live transcript', 'Jarvis conversation'])
                for tab in inner.tabs():
                    inner.select(tab)
                    root.update()
                    self.assertGreater(root.nametowidget(tab).winfo_height(), 60)
                checks = {w.cget('text'): w for w in walk(root) if isinstance(w, ttk.Checkbutton)}
                for name in ('Listen for Jarvis', 'Read aloud', 'Typing & keys', 'Rotate 180°'):
                    self.assertIn(name, checks)
                self.assertNotIn('Noise suppression · RNNoise', checks)
                self.assertNotIn('Show motion and cursor controls', checks)
                for tab in notebook.tabs():
                    self.assertEqual(notebook.tab(tab, 'state'), 'normal')
                # The transcript now uses the themed ttk scrollbar, not a bright native Tk scrollbar.
                self.assertFalse(any(w.winfo_class() == 'Scrollbar' for w in walk(root)))
                buttons = {w.cget('text'): w for w in walk(root) if isinstance(w, ttk.Button)}
                self.assertEqual(str(buttons['Save photo'].cget('state')), 'normal' if live_camera else 'disabled')
                if live_camera:
                    self.assertTrue(any(w.cget('image') for w in walk(root) if isinstance(w, tk.Label)),
                                    'A decoded fixture should reach the actual Tk camera preview')
                self.assertEqual(str(buttons['Start camera'].cget('state')), 'disabled')
                for name in ('Stop reply', 'New chat', 'Start mic'):
                    self.assertIn(name, buttons)
                    if preview:
                        self.assertTrue(buttons[name].instate(['disabled']))
                if not preview:
                    checks['Read aloud'].invoke()
                    configure.assert_called_with(enabled=True, read_aloud=False, type_writes=True)
                    buttons['Start mic'].invoke()
                    speech_start.assert_called_once_with(None, noise_suppression=False)
                    buttons['Stop reply'].invoke()
                    cancel.assert_called()
                    buttons['New chat'].invoke()
                    new_chat.assert_called_once()
                buttons['Stop'].invoke()
                self.assertEqual(str(buttons['Stop'].cget('state')), 'disabled')
            except Exception as exc:
                errors.append(exc)
            finally:
                root.tk.call(root.protocol('WM_DELETE_WINDOW'))

        real_mainloop = tk.Tk.mainloop

        def loop(root):
            root.after(100, lambda: run_checks(root))
            real_mainloop(root)

        query_devices = Mock(return_value=[])
        main_thread = threading.get_ident()
        image_threads = []
        real_photo = ImageTk.PhotoImage
        def make_photo(*args, **kwargs):
            image_threads.append(threading.get_ident())
            return real_photo(*args, **kwargs)
        picture = Image.new('RGB', (640, 480), '#42785e')
        from io import BytesIO
        output = BytesIO()
        picture.save(output, format='JPEG')
        def capture():
            now = time.perf_counter()
            return ReceivedJPEG(output.getvalue(), 640, 480, now - .01, now)
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(query_devices=query_devices)}), \
             patch.object(tk.Tk, 'mainloop', loop), patch.object(FrameRate, 'set', set_rate), \
             patch('bluetooth_viewer.Camera.connect', side_effect=None if live_camera else OSError('No camera attached')) as camera_connect, \
             patch('bluetooth_viewer.Camera.receive_jpeg', side_effect=capture), \
             patch('PIL.ImageTk.PhotoImage', side_effect=make_photo), \
             patch.object(MotionSensor, 'start') as sensor_start, patch.object(MotionSensor, 'close'), \
             patch.object(PointerController, 'start') as pointer_start, \
             patch('speech_stream.SpeechController.start') as speech_start, \
             patch('jarvis_assistant.JarvisAssistant.configure') as configure, \
             patch('jarvis_assistant.JarvisAssistant.cancel') as cancel, \
             patch('jarvis_assistant.JarvisAssistant.new_conversation') as new_chat, \
             patch('jarvis_assistant.GeminiVision.ask') as ask, \
             patch('jarvis_assistant.WindowsSpeech.speak') as speak, \
             patch('text_writer.WindowsTextWriter.write') as write:
            launch_viewer('00:00:00:00:00:00', 1, 15, preview=preview, pause_pointer=pause_pointer)
            if preview:
                camera_connect.assert_not_called()
                sensor_start.assert_not_called()
                pointer_start.assert_not_called()
                speech_start.assert_not_called()
                query_devices.assert_not_called()
                ask.assert_not_called()
                speak.assert_not_called()
                write.assert_not_called()
                configure.assert_not_called()
        if live_camera:
            self.assertTrue(image_threads)
        self.assertTrue(all(thread == main_thread for thread in image_threads), 'Tk images must only be created on main')
        if errors:
            raise errors[0]
        self.assertEqual(observations, ['Glove', 'Speech & Jarvis'])

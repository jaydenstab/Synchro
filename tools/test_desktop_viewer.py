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

    def check_viewer(self, preview):
        import tkinter as tk
        from tkinter import ttk
        from bluetooth_viewer import launch_viewer
        from motion_sensor import MotionSensor
        from motion_pointer import PointerController
        import speech_stream  # Load optional compiled dependencies before the module sandbox.

        errors = []
        observations = []

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        def run_checks(root):
            try:
                root.geometry('980x720')
                root.update()
                notebook = next(w for w in walk(root) if isinstance(w, ttk.Notebook))
                for tab in notebook.tabs():
                    notebook.select(tab)
                    root.update()
                    content = root.nametowidget(tab)
                    for widget in walk(content):
                        if isinstance(widget, (ttk.Button, ttk.Combobox, ttk.Scale, tk.Text)) and widget.winfo_ismapped():
                            right = widget.winfo_rootx() + widget.winfo_width()
                            bottom = widget.winfo_rooty() + widget.winfo_height()
                            self.assertLessEqual(right, root.winfo_rootx() + root.winfo_width())
                            self.assertLessEqual(bottom, root.winfo_rooty() + root.winfo_height())
                    observations.append(notebook.tab(tab, 'text'))
                # Both transcript/conversation views and every screenshot control must survive the redesign.
                inner = next(w for w in walk(root) if isinstance(w, ttk.Notebook) and w is not notebook)
                self.assertEqual([inner.tab(t, 'text') for t in inner.tabs()], ['Live transcript', 'Jarvis conversation'])
                for tab in inner.tabs():
                    inner.select(tab)
                    root.update()
                    self.assertGreater(root.nametowidget(tab).winfo_height(), 60)
                checks = {w.cget('text'): w for w in walk(root) if isinstance(w, ttk.Checkbutton)}
                for name in ('Listen for Jarvis', 'Read aloud', 'Type writing requests',
                             'Noise suppression · RNNoise', 'Show motion and cursor controls', 'Rotate 180°'):
                    self.assertIn(name, checks)
                checks['Show motion and cursor controls'].invoke()
                self.assertEqual(notebook.tab(notebook.tabs()[0], 'state'), 'hidden')
                checks['Show motion and cursor controls'].invoke()
                self.assertEqual(notebook.tab(notebook.tabs()[0], 'state'), 'normal')
                buttons = {w.cget('text'): w for w in walk(root) if isinstance(w, ttk.Button)}
                self.assertEqual(str(buttons['Save photo'].cget('state')), 'disabled')
                self.assertEqual(str(buttons['Start camera'].cget('state')), 'disabled')
                for name in ('Stop reply', 'New chat', 'Start mic'):
                    self.assertIn(name, buttons)
                    if preview:
                        self.assertTrue(buttons[name].instate(['disabled']))
                if not preview:
                    checks['Read aloud'].invoke()
                    configure.assert_called_with(enabled=True, read_aloud=False, type_writes=True)
                    checks['Noise suppression · RNNoise'].invoke()
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
        with patch.dict('sys.modules', {'sounddevice': SimpleNamespace(query_devices=query_devices)}), \
             patch.object(tk.Tk, 'mainloop', loop), \
             patch('bluetooth_viewer.Camera.connect', side_effect=OSError('No camera attached')) as camera_connect, \
             patch.object(MotionSensor, 'start') as sensor_start, patch.object(MotionSensor, 'close'), \
             patch.object(PointerController, 'start') as pointer_start, \
             patch('speech_stream.SpeechController.start') as speech_start, \
             patch('jarvis_assistant.JarvisAssistant.configure') as configure, \
             patch('jarvis_assistant.JarvisAssistant.cancel') as cancel, \
             patch('jarvis_assistant.JarvisAssistant.new_conversation') as new_chat, \
             patch('jarvis_assistant.GeminiVision.ask') as ask, \
             patch('jarvis_assistant.WindowsSpeech.speak') as speak, \
             patch('text_writer.WindowsTextWriter.write') as write:
            launch_viewer('00:00:00:00:00:00', 1, 15, preview=preview)
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
        if errors:
            raise errors[0]
        self.assertEqual(observations, ['Glove', 'Speech & Jarvis'])

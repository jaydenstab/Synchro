"""Typing regressions use fake focus and SendInput; no desktop text is injected."""
import ctypes
import os
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from text_writer import (FocusTarget, TextWriteError, WindowsTextWriter, WindowsTextBackend,
                         CHARACTER_INTERVAL, KEY_CHORDS)


class Backend:
    def __init__(self):
        self.target = FocusTarget(123, 456, (42, 7))
        self.sent = []
        self.keys = []
        self.interruption = None
    def focused(self): return self.target
    def interrupted(self): return self.interruption
    def send(self, text): self.sent.append(text)
    def press(self, key): self.keys.append(key)


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.writer = WindowsTextWriter(self.backend)
        self.addCleanup(self.writer.close)
        self.target = self.writer.capture()
        self.cancel = threading.Event()

    def test_unicode_and_line_breaks_are_preserved(self):
        text = 'hELLo, Alex!\nCafé — 你好 🙂\tend.'
        self.assertEqual(self.writer.write(text, self.target, self.cancel), len(text))
        self.assertEqual(''.join(self.backend.sent), text)

    def test_different_textbox_in_same_window_is_not_typed_into(self):
        self.backend.target = FocusTarget(123, 456, (42, 8))
        with self.assertRaisesRegex(TextWriteError, 'Focus changed'):
            self.writer.write('Hello.', self.target, self.cancel)
        self.assertEqual(self.backend.sent, [])

    def test_focus_change_during_typing_stops_remaining_chunks(self):
        original = self.backend.send
        def send(text):
            original(text)
            self.backend.target = FocusTarget(789, 456, (42, 7))
        self.backend.send = send
        with self.assertRaises(TextWriteError):
            self.writer.write('a' * 150, self.target, self.cancel)
        self.assertEqual(''.join(self.backend.sent), 'a')

    def test_reported_repeating_letter_phrase_is_paced_one_character_at_a_time(self):
        text = 'Kirkland Signature Sparkling Energy Drink Tropical'
        with patch.object(self.cancel, 'wait', return_value=False) as wait:
            self.writer.write(text,self.target,self.cancel)
        self.assertEqual(self.backend.sent,list(text))
        self.assertEqual(wait.call_count,len(text)-1)
        self.assertTrue(all(call.args==(CHARACTER_INTERVAL,) for call in wait.call_args_list))

    def test_cancellation_during_pacing_stops_before_next_character(self):
        with patch.object(self.cancel,'wait',return_value=True):
            with self.assertRaisesRegex(TextWriteError,'cancelled'):
                self.writer.write('abc',self.target,self.cancel)
        self.assertEqual(self.backend.sent,['a'])

    def test_chords_are_explicit_once_and_keep_clipboard_text_out_of_writer(self):
        for key in ('enter','ctrl+a','ctrl+c','ctrl+v','shift+enter'):
            self.writer.press(key,self.target,self.cancel)
        self.assertEqual(self.backend.keys,['enter','ctrl+a','ctrl+c','ctrl+v','shift+enter'])
        self.assertEqual(self.backend.sent,[])

    def test_chord_refuses_changed_focus_cancelled_or_unsupported_commands(self):
        self.backend.target=FocusTarget(789,456,(42,7))
        with self.assertRaisesRegex(TextWriteError,'Focus changed'):
            self.writer.press('enter',self.target,self.cancel)
        self.backend.target=self.target
        self.cancel.set()
        with self.assertRaisesRegex(TextWriteError,'cancelled'):
            self.writer.press('ctrl+a',self.target,self.cancel)
        for key in ('alt+f4','win+r','ctrl+alt+delete'):
            with self.assertRaisesRegex(TextWriteError,'not supported'):
                self.writer.press(key,self.target,threading.Event())
        self.assertEqual(self.backend.keys,[])

    def test_cancel_or_modifier_or_escape_sends_nothing(self):
        self.cancel.set()
        with self.assertRaises(TextWriteError):
            self.writer.write('Hello.', self.target, self.cancel)
        self.cancel.clear()
        self.backend.interruption = 'Typing stopped with Esc.'
        with self.assertRaises(TextWriteError):
            self.writer.write('Hello.', self.target, self.cancel)
        self.assertEqual(self.backend.sent, [])

    def test_invalid_input_or_missing_target_is_rejected_before_typing(self):
        for text, target in [('', self.target), ('a' * 12001, self.target),
                             ('hello\x1b', self.target), ('Hello.', None)]:
            with self.assertRaises(TextWriteError):
                self.writer.write(text, target, self.cancel)
        self.assertEqual(self.backend.sent, [])

    def test_readonly_password_disabled_and_nontext_controls_are_rejected(self):
        base = dict(CurrentIsEnabled=True, CurrentHasKeyboardFocus=True,
                    CurrentIsPassword=False, CurrentControlType=50004)
        for change in (dict(CurrentIsEnabled=False), dict(CurrentHasKeyboardFocus=False),
                       dict(CurrentIsPassword=True), dict(CurrentControlType=50000)):
            self.assertFalse(WindowsTextBackend._editable(SimpleNamespace(**(base | change)), None))
        class Pattern:
            def QueryInterface(self, _): return self
            CurrentIsReadOnly = True
        element = SimpleNamespace(**base, GetCurrentPattern=lambda _: Pattern())
        self.assertFalse(WindowsTextBackend._editable(element, SimpleNamespace(IUIAutomationValuePattern=object())))


@unittest.skipUnless(os.name == 'nt', 'Windows INPUT layout')
class NativePacketTests(unittest.TestCase):
    def test_only_unicode_pairs_no_enter_or_shortcut_virtual_keys(self):
        backend = WindowsTextBackend()
        recorded = []
        def send(count, events, size):
            self.assertEqual(size, 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
            recorded.extend((e.type, e.ki.wVk, e.ki.wScan, e.ki.dwFlags) for e in events)
            return count
        backend.user32 = SimpleNamespace(SendInput=send)
        for character in 'A\n🙂':
            backend.send(character)
        self.assertTrue(all(kind == 1 and vk == 0 for kind, vk, scan, flags in recorded))
        self.assertEqual([row[3] for row in recorded], [4, 6] * 4)
        self.assertEqual([row[2] for row in recorded[::2]], [65, 10, 0xD83D, 0xDE42])

    def test_partial_send_is_not_retried(self):
        backend = WindowsTextBackend()
        calls = []
        def send(count, events, size):
            calls.append(count)
            return 0
        backend.user32 = SimpleNamespace(SendInput=send)
        with self.assertRaisesRegex(TextWriteError, 'partially inserted'):
            backend.send('H')
        self.assertEqual(calls, [2])

    def test_batched_characters_are_rejected(self):
        with self.assertRaisesRegex(TextWriteError,'one Unicode character'):
            WindowsTextBackend().send('Hello')

    def test_partial_unicode_press_is_released(self):
        backend=WindowsTextBackend(); calls=[]
        def send(count,events,size):
            rows=ctypes.cast(events,ctypes.POINTER(backend.input_type))
            calls.append([(rows[i].ki.wScan,rows[i].ki.dwFlags) for i in range(count)])
            return 1
        backend.user32=SimpleNamespace(SendInput=send)
        with self.assertRaises(TextWriteError):backend.send('E')
        self.assertEqual(calls,[[(69,4),(69,6)],[(69,6)]])

    def test_chord_keys_release_in_reverse_order_and_navigation_is_extended(self):
        backend=WindowsTextBackend(); calls=[]
        def send(count,events,size):
            calls.append([(e.ki.wVk,e.ki.wScan,e.ki.dwFlags) for e in events])
            return count
        backend.user32=SimpleNamespace(SendInput=send)
        backend.press('ctrl+a');backend.press('enter');backend.press('left')
        self.assertEqual(calls, [[(17,0,0),(65,0,0),(65,0,2),(17,0,2)],
                                [(13,0,0),(13,0,2)],[(37,0,1),(37,0,3)]])

    def test_partial_chord_releases_pressed_keys_without_repeating_command(self):
        backend=WindowsTextBackend();calls=[]
        def send(count,events,size):
            rows=ctypes.cast(events,ctypes.POINTER(backend.input_type))
            calls.append([(rows[i].ki.wVk,rows[i].ki.dwFlags) for i in range(count)])
            return 2 if len(calls)==1 else 1
        backend.user32=SimpleNamespace(SendInput=send)
        with self.assertRaisesRegex(TextWriteError,'not retried'):backend.press('ctrl+c')
        self.assertEqual(calls,[[(17,0),(67,0),(67,2),(17,2)],[(67,2)],[(17,2)]])


if __name__ == '__main__':
    unittest.main()

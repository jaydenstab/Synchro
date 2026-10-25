"""Typing regressions use fake focus and SendInput; no desktop text is injected."""
import ctypes
import os
import threading
from types import SimpleNamespace
import unittest

from text_writer import FocusTarget, TextWriteError, WindowsTextWriter, WindowsTextBackend


class Backend:
    def __init__(self):
        self.target = FocusTarget(123, 456, (42, 7))
        self.sent = []
        self.interruption = None
    def focused(self): return self.target
    def interrupted(self): return self.interruption
    def send(self, text): self.sent.append(text)


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.writer = WindowsTextWriter(self.backend)
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
        self.assertEqual(''.join(self.backend.sent), 'a' * 64)

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
        backend.send('A\n🙂')
        self.assertTrue(all(kind == 1 and vk == 0 for kind, vk, scan, flags in recorded))
        self.assertEqual([row[3] for row in recorded], [4, 6] * 4)
        self.assertEqual([row[2] for row in recorded[::2]], [65, 10, 0xD83D, 0xDE42])

    def test_partial_send_is_not_retried(self):
        backend = WindowsTextBackend()
        calls = []
        def send(count, events, size):
            calls.append(count)
            return 2
        backend.user32 = SimpleNamespace(SendInput=send)
        with self.assertRaisesRegex(TextWriteError, 'partially inserted'):
            backend.send('Hello.')
        self.assertEqual(calls, [12])


if __name__ == '__main__':
    unittest.main()

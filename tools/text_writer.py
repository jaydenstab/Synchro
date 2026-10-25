"""Insert plain Unicode text into the same focused, writable Windows text field.

No clipboard, window activation, shortcuts or submit/Enter key is used.
UI Automation supplies identity and editability, never the field's contents.
"""
from dataclasses import dataclass
import os
import threading


class TextWriteError(Exception):
    pass


@dataclass(frozen=True)
class FocusTarget:
    window: int
    process: int
    runtime_id: tuple


class WindowsTextBackend:
    def __init__(self):
        if os.name != 'nt':
            raise TextWriteError('Typing into another app currently requires Windows.')
        import ctypes as c
        from ctypes import wintypes as w
        self.c = c
        self.user32 = c.WinDLL('user32', use_last_error=True)
        self.kernel32 = c.WinDLL('kernel32', use_last_error=True)
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = w.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = w.DWORD
        self.user32.GetAsyncKeyState.argtypes = [c.c_int]
        self.user32.GetAsyncKeyState.restype = c.c_short
        self.kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel32.OpenProcess.restype = w.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
        self.kernel32.QueryFullProcessImageNameW.restype = w.BOOL
        self.kernel32.CloseHandle.argtypes = [w.HANDLE]
        self.kernel32.CloseHandle.restype = w.BOOL

        class KeyInput(c.Structure):
            _fields_ = [('wVk', w.WORD), ('wScan', w.WORD), ('dwFlags', w.DWORD),
                        ('time', w.DWORD), ('dwExtraInfo', c.c_size_t)]

        class MouseInput(c.Structure):
            _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD),
                        ('dwFlags', w.DWORD), ('time', w.DWORD), ('dwExtraInfo', c.c_size_t)]

        class InputUnion(c.Union):
            _fields_ = [('ki', KeyInput), ('mi', MouseInput)]

        class Input(c.Structure):
            _anonymous_ = ('value',)
            _fields_ = [('type', w.DWORD), ('value', InputUnion)]

        self.input_type = Input
        self.user32.SendInput.argtypes = [w.UINT, c.POINTER(Input), c.c_int]
        self.user32.SendInput.restype = w.UINT

    def _process_name(self, pid):
        from ctypes import wintypes as w
        handle = self.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            raise TextWriteError('Cannot verify the selected app. Click a text box and try again.')
        try:
            buffer, length = self.c.create_unicode_buffer(32768), w.DWORD(32768)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, self.c.byref(length)):
                raise TextWriteError('Cannot verify the selected app. Click a text box and try again.')
            return os.path.basename(buffer.value).lower()
        finally:
            self.kernel32.CloseHandle(handle)

    @staticmethod
    def _editable(element, uia):
        if (not element.CurrentIsEnabled or not element.CurrentHasKeyboardFocus or
                element.CurrentIsPassword or element.CurrentControlType not in (50004, 50030)):
            return False
        try:
            value = element.GetCurrentPattern(10002).QueryInterface(uia.IUIAutomationValuePattern)
            return not value.CurrentIsReadOnly
        except Exception:
            try:
                text = element.GetCurrentPattern(10014).QueryInterface(uia.IUIAutomationTextPattern)
                # UIA_IsReadOnlyAttributeId; unsupported/mixed attributes are not False.
                return text.DocumentRange.GetAttributeValue(40015) in (False, 0)
            except Exception:
                return False

    def focused(self):
        from ctypes import wintypes as w
        try:
            import comtypes
            from comtypes.client import CreateObject, GetModule
        except ImportError:
            raise TextWriteError('Install the speech requirements to enable text-box typing.') from None
        comtypes.CoInitialize()
        try:
            return self._focused_com(CreateObject, GetModule, w)
        except TextWriteError:
            raise
        except Exception:
            raise TextWriteError('Click a supported editable text box before saying Jarvis.') from None
        finally:
            comtypes.CoUninitialize()

    def _focused_com(self, create, get_module, w):
        hwnd = self.user32.GetForegroundWindow()
        pid = w.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.c.byref(pid))
        if not hwnd or pid.value == os.getpid():
            raise TextWriteError('Click the destination text box in another app, then say Jarvis.')
        if self._process_name(pid.value) in {
                'cmd.exe', 'powershell.exe', 'pwsh.exe', 'windowsterminal.exe',
                'openconsole.exe', 'conhost.exe', 'mintty.exe', 'alacritty.exe', 'wezterm-gui.exe'}:
            raise TextWriteError('Choose a document or text box; terminal command inputs are not supported.')
        uia = get_module('UIAutomationCore.dll')
        automation = create('{FF48DBA4-60EF-4201-AA87-54103EEF594E}', interface=uia.IUIAutomation)
        element = automation.GetFocusedElement()
        if not element or not self._editable(element, uia):
            raise TextWriteError('Click a writable, non-password text box before saying Jarvis.')
        identity = tuple(element.GetRuntimeId())
        if not identity or self.user32.GetForegroundWindow() != hwnd:
            raise TextWriteError('Focus changed. Click your destination text box and try again.')
        return FocusTarget(int(hwnd), pid.value, identity)

    def interrupted(self):
        if self.user32.GetAsyncKeyState(0x1B) & 0x8000:
            return 'Typing stopped with Esc.'
        if any(self.user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            return 'Typing stopped because a modifier key is held. Release it and try again.'
        return None

    def send(self, text):
        raw = text.encode('utf-16-le')
        units = [int.from_bytes(raw[i:i+2], 'little') for i in range(0, len(raw), 2)]
        events = (self.input_type * (2 * len(units)))()
        for index, unit in enumerate(units):
            for released in (0, 1):
                event = events[2*index+released]
                event.type, event.ki.wScan, event.ki.dwFlags = 1, unit, 0x0004 | (0x0002 if released else 0)
        inserted = self.user32.SendInput(len(events), events, self.c.sizeof(self.input_type))
        if inserted != len(events):
            if inserted % 2:
                release = events[inserted]
                self.user32.SendInput(1, self.c.byref(release), self.c.sizeof(self.input_type))
            raise TextWriteError('Windows could not finish typing. Text may be partially inserted; no retry was sent.')


class WindowsTextWriter:
    def __init__(self, backend=None):
        self.backend = backend
        self.lock = threading.RLock()

    def _backend(self):
        if self.backend is None:
            self.backend = WindowsTextBackend()
        return self.backend

    def capture(self):
        with self.lock:
            return self._backend().focused()

    def write(self, text, target, cancel):
        if target is None:
            raise TextWriteError('No destination text box was selected when the request started.')
        if not text or len(text) > 12000:
            raise TextWriteError('Writing must contain between 1 and 12,000 characters.')
        if any(ord(char) < 32 and char not in '\r\n\t' for char in text) or '\x7f' in text:
            raise TextWriteError('The writing contains unsupported control characters; it was not typed.')
        with self.lock:
            backend = self._backend()
            # Unicode packets carry literal characters, including line breaks;
            # never synthesize Enter, Tab, paste or other shortcut keys.
            for start in range(0, len(text), 64):
                if cancel.is_set():
                    raise TextWriteError('Typing cancelled. Any text already inserted remains.')
                interruption = backend.interrupted()
                if interruption:
                    raise TextWriteError(interruption)
                if backend.focused() != target:
                    raise TextWriteError('Focus changed; typing stopped. The response is still in Jarvis.')
                backend.send(text[start:start+64])
        return len(text)

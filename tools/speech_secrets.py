"""Groq credential storage: environment override or Windows-user DPAPI encryption."""
import os
from pathlib import Path
import sys

KEY_FILE = Path(__file__).resolve().parents[1] / '.local' / 'groq-api-key.dpapi'


def _crypt(data, decrypt=False):
    if sys.platform != 'win32':
        raise OSError('Set GROQ_API_KEY in the environment on this platform.')
    import ctypes as c
    from ctypes import wintypes as w

    class Blob(c.Structure):
        _fields_ = [('size', w.DWORD), ('data', c.POINTER(c.c_ubyte))]

    crypt = c.WinDLL('crypt32', use_last_error=True)
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [c.c_void_p]
    kernel.LocalFree.restype = c.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [c.POINTER(Blob), c.c_void_p, c.POINTER(Blob),
                         c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
    function.restype = w.BOOL
    buffer = (c.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = Blob(len(data), buffer), Blob()
    if not function(c.byref(source), None, None, None, None, 1, c.byref(output)):
        raise OSError('Windows could not access the saved Groq credential.')
    try:
        return c.string_at(output.data, output.size)
    finally:
        c.memset(output.data, 0, output.size)
        kernel.LocalFree(output.data)
        c.memset(buffer, 0, len(data))


def save_key(key, path=KEY_FILE):
    key = key.strip()
    if not key.startswith('gsk_') or len(key) < 20:
        raise ValueError('Expected a Groq API key.')
    encrypted = _crypt(key.encode('utf-8'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypted)


def load_key(path=KEY_FILE):
    key = os.environ.get('GROQ_API_KEY', '').strip()
    if key:
        return key
    if not path.exists():
        raise ValueError('Groq key missing. Set GROQ_API_KEY or save a local credential.')
    return _crypt(path.read_bytes(), decrypt=True).decode('utf-8')


if __name__ == '__main__':
    from getpass import getpass
    save_key(getpass('Groq API key (hidden): '))
    print('Credential encrypted for this Windows user.')

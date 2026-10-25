"""Gemini key: environment override or Windows-user encrypted local storage."""
import os
from pathlib import Path
from speech_secrets import _crypt

KEY_FILE = Path(__file__).resolve().parents[1] / '.local' / 'gemini-api-key.dpapi'


def save_key(key, path=KEY_FILE):
    key = key.strip()
    if len(key) < 20 or any(c.isspace() for c in key):
        raise ValueError('Expected a Gemini API key.')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_crypt(key.encode('utf-8')))


def load_key(path=KEY_FILE):
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if key:
        return key
    if not path.exists():
        raise ValueError('Gemini key missing. Set GEMINI_API_KEY or run tools/gemini_secrets.py.')
    return _crypt(path.read_bytes(), decrypt=True).decode('utf-8')


if __name__ == '__main__':
    from getpass import getpass
    save_key(getpass('Gemini API key (hidden): '))
    print('Gemini credential encrypted for this Windows user.')

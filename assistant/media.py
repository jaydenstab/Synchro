"""Validate uploads in memory. Nothing here is written to the recordings store."""
from __future__ import annotations

import array
from dataclasses import dataclass

from assistant.errors import AssistantError

IMAGE_MIMES = {
    'image/jpeg': 'image/jpeg',
    'image/jpg': 'image/jpeg',
    'image/png': 'image/png',
    'image/webp': 'image/webp',
}

# Gemini 3.5 Transcribe's documented audio types, plus Safari's audio/mp4 container.
AUDIO_MIMES = {
    'audio/wav': 'audio/wav',
    'audio/x-wav': 'audio/wav',
    'audio/wave': 'audio/wav',
    'audio/webm': 'audio/webm',
    'audio/ogg': 'audio/ogg',
    'audio/mp3': 'audio/mp3',
    'audio/mpeg': 'audio/mpeg',
    'audio/mp4': 'audio/m4a',
    'audio/m4a': 'audio/m4a',
    'audio/x-m4a': 'audio/m4a',
    'audio/aac': 'audio/aac',
    'audio/flac': 'audio/flac',
    'audio/aiff': 'audio/aiff',
    'audio/opus': 'audio/opus',
}

_SILENCE = {
    '',
    'silence',
    '[silence]',
    '(silence)',
    'no speech',
    '[no speech]',
    '(no speech)',
    '[blank_audio]',
}


@dataclass(frozen=True)
class CheckedMedia:
    data: bytes
    mime_type: str


def normalize_mime(value: str | None) -> str:
    if not value:
        return ''
    return value.split(';', 1)[0].strip().lower()


def inspect_image(data: bytes, declared: str | None) -> CheckedMedia:
    if not data:
        raise AssistantError('missing_image', 'Choose an image before asking.', 400)
    sniffed = _sniff_image(data)
    mime = IMAGE_MIMES.get(normalize_mime(declared), '')
    if sniffed is None or (mime and mime != sniffed):
        raise AssistantError('invalid_image', 'Use a JPEG, PNG, or WebP image.', 400)
    return CheckedMedia(data=data, mime_type=sniffed)


def inspect_audio(data: bytes, declared: str | None) -> CheckedMedia:
    if not data or len(data) < 64:
        raise AssistantError('empty_audio', 'The recording is empty or too short to transcribe.', 422)
    mime = AUDIO_MIMES.get(normalize_mime(declared), '')
    if not mime or not _audio_matches(data, mime):
        raise AssistantError(
            'invalid_audio',
            'This audio format is not supported. Use WebM, MP4, WAV, MP3, or Ogg from the browser recorder.',
            400,
        )
    if mime == 'audio/wav' and _wav_is_silent(data):
        raise AssistantError('silence', 'No speech was detected in that recording.', 422)
    return CheckedMedia(data=data, mime_type=mime)


def interpret_vision(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    token = cleaned.strip('`"\'. ').upper()
    if not cleaned or token == 'UNCLEAR_IMAGE' or token.startswith('UNCLEAR_IMAGE'):
        return 'unclear_image', ''
    return 'answered', cleaned


def transcript_is_silence(text: str) -> bool:
    return text.strip().lower() in _SILENCE


def _sniff_image(data: bytes) -> str | None:
    if len(data) >= 12 and data[:3] == b'\xff\xd8\xff' and data[-2:] == b'\xff\xd9':
        return 'image/jpeg'
    if len(data) >= 24 and data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if len(data) >= 16 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _audio_matches(data: bytes, mime: str) -> bool:
    if mime == 'audio/webm':
        return data.startswith(b'\x1a\x45\xdf\xa3')
    if mime == 'audio/ogg':
        return data.startswith(b'OggS')
    if mime == 'audio/wav':
        return len(data) >= 44 and data[:4] == b'RIFF' and data[8:12] == b'WAVE'
    if mime == 'audio/flac':
        return data.startswith(b'fLaC')
    if mime == 'audio/aiff':
        return len(data) >= 12 and data[:4] == b'FORM' and data[8:12] == b'AIFF'
    if mime in {'audio/m4a', 'audio/aac'}:
        return len(data) >= 12 and data[4:8] == b'ftyp'
    if mime in {'audio/mp3', 'audio/mpeg'}:
        return data.startswith(b'ID3') or (len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)
    if mime == 'audio/opus':
        return data.startswith(b'OggS') or data.startswith(b'\x1a\x45\xdf\xa3')
    return False


def _wav_is_silent(data: bytes) -> bool:
    offset = 12
    samples = b''
    bits = 0
    audio_format = 0
    while offset + 8 <= len(data):
        chunk = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], 'little')
        start = offset + 8
        end = min(len(data), start + size)
        payload = data[start:end]
        if chunk == b'fmt ' and len(payload) >= 16:
            audio_format = int.from_bytes(payload[0:2], 'little')
            bits = int.from_bytes(payload[14:16], 'little')
        elif chunk == b'data':
            samples = payload
            break
        offset = start + size + (size % 2)
    if audio_format != 1 or bits != 16 or len(samples) < 2:
        return len(samples) == 0
    count = len(samples) // 2
    values = array.array('h')
    values.frombytes(samples[:count * 2])
    if not count:
        return True
    mean = sum(abs(int(sample)) for sample in values) / count
    return mean < 40

"""Backend environment for Gemini. The key is never returned to the browser."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VISION_MODEL = 'gemini-3.8-flash'
DEFAULT_STT_MODEL = 'gemini-3.5-transcribe'
DEFAULT_BRIDGE_URL = 'http://127.0.0.1:8765'


def load_local_env(path: Path | None = None) -> None:
    """Fill missing variables from a local .env file. Existing variables win."""
    env_path = path or (ROOT / '.env')
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _float_env(name: str, default: float, low: float, high: float) -> float:
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return min(high, max(low, value))


def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(high, max(low, value))


@dataclass(frozen=True)
class AssistantConfig:
    api_key: str = ''
    vision_model: str = DEFAULT_VISION_MODEL
    stt_model: str = DEFAULT_STT_MODEL
    timeout_s: float = 30
    max_image_bytes: int = 8_000_000
    max_audio_bytes: int = 8_000_000
    rate_limit: int = 30
    rate_window_s: float = 60
    camera_bridge_url: str = DEFAULT_BRIDGE_URL
    camera_status_timeout_s: float = 1.0
    camera_capture_timeout_s: float = 8.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    @classmethod
    def from_env(cls) -> 'AssistantConfig':
        load_local_env()
        vision = os.environ.get('GEMINI_VISION_MODEL', '').strip() or DEFAULT_VISION_MODEL
        stt = os.environ.get('GEMINI_STT_MODEL', '').strip() or DEFAULT_STT_MODEL
        bridge = os.environ.get('SYNCHRO_CAMERA_BRIDGE_URL', '').strip() or DEFAULT_BRIDGE_URL
        return cls(
            api_key=os.environ.get('GEMINI_API_KEY', '').strip(),
            vision_model=vision,
            stt_model=stt,
            timeout_s=_float_env('GEMINI_TIMEOUT_SECONDS', 30, 1, 120),
            max_image_bytes=_int_env('ASSISTANT_MAX_IMAGE_BYTES', 8_000_000, 1024, 20_000_000),
            max_audio_bytes=_int_env('ASSISTANT_MAX_AUDIO_BYTES', 8_000_000, 1024, 20_000_000),
            rate_limit=_int_env('ASSISTANT_RATE_LIMIT', 30, 1, 1000),
            rate_window_s=_float_env('ASSISTANT_RATE_WINDOW_SECONDS', 60, 1, 3600),
            camera_bridge_url=bridge,
            camera_status_timeout_s=_float_env('SYNCHRO_CAMERA_STATUS_TIMEOUT', 1, 0.2, 10),
            camera_capture_timeout_s=_float_env('SYNCHRO_CAMERA_CAPTURE_TIMEOUT', 8, 1, 30),
        )

"""Visual question answering and speech-to-text. Gesture recordings are not used here."""
from __future__ import annotations

import threading
import time
from typing import Protocol

from assistant.bridge import camera_status
from assistant.bridge import capture_jpeg
from assistant.config import AssistantConfig
from assistant.errors import AssistantError
from assistant.errors import scrub
from assistant.gemini import GeminiSpeech
from assistant.gemini import GeminiVision
from assistant.media import inspect_audio
from assistant.media import inspect_image
from assistant.media import interpret_vision
from assistant.media import transcript_is_silence

MISSING_KEY = (
    'Set GEMINI_API_KEY in the backend environment and restart the server. '
    'The key stays on the server and is not sent to the browser.'
)


class VisionProvider(Protocol):
    def answer(self, *, image: bytes, mime_type: str, question: str) -> str: ...


class SpeechProvider(Protocol):
    def transcribe(self, *, audio: bytes, mime_type: str) -> str: ...


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        with self._lock:
            recent = [hit for hit in self._hits.get(key, []) if moment - hit < self.window_s]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                return False
            recent.append(moment)
            self._hits[key] = recent
            return True


class AssistantService:
    def __init__(
        self,
        config: AssistantConfig | None = None,
        vision: VisionProvider | None = None,
        speech: SpeechProvider | None = None,
    ) -> None:
        self.config = config or AssistantConfig.from_env()
        self.vision = vision or GeminiVision(
            api_key=self.config.api_key,
            model=self.config.vision_model,
            timeout_s=self.config.timeout_s,
        )
        self.speech = speech or GeminiSpeech(
            api_key=self.config.api_key,
            model=self.config.stt_model,
            timeout_s=self.config.timeout_s,
        )
        self.limiter = SlidingWindowLimiter(self.config.rate_limit, self.config.rate_window_s)

    @classmethod
    def from_env(cls) -> 'AssistantService':
        return cls(AssistantConfig.from_env())

    def limit(self, key: str) -> None:
        if not self.limiter.allow(key):
            raise AssistantError('rate_limited', 'Too many assistant requests. Wait a moment and try again.', 429)

    def status(self) -> dict:
        return {
            'configured': self.config.configured,
            'vision_model': self.config.vision_model,
            'stt_model': self.config.stt_model,
            'timeout_seconds': self.config.timeout_s,
            'max_image_bytes': self.config.max_image_bytes,
            'max_audio_bytes': self.config.max_audio_bytes,
            'media_retained': False,
            'note': 'GEMINI_API_KEY stays on the backend. This response does not include it.',
        }

    def camera_status(self) -> dict:
        return camera_status(self.config.camera_bridge_url, self.config.camera_status_timeout_s)

    def capture_frame(self) -> bytes:
        return capture_jpeg(self.config.camera_bridge_url, self.config.camera_capture_timeout_s)

    def ask(self, *, image: bytes, mime_type: str, question: str, declared_source: str) -> dict:
        self._require_key()
        if declared_source not in {'upload', 'camera'}:
            raise AssistantError('invalid_source', 'Image source must be upload or camera.', 400)
        checked = inspect_image(image, mime_type)
        prompt = question.strip()
        if not prompt:
            raise AssistantError('missing_question', 'Enter a question before asking.', 400)
        if len(prompt) > 2000:
            raise AssistantError('question_too_long', 'The question is too long.', 400)
        try:
            text = self.vision.answer(image=checked.data, mime_type=checked.mime_type, question=prompt)
        except AssistantError as exc:
            raise AssistantError(exc.code, scrub(exc.message, self.config.api_key), exc.status) from None
        except Exception:
            raise AssistantError('provider_unavailable', 'Gemini could not complete the request.', 503) from None
        state, answer = interpret_vision(text)
        return {
            'state': state,
            'answer': answer,
            'message': 'The image is too unclear to answer that question.' if state == 'unclear_image' else '',
            'model': self.config.vision_model,
            'declared_source': declared_source,
            'media_retained': False,
            'simulated': False,
        }

    def transcribe(self, *, audio: bytes, mime_type: str) -> dict:
        self._require_key()
        checked = inspect_audio(audio, mime_type)
        try:
            text = self.speech.transcribe(audio=checked.data, mime_type=checked.mime_type)
        except AssistantError as exc:
            raise AssistantError(exc.code, scrub(exc.message, self.config.api_key), exc.status) from None
        except Exception:
            raise AssistantError('provider_unavailable', 'Gemini could not complete the request.', 503) from None
        cleaned = text.strip()
        if transcript_is_silence(cleaned):
            raise AssistantError('silence', 'No speech was detected in that recording.', 422)
        return {
            'state': 'transcribed',
            'transcript': cleaned,
            'model': self.config.stt_model,
            'media_retained': False,
        }

    def _require_key(self) -> None:
        if not self.config.configured:
            raise AssistantError('missing_api_key', MISSING_KEY, 503)

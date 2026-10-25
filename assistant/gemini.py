"""Gemini adapters. Speech recognition is separate so another transcriber can replace it."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Callable

from assistant.errors import AssistantError

VISION_INSTRUCTION = (
    'You are Synchro\'s visual assistant. Answer the user\'s question about the attached image. '
    'Use only what is visible. If the image is blank, nearly black, badly corrupted, or too unclear '
    'to answer, reply with exactly UNCLEAR_IMAGE. '
    'Do not claim to control the computer, run commands, or take physical actions. '
    'Reply in plain text.'
)


Generate = Callable[..., str]


def provider_error(exc: Exception, secret: str) -> AssistantError:
    raw = f'{type(exc).__name__}: {exc}'
    if secret:
        raw = raw.replace(secret, '[redacted]')
    lowered = raw.lower()
    if any(token in lowered for token in ('api key', 'api_key', 'unauthenticated', 'permission denied', 'permission_denied')):
        return AssistantError(
            'invalid_api_key',
            'Gemini rejected the API key. Check GEMINI_API_KEY on the server and restart.',
            503,
        )
    if 'quota' in lowered or 'resource_exhausted' in lowered or ' 429' in raw:
        return AssistantError('provider_unavailable', 'Gemini is temporarily unavailable because the quota is exhausted.', 503)
    return AssistantError('provider_unavailable', 'Gemini could not complete the request.', 503)


def call_with_timeout(fn: Callable[[], str], timeout_s: float, secret: str) -> str:
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='synchro-gemini')
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FuturesTimeout:
        raise AssistantError('timeout', 'Gemini took too long to respond.', 504) from None
    except AssistantError:
        raise
    except Exception as exc:
        raise provider_error(exc, secret) from None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def default_vision_generate(
    *,
    api_key: str,
    model: str,
    timeout_s: float,
    image: bytes,
    mime_type: str,
    question: str,
) -> str:
    from google import genai
    from google.genai import types

    client = _client(api_key, timeout_s, genai, types)
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image, mime_type=mime_type),
            question,
        ],
        config=types.GenerateContentConfig(
            system_instruction=VISION_INSTRUCTION,
            temperature=0.2,
            max_output_tokens=800,
        ),
    )
    return response.text or ''


def default_speech_generate(
    *,
    api_key: str,
    model: str,
    timeout_s: float,
    audio: bytes,
    mime_type: str,
) -> str:
    from google import genai
    from google.genai import types

    client = _client(api_key, timeout_s, genai, types)
    # Inline bytes are not kept in the Files API. Push-to-talk clips stay under the inline limit.
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=audio, mime_type=mime_type)],
        config=types.GenerateContentConfig(temperature=0, max_output_tokens=400),
    )
    return response.text or ''


def _client(api_key: str, timeout_s: float, genai, types):
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=max(1, int(timeout_s * 1000)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


class GeminiVision:
    def __init__(self, *, api_key: str, model: str, timeout_s: float, generate: Generate | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._generate = generate or default_vision_generate

    def answer(self, *, image: bytes, mime_type: str, question: str) -> str:
        def run() -> str:
            return self._generate(
                api_key=self.api_key,
                model=self.model,
                timeout_s=self.timeout_s,
                image=image,
                mime_type=mime_type,
                question=question,
            )

        text = call_with_timeout(run, self.timeout_s, self.api_key)
        return text or ''


class GeminiSpeech:
    """Speech-to-text adapter. Replace `generate` to point at another provider later."""

    def __init__(self, *, api_key: str, model: str, timeout_s: float, generate: Generate | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self._generate = generate or default_speech_generate

    def transcribe(self, *, audio: bytes, mime_type: str) -> str:
        def run() -> str:
            return self._generate(
                api_key=self.api_key,
                model=self.model,
                timeout_s=self.timeout_s,
                audio=audio,
                mime_type=mime_type,
            )

        text = call_with_timeout(run, self.timeout_s, self.api_key)
        return text or ''

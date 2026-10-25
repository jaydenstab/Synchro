"""Assistant tests use fake providers. They do not call the Gemini API."""
from __future__ import annotations

import json
import struct
import subprocess
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from assistant.config import AssistantConfig
from assistant.errors import AssistantError
from assistant.gemini import GeminiSpeech
from assistant.gemini import GeminiVision
from assistant.media import inspect_audio
from assistant.service import AssistantService

ROOT = Path(__file__).resolve().parents[1]
JPEG = b'\xff\xd8\xff' + b'\x00' * 32 + b'\xff\xd9'
SECRET = 'super-secret-test-key'


class Scripted:
    def __init__(self, answer: str = 'a red cup', transcript: str = 'what is on the table') -> None:
        self.answer_text = answer
        self.transcript_text = transcript
        self.vision_calls = 0
        self.speech_calls = 0
        self.seen: dict = {}

    def answer(self, *, image: bytes, mime_type: str, question: str) -> str:
        self.vision_calls += 1
        self.seen = {'image': image, 'mime_type': mime_type, 'question': question}
        return self.answer_text

    def transcribe(self, *, audio: bytes, mime_type: str) -> str:
        self.speech_calls += 1
        self.seen = {'audio': audio, 'mime_type': mime_type}
        return self.transcript_text


class Boom:
    def answer(self, **kwargs):
        raise AssertionError('vision provider should not be called')

    def transcribe(self, **kwargs):
        raise AssertionError('speech provider should not be called')


class Unavailable:
    def answer(self, **kwargs):
        raise ConnectionError('network down')

    def transcribe(self, **kwargs):
        raise ConnectionError('network down')


def png_bytes() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b'\x00\xff\x00\x00'
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    signature = b'\x89PNG\r\n\x1a\n'
    return signature + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def wav(samples: bytes) -> bytes:
    fmt = struct.pack('<HHIIHH', 1, 1, 8000, 16000, 2, 16)
    fmt_chunk = b'fmt ' + len(fmt).to_bytes(4, 'little') + fmt
    data_chunk = b'data' + len(samples).to_bytes(4, 'little') + samples
    body = b'WAVE' + fmt_chunk + data_chunk
    return b'RIFF' + len(body).to_bytes(4, 'little') + body


def client_for(tmp_path: Path, vision=None, speech=None, **overrides) -> tuple[TestClient, Scripted]:
    scripted = vision if isinstance(vision, Scripted) else Scripted()
    config = AssistantConfig(
        api_key='test-key',
        camera_bridge_url='http://127.0.0.1:9',
        timeout_s=2,
        **overrides,
    )
    service = AssistantService(
        config,
        vision=vision or scripted,
        speech=speech or scripted,
    )
    return TestClient(create_app(tmp_path, assistant=service)), scripted


def test_successful_image_question_sends_image_and_text_together(tmp_path: Path):
    scripted = Scripted('a red cup on the left')
    client, _ = client_for(tmp_path, vision=scripted, speech=scripted)
    with client:
        before = {path.relative_to(tmp_path) for path in tmp_path.rglob('*')}
        response = client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is on the table?', 'declared_source': 'upload'},
        )
        after = {path.relative_to(tmp_path) for path in tmp_path.rglob('*')}
    assert response.status_code == 200
    body = response.json()
    assert body['state'] == 'answered'
    assert body['answer'] == 'a red cup on the left'
    assert body['model'] == 'gemini-3.8-flash'
    assert body['declared_source'] == 'upload'
    assert body['media_retained'] is False
    assert body['simulated'] is False
    assert scripted.seen['image'] == JPEG
    assert scripted.seen['question'] == 'What is on the table?'
    assert scripted.seen['mime_type'] == 'image/jpeg'
    assert after == before


def test_missing_and_invalid_images(tmp_path: Path):
    client, _ = client_for(tmp_path, vision=Boom(), speech=Boom())
    with client:
        missing = client.post('/api/assistant/ask', files={'question': (None, 'What is this?')})
        empty = client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', b'', 'image/jpeg')},
            data={'question': 'What is this?'},
        )
        invalid = client.post(
            '/api/assistant/ask',
            files={'image': ('notes.txt', b'this is not an image at all', 'text/plain')},
            data={'question': 'What is this?'},
        )
        mismatched = client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', png_bytes(), 'image/jpeg')},
            data={'question': 'What is this?'},
        )
        blank_question = client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': '   '},
        )
    assert missing.status_code == 400 and missing.json()['code'] == 'missing_image'
    assert empty.status_code == 400 and empty.json()['code'] == 'missing_image'
    assert invalid.status_code == 400 and invalid.json()['code'] == 'invalid_image'
    assert mismatched.status_code == 400 and mismatched.json()['code'] == 'invalid_image'
    assert blank_question.status_code == 400 and blank_question.json()['code'] == 'missing_question'


def test_unclear_image_is_a_distinct_state(tmp_path: Path):
    client, _ = client_for(tmp_path, vision=Scripted('UNCLEAR_IMAGE'), speech=Scripted())
    with client:
        response = client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What does the label say?'},
        )
    body = response.json()
    assert response.status_code == 200
    assert body['state'] == 'unclear_image'
    assert body['answer'] == ''
    assert 'unclear' in body['message'].lower()


def test_timeout_and_provider_failure(tmp_path: Path):
    def slow(**kwargs):
        time.sleep(0.35)
        return 'too late'

    timed = GeminiVision(api_key='test-key', model='gemini-3.8-flash', timeout_s=0.1, generate=slow)
    timeout_client, _ = client_for(tmp_path, vision=timed, speech=Boom())
    with timeout_client:
        timed_out = timeout_client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is this?'},
        )
    assert timed_out.status_code == 504
    assert timed_out.json()['code'] == 'timeout'
    assert SECRET not in timed_out.text

    down, _ = client_for(tmp_path / 'down', vision=Unavailable(), speech=Unavailable())
    with down:
        failed = down.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is this?'},
        )
    assert failed.status_code == 503
    assert failed.json()['code'] == 'provider_unavailable'


def test_provider_errors_do_not_echo_the_api_key(tmp_path: Path):
    def leak(**kwargs):
        raise RuntimeError(f"permission denied for key {kwargs['api_key']}")

    vision = GeminiVision(api_key=SECRET, model='gemini-3.8-flash', timeout_s=2, generate=leak)
    config = AssistantConfig(api_key=SECRET, camera_bridge_url='http://127.0.0.1:9')
    service = AssistantService(config, vision=vision, speech=Boom())
    with TestClient(create_app(tmp_path, assistant=service)) as client:
        response = client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is this?'},
        )
        status = client.get('/api/assistant/status')
    assert response.status_code == 503
    assert response.json()['code'] == 'invalid_api_key'
    assert SECRET not in response.text
    assert SECRET not in status.text
    assert 'api_key' not in status.json()
    assert status.json()['configured'] is True
    assert status.json()['media_retained'] is False


def test_missing_api_key_does_not_call_the_provider(tmp_path: Path):
    config = AssistantConfig(api_key='', camera_bridge_url='http://127.0.0.1:9')
    service = AssistantService(config, vision=Boom(), speech=Boom())
    with TestClient(create_app(tmp_path, assistant=service)) as client:
        response = client.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is this?'},
        )
        status = client.get('/api/assistant/status')
    assert response.status_code == 503
    assert response.json()['code'] == 'missing_api_key'
    assert 'GEMINI_API_KEY' in response.json()['detail']
    assert status.json()['configured'] is False


def test_transcription_success_empty_invalid_and_silence(tmp_path: Path):
    scripted = Scripted(transcript='what is on the table')
    client, _ = client_for(tmp_path, vision=scripted, speech=scripted)
    webm = b'\x1a\x45\xdf\xa3' + b'\x00' * 80
    with client:
        before = {path.relative_to(tmp_path) for path in tmp_path.rglob('*')}
        spoken = client.post(
            '/api/assistant/transcribe',
            files={'audio': ('question.webm', webm, 'audio/webm;codecs=opus')},
        )
        empty = client.post('/api/assistant/transcribe', files={'audio': ('question.webm', b'', 'audio/webm')})
        short = client.post(
            '/api/assistant/transcribe',
            files={'audio': ('question.webm', b'\x1a\x45\xdf\xa3short', 'audio/webm')},
        )
        invalid = client.post(
            '/api/assistant/transcribe',
            files={'audio': ('question.txt', b'not an audio file ' * 8, 'text/plain')},
        )
        after = {path.relative_to(tmp_path) for path in tmp_path.rglob('*')}
    assert spoken.status_code == 200
    assert spoken.json()['transcript'] == 'what is on the table'
    assert spoken.json()['model'] == 'gemini-3.5-transcribe'
    assert spoken.json()['media_retained'] is False
    assert scripted.seen['mime_type'] == 'audio/webm'
    assert empty.status_code == 422 and empty.json()['code'] == 'empty_audio'
    assert short.status_code == 422 and short.json()['code'] == 'empty_audio'
    assert invalid.status_code == 400 and invalid.json()['code'] == 'invalid_audio'
    assert after == before

    blank = Scripted(transcript='[silence]')
    blank_client, _ = client_for(tmp_path / 'blank', vision=Boom(), speech=blank)
    with blank_client:
        quiet = blank_client.post(
            '/api/assistant/transcribe',
            files={'audio': ('question.webm', webm, 'audio/webm')},
        )
    wav_client, _ = client_for(tmp_path / 'wav', vision=Boom(), speech=Boom())
    with wav_client:
        silent_wav = wav_client.post(
            '/api/assistant/transcribe',
            files={'audio': ('question.wav', wav(b'\x00\x00' * 200), 'audio/wav')},
        )
    assert quiet.status_code == 422 and quiet.json()['code'] == 'silence'
    assert silent_wav.status_code == 422 and silent_wav.json()['code'] == 'silence'
    with pytest.raises(AssistantError) as exc:
        inspect_audio(wav(b'\x00\x00' * 200), 'audio/wav')
    assert exc.value.code == 'silence'


def test_upload_limit_and_request_limit(tmp_path: Path):
    limited, _ = client_for(tmp_path, max_image_bytes=120)
    with limited:
        oversized = limited.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', b'\xff\xd8\xff' + (b'\x00' * 200) + b'\xff\xd9', 'image/jpeg')},
            data={'question': 'What is this?'},
        )
    assert oversized.status_code == 413 and oversized.json()['code'] == 'too_large'

    counted, _ = client_for(tmp_path / 'rate', rate_limit=2, rate_window_s=60)
    with counted:
        first = counted.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is this?'},
        )
        second = counted.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is this?'},
        )
        third = counted.post(
            '/api/assistant/ask',
            files={'image': ('frame.jpg', JPEG, 'image/jpeg')},
            data={'question': 'What is this?'},
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429 and third.json()['code'] == 'rate_limited'


def test_camera_bridge_unavailable_and_local_jpeg_contract(tmp_path: Path):
    offline, _ = client_for(tmp_path)
    with offline:
        status = offline.get('/api/camera/bridge')
        capture = offline.get('/api/camera/capture')
    assert status.status_code == 200
    assert status.json()['available'] is False
    assert status.json()['simulated'] is False
    assert 'browser' in status.json()['reason'].lower()
    assert capture.status_code == 503
    assert capture.json()['code'] == 'camera_bridge_unavailable'

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/status'):
                body = json.dumps({
                    'service': 'synchro-camera-bridge',
                    'available': True,
                    'connected': True,
                    'has_frame': True,
                    'age_ms': 20,
                    'width': 640,
                    'height': 480,
                    'transport': 'bluetooth-classic-rfcomm',
                    'simulated': False,
                }).encode()
                self._send(200, 'application/json', body)
            elif self.path.startswith('/frame.jpg'):
                self._send(200, 'image/jpeg', JPEG)
            else:
                self._send(404, 'application/json', b'{"error":"not_found"}')

        def _send(self, status_code: int, content_type: str, body: bytes) -> None:
            self.send_response(status_code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        config = AssistantConfig(
            api_key='test-key',
            camera_bridge_url=url,
            camera_status_timeout_s=1,
            camera_capture_timeout_s=2,
        )
        service = AssistantService(config, vision=Boom(), speech=Boom())
        with TestClient(create_app(tmp_path / 'bridge', assistant=service)) as live:
            bridged = live.get('/api/camera/bridge')
            frame = live.get('/api/camera/capture')
        assert bridged.json()['available'] is True
        assert bridged.json()['connected'] is True
        assert bridged.json()['capture_ready'] is True
        assert bridged.json()['frame'] == 'native-viewer'
        assert bridged.json()['simulated'] is False
        assert frame.status_code == 200
        assert frame.content == JPEG
        assert frame.headers['x-synchro-simulated'] == 'false'
        assert frame.headers['x-synchro-frame-source'] == 'native-viewer'
    finally:
        server.shutdown()


def test_frontend_assistant_controls_and_no_key_in_the_browser():
    page = (ROOT / 'frontend' / 'src' / 'pages' / 'CameraPage.tsx').read_text()
    for label in (
        'Upload Image',
        'Capture Photo',
        'Hold to talk',
        'Ask AI',
        'Read Answer Aloud',
        'Stop Speaking',
        'Recording',
    ):
        assert label in page
    for path in (ROOT / 'frontend' / 'src').rglob('*'):
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        assert 'import.meta.env' not in text
        assert 'AIza' not in text
    gemini = (ROOT / 'assistant' / 'gemini.py').read_text()
    assert 'files.upload' not in gemini
    assert 'from_bytes' in gemini
    result = subprocess.run(
        ['node', '--experimental-strip-types', '--test', 'src/assistant.test.ts'],
        cwd=ROOT / 'frontend',
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_vision_adapter_keeps_image_and_question_in_one_call():
    seen = {}

    def generate(**kwargs):
        seen.update(kwargs)
        return 'a red cup'

    vision = GeminiVision(api_key='test-key', model='gemini-3.8-flash', timeout_s=2, generate=generate)
    assert vision.answer(image=JPEG, mime_type='image/jpeg', question='What color?') == 'a red cup'
    assert seen['image'] == JPEG
    assert seen['question'] == 'What color?'
    assert seen['mime_type'] == 'image/jpeg'

    def speak(**kwargs):
        seen['speech'] = kwargs
        return 'turn left'

    speech = GeminiSpeech(api_key='test-key', model='gemini-3.5-transcribe', timeout_s=2, generate=speak)
    assert speech.transcribe(audio=b'audio', mime_type='audio/webm') == 'turn left'
    assert seen['speech']['audio'] == b'audio'
    assert seen['speech']['model'] == 'gemini-3.5-transcribe'

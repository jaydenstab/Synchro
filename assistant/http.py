"""HTTP routes for the assistant. Uploads are closed after each request."""
from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from starlette.datastructures import UploadFile

from assistant.errors import AssistantError
from assistant.service import AssistantService

log = logging.getLogger('synchro.assistant')


def install_assistant(app: FastAPI, service: AssistantService) -> None:
    @app.exception_handler(AssistantError)
    async def handle_assistant_error(_request: Request, exc: AssistantError) -> JSONResponse:
        log.warning('assistant request failed code=%s', exc.code)
        return JSONResponse(status_code=exc.status, content={'code': exc.code, 'detail': exc.message})

    @app.get('/api/assistant/status')
    def assistant_status() -> dict:
        return service.status()

    @app.get('/api/camera/bridge')
    def camera_bridge() -> dict:
        return service.camera_status()

    @app.get('/api/camera/capture')
    def camera_capture(request: Request) -> Response:
        service.limit(_client_key(request))
        frame = service.capture_frame()
        return _jpeg(frame)

    @app.get('/api/camera/preview')
    def camera_preview() -> Response:
        frame = service.capture_frame()
        return _jpeg(frame)

    @app.post('/api/assistant/ask')
    async def ask(request: Request) -> dict:
        service.limit(_client_key(request))
        upload, mime, question, source = await _read_image_form(request, service.config.max_image_bytes)
        try:
            data = await _read_limited(upload, service.config.max_image_bytes)
        finally:
            await upload.close()
        return await asyncio.to_thread(
            service.ask,
            image=data,
            mime_type=mime,
            question=question,
            declared_source=source,
        )

    @app.post('/api/assistant/transcribe')
    async def transcribe(request: Request) -> dict:
        service.limit(_client_key(request))
        upload, mime = await _read_audio_form(request, service.config.max_audio_bytes)
        try:
            data = await _read_limited(upload, service.config.max_audio_bytes)
        finally:
            await upload.close()
        return await asyncio.to_thread(service.transcribe, audio=data, mime_type=mime)


def _jpeg(frame: bytes) -> Response:
    return Response(
        content=frame,
        media_type='image/jpeg',
        headers={
            'Cache-Control': 'no-store',
            'X-Synchro-Frame-Source': 'native-viewer',
            'X-Synchro-Simulated': 'false',
        },
    )


def _client_key(request: Request) -> str:
    if request.client is None or not request.client.host:
        return 'local'
    return request.client.host


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = await upload.read(64 * 1024)
        if not block:
            break
        total += len(block)
        if total > limit:
            raise AssistantError('too_large', f'The upload is larger than {limit} bytes.', 413)
        chunks.append(block)
    return b''.join(chunks)


async def _form(request: Request, limit: int):
    content_type = request.headers.get('content-type', '')
    if 'multipart/form-data' not in content_type.lower():
        raise AssistantError('invalid_request', 'Send the recording as a multipart form.', 400)
    try:
        return await request.form(max_files=2, max_fields=8, max_part_size=limit + 1)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else ''
        if exc.status_code == 400 and 'maximum size' in detail.lower():
            raise AssistantError('too_large', f'The upload is larger than {limit} bytes.', 413) from None
        raise AssistantError('invalid_request', 'The upload could not be read.', 400) from None


async def _read_image_form(request: Request, limit: int):
    form = await _form(request, limit)
    upload = form.get('image')
    if not isinstance(upload, UploadFile):
        raise AssistantError('missing_image', 'Choose an image before asking.', 400)
    question = form.get('question')
    source = form.get('declared_source') or 'upload'
    if not isinstance(question, str):
        question = ''
    if not isinstance(source, str):
        source = 'upload'
    return upload, upload.content_type or '', question, source


async def _read_audio_form(request: Request, limit: int):
    form = await _form(request, limit)
    upload = form.get('audio')
    if not isinstance(upload, UploadFile):
        raise AssistantError('empty_audio', 'The recording is empty or too short to transcribe.', 422)
    return upload, upload.content_type or ''

"""Synchro local server. Synthetic inputs are explicitly labeled."""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from assistant.http import install_assistant
from assistant.service import AssistantService
from engine import GestureEngine
from imu import SOURCES, normalize_label
from live_feed import SyntheticLiveFeed
from motion.service import MotionService
from recorder import Recorder
from simulator import KINDS, make_motion
from store import Store

DEFAULT_DATA = Path(os.environ.get('VISIONGLOVE_DATA_DIR', Path(__file__).parent / 'data'))
STATIC_DIR = Path(__file__).parent / 'static'
FRONTEND_DIST = Path(__file__).parent / 'frontend' / 'dist'


class Recording(BaseModel):
    label: str
    samples: list[dict] = Field(min_length=8, max_length=1000)
    source: str = 'hardware'


class GenerateRequest(BaseModel):
    label: str
    motion: str
    examples: int = Field(default=8, ge=2, le=40)


class PredictionRequest(BaseModel):
    samples: list[dict] = Field(min_length=8, max_length=1000)


class GestureCreate(BaseModel):
    name: str


class GestureRename(BaseModel):
    name: str


class StartRecordingRequest(BaseModel):
    gesture_id: str
    source: str = 'synthetic'
    session_id: str | None = None


class PointerUpdate(BaseModel):
    enabled: bool | None = None
    recenter: bool = False
    speed: float | None = None
    invert_x: bool | None = None
    invert_y: bool | None = None
    auto_enable: bool | None = None
    stabilize: bool | None = None
    sideways_axis: str | None = None


class SpeechStart(BaseModel):
    device: int | None = None


def _http_error(exc: Exception, not_found: bool = False) -> HTTPException:
    if isinstance(exc, KeyError) or not_found:
        return HTTPException(404, str(exc) if str(exc) else 'Not found')
    if isinstance(exc, RuntimeError):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))


def create_app(data_dir: Path | None = None, assistant: AssistantService | None = None) -> FastAPI:
    data_path = Path(data_dir) if data_dir is not None else DEFAULT_DATA
    data_path.mkdir(parents=True, exist_ok=True)
    store = Store(data_path)
    engine = GestureEngine()
    recorder = Recorder(store)
    period = float(os.environ.get('VISIONGLOVE_TELEMETRY_PERIOD', '0.02'))
    feed = SyntheticLiveFeed(period_s=period, on_sample=lambda sample, _kind: recorder.ingest(sample))
    motion = MotionService(data_path)

    store.import_legacy_jsonl()
    engine.replace_recordings(store.list_recordings(include_samples=True))
    if engine.recordings:
        engine.train()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        windows_camera = None
        if os.environ.get('VISIONGLOVE_MOTION_USB', '1') == '1':
            motion.start_usb()
            if os.environ.get('SYNCHRO_SPEECH_LISTEN') == '1':
                try:
                    motion.speech_start(None)
                except ValueError:
                    pass
        if os.environ.get('SYNCHRO_WINDOWS_CAMERA', '1' if sys.platform == 'win32' else '0') == '1':
            from camera.windows_bridge import WindowsCameraBridge
            windows_camera = WindowsCameraBridge.from_env()
            windows_camera.start()
        task = asyncio.create_task(feed.run())
        try:
            yield
        finally:
            if windows_camera is not None:
                windows_camera.close()
            motion.close()
            feed.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, RuntimeError):
                pass
            store.close()

    app = FastAPI(title='Synchro', lifespan=lifespan)
    assistant_service = assistant or AssistantService.from_env()
    app.state.store = store
    app.state.engine = engine
    app.state.recorder = recorder
    app.state.feed = feed
    app.state.motion = motion
    app.state.assistant = assistant_service

    def refresh_engine() -> None:
        engine.replace_recordings(store.list_recordings(include_samples=True))

    @app.get('/')
    def home():
        built = FRONTEND_DIST / 'index.html'
        if built.is_file():
            return FileResponse(built)
        return FileResponse(STATIC_DIR / 'index.html')

    @app.get('/legacy')
    def legacy_ui():
        return FileResponse(STATIC_DIR / 'index.html')

    install_assistant(app, assistant_service)

    @app.get('/api/motion')
    def motion_status():
        return motion.snapshot()

    @app.post('/api/motion/calibrate')
    def motion_calibrate():
        try:
            motion.request_calibration()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return motion.snapshot()

    @app.post('/api/pointer')
    def update_pointer(req: PointerUpdate):
        try:
            motion.update_pointer(
                enabled=req.enabled,
                recenter=req.recenter,
                speed=req.speed,
                invert_x=req.invert_x,
                invert_y=req.invert_y,
                auto_enable=req.auto_enable,
                stabilize=req.stabilize,
                sideways_axis=req.sideways_axis,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return motion.snapshot()

    @app.get('/api/speech')
    def speech_status():
        return motion.speech_snapshot()

    @app.get('/api/speech/devices')
    def speech_devices():
        return motion.speech_devices()

    @app.post('/api/speech/start')
    def speech_start(req: SpeechStart):
        try:
            motion.speech_start(req.device)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return motion.speech_snapshot()

    @app.post('/api/speech/stop')
    def speech_stop():
        motion.speech_stop()
        return motion.speech_snapshot()

    @app.post('/api/speech/clear')
    def speech_clear():
        motion.speech_clear()
        return motion.speech_snapshot()

    @app.get('/api/status')
    def status():
        return {
            'source': 'synthetic demo / uploaded recordings (not yet physical glove)',
            'trained': list(engine.templates),
            'recordings': len(engine.recordings),
            'counts': dict(Counter(x['label'] for x in engine.recordings)),
            'gestures': store.list_gestures(),
            'active_recording': recorder.status(),
            'persistence': 'sqlite+jsonl',
        }

    @app.get('/api/gestures')
    def list_gestures():
        return {'gestures': store.list_gestures()}

    @app.post('/api/gestures')
    def create_gesture(req: GestureCreate):
        try:
            return store.create_gesture(req.name)
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.patch('/api/gestures/{gesture_id}')
    def rename_gesture(gesture_id: str, req: GestureRename):
        try:
            updated = store.rename_gesture(gesture_id, req.name)
        except (KeyError, ValueError) as exc:
            raise _http_error(exc) from exc
        refresh_engine()
        return updated

    @app.delete('/api/gestures/{gesture_id}')
    def delete_gesture(gesture_id: str):
        try:
            store.delete_gesture(gesture_id)
        except KeyError as exc:
            raise _http_error(exc) from exc
        refresh_engine()
        return {'deleted': True, 'id': gesture_id}

    @app.post('/api/sessions')
    def create_session():
        return store.create_session()

    @app.post('/api/recordings/start')
    def start_recording(req: StartRecordingRequest):
        try:
            return recorder.start(gesture_id=req.gesture_id, source=req.source, session_id=req.session_id)
        except (KeyError, ValueError, RuntimeError) as exc:
            raise _http_error(exc) from exc

    @app.post('/api/recordings/stop')
    def stop_recording():
        try:
            saved = recorder.stop()
        except (RuntimeError, ValueError, KeyError) as exc:
            raise _http_error(exc) from exc
        engine.add(saved['label'], saved['samples'], saved['source'])
        store.append_jsonl({'label': saved['label'], 'samples': saved['samples'], 'source': saved['source']})
        summary = {key: saved[key] for key in saved if key != 'samples'}
        summary['saved'] = True
        return summary

    @app.post('/api/recordings/cancel')
    def cancel_recording():
        recorder.cancel()
        return {'cancelled': True}

    @app.get('/api/recordings')
    def list_recordings(gesture_id: str | None = None):
        return {'recordings': store.list_recordings(include_samples=False, gesture_id=gesture_id)}

    @app.get('/api/recordings/{recording_id}')
    def get_recording(recording_id: str):
        rec = store.get_recording(recording_id, include_samples=True)
        if rec is None:
            raise HTTPException(404, 'Recording not found.')
        return rec

    @app.delete('/api/recordings/{recording_id}')
    def delete_recording(recording_id: str):
        try:
            store.delete_recording(recording_id)
        except KeyError as exc:
            raise _http_error(exc) from exc
        refresh_engine()
        return {'deleted': True, 'id': recording_id}

    @app.post('/api/demo/generate')
    def generate(req: GenerateRequest):
        if req.motion not in KINDS:
            raise HTTPException(400, f'Valid motion types: {KINDS}')
        try:
            label = normalize_label(req.label)
            gesture = store.get_or_create_gesture(label)
            session = store.create_session()
            saved = 0
            for i in range(req.examples):
                seed = len(engine.recordings) + 1000 + i
                samples = make_motion(req.motion, seed=seed)
                engine.add(label, samples, source='synthetic')
                rec = store.save_recording(
                    gesture_id=gesture['id'],
                    session_id=session['id'],
                    source='synthetic',
                    samples=samples,
                )
                store.append_jsonl({'label': rec['label'], 'samples': samples, 'source': 'synthetic'})
                saved += 1
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'saved': saved, 'label': label, 'source': 'synthetic'}

    @app.post('/api/recordings')
    def save_recording(req: Recording):
        if req.source not in ('hardware', 'phone', 'public_dataset'):
            raise HTTPException(400, 'Unsupported source')
        try:
            label = normalize_label(req.label)
            engine.add(label, req.samples, req.source)
            gesture = store.get_or_create_gesture(label)
            session = store.create_session()
            store.save_recording(
                gesture_id=gesture['id'],
                session_id=session['id'],
                source=req.source,
                samples=req.samples,
            )
            store.append_jsonl(req.model_dump())
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'saved': True, 'label': label, 'source': req.source}

    @app.post('/api/train')
    def train():
        return engine.train()

    @app.post('/api/predict')
    def predict(req: PredictionRequest):
        try:
            return engine.predict(req.samples)
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/demo/predict/{motion}')
    def predict_demo(motion: str):
        if motion not in KINDS:
            raise HTTPException(400, f'Valid motion types: {KINDS}')
        try:
            result = engine.predict(make_motion(motion, seed=99999))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**result, 'actual_simulated_type': motion}

    @app.websocket('/ws/telemetry')
    async def telemetry(ws: WebSocket):
        await ws.accept()
        queue = feed.subscribe()
        try:
            while True:
                message = await queue.get()
                await ws.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            feed.unsubscribe(queue)

    @app.get('/{full_path:path}')
    def frontend_asset(full_path: str):
        if full_path == 'api' or full_path.startswith('api/'):
            raise HTTPException(404, 'Not found')
        root = FRONTEND_DIST.resolve()
        candidate = (FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and (candidate == root or root in candidate.parents):
            return FileResponse(candidate)
        index = FRONTEND_DIST / 'index.html'
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(404, 'Not found')

    return app


app = create_app()

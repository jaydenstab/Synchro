import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import create_app
from engine import GestureEngine
from imu import validate_samples
from simulator import make_motion
from store import Store


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path))


def test_validate_rejects_malformed_samples():
    good = make_motion('circle', seed=1)
    validate_samples(good)
    missing = [{k: v for k, v in sample.items() if k != 'gx'} for sample in good]
    try:
        validate_samples(missing)
        assert False, 'expected missing-axis rejection'
    except ValueError:
        pass
    nan = [dict(sample) for sample in good]
    nan[3]['ay'] = float('nan')
    try:
        validate_samples(nan)
        assert False, 'expected NaN rejection'
    except ValueError:
        pass
    reversed_time = [dict(sample) for sample in good]
    reversed_time[4]['t_ms'] = reversed_time[3]['t_ms']
    try:
        validate_samples(reversed_time)
        assert False, 'expected timestamp rejection'
    except ValueError:
        pass
    try:
        validate_samples(good[:3])
        assert False, 'expected empty/short rejection'
    except ValueError:
        pass


def test_gesture_crud_and_persistence(tmp_path: Path):
    with _client(tmp_path) as client:
        created = client.post('/api/gestures', json={'name': 'wave hello'}).json()
        assert created['name'] == 'wave_hello'
        listed = client.get('/api/gestures').json()['gestures']
        assert any(item['id'] == created['id'] for item in listed)
        renamed = client.patch(f"/api/gestures/{created['id']}", json={'name': 'wave_right'}).json()
        assert renamed['name'] == 'wave_right'
        assert client.post('/api/gestures', json={'name': 'wave_right'}).status_code == 400
    with _client(tmp_path) as client:
        names = [item['name'] for item in client.get('/api/gestures').json()['gestures']]
        assert 'wave_right' in names
        gesture_id = client.get('/api/gestures').json()['gestures'][0]['id']
        assert client.delete(f'/api/gestures/{gesture_id}').status_code == 200
        assert client.get('/api/gestures').json()['gestures'] == []


def test_live_synthetic_recording_persists_real_samples(tmp_path: Path):
    with _client(tmp_path) as client:
        gesture = client.post('/api/gestures', json={'name': 'circle'}).json()
        started = client.post('/api/recordings/start', json={'gesture_id': gesture['id']})
        assert started.status_code == 200, started.text
        assert started.json()['source'] == 'synthetic'
        duplicate = client.post('/api/recordings/start', json={'gesture_id': gesture['id']})
        assert duplicate.status_code == 409
        deadline = time.time() + 2.0
        while time.time() < deadline:
            status = client.get('/api/status').json()['active_recording']
            if status and status['sample_count'] >= 12:
                break
            time.sleep(0.02)
        stopped = client.post('/api/recordings/stop')
        assert stopped.status_code == 200, stopped.text
        body = stopped.json()
        assert body['saved'] is True
        assert body['source'] == 'synthetic'
        assert body['sample_count'] >= 8
        assert body['duration_ms'] >= 0
        recording_id = body['recording_id']
        fetched = client.get(f'/api/recordings/{recording_id}').json()
        assert fetched['source'] == 'synthetic'
        assert len(fetched['samples']) == body['sample_count']
        validate_samples(fetched['samples'])
        axes = {key for sample in fetched['samples'] for key in sample}
        assert {'t_ms', 'ax', 'ay', 'az', 'gx', 'gy', 'gz'} <= axes

    with _client(tmp_path) as client:
        listed = client.get('/api/recordings').json()['recordings']
        assert listed[0]['id'] == recording_id
        again = client.get(f'/api/recordings/{recording_id}').json()
        assert len(again['samples']) >= 8
        assert client.get('/api/status').json()['recordings'] >= 1


def test_empty_and_invalid_uploads_rejected(tmp_path: Path):
    with _client(tmp_path) as client:
        empty = client.post('/api/recordings', json={'label': 'flick_right', 'source': 'phone', 'samples': []})
        assert empty.status_code == 422
        samples = make_motion('flick_right', seed=3)
        samples[0] = {**samples[0], 'az': 'not-a-number'}
        bad = client.post('/api/recordings', json={'label': 'flick_right', 'source': 'phone', 'samples': samples})
        assert bad.status_code == 400
        synth = client.post(
            '/api/recordings',
            json={'label': 'flick_right', 'source': 'synthetic', 'samples': make_motion('flick_right', seed=4)},
        )
        assert synth.status_code == 400


def test_legacy_jsonl_is_imported_not_overwritten(tmp_path: Path):
    samples = make_motion('double_twist', seed=11)
    jsonl = tmp_path / 'recordings.jsonl'
    jsonl.write_text(json.dumps({'label': 'legacy_twist', 'samples': samples, 'source': 'synthetic'}) + '\n')
    original = jsonl.read_text()
    with _client(tmp_path) as client:
        status = client.get('/api/status').json()
        assert status['counts'].get('legacy_twist') == 1
        gestures = client.get('/api/gestures').json()['gestures']
        assert any(item['name'] == 'legacy_twist' for item in gestures)
    assert jsonl.read_text() == original


def test_saved_recordings_train_existing_dtw_engine(tmp_path: Path):
    store = Store(tmp_path)
    gesture = store.create_gesture('flick_right')
    session = store.create_session()
    for seed in range(8):
        store.save_recording(
            gesture_id=gesture['id'],
            session_id=session['id'],
            source='synthetic',
            samples=make_motion('flick_right', seed=seed),
        )
    engine = GestureEngine()
    engine.replace_recordings(store.list_recordings(include_samples=True))
    trained = engine.train()
    assert 'flick_right' in trained['trained_classes']
    predicted = engine.predict(make_motion('flick_right', seed=90))
    assert predicted['closest_class'] == 'flick_right'
    store.close()


def test_demo_generate_train_predict_still_work(tmp_path: Path):
    with _client(tmp_path) as client:
        generated = client.post('/api/demo/generate', json={'label': 'circle', 'motion': 'circle', 'examples': 8})
        assert generated.status_code == 200
        assert generated.json()['source'] == 'synthetic'
        trained = client.post('/api/train')
        assert trained.status_code == 200
        assert 'circle' in trained.json()['trained_classes']
        predicted = client.post('/api/demo/predict/circle')
        assert predicted.status_code == 200
        assert 'distance' in predicted.json()
        status = client.get('/api/status').json()
        assert status['recordings'] == 8
        recording_id = client.get('/api/recordings').json()['recordings'][0]['id']
        assert client.delete(f'/api/recordings/{recording_id}').status_code == 200
        assert client.get('/api/status').json()['recordings'] == 7

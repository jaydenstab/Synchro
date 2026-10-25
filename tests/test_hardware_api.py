"""Shared UI contract for the imported glove stack. No radio or microphone is opened."""
from fastapi.testclient import TestClient

from app import create_app
from motion.host import present_motion


def test_present_motion_matches_the_shared_panel():
    body = present_motion({
        'connected': True,
        'ready': True,
        'fresh': True,
        'transport': 'Bluetooth LE',
        'status': 'Live MPU angles',
        'angles': (1.0, -2.5, 3.0),
        'sample_hz': 1000,
        'temperature_c': 28.25,
        'left_down': False,
        'right_down': True,
        'left_presses': 2,
        'right_presses': 5,
        'tracking_restarts': 1,
        'calibrated': True,
        'calibration': {'state': 'idle', 'progress': 0},
        'packet_errors': 0,
        'pointer': {'enabled': False, 'available': True, 'message': 'Pointer off'},
    })
    assert body['transport'] == 'Bluetooth LE'
    assert body['line'].startswith('Bluetooth LE')
    assert '1000 samples/s' in body['line']
    assert '28.2 °C' in body['line']
    assert body['angles'] == [1.0, -2.5, 3.0]
    assert body['right_down'] is True
    assert body['calibration_note'] == 'Calibrated. Yaw can still drift.'
    assert body['simulated'] is False
    assert body['pointer']['message'] == 'Pointer off'


def test_stale_hardware_snapshot_hides_angles():
    body = present_motion({
        'connected': True,
        'ready': False,
        'fresh': False,
        'status': 'No MPU packets. Upload NanoMotionAngles, or reconnect USB.',
        'angles': (1, 2, 3),
        'left_down': True,
        'calibration': {'state': 'failed', 'progress': 0, 'message': 'Sensor data gap or reset; retry while connected.'},
    })
    assert body['angles'] is None
    assert body['left_down'] is None
    assert body['connected'] is False
    assert 'Sensor data gap' in body['calibration_note']


def test_pointer_and_speech_routes_without_a_glove(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        speech = client.get('/api/speech')
        assert speech.status_code == 200
        assert speech.json()['listening'] is False
        assert speech.json()['model'] == 'parakeet-tdt-0.6b-v2'
        stopped = client.post('/api/speech/stop')
        assert stopped.status_code == 200
        pointer = client.post('/api/pointer', json={'enabled': True})
        assert pointer.status_code == 409
        assert 'glove link' in pointer.json()['detail']

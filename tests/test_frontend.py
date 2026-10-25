from pathlib import Path

from fastapi.testclient import TestClient

from app import FRONTEND_DIST, create_app

STUDIO_MARKERS = (
    'Live sensor dashboard',
    'Custom gesture recorder',
    'Gesture library',
    'Model training',
    'Gesture testing',
    '/api/recordings/start',
    '/api/recordings/stop',
    '/api/recordings/cancel',
    '/api/train',
    '/ws/telemetry',
    'SIMULATED SENSOR DATA',
    'Unknown Gesture',
)


def test_dashboard_is_served_with_studio_sections(tmp_path: Path):
    with TestClient(create_app(tmp_path)) as client:
        legacy = client.get('/legacy')
        assert legacy.status_code == 200
        for marker in STUDIO_MARKERS:
            assert marker in legacy.text, marker

        bridge = client.get('/api/camera/bridge')
        assert bridge.status_code == 200
        body = bridge.json()
        assert body['available'] is False
        assert body['connected'] is False
        assert body['capture_ready'] is False
        assert body['simulated'] is False
        assert body['frame'] == 'none'
        assert body['transport'] == 'bluetooth-classic-rfcomm'
        assert 'browser' in body['reason'].lower()

        capture = client.get('/api/camera/capture')
        assert capture.status_code == 503
        assert capture.json()['code'] == 'camera_bridge_unavailable'

        page = client.get('/')
        assert page.status_code == 200
        built = FRONTEND_DIST / 'index.html'
        if built.is_file():
            assert 'Synchro' in page.text
            assert client.get('/gestures').status_code == 200
            assert 'Synchro' in client.get('/gestures').text
        else:
            for marker in STUDIO_MARKERS:
                assert marker in page.text, marker

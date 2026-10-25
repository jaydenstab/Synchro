"""Read a JPEG from the native viewer. This client does not open Bluetooth."""
from __future__ import annotations

import httpx

from assistant.errors import AssistantError

UNAVAILABLE_REASON = (
    'The ESP32-CAM is opened by the native Mac viewer over Bluetooth Classic RFCOMM. '
    'This browser has no local bridge to that connection.'
)


def unavailable_status() -> dict:
    return {
        'available': False,
        'connected': False,
        'capture_ready': False,
        'transport': 'bluetooth-classic-rfcomm',
        'viewer': 'camera/synchro_mac',
        'reason': UNAVAILABLE_REASON,
        'width': None,
        'height': None,
        'frame': 'none',
        'simulated': False,
    }


def camera_status(base_url: str, timeout_s: float) -> dict:
    url = base_url.rstrip('/')
    try:
        response = httpx.get(f'{url}/status', timeout=timeout_s)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return unavailable_status()
    if response.status_code != 200 or payload.get('service') != 'synchro-camera-bridge':
        return unavailable_status()
    connected = bool(payload.get('connected'))
    has_frame = bool(payload.get('has_frame'))
    width = payload.get('width') if isinstance(payload.get('width'), int) and payload.get('width') else None
    height = payload.get('height') if isinstance(payload.get('height'), int) and payload.get('height') else None
    if connected and has_frame:
        reason = (
            'The native viewer is live. Capture Photo requests a JPEG from that existing '
            'Bluetooth session. This page does not open a second connection.'
        )
        frame = 'native-viewer'
    elif connected:
        reason = 'The native viewer is connected, but it has not published a JPEG yet.'
        frame = 'none'
    else:
        reason = 'The native viewer is running. Press Start there to open the camera. This page does not open Bluetooth.'
        frame = 'none'
    return {
        'available': True,
        'connected': connected,
        'capture_ready': connected and has_frame,
        'transport': 'bluetooth-classic-rfcomm',
        'viewer': 'camera/synchro_mac',
        'reason': reason,
        'width': width,
        'height': height,
        'frame': frame,
        'simulated': False,
    }


def capture_jpeg(base_url: str, timeout_s: float) -> bytes:
    url = base_url.rstrip('/')
    try:
        response = httpx.get(f'{url}/frame.jpg', timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise AssistantError(
            'camera_bridge_unavailable',
            'Camera bridge unavailable. Start the native Mac viewer and press Start, or upload an image.',
            503,
        ) from exc
    if response.status_code != 200 or 'image/jpeg' not in response.headers.get('content-type', ''):
        raise AssistantError(
            'camera_bridge_unavailable',
            'Camera bridge unavailable. The native viewer has no live JPEG from its existing Bluetooth session.',
            503,
        )
    data = response.content
    if len(data) < 4 or data[:3] != b'\xff\xd8\xff' or data[-2:] != b'\xff\xd9':
        raise AssistantError('invalid_image', 'The camera bridge did not return a JPEG.', 502)
    return data

"""Shared API view of the Windows glove stack.

`tools/motion_sensor.py` owns USB and Bluetooth LE. This module does not draw
a window. The React UI and the Mac camera shell read `present_motion`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'


def ensure_tools_path() -> None:
    text = str(TOOLS)
    if text not in sys.path:
        sys.path.insert(0, text)


def idle_pointer() -> dict:
    windows = sys.platform == 'win32'
    return {
        'enabled': False,
        'available': windows,
        'message': (
            'Pointer follows the glove on Windows. Connect the Nano, calibrate, then enable it here.'
            if windows else
            'Pointer control moves the Windows cursor. Angles and contacts still update on this Mac.'
        ),
        'speed': 1.0,
        'invert_x': False,
        'invert_y': False,
        'auto_enable': True,
        'stabilized': True,
        'sideways_axis': 'X',
        'left_clicks': 0,
        'right_clicks': 0,
        'manual_pause': False,
    }


def idle_speech() -> dict:
    return {
        'listening': False,
        'status': 'Mic off · Parakeet v2 + Silero · local',
        'model': 'parakeet-tdt-0.6b-v2',
        'vad': 'silero',
        'local': True,
        'device': None,
        'level': 0.0,
        'voice': False,
        'requests': 0,
        'results': 0,
        'dropped': 0,
        'pending': 0,
        'latency_ms': None,
        'error': None,
        'text': '',
        'revision': 0,
    }


def present_motion(raw: dict) -> dict:
    """Map a MotionSensor snapshot onto the fields the shared UI already renders."""
    fresh = bool(raw.get('fresh'))
    ready = bool(raw.get('ready')) and fresh
    transport = raw.get('transport') if fresh else None
    status = str(raw.get('status') or 'Looking for Nano USB...')
    temperature = raw.get('temperature_c') if fresh else None
    sample_hz = float(raw.get('sample_hz') or 0.0) if fresh else 0.0
    restarts = int(raw.get('tracking_restarts') or 0)
    if fresh and ready and temperature is not None and transport:
        line = (
            f'{transport}  ·  {sample_hz:.0f} samples/s  ·  '
            f'{float(temperature):.1f} °C  ·  {restarts} tracking restarts'
        )
    else:
        line = status
    calibration = raw.get('calibration') if isinstance(raw.get('calibration'), dict) else {}
    state = str(calibration.get('state') or 'idle')
    progress = float(calibration.get('progress') or 0.0)
    message = calibration.get('message')
    if state in ('queued', 'running', 'saving'):
        note = f'KEEP STILL — {15 * progress:.1f} / 15 seconds'
    elif state == 'failed' and message:
        note = str(message)
    elif state == 'passed' and message:
        note = str(message)
    elif raw.get('calibrated'):
        note = 'Calibrated. Yaw can still drift.'
    else:
        note = 'Not calibrated. Yaw can drift.'
    angles = raw.get('angles') if ready else None
    if angles is not None:
        angles = [float(value) for value in angles]
    pointer = raw.get('pointer') if isinstance(raw.get('pointer'), dict) else idle_pointer()
    speech = raw.get('speech') if isinstance(raw.get('speech'), dict) else None
    return {
        'connected': bool(raw.get('connected')) and fresh,
        'ready': ready,
        'fresh': fresh,
        'transport': transport,
        'status': status,
        'line': line,
        'angles': angles,
        'sample_hz': sample_hz,
        'temperature_c': float(temperature) if temperature is not None else None,
        'left_down': raw.get('left_down') if fresh else None,
        'right_down': raw.get('right_down') if fresh else None,
        'left_presses': int(raw.get('left_presses') or 0),
        'right_presses': int(raw.get('right_presses') or 0),
        'tracking_restarts': restarts,
        'calibrated': bool(raw.get('calibrated')),
        'calibration_state': state,
        'calibration_progress': progress,
        'calibration_note': note,
        'calibrate_enabled': ready and state not in ('queued', 'running', 'saving'),
        'packet_errors': int(raw.get('packet_errors') or 0),
        'simulated': False,
        'pointer': pointer,
        'speech': speech,
    }


class HardwareSession:
    """USB-or-BLE glove reader, Windows pointer, and local speech. No Tk widgets."""

    def __init__(self, transport: str = 'auto', port: str | None = None, ble_address: str | None = None) -> None:
        ensure_tools_path()
        from motion_pointer import PointerController
        from motion_sensor import MotionSensor
        from speech_stream import SpeechController

        self.sensor = MotionSensor(port=port, transport=transport, ble_address=ble_address)
        self.pointer = PointerController(self.sensor)
        self.sensor.pointer = self.pointer
        self.speech = SpeechController()
        self.sensor.speech = self.speech

    def start(self) -> None:
        self.sensor.start()
        self.pointer.start()

    def close(self) -> None:
        self.pointer.close()
        self.speech.stop()
        self.sensor.close()

    def snapshot(self) -> dict:
        raw = self.sensor.snapshot()
        speech = self.speech.snapshot(include_text=True)
        raw['speech'] = speech
        body = present_motion(raw)
        body['speech'] = speech
        return body


def speech_controller():
    ensure_tools_path()
    from speech_stream import SpeechController
    return SpeechController()


def speech_devices() -> dict:
    try:
        import sounddevice as sd
    except Exception as exc:
        return {
            'devices': [{'id': None, 'label': 'Default laptop microphone'}],
            'error': f'Install local speech dependencies to list microphones: {exc}',
        }
    devices = [{'id': None, 'label': 'Default laptop microphone'}]
    try:
        found = sd.query_devices()
    except Exception as exc:
        return {'devices': devices, 'error': str(exc)}
    for item in found:
        if int(item.get('max_input_channels') or 0) > 0:
            devices.append({'id': int(item['index']), 'label': str(item['name'])})
    return {'devices': devices, 'error': None}


def session_from_env() -> HardwareSession:
    transport = os.environ.get('SYNCHRO_MOTION_TRANSPORT', 'auto').strip() or 'auto'
    if transport not in ('auto', 'usb', 'ble'):
        transport = 'auto'
    port = os.environ.get('SYNCHRO_MPU_PORT', '').strip() or None
    ble = os.environ.get('SYNCHRO_MPU_BLE_ADDRESS', '').strip() or None
    return HardwareSession(transport=transport, port=port, ble_address=ble)

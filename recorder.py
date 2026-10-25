"""Start/stop capture of live IMU samples into a single active recording."""
from __future__ import annotations

import threading
import time
from typing import Any

from imu import MAX_SAMPLES, SOURCES, normalize_sample
from store import Store, new_id


class Recorder:
    def __init__(self, store: Store):
        self.store = store
        self._lock = threading.Lock()
        self._active: dict[str, Any] | None = None

    def status(self) -> dict[str, Any] | None:
        with self._lock:
            if self._active is None:
                return None
            samples = self._active['samples']
            return {
                'recording_id': self._active['recording_id'],
                'gesture_id': self._active['gesture_id'],
                'label': self._active['label'],
                'session_id': self._active['session_id'],
                'source': self._active['source'],
                'sample_count': len(samples),
                'started_at': self._active['started_at'],
            }

    def start(self, *, gesture_id: str, source: str = 'synthetic',
              session_id: str | None = None) -> dict[str, Any]:
        if source not in SOURCES:
            raise ValueError(f'Unsupported source. Expected one of {SOURCES}.')
        gesture = self.store.get_gesture(gesture_id)
        if gesture is None:
            raise KeyError('Gesture not found.')
        session = self.store.create_session(session_id)
        with self._lock:
            if self._active is not None:
                raise RuntimeError('A recording session is already active. Stop it before starting another.')
            self._active = {
                'recording_id': new_id(),
                'gesture_id': gesture['id'],
                'label': gesture['name'],
                'session_id': session['id'],
                'source': source,
                'samples': [],
                'started_at': time.time(),
                'started_mono': time.monotonic(),
            }
            return {
                'recording_id': self._active['recording_id'],
                'gesture_id': self._active['gesture_id'],
                'label': self._active['label'],
                'session_id': self._active['session_id'],
                'source': self._active['source'],
                'sample_count': 0,
                'started_at': self._active['started_at'],
            }

    def ingest(self, sample: dict[str, Any]) -> None:
        try:
            parsed = normalize_sample(sample)
        except ValueError:
            return
        with self._lock:
            if self._active is None:
                return
            if len(self._active['samples']) >= MAX_SAMPLES:
                return
            elapsed_ms = (time.monotonic() - self._active['started_mono']) * 1000.0
            parsed['t_ms'] = round(elapsed_ms, 2)
            previous = self._active['samples'][-1]['t_ms'] if self._active['samples'] else None
            if previous is not None and parsed['t_ms'] <= previous:
                parsed['t_ms'] = round(previous + 0.01, 2)
            self._active['samples'].append(parsed)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._active is None:
                raise RuntimeError('No active recording to stop.')
            snapshot = self._active
            self._active = None
        if not snapshot['samples']:
            raise ValueError('Recording captured no samples. Leave the session running while the synthetic feed emits data.')
        return self.store.save_recording(
            gesture_id=snapshot['gesture_id'],
            session_id=snapshot['session_id'],
            source=snapshot['source'],
            samples=snapshot['samples'],
            recording_id=snapshot['recording_id'],
        )

    def cancel(self) -> None:
        with self._lock:
            self._active = None

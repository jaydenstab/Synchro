"""Shared IMU sample contract and validation.

Units: acceleration m/s^2, angular rate rad/s, t_ms monotonic milliseconds
within a recording. Device axes are the generating device's local frame.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

AXES = ('ax', 'ay', 'az', 'gx', 'gy', 'gz')
SAMPLE_FIELDS = ('t_ms',) + AXES
SOURCES = ('synthetic', 'hardware', 'phone', 'public_dataset')
MIN_SAMPLES = 8
MAX_SAMPLES = 1000
LABEL_MAX = 40


def is_finite_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def normalize_label(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError('Gesture name must be a string.')
    label = name.strip().replace(' ', '_')
    if not (1 <= len(label) <= LABEL_MAX and all(c.isalnum() or c in '_-' for c in label)):
        raise ValueError('Gesture label must be 1-40 letters, numbers, spaces, _ or -.')
    return label


def normalize_sample(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError('Each sample must be an object with t_ms and six IMU axes.')
    missing = [field for field in SAMPLE_FIELDS if field not in raw]
    if missing:
        raise ValueError(f'Sample missing fields: {", ".join(missing)}.')
    parsed: dict[str, float] = {}
    for field in SAMPLE_FIELDS:
        value = raw[field]
        if not is_finite_number(value):
            raise ValueError(f'Sample field {field} must be a finite number.')
        parsed[field] = float(value)
    extra = {key: raw[key] for key in raw if key not in SAMPLE_FIELDS}
    # Optional button/arm field is allowed but not required.
    if 'button' in extra and extra['button'] is not None:
        parsed['button'] = extra['button']
    return parsed


def validate_samples(samples: Iterable[Any], *, min_samples: int = MIN_SAMPLES,
                     max_samples: int = MAX_SAMPLES) -> list[dict[str, float]]:
    if samples is None:
        raise ValueError('Recording samples are required.')
    if not isinstance(samples, (list, tuple)):
        raise ValueError('Samples must be a list.')
    parsed = [normalize_sample(item) for item in samples]
    if len(parsed) < min_samples:
        raise ValueError(f'Need at least {min_samples} samples per recording.')
    if len(parsed) > max_samples:
        raise ValueError(f'Recordings are limited to {max_samples} samples.')
    times = [item['t_ms'] for item in parsed]
    for previous, current in zip(times, times[1:]):
        if current <= previous:
            raise ValueError('Timestamps must be finite and strictly increasing.')
    duration_ms = times[-1] - times[0]
    if duration_ms < 0:
        raise ValueError('Recording duration must be non-negative.')
    return parsed


def recording_stats(samples: list[dict[str, float]]) -> dict[str, float | int]:
    duration_ms = float(samples[-1]['t_ms'] - samples[0]['t_ms']) if samples else 0.0
    return {'sample_count': len(samples), 'duration_ms': round(duration_ms, 3)}

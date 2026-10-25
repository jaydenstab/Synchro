"""Text for the shared window. Mac layout, Windows glove measurements."""
from __future__ import annotations

ANGLE_CAPTIONS = ('ROLL / X', 'PITCH / Y', 'YAW / RELATIVE')
CONTACT_CAPTIONS = ('Index / LEFT CLICK', 'Middle / RIGHT CLICK')
AXIS_CAPTIONS = ('ax g', 'ay g', 'az g', 'gx deg/s', 'gy deg/s', 'gz deg/s')


def format_angle(value: float | None) -> str:
    if value is None:
        return '—'
    return f'{value:+.2f}°'


def format_axis(value: float | None) -> str:
    if value is None:
        return '—'
    return f'{value:+.3f}'


def contact_text(fresh: bool, down: bool | None, presses: int, tapping: bool) -> tuple[str, bool]:
    if not fresh or down is None:
        return 'NO SIGNAL', False
    if down:
        return 'HELD', True
    if tapping:
        return 'TAP', True
    return 'released', False


def contact_line(caption: str, fresh: bool, down: bool | None, presses: int, tapping: bool) -> tuple[str, bool]:
    text, active = contact_text(fresh, down, presses, tapping)
    return f'{caption}: {text}  ·  {presses} taps', active

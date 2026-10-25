"""Synthetic six-channel IMU generator. This does NOT establish real-world ML accuracy."""
import numpy as np

KINDS = ('flick_right', 'flick_left', 'double_twist', 'circle', 'idle', 'unknown')


def make_motion(kind: str, seed: int = 0, n: int = 90) -> list[dict]:
    if kind not in KINDS:
        raise ValueError(f'Unknown simulated motion type: {kind}')
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, n)
    # Vary timing and magnitude between trials without changing the class definition.
    w = np.clip(t + rng.uniform(-0.35, 0.35) * t * (1 - t), 0, 1)
    amp = rng.uniform(0.83, 1.17)
    g = np.zeros((n, 3))
    a = np.zeros((n, 3))
    a[:, 2] = 9.81
    bump = lambda c, width: np.exp(-((w - c) / width) ** 2)
    if kind == 'flick_right':
        g[:, 2] = 2.8 * bump(0.42, 0.15)
        a[:, 0] = 1.25 * (bump(0.34, 0.1) - bump(0.55, 0.12))
    elif kind == 'flick_left':
        g[:, 2] = -2.8 * bump(0.42, 0.15)
        a[:, 0] = -1.25 * (bump(0.34, 0.1) - bump(0.55, 0.12))
    elif kind == 'double_twist':
        g[:, 1] = 2.1 * (bump(0.28, 0.10) - bump(0.7, 0.11))
        a[:, 1] = 0.7 * (bump(0.25, 0.13) + bump(0.72, 0.1))
    elif kind == 'circle':
        envelope = np.sin(np.pi * w)**2
        g[:, 0] = 1.6 * np.sin(2 * np.pi * w) * envelope
        g[:, 1] = 1.6 * np.cos(2 * np.pi * w) * envelope
        a[:, 0] = 0.85 * np.sin(2 * np.pi * w) * envelope
        a[:, 1] = 0.85 * np.cos(2 * np.pi * w) * envelope
    elif kind == 'unknown':
        g[:, 0] = 4.0 * np.sin(5 * np.pi * w) * np.sin(np.pi * w)
        a[:, 1] = 2.0 * np.sin(4 * np.pi * w)
    g = amp * g + rng.normal(0, 0.07, size=(n, 3))
    a = a + rng.normal(0, 0.08, size=(n, 3))
    duration_ms = rng.uniform(700, 1200)
    return [
        {'t_ms': round(float(i * duration_ms / (n - 1)), 2),
         'ax': float(a[i, 0]), 'ay': float(a[i, 1]), 'az': float(a[i, 2]),
         'gx': float(g[i, 0]), 'gy': float(g[i, 1]), 'gz': float(g[i, 2])}
        for i in range(n)
    ]

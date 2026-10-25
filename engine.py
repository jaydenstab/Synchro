"""Simple multivariate DTW baseline for recordings of 6-axis IMU data."""
from collections import defaultdict
import numpy as np

from imu import AXES, normalize_label, validate_samples


def vectorize(samples: list[dict], length: int = 48) -> np.ndarray:
    parsed = validate_samples(samples)
    times = np.asarray([s['t_ms'] for s in parsed], dtype=float)
    x = np.asarray([[s[k] for k in AXES] for s in parsed], dtype=float)
    # Simulator-oriented shortcut: gravity is generated on +z. Do not treat this
    # as orientation-aware preprocessing for real hardware/phone recordings.
    x[:, 2] -= 9.81
    time_grid = np.linspace(times[0], times[-1], length)
    return np.column_stack([np.interp(time_grid, times, x[:, j]) for j in range(6)])


def dtw_distance(a: np.ndarray, b: np.ndarray, radius: int = 9) -> float:
    """Band-limited DTW mean point distance. O(T^2) for short recordings."""
    m, n = len(a), len(b)
    cost = np.full((m + 1, n + 1), np.inf)
    steps = np.zeros((m + 1, n + 1), dtype=int)
    cost[0, 0] = 0
    for i in range(1, m + 1):
        for j in range(max(1, i - radius), min(n, i + radius) + 1):
            candidates = ((cost[i-1, j], steps[i-1, j]),
                          (cost[i, j-1], steps[i, j-1]),
                          (cost[i-1, j-1], steps[i-1, j-1]))
            c, count = min(candidates, key=lambda x: x[0])
            cost[i, j] = c + np.linalg.norm(a[i-1] - b[j-1])
            steps[i, j] = count + 1
    return float(cost[m, n] / max(1, steps[m, n]))


class GestureEngine:
    def __init__(self):
        self.recordings: list[dict] = []
        self.templates: dict[str, list[np.ndarray]] = {}
        self.thresholds: dict[str, float] = {}

    def add(self, label: str, samples: list[dict], source: str = 'hardware'):
        label = normalize_label(label)
        vectorize(samples)  # validate before storing
        self.recordings.append({'label': label, 'samples': samples, 'source': source})

    def replace_recordings(self, recordings: list[dict]):
        self.recordings = []
        self.templates = {}
        self.thresholds = {}
        for rec in recordings:
            self.add(rec['label'], rec['samples'], rec.get('source', 'hardware'))

    def train(self):
        grouped = defaultdict(list)
        for rec in self.recordings:
            if rec['label'] != 'idle':
                grouped[rec['label']].append(vectorize(rec['samples']))
        self.templates = {label: arr for label, arr in grouped.items() if len(arr) >= 2}
        self.thresholds = {}
        for label, arr in self.templates.items():
            nearest = [min(dtw_distance(x, other) for j, other in enumerate(arr) if i != j)
                       for i, x in enumerate(arr)]
            # Heuristic threshold for a DEMO only. Tune with held-out real data.
            self.thresholds[label] = float(max(0.28, np.percentile(nearest, 90) * 2.2))
        return {'trained_classes': list(self.templates),
                'recordings': len(self.recordings),
                'thresholds': self.thresholds}

    def predict(self, samples: list[dict]):
        if not self.templates:
            raise ValueError('Train a model before predicting.')
        x = vectorize(samples)
        distances = {label: min(dtw_distance(x, arr) for arr in templates)
                     for label, templates in self.templates.items()}
        best_label = min(distances, key=distances.get)
        best_distance = distances[best_label]
        accepted = best_distance <= self.thresholds[best_label]
        return {'label': best_label if accepted else 'unknown',
                'closest_class': best_label,
                'distance': round(best_distance, 4),
                'threshold': round(self.thresholds[best_label], 4),
                'match': bool(accepted),
                'distances': {k: round(v, 4) for k, v in distances.items()},
                'note': 'DTW distance is not a calibrated probability.'}

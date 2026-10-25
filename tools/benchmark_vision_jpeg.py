"""Compare local vision JPEG preparation. Reads supplied images; no cloud calls.

Run: python tools/benchmark_vision_jpeg.py frame.jpg --repeat 30
Results describe local preparation time and bytes, not Gemini answer accuracy.
"""
import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import statistics
import time
from PIL import Image
from jarvis_assistant import encode_vision_jpeg

PRESETS = ((90, None), (80, None), (75, 480), (70, 320))


def summarize(values):
    ordered = sorted(values)
    return {'median': statistics.median(ordered),
            'p95': ordered[max(0, math.ceil(len(ordered) * .95) - 1)]}


def benchmark(path, repeat, output_dir=None):
    with Image.open(path) as source:
        image = source.convert('RGB')
    results = []
    for quality, max_edge in PRESETS:
        encode_vision_jpeg(image, rotation=True, quality=quality, max_edge=max_edge)  # Warm-up.
        durations = []
        for _ in range(repeat):
            began = time.perf_counter()
            jpeg = encode_vision_jpeg(image, rotation=True, quality=quality, max_edge=max_edge)
            durations.append((time.perf_counter() - began) * 1000)
        with Image.open(BytesIO(jpeg)) as encoded:
            size = list(encoded.size)
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / f'{path.stem}-q{quality}-edge{max_edge or "original"}.jpg').write_bytes(jpeg)
        results.append({'quality': quality, 'max_edge': max_edge, 'size': size,
                        'jpeg_bytes': len(jpeg), 'preparation_ms': summarize(durations)})
    return {'source': str(path), 'source_size': list(image.size), 'repeat': repeat,
            'runtime_default': 'quality 75, original dimensions', 'presets': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+', type=Path)
    parser.add_argument('--repeat', type=int, default=30)
    parser.add_argument('--output-dir', type=Path, help='Optionally save rotated variants for visual comparison')
    args = parser.parse_args()
    if not 1 <= args.repeat <= 1000:
        parser.error('--repeat must be between 1 and 1000')
    print(json.dumps([benchmark(path, args.repeat, args.output_dir) for path in args.images], indent=2))


if __name__ == '__main__': main()

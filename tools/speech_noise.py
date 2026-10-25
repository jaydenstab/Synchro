"""Streaming RNNoise for mono PCM16 at 16 kHz; no audio files or cloud calls.

Use pyrnnoise's bundled native library directly so its file-oriented resampler
does not buffer microphone audio. Both FIR resamplers retain their history.
"""
import ctypes
import importlib.util
from pathlib import Path
import sys

import numpy as np


class NoiseSuppressionError(RuntimeError):
    pass


class _RNNoise:
    def __init__(self):
        self.state = None
        spec = importlib.util.find_spec('pyrnnoise')
        if spec is None or spec.origin is None:
            raise NoiseSuppressionError('RNNoise is missing. Install tools/requirements-speech.txt or turn off Noise suppression.')
        filename = {'win32': 'rnnoise.dll', 'darwin': 'librnnoise.dylib',
                    'linux': 'librnnoise.so'}.get(sys.platform)
        if filename is None:
            raise NoiseSuppressionError('RNNoise is unavailable on this platform. Turn off Noise suppression.')
        try:
            self.lib = ctypes.CDLL(str(Path(spec.origin).parent / filename))
            self.lib.rnnoise_create.argtypes = [ctypes.c_void_p]
            self.lib.rnnoise_create.restype = ctypes.c_void_p
            self.lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
            self.lib.rnnoise_destroy.restype = None
            self.lib.rnnoise_get_frame_size.argtypes = []
            self.lib.rnnoise_get_frame_size.restype = ctypes.c_int
            self.lib.rnnoise_process_frame.argtypes = [ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_float)]
            self.lib.rnnoise_process_frame.restype = ctypes.c_float
            if self.lib.rnnoise_get_frame_size() != 480:
                raise ValueError('Unsupported RNNoise frame size')
            self.reset()
        except (OSError, AttributeError, ValueError) as exc:
            raise NoiseSuppressionError('RNNoise could not load. Reinstall speech dependencies or turn off Noise suppression.') from exc

    def reset(self):
        self.close()
        self.state = self.lib.rnnoise_create(None)
        if not self.state:
            raise NoiseSuppressionError('RNNoise could not allocate its audio state.')

    def process(self, frame):
        # RNNoise expects float32 samples in PCM16 amplitude units, not [-1, 1].
        frame = np.array(frame, dtype=np.float32, copy=True)
        ptr = frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self.lib.rnnoise_process_frame(self.state, ptr, ptr)
        return frame

    def close(self):
        if self.state is not None:
            self.lib.rnnoise_destroy(self.state)
            self.state = None


class _FIR:
    def __init__(self, taps):
        self.taps = taps
        self.history = np.zeros(len(taps) - 1, dtype=np.float32)

    def process(self, samples):
        joined = np.concatenate((self.history, samples))
        self.history = joined[-len(self.history):].copy()
        return np.convolve(joined, self.taps, mode='valid')


class RNNoiseFilter:
    """One 512-sample frame in/out, with fixed delay and bounded buffers.

    Native processing uses 480 samples at 48 kHz. A 160-sample output reserve
    bridges the 10 ms/32 ms frame mismatch without dropping or duplicating audio.
    This adds a fixed 10 ms reserve and 2 ms FIR delay, plus RNNoise's own delay.
    Call only from the capture worker; reset on gaps, clear and assistant mute.
    """
    def __init__(self):
        self.core = _RNNoise()
        self._reset_buffers()

    def _reset_buffers(self):
        # 97-tap, unity-DC low-pass at the 16 kHz Nyquist frequency, sampled
        # at 48 kHz. Kaiser window suppresses interpolation images/aliasing.
        taps = np.sinc(np.arange(-48, 49) / 3) * np.kaiser(97, 8.6)
        taps = (taps / taps.sum()).astype(np.float32)
        self.up = _FIR(taps * 3)
        self.down = _FIR(taps)
        self.pending = np.empty(0, dtype=np.float32)
        self.output = np.zeros(160, dtype=np.float32)

    def reset(self):
        self.core.reset()
        self._reset_buffers()

    def process(self, pcm):
        if len(pcm) != 1024:
            raise ValueError('RNNoise expects 512 samples of mono PCM16 at 16 kHz.')
        if self.core is None:
            raise NoiseSuppressionError('RNNoise is closed.')
        samples = np.frombuffer(pcm, dtype='<i2')
        upsampled = np.zeros(1536, dtype=np.float32)
        upsampled[::3] = samples
        self.pending = np.concatenate((self.pending, self.up.process(upsampled)))
        count = len(self.pending) // 480
        cleaned = np.concatenate([self.core.process(self.pending[i*480:(i+1)*480])
                                  for i in range(count)])
        self.pending = self.pending[count*480:].copy()
        # Every native frame is divisible by three, preserving decimation phase.
        self.output = np.concatenate((self.output, self.down.process(cleaned)[::3]))
        result = self.output[:512]
        self.output = self.output[512:].copy()
        return np.clip(np.rint(result), -32768, 32767).astype('<i2').tobytes()

    def close(self):
        if self.core is not None:
            self.core.close()
            self.core = None

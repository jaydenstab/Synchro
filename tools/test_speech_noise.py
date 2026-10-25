"""Streaming DSP and capture integration regressions; never opens a microphone."""
import importlib.util
import queue
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from speech_noise import NoiseSuppressionError, RNNoiseFilter
from speech_stream import FRAME_BYTES, SpeechController


class PassThrough:
    def process(self, frame):
        return frame.copy()

    def reset(self):
        pass

    def close(self):
        pass


class ResamplingTests(unittest.TestCase):
    def test_stream_matches_continuous_filtering_without_length_drift(self):
        rng = np.random.default_rng(3)
        samples = rng.integers(-12000, 12000, 512 * 125, dtype=np.int16)
        with patch('speech_noise._RNNoise', PassThrough):
            denoiser = RNNoiseFilter()
        actual = []
        for frame in samples.reshape(-1, 512):
            result = denoiser.process(frame.tobytes())
            self.assertEqual(len(result), FRAME_BYTES)
            self.assertLess(len(denoiser.pending), 480)
            self.assertLessEqual(len(denoiser.output), 160)
            actual.append(np.frombuffer(result, dtype='<i2'))
        taps = denoiser.down.taps
        up = np.zeros(len(samples) * 3, dtype=np.float32)
        up[::3] = samples
        reference = np.convolve(np.convolve(up, taps * 3), taps)[::3]
        reference = np.concatenate((np.zeros(160), reference))[:len(samples)]
        reference = np.clip(np.rint(reference), -32768, 32767).astype('<i2')
        np.testing.assert_allclose(np.concatenate(actual), reference, atol=1)
        denoiser.close()

    def test_passband_and_delay(self):
        samples = (10000 * np.sin(2 * np.pi * 1000 * np.arange(512*20) / 16000)).astype('<i2')
        with patch('speech_noise._RNNoise', PassThrough):
            denoiser = RNNoiseFilter()
        result = np.frombuffer(b''.join(denoiser.process(f.tobytes())
                              for f in samples.reshape(-1, 512)), dtype='<i2')
        # Two 48-sample FIR delays at 48 kHz + the 160-sample reserve.
        np.testing.assert_allclose(result[512:], samples[512-192:-192], atol=3)
        denoiser.close()

    def test_clips_instead_of_pcm_integer_wraparound(self):
        class Loud(PassThrough):
            def process(self, frame):
                return np.full(480, 100000, dtype=np.float32)
        with patch('speech_noise._RNNoise', Loud):
            denoiser = RNNoiseFilter()
        for _ in range(3):
            result = np.frombuffer(denoiser.process(bytes(FRAME_BYTES)), dtype='<i2')
        self.assertTrue(np.all(result == 32767))
        denoiser.close()
        denoiser.close()
        with self.assertRaises(NoiseSuppressionError):
            denoiser.process(bytes(FRAME_BYTES))

    def test_rejects_wrong_frame_size(self):
        with patch('speech_noise._RNNoise', PassThrough):
            denoiser = RNNoiseFilter()
        with self.assertRaises(ValueError):
            denoiser.process(bytes(100))
        denoiser.close()


class CaptureTests(unittest.TestCase):
    def capture(self, *, enabled=True, gates=None, clear_at=None, fail=False):
        controller = SpeechController()
        controller.state['listening'] = True
        stop, clear, clips = threading.Event(), threading.Event(), queue.Queue()
        raw_pcm = np.full(512, 1000, dtype='<i2').tobytes()
        clean_pcm = np.full(512, 200, dtype='<i2').tobytes()
        frames = iter(range(25))
        raw = Mock()
        raw.empty.return_value = True
        def get(timeout):
            try:
                i = next(frames)
            except StopIteration:
                stop.set()
                raise queue.Empty
            return raw_pcm, i * .032, (True, 0)
        raw.get.side_effect = get
        filter_mock = Mock()
        filter_mock.process.return_value = clean_pcm
        seen = []
        vad = Mock()
        def probability(samples):
            seen.append(samples.copy())
            if clear_at == len(seen):
                clear.set()
            return .9 if len(seen) <= 7 else .1
        vad.probability.side_effect = probability
        if gates is not None:
            controller.assistant = Mock()
            controller.assistant.audio_gate.side_effect = [(allowed, 0) for allowed in gates]
        with patch('speech_stream.queue.Queue', return_value=raw), \
             patch('speech_stream.RNNoiseFilter', return_value=filter_mock) as factory, \
             patch('sounddevice.RawInputStream') as stream:
            if fail:
                factory.side_effect = NoiseSuppressionError('RNNoise is missing')
            controller._capture(0, stop, clear, clips, None, vad, enabled)
            if fail:
                stream.assert_not_called()
            elif not enabled:
                factory.assert_not_called()
        return controller, filter_mock, seen, clips, clean_pcm, raw_pcm

    def test_filtered_audio_reaches_both_vad_and_transcription(self):
        controller, denoiser, seen, clips, clean, _ = self.capture()
        self.assertEqual(len(seen), 25)
        self.assertTrue(all(np.all(s == 200 / 32768) for s in seen))
        chunk, epoch = clips.get_nowait()
        self.assertEqual(chunk.pcm, clean * 23)
        self.assertEqual(epoch, 0)
        denoiser.close.assert_called_once()
        self.assertFalse(controller.snapshot()['noise_suppression'])

    def test_disabled_path_preserves_raw_audio(self):
        _, denoiser, seen, clips, _, raw = self.capture(enabled=False)
        denoiser.process.assert_not_called()
        self.assertTrue(all(np.all(s == 1000 / 32768) for s in seen))
        self.assertEqual(clips.get_nowait()[0].pcm, raw * 23)

    def test_clear_and_assistant_mute_reset_filter_and_discard_muted_frames(self):
        _, denoiser, seen, _, _, _ = self.capture(
            gates=[True]*3 + [False]*2 + [True]*20, clear_at=2)
        self.assertEqual(len(seen), 23)
        self.assertEqual(denoiser.process.call_count, 23)
        self.assertEqual(denoiser.reset.call_count, 2)
        denoiser.close.assert_called_once()

    def test_missing_library_is_visible_and_does_not_open_mic(self):
        controller, _, seen, _, _, _ = self.capture(fail=True)
        self.assertFalse(controller.snapshot()['listening'])
        self.assertFalse(controller.snapshot()['noise_suppression'])
        self.assertEqual(controller.snapshot()['error'], 'RNNoise is missing')
        self.assertEqual(seen, [])


@unittest.skipUnless(importlib.util.find_spec('pyrnnoise'), 'Install speech dependencies for native RNNoise tests')
class NativeTests(unittest.TestCase):
    def test_noise_attenuation_and_reset_do_not_leak_old_audio(self):
        rng = np.random.default_rng(12)
        noise = np.clip(rng.normal(0, 1200, 512*100), -32768, 32767).astype('<i2')
        denoiser = RNNoiseFilter()
        try:
            clean = np.frombuffer(b''.join(denoiser.process(f.tobytes())
                                  for f in noise.reshape(-1, 512)), dtype='<i2').astype(float)
            ratio = np.sqrt(np.mean(clean[16000:]**2) / np.mean(noise[16000:].astype(float)**2))
            self.assertLess(ratio, .32)  # At least about 10 dB on stationary noise.
            denoiser.reset()
            for _ in range(8):
                self.assertEqual(denoiser.process(bytes(FRAME_BYTES)), bytes(FRAME_BYTES))
        finally:
            denoiser.close()


if __name__ == '__main__':
    unittest.main()

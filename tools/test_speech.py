"""Speech regressions: no microphone recording, downloads or real inference."""
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np

from speech_stream import (FRAME_BYTES, PAUSE_FRAMES, MAX_FRAMES, Segmenter,
                           SpeechChunk, SpeechController, append_transcript)
from speech_models import ParakeetTranscriber, SileroStream

PCM = b'\x10\x00' * (FRAME_BYTES // 2)


class SegmentTests(unittest.TestCase):
    def test_silence_never_transcribes(self):
        segmenter = Segmenter()
        for _ in range(1000):
            self.assertIsNone(segmenter.feed(PCM, .1))

    def test_pause_flushes_once_with_preroll(self):
        s = Segmenter()
        for _ in range(10): s.feed(PCM, .1)
        for _ in range(20): self.assertIsNone(s.feed(PCM, .9))
        for _ in range(PAUSE_FRAMES-1): self.assertIsNone(s.feed(PCM, .1))
        chunk = s.feed(PCM, .1)
        self.assertIsNotNone(chunk)
        self.assertGreater(len(chunk.pcm), 20 * FRAME_BYTES)
        for _ in range(100): self.assertIsNone(s.feed(PCM, .1))

    def test_continuous_speech_does_not_transcribe_at_old_time_cap(self):
        s = Segmenter()
        for _ in range(400): self.assertIsNone(s.feed(PCM, .9))
        chunks = [s.feed(PCM, .1) for _ in range(PAUSE_FRAMES)]
        self.assertEqual(sum(c is not None for c in chunks), 1)
        self.assertGreater(len(chunks[-1].pcm), 400 * FRAME_BYTES)

    def test_hysteresis_does_not_split_speech_or_trigger_from_ambiguous_noise(self):
        s = Segmenter()
        for _ in range(30): self.assertIsNone(s.feed(PCM, .4))
        self.assertFalse(s.active)
        for _ in range(10): s.feed(PCM, .9)
        for _ in range(30): self.assertIsNone(s.feed(PCM, .4))
        self.assertTrue(s.active)
        self.assertEqual(s.silence, 0)

    def test_overlong_utterance_stays_bounded_and_waits_for_pause(self):
        s = Segmenter()
        for _ in range(MAX_FRAMES+300):
            self.assertIsNone(s.feed(PCM, .9))
            self.assertLessEqual(len(s.frames), MAX_FRAMES)
        self.assertTrue(s.overflowed)
        for _ in range(PAUSE_FRAMES): self.assertIsNone(s.feed(PCM, .1))
        self.assertFalse(s.overflowed)
        for _ in range(20): s.feed(PCM, .9)
        chunks = [s.feed(PCM, .1) for _ in range(PAUSE_FRAMES)]
        self.assertIsNotNone(chunks[-1])

    def test_short_click_noise_is_not_speech(self):
        s = Segmenter()
        for _ in range(3): s.feed(PCM, .9)
        self.assertTrue(all(s.feed(PCM, .1) is None for _ in range(30)))

    def test_overlap_removed_only_within_one_long_utterance(self):
        self.assertEqual(append_transcript('Move the mouse', 'The mouse right.', True), 'Move the mouse right.')
        self.assertEqual(append_transcript('Hello.', 'Hello.', False), 'Hello.\nHello.')
        self.assertEqual(append_transcript('Hello.', ''), 'Hello.')


class LifecycleTests(unittest.TestCase):
    def controller(self):
        c = SpeechController()
        c.state['listening'] = True
        return c

    def test_stop_discards_inflight_result(self):
        c = self.controller()
        c.stop()
        c._result(0, 0, 'late words', 100)
        self.assertFalse(c.snapshot()['listening'])
        self.assertEqual(c.snapshot()['text'], '')

    def test_clear_discards_old_results_but_accepts_new(self):
        c = self.controller()
        c._result(0, 0, 'first', 100)
        c.clear()
        c._result(0, 0, 'old words', 100)
        self.assertEqual(c.snapshot()['text'], '')
        c._result(0, 1, 'new words', 100)
        self.assertEqual(c.snapshot()['text'], 'new words')
        self.assertNotIn('text', c.snapshot(include_text=False))

    def test_stop_prevents_next_queued_decode(self):
        c = self.controller()
        clips = queue.Queue()
        for _ in range(3): clips.put((SpeechChunk(PCM), 0))
        entered, release = threading.Event(), threading.Event()
        class Client:
            calls = 0
            def transcribe(self, pcm, stop=None):
                self.calls += 1
                entered.set()
                release.wait(2)
                return 'late'
        client = Client()
        worker = threading.Thread(target=c._transcribe, args=(0, c.stop_event, clips, client))
        worker.start()
        self.assertTrue(entered.wait(2))
        c.stop()
        release.set()
        worker.join(2)
        self.assertEqual(client.calls, 1)
        self.assertEqual(c.snapshot()['text'], '')
        self.assertFalse(worker.is_alive())

    def test_clear_skips_queued_old_utterances(self):
        c = self.controller()
        clips = queue.Queue()
        clips.put((SpeechChunk(PCM), 0))
        c.clear()
        clips.put((SpeechChunk(PCM), 1))
        class Client:
            calls = 0
            def transcribe(self, pcm, stop=None):
                self.calls += 1
                stop.set()
                return 'fresh'
        client = Client()
        c._transcribe(0, c.stop_event, clips, client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(c.snapshot()['text'], 'fresh')

    def test_stop_during_model_load_does_not_open_microphone(self):
        c = self.controller()
        entered, release = threading.Event(), threading.Event()
        def load():
            entered.set()
            release.wait(2)
            return object()
        with patch('speech_models.ParakeetTranscriber', side_effect=load), \
             patch('speech_models.SileroStream'), patch.object(c, '_capture') as capture:
            worker = threading.Thread(target=c._session, args=(0,c.stop_event,c.clear_event,None))
            worker.start()
            self.assertTrue(entered.wait(2))
            c.stop()
            release.set()
            worker.join(2)
            capture.assert_not_called()
        self.assertFalse(worker.is_alive())

    def test_old_generation_cannot_overwrite_restarted_status(self):
        c = self.controller()
        c.stop()
        c.state.update(listening=True, status='new session')
        c._set(0, listening=False, status='old failure')
        self.assertEqual(c.snapshot()['status'], 'new session')


class ModelTests(unittest.TestCase):
    def test_pcm_normalization_sample_rate_and_bounded_long_decodes(self):
        client = ParakeetTranscriber.__new__(ParakeetTranscriber)
        sizes = []
        class Model:
            def recognize(self, audio, sample_rate):
                self_outer.assertEqual(sample_rate, 16000)
                self_outer.assertEqual(audio.dtype, np.float32)
                self_outer.assertLessEqual(float(abs(audio).max()), 1)
                sizes.append(len(audio))
                return 'hello world' if len(sizes)==1 else 'world again'
        self_outer = self
        client.model = Model()
        text = client.transcribe(b'\xff\x7f' * (25*16000))
        self.assertEqual(sizes, [20*16000, int(5.25*16000)])
        self.assertEqual(text, 'hello world again')

    def test_cancelled_decode_does_no_inference(self):
        client = ParakeetTranscriber.__new__(ParakeetTranscriber)
        stop = threading.Event()
        stop.set()
        self.assertEqual(client.transcribe(PCM, stop), '')

    def test_silero_context_and_state_are_continuous_then_reset(self):
        vad = SileroStream.__new__(SileroStream)
        vad.reset()
        self_outer = self
        class Model:
            calls = 0
            def run(self, names, inputs):
                self_outer.assertEqual(inputs['input'].shape, (1, 576))
                self_outer.assertEqual(int(inputs['sr'][0]), 16000)
                self_outer.assertEqual(float(inputs['state'].mean()), self.calls)
                if self.calls == 1:
                    np.testing.assert_array_equal(inputs['input'][0,:64], np.ones(64))
                self.calls += 1
                return np.array([[.9]],dtype=np.float32), np.full((2,1,128), self.calls,dtype=np.float32)
        vad.model = Model()
        self.assertAlmostEqual(vad.probability(np.ones(512,dtype=np.float32)), .9)
        vad.probability(np.zeros(512,dtype=np.float32))
        vad.reset()
        self.assertEqual(float(vad.state.sum()), 0)
        self.assertEqual(float(vad.context.sum()), 0)


@unittest.skipUnless(sys.platform == 'win32', 'Windows-user encryption')
class CredentialTests(unittest.TestCase):
    def test_legacy_credential_remains_encrypted(self):
        from speech_secrets import load_key, save_key
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'GROQ_API_KEY': ''}):
            path = Path(folder) / 'key.dpapi'
            key = 'gsk_synthetic_unit_test_not_a_real_key'
            save_key(key, path)
            self.assertNotIn(key.encode(), path.read_bytes())
            self.assertEqual(load_key(path), key)


if __name__ == '__main__':
    unittest.main()


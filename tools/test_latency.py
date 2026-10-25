"""Deterministic concurrency/resource regressions. No radios, cloud or OS input."""
import base64
from io import BytesIO
import json
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
from bluetooth_viewer import (FrameDecoder, FrameRate, ReceivedJPEG, decode_jpeg,
                              receive_frames, put_latest, ProtocolError)
from jarvis_assistant import (CameraSnapshot, GeminiVision, WindowsSpeech, AssistantError,
                              encode_vision_jpeg)
from text_writer import WindowsTextWriter, WindowsTextBackend, TextWriteError
from test_text_writer import Backend


class PipelineTests(unittest.TestCase):
    def test_one_transfer_overlaps_decode_and_the_next_waits(self):
        started, release, overlapped, third = [threading.Event() for _ in range(4)]
        received, decoded = [], []
        class Camera:
            def receive_jpeg(self):
                received.append(len(received))
                if len(received) == 2:
                    overlapped.set()
                if len(received) == 3:
                    third.set()
                return len(received)
        class Rate:
            def get(self): return 1000000  # No real pacing in this concurrency fixture.
        def decode(packet):
            decoded.append(packet)
            if packet == 1:
                started.set()
                if not release.wait(2):
                    raise RuntimeError('test release timed out')
            return packet
        decoder = FrameDecoder(lambda frame: None, lambda: self.fail('decode failed'), decode)
        stop = threading.Event()
        receiver = threading.Thread(target=receive_frames, args=(Camera(), decoder, Rate(), stop))
        try:
            receiver.start()
            self.assertTrue(started.wait(2), 'the first frame should start decoding')
            self.assertTrue(overlapped.wait(2), 'one transfer may overlap that decode')
            time.sleep(0.2)
            self.assertFalse(third.is_set(), 'a full pending slot must wait')
            self.assertEqual(received, [0, 1])
            release.set()
            self.assertTrue(third.wait(2), 'capture resumes after the pending frame is accepted')
            stop.set()
            receiver.join(2)
            self.assertFalse(receiver.is_alive())
            self.assertEqual(decoded[0], 1)
        finally:
            stop.set()
            release.set()
            receiver.join(2)
            decoder.close()

    def test_stop_discards_busy_and_pending_decode(self):
        entered, release = threading.Event(), threading.Event()
        published = []
        def decode(packet):
            entered.set(); release.wait(2); return packet
        decoder = FrameDecoder(published.append, lambda: None, decode)
        decoder.submit('old')
        self.assertTrue(entered.wait(2))
        decoder.submit('pending')
        closer = threading.Thread(target=decoder.close)
        closer.start()
        with decoder.condition:
            self.assertTrue(decoder.condition.wait_for(lambda: decoder.closed, timeout=2))
        release.set(); closer.join(2)
        self.assertEqual(published, [])
        self.assertFalse(decoder.thread.is_alive())

    def test_decode_failure_closes_session_and_is_not_published(self):
        failed = threading.Event()
        def decode(packet): raise ValueError('bad JPEG')
        published = []
        decoder = FrameDecoder(published.append, failed.set, decode)
        try:
            decoder.submit('bad')
            self.assertTrue(failed.wait(2))
            decoder.submit('later')
            self.assertTrue(decoder.closed)
            self.assertIsNone(decoder.pending)
            self.assertEqual(published, [])
        finally: decoder.close()

    def test_decode_preserves_receive_time_and_validates_dimensions(self):
        output = BytesIO(); Image.new('RGB', (320, 240)).save(output, format='JPEG')
        now = time.perf_counter()
        packet = ReceivedJPEG(output.getvalue(), 320, 240, now - .02, now - .01)
        frame = decode_jpeg(packet)
        self.assertEqual(frame.received_at, packet.received_at)
        self.assertAlmostEqual(frame.transfer_seconds, .01)
        self.assertGreaterEqual(frame.seconds, .02)
        self.assertGreaterEqual(frame.decode_seconds, 0)
        with self.assertRaises(ProtocolError):
            decode_jpeg(ReceivedJPEG(packet.jpeg, 640, 480, now, now))

    def test_rate_can_change_between_requests(self):
        rate, waits, stop = FrameRate(15), [], threading.Event()
        class Decoder:
            def wait_for_slot(self, stop): return True
            def submit(self, packet): rate.set(30)
        class Stop:
            def is_set(self): return stop.is_set()
            def wait(self, duration): waits.append(duration); stop.set()
        with patch('bluetooth_viewer.time.perf_counter', side_effect=[1, 1.01]):
            receive_frames(SimpleNamespace(receive_jpeg=lambda: object()), Decoder(), rate, Stop())
        self.assertAlmostEqual(waits[0], 1 / 30 - .01)
        for value in (0, -1, 31, float('nan'), float('inf')):
            with self.assertRaises(ValueError): rate.set(value)

    def test_output_queue_is_bounded_latest_frame(self):
        frames = queue.Queue(maxsize=1)
        for number in range(50): put_latest(frames, number)
        self.assertEqual(frames.qsize(), 1)
        self.assertEqual(frames.get_nowait(), 49)


class CacheTests(unittest.TestCase):
    def frame(self):
        return SimpleNamespace(image=Image.new('RGB', (640, 480), 'blue'), jpeg=b'original',
                               received_at=time.perf_counter())

    def test_cache_reuse_new_frame_rotation_clear_and_expiry(self):
        snapshot, frame = CameraSnapshot(), self.frame()
        snapshot.update(frame, True)
        with patch('jarvis_assistant.encode_vision_jpeg', wraps=encode_vision_jpeg) as encode:
            first = snapshot.jpeg()
            self.assertIs(snapshot.jpeg(), first)
            snapshot.update(frame, True)
            self.assertIs(snapshot.jpeg(), first)
            self.assertEqual(encode.call_count, 1)
            snapshot.set_rotation(False)
            self.assertEqual(snapshot.jpeg(), b'original')
            snapshot.set_rotation(True); snapshot.jpeg()
            self.assertEqual(encode.call_count, 2)
            snapshot.update(self.frame(), True); snapshot.jpeg()
            self.assertEqual(encode.call_count, 3)
            snapshot.frame.received_at -= 6
            with self.assertRaises(AssistantError): snapshot.jpeg()
            snapshot.clear()
            with self.assertRaises(AssistantError): snapshot.jpeg()

    def test_inflight_encode_cannot_restore_cache_after_clear(self):
        snapshot = CameraSnapshot(); snapshot.update(self.frame(), True)
        entered, release = threading.Event(), threading.Event()
        def encode(*args, **kwargs): entered.set(); release.wait(2); return b'old'
        errors = []
        def get():
            try: snapshot.jpeg()
            except AssistantError as error: errors.append(error)
        with patch('jarvis_assistant.encode_vision_jpeg', side_effect=encode):
            worker = threading.Thread(target=get)
            worker.start(); self.assertTrue(entered.wait(2))
            snapshot.clear(); release.set(); worker.join(2)
        self.assertIsNone(snapshot.cached)
        self.assertIsNone(snapshot.frame)
        self.assertEqual(len(errors), 1)

    def test_default_cloud_jpeg_stays_full_size_and_smaller_than_quality_90(self):
        image = self.frame().image.copy()
        noisy = image.load()
        for x in range(0, 640, 3):
            for y in range(0, 480, 5):
                noisy[x, y] = ((x * 13) % 256, (y * 7) % 256, (x + y) % 256)
        default = encode_vision_jpeg(image, rotation=True)
        larger = encode_vision_jpeg(image, rotation=True, quality=90)
        self.assertEqual(Image.open(BytesIO(default)).size, (640, 480))
        self.assertLess(len(default), len(larger))

    def test_benchmark_encoding_does_not_mutate_source(self):
        image = self.frame().image
        pixels = image.tobytes()
        result = encode_vision_jpeg(image, rotation=True, quality=75, max_edge=320)
        self.assertEqual(Image.open(BytesIO(result)).size, (320, 240))
        self.assertEqual(image.tobytes(), pixels)


class GeminiReuseTests(unittest.TestCase):
    def test_reuses_client_replaces_changed_key_and_closes(self):
        first, second = MagicMock(), MagicMock()
        for client in (first, second):
            client.models.generate_content.return_value.text = json.dumps({'reply': 'ok', 'actions': []})
        vision = GeminiVision()
        with patch('gemini_secrets.load_key', side_effect=['one', 'one', 'two', 'two']), \
             patch('google.genai.Client', side_effect=[first, second]) as factory:
            vision.ask('first'); vision.ask('second')
            self.assertEqual(factory.call_count, 1)
            vision.ask('third')
            first.close.assert_called_once()
            self.assertEqual(factory.call_count, 2)
            vision.close().join(2)
            second.close.assert_called_once()
            with self.assertRaises(AssistantError): vision.ask('closed')
            self.assertEqual(factory.call_count, 2)

    def test_close_does_not_block_ui_on_inflight_request(self):
        entered, release = threading.Event(), threading.Event()
        client = MagicMock()
        def generate(**kwargs): entered.set(); release.wait(2); return SimpleNamespace(text='{"reply":"ok","actions":[]}')
        client.models.generate_content.side_effect = generate
        vision = GeminiVision()
        with patch('gemini_secrets.load_key', return_value='synthetic'), patch('google.genai.Client', return_value=client):
            worker = threading.Thread(target=vision.ask, args=('test',))
            worker.start(); self.assertTrue(entered.wait(2))
            closer = vision.close()
            self.assertFalse(closer is None)
            client.close.assert_not_called()
            release.set(); worker.join(2); closer.join(2)
        client.close.assert_called_once()


class SpeechProcess:
    def __init__(self):
        self.stdin = self
        self.stdout = self
        self.lines = queue.Queue()
        self.lines.put(b'READY\n')
        self.payloads = []
        self.returncode = None
        self.autocomplete = True
        self.killed = threading.Event()
    def __iter__(self): return self
    def __next__(self):
        line = self.lines.get()
        if line is None: raise StopIteration
        return line
    def write(self, data):
        self.payloads.append(base64.b64decode(data).decode('utf-8'))
        if self.autocomplete: self.lines.put(b'DONE\n')
    def flush(self): pass
    def close(self): pass
    def poll(self): return self.returncode
    def kill(self):
        self.returncode = -1
        self.killed.set()
        self.lines.put(None)
    def wait(self, timeout=None): return self.returncode


class SpeechReuseTests(unittest.TestCase):
    def setUp(self):
        errors = []
        hook = patch('threading.excepthook', side_effect=errors.append)
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(errors, [], 'Background worker raised an exception'))

    def test_normal_replies_share_process_and_treat_text_as_data(self):
        process, speech = SpeechProcess(), WindowsSpeech()
        with patch('jarvis_assistant.os.name', 'nt'), \
             patch('jarvis_assistant.subprocess.CREATE_NO_WINDOW', 0, create=True), \
             patch('jarvis_assistant.subprocess.Popen', return_value=process) as factory:
            try:
                speech.speak('Café\n$([not code])', threading.Event())
                speech.speak('second reply', threading.Event())
                self.assertEqual(factory.call_count, 1)
                self.assertEqual(process.payloads, ['Café\n$([not code])', 'second reply'])
            finally: speech.close()
        self.assertTrue(process.killed.is_set())

    def test_cancel_kills_playback_and_next_reply_restarts_cleanly(self):
        first, second, speech = SpeechProcess(), SpeechProcess(), WindowsSpeech()
        first.autocomplete = False
        cancel = threading.Event()
        with patch('jarvis_assistant.os.name', 'nt'), \
             patch('jarvis_assistant.subprocess.CREATE_NO_WINDOW', 0, create=True), \
             patch('jarvis_assistant.subprocess.Popen', side_effect=[first, second]) as factory:
            worker = threading.Thread(target=speech.speak, args=('long reply', cancel))
            try:
                worker.start()
                deadline = time.monotonic() + 2
                while not first.payloads and time.monotonic() < deadline: time.sleep(.001)
                self.assertTrue(first.payloads)
                cancel.set(); worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertTrue(first.killed.is_set())
                speech.speak('new reply', threading.Event())
                self.assertEqual(factory.call_count, 2)
                self.assertEqual(second.payloads, ['new reply'])
            finally: cancel.set(); speech.close(); worker.join(2)

    def test_shutdown_unblocks_active_playback(self):
        process, speech = SpeechProcess(), WindowsSpeech()
        process.autocomplete = False
        with patch('jarvis_assistant.os.name', 'nt'), \
             patch('jarvis_assistant.subprocess.CREATE_NO_WINDOW', 0, create=True), \
             patch('jarvis_assistant.subprocess.Popen', return_value=process):
            worker = threading.Thread(target=speech.speak, args=('reply', threading.Event()))
            worker.start()
            deadline = time.monotonic() + 2
            while not process.payloads and time.monotonic() < deadline: time.sleep(.001)
            speech.close(); worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(process.killed.is_set())

    def test_speech_worker_failure_is_reported_and_next_reply_recovers(self):
        first, second, speech = SpeechProcess(), SpeechProcess(), WindowsSpeech()
        def crash(data):
            first.returncode = 1
            first.lines.put(None)
        first.write = crash
        with patch('jarvis_assistant.os.name', 'nt'), \
             patch('jarvis_assistant.subprocess.CREATE_NO_WINDOW', 0, create=True), \
             patch('jarvis_assistant.subprocess.Popen', side_effect=[first, second]) as factory:
            try:
                with self.assertRaises(AssistantError): speech.speak('failed reply', threading.Event())
                speech.speak('fresh reply', threading.Event())
                self.assertEqual(factory.call_count, 2)
                self.assertEqual(second.payloads, ['fresh reply'])
            finally: speech.close()


class InputWorkerTests(unittest.TestCase):
    def test_all_backend_calls_and_cleanup_share_one_dedicated_thread(self):
        backend, calls = Backend(), []
        for name in ('focused', 'interrupted', 'send', 'press'):
            original = getattr(backend, name)
            def track(*args, original=original, name=name):
                calls.append((name, threading.get_ident()))
                return original(*args)
            setattr(backend, name, track)
        backend.close = lambda: calls.append(('close', threading.get_ident()))
        writer = WindowsTextWriter(backend)
        try:
            target = writer.capture()
            writer.write('abc', target, threading.Event())
            writer.press('enter', target, threading.Event())
        finally: writer.close()
        self.assertEqual(len({thread for _, thread in calls}), 1)
        self.assertNotEqual(calls[0][1], threading.get_ident())
        self.assertEqual(calls[-1][0], 'close')
        self.assertFalse(writer.thread.is_alive())
        with self.assertRaises(TextWriteError): writer.capture()

    def test_close_during_focus_check_prevents_next_character(self):
        backend, entered, release = Backend(), threading.Event(), threading.Event()
        writer = WindowsTextWriter(backend)
        target = writer.capture()
        def focused():
            entered.set(); release.wait(2); return target
        backend.focused = focused
        errors = []
        def write():
            try: writer.write('abc', target, threading.Event())
            except TextWriteError as error: errors.append(error)
        worker = threading.Thread(target=write)
        closer = threading.Thread(target=writer.close)
        try:
            worker.start(); self.assertTrue(entered.wait(2))
            closer.start(); self.assertTrue(writer.closed.wait(2))
            release.set(); worker.join(2); closer.join(2)
            self.assertEqual(backend.sent, [])
            self.assertEqual(len(errors), 1)
            self.assertFalse(writer.thread.is_alive())
        finally:
            release.set(); writer.close(); worker.join(2); closer.join(2)

    def test_automation_is_initialized_once_and_released_on_owner(self):
        import sys
        automation = object()
        com = SimpleNamespace(CoInitialize=MagicMock(), CoUninitialize=MagicMock())
        client = SimpleNamespace(GetModule=MagicMock(return_value=SimpleNamespace(IUIAutomation=object())),
                                 CreateObject=MagicMock(return_value=automation))
        backend = WindowsTextBackend.__new__(WindowsTextBackend)
        backend.comtypes = backend.uia = backend.automation = None
        with patch.dict(sys.modules, {'comtypes': com, 'comtypes.client': client}):
            backend._ensure_automation(); backend._ensure_automation()
            self.assertIs(backend.automation, automation)
            self.assertEqual(client.CreateObject.call_count, 1)
            self.assertEqual(com.CoInitialize.call_count, 1)
            backend.close(); backend.close()
            com.CoUninitialize.assert_called_once()


if __name__ == '__main__': unittest.main()

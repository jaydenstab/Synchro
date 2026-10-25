from io import BytesIO
import queue
import socket
import struct
import threading
import time
import unittest
from unittest.mock import patch
from PIL import Image
import bluetooth_viewer
from bluetooth_viewer import (Camera, ReceivedJPEG, FrameDecoder, ProtocolError, Reader,
                              CAPTURE_SKIP_LIMIT, CONNECT_TIMEOUT_SECONDS, FRAME_STALL_SECONDS,
                              configure_link, decode_jpeg, format_latency, put_latest,
                              receive_frames, reconnect_delay, replace_preview, schedule_reconnect,
                              FrameRate)


class FragmentedSocket:
    def __init__(self, data, chunk=7):
        self.data, self.chunk, self.sent = bytearray(data), chunk, []

    def recv(self, size):
        length = min(size, self.chunk, len(self.data))
        result = bytes(self.data[:length])
        del self.data[:length]
        return result

    def sendall(self, data):
        self.sent.append(data)


class BluetoothProtocolTests(unittest.TestCase):
    def packet(self, tail=b'\nJPEG_END\n', size=(320, 240), header_size=None):
        output = BytesIO()
        Image.new('RGB', size, '#42785e').save(output, format='JPEG')
        jpeg = output.getvalue()
        width, height = header_size or size
        return f'JPEG_BEGIN {len(jpeg)} {width} {height}\n'.encode() + jpeg + tail

    def camera(self, packet, chunk=7):
        camera = Camera('00:00:00:00:00:00', 1)
        camera.connection = FragmentedSocket(packet, chunk)
        camera.reader = Reader(camera.connection)
        return camera

    def test_fragmented_frame(self):
        for size in ((320, 240), (640, 480)):
            with self.subTest(size=size):
                camera = self.camera(self.packet(size=size), 1)
                frame = camera.capture()
                self.assertEqual(frame.image.size, size)
                self.assertEqual(camera.connection.sent, [b'CAPTURE\n'])

    def test_coalesced_frames(self):
        camera = self.camera(self.packet() + self.packet(), 8192)
        self.assertEqual(camera.capture().jpeg, camera.capture().jpeg)

    def test_disconnect_mid_frame(self):
        with self.assertRaises(ConnectionError):
            self.camera(self.packet()[:-20]).capture()

    def test_bad_trailer(self):
        with self.assertRaises(ProtocolError):
            self.camera(self.packet(b'\nWRONGEND\n')).capture()

    def test_unbounded_header(self):
        with self.assertRaises(ProtocolError):
            Reader(FragmentedSocket(b'x' * 600)).line()

    def test_invalid_frame_size(self):
        for header in (b'JPEG_BEGIN 999999999 320 240\n', b'JPEG_BEGIN 100 8192 8192\n'):
            with self.subTest(header=header), self.assertRaises(ProtocolError):
                self.camera(header).capture()

    def test_mismatched_jpeg_dimensions(self):
        with self.assertRaises(ProtocolError):
            self.camera(self.packet(size=(320, 240), header_size=(640, 480))).capture()

    def test_receive_returns_jpeg_without_decoding(self):
        camera = self.camera(self.packet())
        with patch('bluetooth_viewer.Image.open', side_effect=AssertionError('receive decoded a JPEG')):
            frame = camera.receive_jpeg()
        self.assertEqual((frame.width, frame.height), (320, 240))
        self.assertTrue(frame.jpeg.startswith(b'\xff\xd8'))
        frame = decode_jpeg(frame)
        self.assertEqual(frame.image.size, (320, 240))

    def jpeg(self, color):
        output = BytesIO()
        Image.new('RGB', (32, 16), color).save(output, format='JPEG')
        return output.getvalue()

    def test_decoder_keeps_the_newest_frame_and_does_not_block_submit(self):
        output = queue.Queue(maxsize=1)
        first = ReceivedJPEG(self.jpeg('#204080'), 32, 16, 0.0, 0.0)
        second = ReceivedJPEG(self.jpeg('#80a040'), 32, 16, 0.0, 0.0)
        started, release = threading.Event(), threading.Event()
        from bluetooth_viewer import decode_jpeg as real_decode

        def slow(frame):
            if frame is first:
                started.set()
                if not release.wait(2):
                    raise RuntimeError('decoder test timed out')
            return real_decode(frame)

        decoder = FrameDecoder(lambda frame: put_latest(output, frame), lambda: None,
                               decode=lambda packet: bluetooth_viewer.decode_jpeg(packet))
        try:
            with patch('bluetooth_viewer.decode_jpeg', side_effect=slow):
                decoder.submit(first)
                self.assertTrue(started.wait(2))
                began = time.perf_counter()
                decoder.submit(second)
                self.assertLess(time.perf_counter() - began, 0.1)
                release.set()
                deadline = time.monotonic() + 2
                ready = output.get(timeout=2)
                while ready.jpeg != second.jpeg and time.monotonic() < deadline:
                    ready = output.get(timeout=2)
            self.assertEqual(ready.jpeg, second.jpeg)
            self.assertEqual(ready.image.size, (32, 16))
            self.assertTrue(output.empty())
        finally:
            release.set()
            decoder.close()

    def test_capture_error_keeps_the_following_frame_on_the_same_socket(self):
        camera = self.camera(b'CAPTURE_ERROR\n' + self.packet(), 3)
        self.assertIsNone(camera.receive_jpeg())
        frame = camera.receive_jpeg()
        self.assertEqual((frame.width, frame.height), (320, 240))
        self.assertEqual(camera.connection.sent, [b'CAPTURE\n', b'CAPTURE\n'])

    def test_repeated_capture_errors_stop_before_the_stream_can_spin(self):
        calls = []

        class Source:
            def receive_jpeg(self):
                calls.append(1)
                return None

        class Decoder:
            def wait_for_slot(self, stop):
                return not stop.is_set()

            def submit(self, packet):
                raise AssertionError('a capture error was decoded')

        with self.assertRaises(ProtocolError) as error:
            receive_frames(Source(), Decoder(), FrameRate(30), threading.Event())
        self.assertIn('repeated captures', str(error.exception))
        self.assertEqual(len(calls), CAPTURE_SKIP_LIMIT)

    def test_one_capture_error_still_accepts_the_next_frame(self):
        calls = []
        seen = []
        stop = threading.Event()

        class Source:
            def receive_jpeg(self):
                calls.append(1)
                return None if len(calls) == 1 else 'frame'

        class Decoder:
            def wait_for_slot(self, stop_event):
                return not stop_event.is_set()

            def submit(self, packet):
                seen.append(packet)
                stop.set()

        receive_frames(Source(), Decoder(), FrameRate(30), stop)
        self.assertEqual(seen, ['frame'])
        self.assertEqual(len(calls), 2)

    def test_closed_decoder_does_not_request_another_frame(self):
        class Source:
            def receive_jpeg(self):
                raise AssertionError('requested a frame after decode failed')

        class Decoder:
            def wait_for_slot(self, stop):
                return False

        with self.assertRaises(ProtocolError) as error:
            receive_frames(Source(), Decoder(), FrameRate(15), threading.Event())
        self.assertIn('decode failed', str(error.exception))

    def test_reconnect_backs_off_and_a_live_session_retries_after_linger(self):
        self.assertEqual(reconnect_delay(False, 0), 2)
        self.assertEqual(reconnect_delay(False, 1), 4)
        self.assertEqual(reconnect_delay(False, 5), 8)
        self.assertEqual([reconnect_delay(True, attempt) for attempt in range(4)], [1, 2, 4, 8])
        self.assertEqual(schedule_reconnect(True, 3), (1, 0))
        self.assertEqual(schedule_reconnect(False, 0), (2, 1))
        self.assertEqual(schedule_reconnect(False, 1), (4, 2))

    def test_latency_readout_adds_preview_time_without_dropping_transfer(self):
        self.assertEqual(format_latency(None), '—')
        self.assertEqual(format_latency(0.042, 18000), '42 ms · 18 kB')
        self.assertEqual(format_latency(0.042, 18000, 0.07), '42 ms · 18 kB\nshow 70 ms')
        self.assertEqual(format_latency(0.042, None, 0), '42 ms\nshow 0 ms')

    def test_same_size_preview_reuses_the_tk_image(self):
        class Photo:
            def __init__(self, size):
                self.size, self.pasted = size, None

            def width(self):
                return self.size[0]

            def height(self):
                return self.size[1]

            def paste(self, image):
                self.pasted = image

        image = type('Image', (), {'width': 4, 'height': 2})()
        current = Photo((4, 2))
        created = []
        self.assertIs(replace_preview(current, image, created.append), current)
        self.assertIs(current.pasted, image)
        self.assertEqual(created, [])
        larger = type('Image', (), {'width': 8, 'height': 2})()
        made = replace_preview(current, larger, lambda item: Photo((item.width, item.height)))
        self.assertEqual(made.size, (8, 2))
        self.assertIsNone(made.pasted)

    def test_connect_limits_silence_after_the_handshake(self):
        payload = b'{"firmware":"bluetooth-2","camera_ready":true}\n'
        sock = unittest.mock.MagicMock()
        sock.recv.return_value = payload
        with patch('bluetooth_viewer.socket.AF_BLUETOOTH', 31, create=True), \
             patch('bluetooth_viewer.socket.BTPROTO_RFCOMM', 3, create=True), \
             patch('bluetooth_viewer.socket.socket', return_value=sock):
            camera = Camera('00:00:00:00:00:00', 1)
            status = camera.connect()
            self.assertTrue(status['camera_ready'])
            self.assertEqual([item.args[0] for item in sock.settimeout.call_args_list],
                             [CONNECT_TIMEOUT_SECONDS, FRAME_STALL_SECONDS])
            sock.recv.side_effect = TimeoutError('stall')
            with self.assertRaises(TimeoutError):
                camera.receive_jpeg()

    def test_link_options_keep_a_receive_buffer_and_request_a_short_close(self):
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            configure_link(connection)
            self.assertGreaterEqual(connection.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF), 256 * 1024)
            linger = struct.unpack('ii', connection.getsockopt(socket.SOL_SOCKET, socket.SO_LINGER, 8))
        finally:
            connection.close()
        self.assertEqual(linger, (1, 1))

    def test_decoder_close_discards_the_frame_being_decoded(self):
        output = queue.Queue(maxsize=1)
        frame = ReceivedJPEG(self.jpeg('#204080'), 32, 16, 0.0, 0.0)
        started, release = threading.Event(), threading.Event()

        def slow(ignored):
            started.set()
            release.wait(2)

        decoder = FrameDecoder(lambda frame: put_latest(output, frame), lambda: None,
                               decode=lambda packet: bluetooth_viewer.decode_jpeg(packet))
        try:
            with patch('bluetooth_viewer.decode_jpeg', side_effect=slow):
                decoder.submit(frame)
                self.assertTrue(started.wait(2))
                decoder.close()
                release.set()
                deadline = time.monotonic() + 0.5
                while time.monotonic() < deadline:
                    self.assertTrue(output.empty())
                    time.sleep(.01)
        finally:
            release.set()
            decoder.close()


if __name__ == '__main__':
    unittest.main()

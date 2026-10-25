from io import BytesIO
import unittest
from PIL import Image
from bluetooth_viewer import Camera, ProtocolError, Reader


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


if __name__ == '__main__':
    unittest.main()

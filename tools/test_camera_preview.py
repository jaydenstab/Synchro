"""Preview concurrency and pixel integrity; synthetic images, no radio or Tk."""
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

from camera_preview import PreviewRenderer, prepare_image


class PreviewTests(unittest.TestCase):
    def frame(self, color='red'):
        return SimpleNamespace(image=Image.new('RGB', (8, 4), color), jpeg=b'original-jpeg')

    def wait_result(self, renderer, expected):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            result = renderer.poll()
            if result is not None:
                self.assertIs(result.frame, expected)
                return result
            time.sleep(.001)
        self.fail('Preview worker did not return a result')

    def test_rotation_and_fit_preserve_source_pixels_and_jpeg(self):
        frame = self.frame()
        frame.image.putpixel((0, 0), (0, 0, 255))
        source = frame.image.tobytes()
        picture = prepare_image(frame.image, 16, 8, True)
        self.assertEqual(picture.size, (16, 8))
        self.assertEqual(picture.getpixel((15, 7)), (0, 0, 255))
        self.assertEqual(frame.image.tobytes(), source)
        self.assertEqual(frame.jpeg, b'original-jpeg')
        self.assertIs(prepare_image(frame.image, 8, 4, False), frame.image)
        self.assertEqual(prepare_image(frame.image, 4, 4, False).size, (4, 2))

    def test_worker_coalesces_pending_frames_and_never_runs_on_caller(self):
        renderer = PreviewRenderer()
        started, release = threading.Event(), threading.Event()
        frames = [self.frame() for _ in range(20)]
        calls, threads = [], []
        main_thread = threading.get_ident()
        def prepare(image, *view):
            calls.append(image)
            threads.append(threading.get_ident())
            if image is frames[0].image:
                started.set()
                if not release.wait(2):
                    raise RuntimeError('test worker timed out')
            return prepare_image(image, *view)
        try:
            with patch('camera_preview.prepare_image', side_effect=prepare):
                renderer.configure(80, 40, False)
                renderer.submit(frames[0])
                self.assertTrue(started.wait(2))
                for frame in frames[1:]:
                    renderer.submit(frame)
                # Ignore the legitimately completed first image; await the final pending one.
                release.set()
                deadline = time.monotonic() + 2
                result = None
                while time.monotonic() < deadline:
                    current = renderer.poll()
                    if current is not None and current.frame is frames[-1]:
                        result = current
                        break
                    time.sleep(.001)
                self.assertIsNotNone(result)
                self.assertEqual([id(image) for image in calls], [id(frames[0].image), id(frames[-1].image)])
                self.assertTrue(all(t != main_thread for t in threads))
        finally:
            release.set()
            renderer.close()

    def test_disconnect_discards_work_in_progress_and_accepts_new_session(self):
        renderer = PreviewRenderer()
        started, release = threading.Event(), threading.Event()
        old, new = self.frame('red'), self.frame('blue')
        def prepare(image, *view):
            if image is old.image:
                started.set()
                release.wait(2)
            return prepare_image(image, *view)
        try:
            with patch('camera_preview.prepare_image', side_effect=prepare):
                renderer.submit(old)
                self.assertTrue(started.wait(2))
                renderer.clear()
                renderer.configure(40, 20, True)
                renderer.submit(new)
                release.set()
                result = self.wait_result(renderer, new)
                self.assertEqual(result.image.size, (40, 20))
                self.assertEqual(result.image.getpixel((0, 0)), (0, 0, 255))
        finally:
            release.set()
            renderer.close()

    def test_resize_invalidates_old_work_without_another_camera_frame(self):
        renderer = PreviewRenderer()
        started, release = threading.Event(), threading.Event()
        frame = self.frame()
        def prepare(image, *view):
            if view[:2] == (80, 40):
                started.set()
                release.wait(2)
            return prepare_image(image, *view)
        try:
            with patch('camera_preview.prepare_image', side_effect=prepare):
                renderer.configure(80, 40, False)
                renderer.submit(frame)
                self.assertTrue(started.wait(2))
                renderer.configure(16, 8, True)
                release.set()
                self.assertEqual(self.wait_result(renderer, frame).image.size, (16, 8))
        finally:
            release.set()
            renderer.close()

    def test_preparation_failure_is_visible_and_worker_can_recover(self):
        renderer = PreviewRenderer()
        try:
            with patch('camera_preview.prepare_image', side_effect=ValueError('bad frame')):
                bad = self.frame()
                renderer.submit(bad)
                result = self.wait_result(renderer, bad)
                self.assertIsNone(result.image)
                self.assertIn('Could not prepare', result.error)
            good = self.frame()
            renderer.submit(good)
            self.assertIsNotNone(self.wait_result(renderer, good).image)
        finally:
            renderer.close()
        self.assertFalse(renderer._thread.is_alive())
        renderer.submit(self.frame())
        self.assertIsNone(renderer.poll())

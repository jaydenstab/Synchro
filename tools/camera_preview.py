"""Bounded latest-frame preparation. No Tk, camera I/O, or JPEG re-encoding."""
from dataclasses import dataclass
import threading
from PIL import Image


@dataclass
class PreparedPreview:
    frame: object
    image: Image.Image | None
    error: str | None = None


def prepare_image(image, width, height, rotated):
    """Fit a display copy without changing the original image or its JPEG bytes."""
    if rotated:
        image = image.transpose(Image.Transpose.ROTATE_180)
    scale = min(max(1, width) / image.width, max(1, height) / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image if image.size == size else image.resize(size, Image.Resampling.BILINEAR)


class PreviewRenderer:
    """One busy frame, one replaceable pending frame, one replaceable result.

    Configure, submit, clear and poll are called from the UI thread. Pillow work
    runs on a lazy worker; only the UI may turn its result into a Tk PhotoImage.
    An epoch prevents old work reappearing after stop, reconnect, or view changes.
    """
    def __init__(self):
        self._condition = threading.Condition()
        self._view = (1, 1, False)
        self._frame = None
        self._pending = None
        self._result = None
        self._epoch = 0
        self._closed = False
        self._thread = None

    def _wake_locked(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='synchro-preview', daemon=True)
            self._thread.start()
        self._condition.notify()

    def configure(self, width, height, rotated):
        view = (max(1, width), max(1, height), bool(rotated))
        with self._condition:
            if self._closed or view == self._view:
                return
            self._view = view
            self._epoch += 1
            self._result = None
            self._pending = self._frame
            if self._pending is not None:
                self._wake_locked()

    def submit(self, frame):
        with self._condition:
            if self._closed:
                return
            self._frame = self._pending = frame
            self._wake_locked()

    def poll(self):
        with self._condition:
            result, self._result = self._result, None
            return result

    def clear(self):
        with self._condition:
            self._epoch += 1
            self._frame = self._pending = self._result = None

    def close(self):
        with self._condition:
            self._closed = True
            self._epoch += 1
            self._frame = self._pending = self._result = None
            self._condition.notify()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                frame, self._pending = self._pending, None
                epoch, view = self._epoch, self._view
            try:
                result = PreparedPreview(frame, prepare_image(frame.image, *view))
            except Exception:
                result = PreparedPreview(frame, None, 'Could not prepare the camera preview.')
            with self._condition:
                if not self._closed and epoch == self._epoch:
                    self._result = result

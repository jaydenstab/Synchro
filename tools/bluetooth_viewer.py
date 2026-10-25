"""Direct Bluetooth Classic camera viewer. No Wi-Fi or USB image fallback."""
import argparse
from collections import deque
from dataclasses import dataclass
from io import BytesIO
import json
import math
from pathlib import Path
import queue
import re
import socket
import struct
import sys
import threading
import time

from PIL import Image

from camera_preview import PreviewRenderer

CAMERA_REFRESH_MS = 10
CONTROL_REFRESH_MS = 30
CAMERA_RETRY_SECONDS = 2
CAMERA_RECOVER_SECONDS = 8
CAMERA_LINGER_SECONDS = 1
CONNECT_TIMEOUT_SECONDS = 12
FRAME_STALL_SECONDS = 2
CAPTURE_SKIP_LIMIT = 5

PROJECT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT / '.local' / 'bluetooth-camera.json'
SUPPORTED_FRAME_SIZES = {(320, 240), (640, 480)}


class ProtocolError(Exception):
    pass


class Reader:
    def __init__(self, connection):
        self.connection = connection
        self.buffer = bytearray()

    def receive(self):
        block = self.connection.recv(8192)
        if not block:
            raise ConnectionError('Camera disconnected')
        self.buffer.extend(block)

    def line(self):
        while True:
            end = self.buffer.find(b'\n')
            if end >= 0:
                if end > 512:
                    raise ProtocolError('Oversized response header')
                result = bytes(self.buffer[:end]).rstrip(b'\r')
                del self.buffer[:end + 1]
                return result
            if len(self.buffer) > 512:
                raise ProtocolError('Missing response header')
            self.receive()

    def exact(self, length):
        while len(self.buffer) < length:
            self.receive()
        result = bytes(self.buffer[:length])
        del self.buffer[:length]
        return result


@dataclass
class Frame:
    jpeg: bytes
    image: Image.Image
    seconds: float
    received_at: float
    transfer_seconds: float = 0.0
    decode_seconds: float = 0.0


@dataclass(frozen=True)
class ReceivedJPEG:
    jpeg: bytes
    width: int
    height: int
    began_at: float
    received_at: float


def decode_jpeg(packet):
    began = time.perf_counter()
    with Image.open(BytesIO(packet.jpeg)) as decoded:
        if decoded.size != (packet.width, packet.height):
            raise ProtocolError('JPEG dimensions do not match its header')
        decoded.load()
        picture = decoded.convert('RGB')
    now = time.perf_counter()
    return Frame(packet.jpeg, picture, now - packet.began_at, packet.received_at,
                 packet.received_at - packet.began_at, now - began)


class FrameDecoder:
    """One busy decode and one replaceable pending JPEG, scoped to a connection.

    A capture may transfer while this decode runs. The receiver waits when that
    pending slot is already full, instead of downloading a frame that would be
    replaced before it is shown.
    """
    def __init__(self, publish, failed, decode=decode_jpeg):
        self.condition = threading.Condition()
        self.pending = None
        self.closed = False
        self.publish, self.failed, self.decode = publish, failed, decode
        self.thread = threading.Thread(target=self._run, name='synchro-decode', daemon=True)
        self.thread.start()

    def submit(self, packet):
        with self.condition:
            if not self.closed:
                self.pending = packet
                self.condition.notify_all()

    def wait_for_slot(self, stop_event):
        """Return once the pending slot is empty. Stop and close unblock the wait."""
        with self.condition:
            while self.pending is not None and not self.closed and not stop_event.is_set():
                self.condition.wait(timeout=0.05)
            return not self.closed and not stop_event.is_set()

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify_all()
        self.thread.join(timeout=1)

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending is not None)
                if self.closed:
                    return
                packet, self.pending = self.pending, None
                self.condition.notify_all()
            try:
                frame = self.decode(packet)
            except Exception:
                with self.condition:
                    if not self.closed:
                        self.closed = True
                        self.pending = None
                        self.condition.notify_all()
                        self.failed()
                return
            with self.condition:
                if not self.closed:
                    self.publish(frame)


class FrameRate:
    """UI writes, receiver reads; never access Tk variables from a worker."""
    def __init__(self, value=15):
        self.lock = threading.Lock()
        self.set(value)

    def set(self, value):
        value = float(value)
        if not math.isfinite(value) or not 0 < value <= 30:
            raise ValueError('FPS cap must be greater than 0 and at most 30.')
        with self.lock:
            self.value = value

    def get(self):
        with self.lock:
            return self.value


def reconnect_delay(opened, attempt=0):
    """Backoff after a dropped camera session. The camera accepts one client."""
    attempt = max(0, attempt)
    if opened:
        # 1s matches SO_LINGER. Later steps cover a radio that is still releasing.
        schedule = (CAMERA_LINGER_SECONDS, CAMERA_RETRY_SECONDS, 4, CAMERA_RECOVER_SECONDS)
    else:
        schedule = (CAMERA_RETRY_SECONDS, 4, CAMERA_RECOVER_SECONDS)
    return schedule[min(attempt, len(schedule) - 1)]


def schedule_reconnect(opened, attempt):
    """Wait, then the attempt count for the following failure.

    A session that connected retries after linger. The next refused connect
    starts the cold schedule over, so a live drop is not punished by earlier
    power-off retries and a powered-off camera does not retry every second.
    """
    if opened:
        return reconnect_delay(True, 0), 0
    return reconnect_delay(False, attempt), attempt + 1


def configure_link(connection):
    try:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
    except OSError:
        pass
    try:
        # Finish the RFCOMM close so the camera can accept the next session.
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                           struct.pack('ii', 1, CAMERA_LINGER_SECONDS))
    except OSError:
        pass


def put_latest(destination, value):
    try:
        destination.put_nowait(value)
    except queue.Full:
        try:
            destination.get_nowait()
        except queue.Empty:
            pass
        destination.put_nowait(value)


def format_latency(seconds, jpeg_bytes=None, display_seconds=None):
    """Request-to-decode, then receipt-to-preview when that update has happened."""
    if seconds is None:
        return '—'
    text = f'{seconds * 1000:.0f} ms'
    if jpeg_bytes:
        text += f' · {max(1, round(jpeg_bytes / 1000))} kB'
    if display_seconds is not None:
        text += f'\nshow {max(0, display_seconds) * 1000:.0f} ms'
    return text


def replace_preview(existing, image, create):
    """Keep one Tk image while the preview size is unchanged."""
    if (existing is not None and existing.width() == image.width
            and existing.height() == image.height):
        existing.paste(image)
        return existing
    return create(image)


def receive_frames(camera, decoder, rate_limit, stop_event):
    """One transfer may overlap the decode in progress. A full pending slot waits.

    CAPTURE_ERROR keeps this socket. Five in a row, a broken frame, or a recv
    that goes silent close the session so the byte stream cannot drift.
    """
    skips = 0
    while not stop_event.is_set():
        if not decoder.wait_for_slot(stop_event):
            if stop_event.is_set():
                break
            raise ProtocolError('JPEG decode failed')
        began = time.perf_counter()
        packet = camera.receive_jpeg()
        if stop_event.is_set():
            break
        if packet is None:
            skips += 1
            if skips >= CAPTURE_SKIP_LIMIT:
                raise ProtocolError('Camera failed repeated captures')
            stop_event.wait(min(0.2, 1 / rate_limit.get()))
            continue
        skips = 0
        decoder.submit(packet)
        stop_event.wait(max(0, 1 / rate_limit.get() - (time.perf_counter() - began)))


class Camera:
    def __init__(self, address, channel):
        self.address, self.channel = address, channel
        self.connection = None
        self.reader = None

    def connect(self):
        self.connection = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        configure_link(self.connection)
        self.connection.settimeout(CONNECT_TIMEOUT_SECONDS)
        self.connection.connect((self.address, self.channel))
        # Each silent gap is limited. Bytes that keep arriving extend the frame.
        self.connection.settimeout(FRAME_STALL_SECONDS)
        self.reader = Reader(self.connection)
        self.connection.sendall(b'STATUS\n')
        status = json.loads(self.reader.line())
        if status.get('firmware') not in ('bluetooth-1', 'bluetooth-2') or not status.get('camera_ready'):
            raise ProtocolError('The Bluetooth camera firmware is not ready')
        return status

    def receive_jpeg(self):
        began = time.perf_counter()
        self.connection.sendall(b'CAPTURE\n')
        header = self.reader.line()
        if header == b'CAPTURE_ERROR':
            # The firmware stays on this client and the next command is in sync.
            return None
        match = re.fullmatch(rb'JPEG_BEGIN (\d+) (\d+) (\d+)', header)
        if not match:
            raise ProtocolError('Camera did not return a photo: ' + repr(header))
        length, width, height = map(int, match.groups())
        if not 4 <= length <= 1_000_000 or (width, height) not in SUPPORTED_FRAME_SIZES:
            raise ProtocolError('Invalid frame size')
        jpeg = self.reader.exact(length)
        if self.reader.exact(10) != b'\nJPEG_END\n':
            raise ProtocolError('Incomplete frame trailer')
        if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            raise ProtocolError('Invalid JPEG markers')
        return ReceivedJPEG(jpeg, width, height, began, time.perf_counter())

    def capture(self):
        # Synchronous compatibility path for the protocol probe.
        packet = self.receive_jpeg()
        if packet is None:
            raise ProtocolError('Camera did not return a photo: CAPTURE_ERROR')
        return decode_jpeg(packet)

    def close(self):
        connection, self.connection = self.connection, None
        if connection:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()


def probe(address, channel, count, output):
    output.mkdir(parents=True, exist_ok=True)
    camera = Camera(address, channel)
    try:
        status = camera.connect()
        print(json.dumps({'bluetooth_connected': True, 'status': status}), flush=True)
        durations, sizes = [], []
        began = time.perf_counter()
        for index in range(count):
            frame = camera.capture()
            durations.append(frame.seconds)
            sizes.append(len(frame.jpeg))
            if index in (0, count - 1):
                (output / f'frame-{index + 1}.jpg').write_bytes(frame.jpeg)
            print(f'BT_FRAME {index + 1}/{count} size={frame.image.width}x{frame.image.height} bytes={len(frame.jpeg)} ms={frame.seconds * 1000:.0f}', flush=True)
        elapsed = time.perf_counter() - began
        report = {'transport': 'bluetooth_classic_rfcomm', 'address': address, 'channel': channel,
                  'frames': count, 'seconds': elapsed, 'fps': count / elapsed, 'frame_size': list(frame.image.size),
                  'frame_seconds': durations, 'jpeg_bytes': sizes, 'status': status}
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'PASS: {count} decoded Bluetooth frames at {count / elapsed:.2f} fps. No Wi-Fi or USB image transport.', flush=True)
    finally:
        camera.close()


def launch_viewer(address, channel, fps, rotation=180, mpu_port=None, motion_transport='auto', mpu_ble_address=None, listen=False, pause_pointer=False, preview=False):
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageTk
    from motion_panel import MotionPanel
    from speech_panel import SpeechPanel
    from jarvis_assistant import CameraSnapshot, JarvisAssistant

    from desktop_theme import (BG, PANEL, INSET, TEXT, MUTED, MINT, WARN, FONT,
                             BANNER, BANNER_TEXT, install_theme, wrap_labels)

    root = tk.Tk()
    root.title('Synchro · Windows UI preview' if preview else 'Synchro')
    root.geometry(f'{min(1280, root.winfo_screenwidth() - 60)}x{min(900, root.winfo_screenheight() - 80)}')
    root.minsize(980, 720)
    install_theme(root)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)
    header = tk.Frame(root, bg=BG, padx=24, pady=18)
    header.grid(row=0, column=0, sticky='ew')
    tk.Label(header, text='Synchro', fg=TEXT, bg=BG, font=(FONT, 22, 'bold')).pack(side='left')
    tk.Label(header, text='Camera, glove, and speech', fg=MUTED, bg=BG).pack(side='left', padx=18)
    connection_text = tk.StringVar(value='●  Connecting')
    connection_label = tk.Label(header, textvariable=connection_text, fg=WARN, bg=BG)
    connection_label.pack(side='right')
    mic_label = tk.Label(header, text='Mic off', fg=MUTED, bg=BG)
    mic_label.pack(side='right', padx=18)
    if preview:
        tk.Label(root, text='PREVIEW MODE   Hardware, microphone and Jarvis actions are disabled on this computer.',
                 bg=BANNER, fg=BANNER_TEXT, font=(FONT, 10), anchor='w', padx=14, pady=9
                 ).grid(row=1, column=0, sticky='ew', padx=24, pady=(0, 12))
    panes = ttk.Panedwindow(root, orient='horizontal')
    panes.grid(row=2, column=0, sticky='nsew', padx=24, pady=(0, 18))
    camera_panel = tk.Frame(panes, bg=PANEL, padx=18, pady=16)
    camera_panel.columnconfigure(0, weight=1)
    camera_panel.rowconfigure(2, weight=1)
    panes.add(camera_panel, weight=3)
    inspector = ttk.Notebook(panes, width=490)
    panes.add(inspector, weight=2)
    tk.Label(camera_panel, text='Camera', fg=TEXT, bg=PANEL,
             font=(FONT, 17, 'bold'), anchor='w').grid(row=0, column=0, sticky='ew')
    tk.Label(camera_panel, text=f'Synchro-Cam-BT · {address}' if address != 'Not configured' else 'Bluetooth camera', fg=MUTED, bg=PANEL,
             anchor='w').grid(row=1, column=0, sticky='ew', pady=(4, 14))
    image_label = tk.Label(camera_panel, width=1, height=1, bg=INSET, fg=MUTED,
                          text='Waiting for camera\n\nPower on Synchro-Cam-BT and pair it in Windows settings.',
                          font=(FONT, 12), wraplength=360)
    image_label.grid(row=2, column=0, sticky='nsew')
    status_text = tk.StringVar(value='Connecting over Bluetooth…')
    camera_status = tk.Label(camera_panel, textvariable=status_text, fg=MUTED, bg=PANEL,
                             anchor='w', justify='left', wraplength=360)
    camera_status.grid(row=3, column=0, sticky='ew', pady=(12, 8))
    buttons = tk.Frame(camera_panel, bg=PANEL)
    buttons.grid(row=4, column=0, sticky='ew')
    metrics = tk.Frame(camera_panel, bg=PANEL)
    metrics.grid(row=6, column=0, sticky='ew', pady=(12, 0))
    metric_values = [tk.StringVar(value='—') for _ in range(3)]
    for index, caption in enumerate(('DECODED FPS', 'REQUEST → DECODE', 'RESOLUTION')):
        metrics.columnconfigure(index, weight=1, uniform='metric')
        cell = tk.Frame(metrics, bg=INSET, padx=9, pady=9)
        cell.grid(row=0, column=index, sticky='ew', padx=(0 if index == 0 else 5, 0))
        tk.Label(cell, text=caption, font=(FONT, 8), fg=MUTED, bg=INSET, anchor='w').pack(fill='x')
        tk.Label(cell, textvariable=metric_values[index], font=(FONT, 11, 'bold'),
                 fg=TEXT, bg=INSET, anchor='w', justify='left').pack(fill='x', pady=(4, 0))

    readout = {'rate': None, 'seconds': None, 'width': None, 'height': None,
               'jpeg_bytes': None, 'display_seconds': None}

    def set_camera_metrics(rate=None, seconds=None, width=None, height=None, jpeg_bytes=None,
                           display_seconds=None, *, display_only=False):
        if display_only:
            readout['display_seconds'] = display_seconds
        elif rate is None and seconds is None and width is None:
            readout.update(rate=None, seconds=None, width=None, height=None,
                           jpeg_bytes=None, display_seconds=None)
        else:
            readout.update(rate=rate, seconds=seconds, width=width, height=height,
                           jpeg_bytes=jpeg_bytes, display_seconds=display_seconds)
        metric_values[0].set(f"{readout['rate']:.1f} fps" if readout['rate'] else '—')
        metric_values[1].set(format_latency(readout['seconds'], readout['jpeg_bytes'],
                                            readout['display_seconds']))
        metric_values[2].set(f"{readout['width']} × {readout['height']}" if readout['width'] is not None else '—')

    tk.Label(camera_panel, text='Bluetooth Classic · Local device connection', fg=MUTED, bg=PANEL,
             anchor='w').grid(row=7, column=0, sticky='ew', pady=(6, 0))
    photo_note = tk.StringVar(value='')
    photo_status = tk.Label(camera_panel, textvariable=photo_note, fg=MUTED, bg=PANEL, anchor='w',
                            justify='left', wraplength=360)
    photo_status.grid(row=8, column=0, sticky='ew', pady=(6, 0))
    wrap_labels(camera_panel, camera_status, photo_status, image_label)
    frames = queue.Queue(maxsize=1)
    events = queue.Queue()
    state = {'thread': None, 'stop': None, 'camera': None, 'frame': None, 'photo': None, 'closing': False, 'session': 0}
    timings = deque()
    rate_limit = FrameRate(fps)
    rotated = tk.BooleanVar(value=rotation == 180)
    camera_snapshot = CameraSnapshot()
    assistant = JarvisAssistant(camera_snapshot)
    renderer = PreviewRenderer()

    def oriented_picture():
        picture = state['frame'].image
        return picture.transpose(Image.Transpose.ROTATE_180) if rotated.get() else picture

    def render_picture():
        # Read Tk geometry on main; prepare display pixels on the worker.
        renderer.configure(max(1, image_label.winfo_width() - 4),
                           max(1, image_label.winfo_height() - 4), rotated.get())

    root.after_idle(lambda: panes.sashpos(0, max(400, root.winfo_width() - 560)))

    radio_hold = threading.Event()
    motion = MotionPanel(inspector, mpu_port, motion_transport, mpu_ble_address,
                         connect=not preview, radio_hold=radio_hold)
    if pause_pointer:
        motion.pointer.disable('Pointer paused for voice testing. Enable to resume.')
    inspector.add(motion.frame, text='Glove')
    speech = SpeechPanel(inspector, listen=listen, assistant=assistant, preview=preview)
    motion.sensor.speech = speech.controller
    motion.sensor.assistant = None if preview else assistant
    inspector.add(speech.frame, text='Speech & Jarvis')
    def change_rotation():
        camera_snapshot.set_rotation(rotated.get())
        render_picture()

    # Both destinations stay visible. Voice-test launches select Speech without hiding Glove.
    if pause_pointer:
        inspector.select(speech.frame)
    camera_options = tk.Frame(camera_panel, bg=PANEL)
    camera_options.grid(row=5, column=0, sticky='ew', pady=(10, 0))
    ttk.Checkbutton(camera_options, text='Rotate 180°', variable=rotated,
                    command=change_rotation).pack(side='left')
    tk.Label(camera_options, text='FPS cap', bg=PANEL, fg=MUTED).pack(side='left', padx=(16, 6))
    fps_value = tk.StringVar(value=f'{fps:g}')
    fps_choice = ttk.Combobox(camera_options, textvariable=fps_value, width=5,
                              values=tuple(dict.fromkeys((f'{fps:g}', '5', '10', '15', '20', '30'))),
                              state='readonly')
    fps_choice.pack(side='left')
    fps_choice.bind('<<ComboboxSelected>>', lambda event: rate_limit.set(fps_value.get()))
    image_label.bind('<Configure>', lambda event: render_picture())

    def worker(stop_event):
        attempt = 0
        while not stop_event.is_set():
            camera = Camera(address, channel)
            state['camera'] = camera
            state['session'] += 1
            session = state['session']
            decoder = FrameDecoder(lambda frame: put_latest(frames, (session, frame)), camera.close)
            opened = False
            try:
                camera.connect()
                opened = True
                radio_hold.set()
                events.put((session, 'Bluetooth connected. Receiving images...'))
                receive_frames(camera, decoder, rate_limit, stop_event)
            except (TimeoutError, OSError, ValueError, ProtocolError, AttributeError) as error:
                decoder.close()
                camera_snapshot.clear()
                if not stop_event.is_set():
                    print(f'Camera Bluetooth: {error}', file=sys.stderr, flush=True)
                    if not opened:
                        message = 'Camera unavailable. Check camera power; reconnecting...'
                    elif isinstance(error, TimeoutError):
                        message = 'Camera unavailable. Transfer stalled; reconnecting...'
                    elif isinstance(error, ProtocolError):
                        message = 'Camera unavailable. Capture failed; reconnecting...'
                    else:
                        message = 'Camera unavailable. Link dropped; reconnecting once the radio is free...'
                    events.put((session, message))
            finally:
                radio_hold.clear()
                decoder.close()
                camera.close()
                if state['camera'] is camera:
                    state['camera'] = None
            if stop_event.is_set():
                break
            delay, attempt = schedule_reconnect(opened, attempt)
            stop_event.wait(delay)

    def start():
        if preview:
            return
        if state['thread'] and state['thread'].is_alive():
            return
        while not events.empty():
            events.get_nowait()
        while not frames.empty():
            frames.get_nowait()
        timings.clear()
        renderer.clear()
        state['frame'] = None
        state['photo'] = None
        image_label.config(image='', text='Connecting to camera…')
        save_button.config(state='disabled')
        set_camera_metrics()
        connection_text.set('●  Connecting')
        connection_label.config(fg=WARN)
        state['stop'] = threading.Event()
        state['thread'] = threading.Thread(target=worker, args=(state['stop'],), daemon=True)
        state['thread'].start()
        start_button.config(state='disabled')
        stop_button.config(state='normal')
        status_text.set('Connecting over Bluetooth...')

    def stop():
        camera_snapshot.clear()
        if state['stop']:
            state['stop'].set()
        camera = state['camera']
        if camera:
            camera.close()
        renderer.clear()
        if state['frame'] is not None:
            renderer.submit(state['frame'])
        stop_button.config(state='disabled')
        status_text.set('Camera stopped. Glove and speech remain available.')
        connection_text.set('●  Stopped')
        connection_label.config(fg=MUTED)
        if state['frame'] is not None:
            status_text.set('Camera paused · Showing the last received frame.')

    def snapshot():
        if state['frame'] is None:
            return
        try:
            folder = PROJECT / '.local' / 'bluetooth-photos'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (time.strftime('%Y%m%d-%H%M%S') + f'-{time.time_ns() % 1_000_000_000:09d}.jpg')
            if rotated.get():
                oriented_picture().save(target, format='JPEG', quality=95)
            else:
                target.write_bytes(state['frame'].jpeg)
            photo_note.set('Saved to .local/bluetooth-photos/' + target.name)
        except OSError as error:
            photo_note.set(f'Could not save photo: {error}')

    start_button = ttk.Button(buttons, text='Start camera', command=start, style='Primary.TButton')
    start_button.pack(side='left', padx=5)
    stop_button = ttk.Button(buttons, text='Stop', command=stop, style='Danger.TButton')
    stop_button.pack(side='left', padx=5)
    save_button = ttk.Button(buttons, text='Save photo', command=snapshot, state='disabled')
    save_button.pack(side='left', padx=5)

    def update_camera():
        if state['closing']:
            return
        running = state['stop'] and not state['stop'].is_set()
        while not events.empty():
            session, text = events.get_nowait()
            if running and session == state['session']:
                status_text.set(text)
                connection_text.set('●  Reconnecting' if 'unavailable' in text else '●  Connected')
                connection_label.config(fg=WARN if 'unavailable' in text else MINT)
                if 'unavailable' in text:
                    renderer.clear()
                    state['frame'] = None
                    state['photo'] = None
                    image_label.config(image='', text='Camera unavailable\nCheck power and Windows Bluetooth pairing. Retrying…')
                    save_button.config(state='disabled')
                    while not frames.empty():
                        try:
                            frames.get_nowait()
                        except queue.Empty:
                            break
                    timings.clear()
                    set_camera_metrics()
        try:
            session, frame = frames.get_nowait()
        except queue.Empty:
            frame = None
        if frame and running and session == state['session']:
            state['frame'] = frame
            camera_snapshot.update(frame, rotated.get())
            width, height = frame.image.size
            renderer.submit(frame)
            timings.append(frame.received_at)
            while len(timings) > 2 and timings[0] < frame.received_at - 3:
                timings.popleft()
            rate = (len(timings) - 1) / (timings[-1] - timings[0]) if len(timings) > 1 else 0
            connection_text.set('●  Live')
            connection_label.config(fg=MINT)
            save_button.config(state='normal')
            set_camera_metrics(rate, frame.seconds, width, height, len(frame.jpeg))
            status_text.set('Live image from Synchro-Cam-BT.')
        if state['thread'] and not state['thread'].is_alive():
            start_button.config(state='normal')
            stop_button.config(state='disabled')
        prepared = renderer.poll()
        if prepared is not None and state['frame'] is not None:
            if prepared.error:
                status_text.set(prepared.error)
            else:
                # Tk object creation must remain on this thread. Same-size frames reuse it.
                state['photo'] = replace_preview(state['photo'], prepared.image, ImageTk.PhotoImage)
                image_label.config(image=state['photo'], text='')
                received_at = getattr(prepared.frame, 'received_at', None)
                if received_at is not None:
                    set_camera_metrics(display_seconds=time.perf_counter() - received_at, display_only=True)
        root.after(CAMERA_REFRESH_MS, update_camera)

    def update_controls():
        if state['closing']:
            return
        motion.update()
        speech.update()
        mic_on = speech.controller.snapshot()['listening']
        mic_label.config(text='●  Mic on' if mic_on else 'Mic off', fg=MINT if mic_on else MUTED)
        root.after(CONTROL_REFRESH_MS, update_controls)

    def close():
        state['closing'] = True
        stop()
        renderer.close()
        speech.close()
        assistant.close()
        motion.close()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', close)
    if preview:
        connection_text.set('Preview')
        connection_label.config(fg=MUTED)
        image_label.config(text='Your camera view\n\nLive video appears here when the camera connects.')
        status_text.set('Camera not connected')
        start_button.config(state='disabled')
        stop_button.config(state='disabled')
    else:
        start()
    update_camera()
    update_controls()
    root.mainloop()


def main():
    defaults = json.loads(CONFIG.read_text(encoding='utf-8-sig')) if CONFIG.exists() else {}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', default=defaults.get('bt_address'))
    parser.add_argument('--channel', type=int, default=defaults.get('bt_channel', 1))
    parser.add_argument('--probe', type=int, default=0, help='Verify this many frames, then exit')
    parser.add_argument('--output', type=Path, default=PROJECT / '.local' / 'bluetooth-test')
    parser.add_argument('--fps', type=float, default=15, help='Maximum requested fps')
    parser.add_argument('--rotate', type=int, choices=(0, 180), default=180,
                        help='Viewer/photo rotation in degrees (default: 180); probe saves raw camera frames')
    parser.add_argument('--mpu-port', help='Nano USB serial port (default: automatically find one Nano ESP32)')
    parser.add_argument('--motion-transport', choices=('auto', 'usb', 'ble'), default='auto',
                        help='auto uses USB if present, otherwise Bluetooth LE')
    parser.add_argument('--mpu-ble-address', help='Optional BLE glove address when multiple gloves are nearby')
    parser.add_argument('--preview', action='store_true', help='Preview the Windows UI without opening camera, glove, microphone or pointer devices')
    parser.add_argument('--pause-pointer', action='store_true', help='Start with cursor control paused and Speech & Jarvis selected')
    parser.add_argument('--listen', action='store_true', help='Start continuous laptop microphone transcription')
    args = parser.parse_args()
    if args.preview and (args.probe or args.listen):
        parser.error('--preview cannot be combined with --probe or --listen')
    if sys.platform != 'win32' and not args.preview:
        parser.error('The hardware viewer targets Windows. Use --preview to inspect its interface on this computer.')
    if not args.preview and (not args.address or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', args.address)):
        parser.error('Provide --address with the camera Bluetooth MAC, or save .local/bluetooth-camera.json')
    if not 1 <= args.channel <= 30 or not 0 < args.fps <= 30 or not 0 <= args.probe <= 1000:
        parser.error('Invalid channel, fps, or probe count')
    if args.probe:
        probe(args.address, args.channel, args.probe, args.output)
    else:
        launch_viewer(args.address or 'Not configured', args.channel, args.fps, args.rotate, args.mpu_port,
                      args.motion_transport, args.mpu_ble_address, args.listen, args.pause_pointer, args.preview)


if __name__ == '__main__':
    main()

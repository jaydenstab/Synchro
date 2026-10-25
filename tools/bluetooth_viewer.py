"""Direct Bluetooth Classic camera viewer. No Wi-Fi or USB image fallback."""
import argparse
from collections import deque
from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import queue
import re
import socket
import sys
import threading
import time

from PIL import Image

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


class Camera:
    def __init__(self, address, channel):
        self.address, self.channel = address, channel
        self.connection = None
        self.reader = None

    def connect(self):
        self.connection = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.connection.settimeout(12)
        self.connection.connect((self.address, self.channel))
        self.connection.settimeout(6)
        self.reader = Reader(self.connection)
        self.connection.sendall(b'STATUS\n')
        status = json.loads(self.reader.line())
        if status.get('firmware') not in ('bluetooth-1', 'bluetooth-2') or not status.get('camera_ready'):
            raise ProtocolError('The Bluetooth camera firmware is not ready')
        return status

    def capture(self):
        began = time.perf_counter()
        self.connection.sendall(b'CAPTURE\n')
        header = self.reader.line()
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
        with Image.open(BytesIO(jpeg)) as decoded:
            if decoded.size != (width, height):
                raise ProtocolError('JPEG dimensions do not match its header')
            decoded.load()
            picture = decoded.convert('RGB')
        now = time.perf_counter()
        return Frame(jpeg, picture, now - began, now)

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


def launch_viewer(address, channel, fps, rotation=180, mpu_port=None, motion_transport='auto', mpu_ble_address=None, listen=False):
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageTk
    from motion_panel import MotionPanel
    from speech_panel import SpeechPanel

    root = tk.Tk()
    root.title('Synchro | Bluetooth Camera')
    root.geometry(f'{min(860, root.winfo_screenwidth() - 80)}x{min(800, root.winfo_screenheight() - 100)}')
    root.minsize(650, 600)
    root.configure(bg='#10181c')
    root.columnconfigure(0, weight=1)
    root.rowconfigure(3, weight=1)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('TButton', padding=9)
    tk.Label(root, text='Synchro · camera, motion & speech', fg='#eaf1ee', bg='#10181c', font=('Segoe UI', 16, 'bold')).grid(row=0, column=0, pady=(8, 2))
    tk.Label(root, text=f'Synchro-Cam-BT  ·  {address}', fg='#aec1b9', bg='#10181c', font=('Segoe UI', 9)).grid(row=1, column=0)
    image_label = tk.Label(root, width=1, height=1, bg='#1a262b', fg='#aec1b9', text='Connecting over Bluetooth...', font=('Segoe UI', 14))
    image_label.grid(row=3, column=0, padx=20, pady=10, sticky='nsew')
    status_text = tk.StringVar(value='Connecting...')
    tk.Label(root, textvariable=status_text, fg='#b5e5ca', bg='#10181c', font=('Segoe UI', 11), wraplength=470).grid(row=4, column=0, padx=10, pady=5)
    buttons = tk.Frame(root, bg='#10181c')
    buttons.grid(row=8, column=0, pady=(6, 10))
    frames = queue.Queue(maxsize=1)
    events = queue.Queue()
    state = {'thread': None, 'stop': None, 'camera': None, 'frame': None, 'photo': None, 'closing': False}
    timings = deque()
    rotated = tk.BooleanVar(value=rotation == 180)

    def oriented_picture():
        picture = state['frame'].image
        return picture.transpose(Image.Transpose.ROTATE_180) if rotated.get() else picture

    def render_picture():
        if state['frame'] is None:
            return
        picture = oriented_picture()
        width, height = picture.size
        scale = min(max(4, image_label.winfo_width() - 4) / width,
                    max(4, image_label.winfo_height() - 4) / height)
        picture = picture.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BILINEAR)
        state['photo'] = ImageTk.PhotoImage(picture)
        image_label.config(image=state['photo'], text='')

    motion = MotionPanel(root, mpu_port, motion_transport, mpu_ble_address)
    motion.frame.grid(row=5, column=0, padx=20, pady=6, sticky='ew')
    speech = SpeechPanel(root, listen=listen)
    motion.sensor.speech = speech.controller
    speech.frame.grid(row=6, column=0, padx=20, pady=4, sticky='ew')
    ttk.Checkbutton(root, text='Rotate 180°', variable=rotated, command=render_picture).grid(row=7, column=0, pady=3)
    image_label.bind('<Configure>', lambda event: render_picture())

    def worker(stop_event):
        while not stop_event.is_set():
            camera = Camera(address, channel)
            state['camera'] = camera
            try:
                camera.connect()
                events.put('Bluetooth connected. Receiving images...')
                while not stop_event.is_set():
                    began = time.perf_counter()
                    frame = camera.capture()
                    if stop_event.is_set():
                        break
                    try:
                        frames.put_nowait(frame)
                    except queue.Full:
                        try:
                            frames.get_nowait()
                        except queue.Empty:
                            pass
                        frames.put_nowait(frame)
                    stop_event.wait(max(0, 1 / fps - (time.perf_counter() - began)))
            except (OSError, ValueError, ProtocolError, AttributeError) as error:
                if not stop_event.is_set():
                    print(f'Camera Bluetooth: {error}', file=sys.stderr, flush=True)
                    events.put('Camera unavailable. Check camera power; reconnecting...')
            finally:
                camera.close()
                if state['camera'] is camera:
                    state['camera'] = None
            stop_event.wait(2)

    def start():
        if state['thread'] and state['thread'].is_alive():
            return
        while not events.empty():
            events.get_nowait()
        while not frames.empty():
            frames.get_nowait()
        timings.clear()
        state['stop'] = threading.Event()
        state['thread'] = threading.Thread(target=worker, args=(state['stop'],), daemon=True)
        state['thread'].start()
        start_button.config(state='disabled')
        stop_button.config(state='normal')
        status_text.set('Connecting over Bluetooth...')

    def stop():
        if state['stop']:
            state['stop'].set()
        camera = state['camera']
        if camera:
            camera.close()
        stop_button.config(state='disabled')
        status_text.set('Stopped. The laptop can stay connected to its normal Wi-Fi.')

    def snapshot():
        if state['frame'] is not None:
            folder = PROJECT / '.local' / 'bluetooth-photos'
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (time.strftime('%Y%m%d-%H%M%S') + '.jpg')
            if rotated.get():
                oriented_picture().save(target, format='JPEG', quality=95)
            else:
                target.write_bytes(state['frame'].jpeg)
            status_text.set('Saved photo: ' + str(target))

    start_button = ttk.Button(buttons, text='Start', command=start)
    start_button.pack(side='left', padx=5)
    stop_button = ttk.Button(buttons, text='Stop', command=stop)
    stop_button.pack(side='left', padx=5)
    ttk.Button(buttons, text='Save photo', command=snapshot).pack(side='left', padx=5)

    def update():
        if state['closing']:
            return
        running = state['stop'] and not state['stop'].is_set()
        while not events.empty():
            text = events.get_nowait()
            if running:
                status_text.set(text)
        try:
            frame = frames.get_nowait()
        except queue.Empty:
            frame = None
        if frame and running:
            state['frame'] = frame
            width, height = frame.image.size
            render_picture()
            timings.append(frame.received_at)
            while len(timings) > 2 and timings[0] < frame.received_at - 3:
                timings.popleft()
            rate = (len(timings) - 1) / (timings[-1] - timings[0]) if len(timings) > 1 else 0
            status_text.set(f'Bluetooth live  ·  {rate:.1f} fps  ·  {frame.seconds * 1000:.0f} ms/image  ·  {width} × {height}')
        if state['thread'] and not state['thread'].is_alive():
            start_button.config(state='normal')
        motion.update()
        speech.update()
        root.after(30, update)

    def close():
        state['closing'] = True
        stop()
        speech.close()
        motion.close()
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', close)
    start()
    update()
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
    parser.add_argument('--listen', action='store_true', help='Start continuous laptop microphone transcription')
    args = parser.parse_args()
    if not args.address or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', args.address):
        parser.error('Provide --address with the camera Bluetooth MAC, or save .local/bluetooth-camera.json')
    if not 1 <= args.channel <= 30 or not 0 < args.fps <= 30 or not 0 <= args.probe <= 1000:
        parser.error('Invalid channel, fps, or probe count')
    if args.probe:
        probe(args.address, args.channel, args.probe, args.output)
    else:
        launch_viewer(args.address, args.channel, args.fps, args.rotate, args.mpu_port,
                      args.motion_transport, args.mpu_ble_address, args.listen)


if __name__ == '__main__':
    main()

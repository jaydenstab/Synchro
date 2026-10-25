"""One Synchro window for macOS and Windows.

The layout follows the Mac app: dark sidebar, Camera page, mint selection.
The Data page carries the Windows glove test readings: roll, pitch, yaw,
finger contacts, link rate, calibration, packet errors, and the latest axes.
"""
from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from pathlib import Path

from desktop.camera_link import (
    ADDRESS,
    camera_limitation,
    capture_frame,
    handshake,
    open_bluetooth,
)
from desktop.present import (
    ANGLE_CAPTIONS,
    AXIS_CAPTIONS,
    CONTACT_CAPTIONS,
    contact_line,
    format_angle,
    format_axis,
)
from motion.service import MotionService

BG = '#0d0f11'
SIDEBAR = '#101214'
PANEL = '#15181b'
PANEL2 = '#101214'
TEXT = '#f3f6f4'
MUTED = '#9aa39c'
MINT = '#3ddc97'
INK = '#06281a'
LINE = '#2a2e32'
DANGER = '#ff6b6b'
WARN = '#f0b429'
CHIP = '#25353a'
CHIP_ON = '#285d46'
CHIP_TEXT = '#d2ffe3'
FONT = 'Segoe UI' if sys.platform == 'win32' else 'Helvetica Neue'


class SynchroWindow:
    def __init__(self, motion: MotionService, root: tk.Tk | None = None) -> None:
        self.motion = motion
        self.root = root or tk.Tk()
        self.root.title('Synchro')
        self.root.configure(bg=BG)
        self.root.geometry('1280x780')
        self.root.minsize(1100, 680)
        self.page = 'camera'
        self._flash = [0.0, 0.0]
        self._presses: list[int | None] = [None, None]
        self._camera_lock = threading.Lock()
        self._camera_stop = threading.Event()
        self._camera_thread: threading.Thread | None = None
        self._camera = {
            'status': 'Idle',
            'message': camera_limitation() or 'Power the camera, then press Start.',
            'fps': None,
            'latency_ms': None,
            'width': 0,
            'height': 0,
            'jpeg_bytes': 0,
            'frames': 0,
            'running': False,
        }
        self._build()
        self.show('camera')
        self.refresh()

    def _build(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        side = tk.Frame(self.root, bg=SIDEBAR, width=208)
        side.grid(row=0, column=0, sticky='ns')
        side.grid_propagate(False)
        tk.Label(side, text='Synchro', bg=SIDEBAR, fg=TEXT, font=(FONT, 18, 'bold')).pack(anchor='w', padx=24, pady=(22, 0))
        tk.Label(side, text='Camera and glove', bg=SIDEBAR, fg=MUTED, font=(FONT, 12)).pack(anchor='w', padx=24, pady=(0, 22))
        self.nav = {}
        for key, title in (('camera', 'Camera'), ('data', 'Data')):
            button = tk.Label(
                side, text=title, bg=SIDEBAR, fg=MUTED, anchor='w',
                font=(FONT, 14), padx=12, pady=8, cursor='hand2',
            )
            button.pack(fill='x', padx=16, pady=2)
            button.bind('<Button-1>', lambda _event, name=key: self.show(name))
            self.nav[key] = button
        tk.Frame(side, bg=SIDEBAR).pack(fill='both', expand=True)
        self.side_status = tk.Label(side, text='Glove idle', bg=SIDEBAR, fg=MUTED, font=(FONT, 12))
        self.side_status.pack(anchor='w', padx=24, pady=(0, 22))

        self.body = tk.Frame(self.root, bg=BG)
        self.body.grid(row=0, column=1, sticky='nsew')
        self.camera_page = tk.Frame(self.body, bg=BG)
        self.data_page = tk.Frame(self.body, bg=BG)
        self._build_camera()
        self._build_data()

    def _build_camera(self) -> None:
        page = self.camera_page
        head = tk.Frame(page, bg=BG)
        head.pack(fill='x', padx=28, pady=(22, 12))
        tk.Label(head, text='Camera', bg=BG, fg=TEXT, font=(FONT, 28, 'bold')).pack(side='left')
        self.camera_pill = tk.Label(head, text='Idle', bg=BG, fg=MUTED, font=(FONT, 13))
        self.camera_pill.pack(side='right')
        self.preview = tk.Label(
            page, text='No signal\n\nThe picture appears with the first frame.',
            bg='#000000', fg=TEXT, font=(FONT, 18), width=60, height=12,
        )
        self.preview.pack(fill='both', expand=True, padx=28, pady=(0, 12))
        stats = tk.Frame(page, bg=BG)
        stats.pack(fill='x', padx=28, pady=(0, 8))
        self.camera_readouts = {}
        for key, caption in (
            ('fps', 'Current fps'),
            ('latency', 'Request to frame'),
            ('resolution', 'Resolution'),
            ('jpeg', 'JPEG size'),
        ):
            box = tk.Frame(stats, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            box.pack(side='left', fill='x', expand=True, padx=(0, 8))
            tk.Label(box, text=caption, bg=PANEL, fg=MUTED, font=(FONT, 11)).pack(anchor='w', padx=10, pady=(8, 0))
            value = tk.Label(box, text='—', bg=PANEL, fg=MUTED, font=(FONT, 18, 'bold'))
            value.pack(anchor='w', padx=10, pady=(0, 8))
            self.camera_readouts[key] = value
        controls = tk.Frame(page, bg=BG)
        controls.pack(fill='x', padx=28, pady=(4, 8))
        self.start_button = self._button(controls, 'Start', self.start_camera, primary=True)
        self.stop_button = self._button(controls, 'Stop', self.stop_camera)
        self._set_enabled(self.stop_button, False)
        self.camera_message = tk.Label(
            page, text='', bg=BG, fg=MUTED, font=(FONT, 12), anchor='w', justify='left', wraplength=860,
        )
        self.camera_message.pack(fill='x', padx=28, pady=(0, 18))

    def _build_data(self) -> None:
        page = self.data_page
        tk.Label(page, text='Data', bg=BG, fg=TEXT, font=(FONT, 28, 'bold')).pack(anchor='w', padx=28, pady=(22, 4))
        tk.Label(
            page,
            text='Live glove test readings. Distances and gestures are not on this page.',
            bg=BG, fg=MUTED, font=(FONT, 13),
        ).pack(anchor='w', padx=28, pady=(0, 12))
        card = tk.Frame(page, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill='x', padx=28, pady=(0, 12))
        angles = tk.Frame(card, bg=PANEL)
        angles.pack(fill='x', padx=14, pady=(12, 6))
        self.angle_values = []
        for caption in ANGLE_CAPTIONS:
            column = tk.Frame(angles, bg=PANEL)
            column.pack(side='left', fill='x', expand=True)
            tk.Label(column, text=caption, bg=PANEL, fg=MUTED, font=(FONT, 11)).pack(anchor='w')
            value = tk.Label(column, text='—', bg=PANEL, fg=MUTED, font=(FONT, 22, 'bold'))
            value.pack(anchor='w')
            self.angle_values.append(value)
        contacts = tk.Frame(card, bg=PANEL)
        contacts.pack(fill='x', padx=14, pady=6)
        self.contact_values = []
        for _caption in CONTACT_CAPTIONS:
            chip = tk.Label(contacts, text='', bg=CHIP, fg=MUTED, font=(FONT, 12, 'bold'), padx=10, pady=8)
            chip.pack(side='left', fill='x', expand=True, padx=(0, 8))
            self.contact_values.append(chip)
        self.link_line = tk.Label(card, text='Looking for Nano USB...', bg=PANEL, fg=MUTED, font=(FONT, 13))
        self.link_line.pack(anchor='w', padx=14, pady=(4, 6))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill='x', padx=14, pady=(0, 6))
        self.calibrate_button = self._button(row, 'Calibrate — hold still 15 s', self.calibrate)
        self.progress = tk.Label(row, text='', bg=PANEL2, fg=MINT, font=(FONT, 11), width=18, anchor='w')
        self.progress.pack(side='left', padx=8)
        self.calibration_note = tk.Label(card, text='Not calibrated. Yaw can drift.', bg=PANEL, fg=WARN, font=(FONT, 12))
        self.calibration_note.pack(anchor='w', padx=14, pady=(0, 12))

        axes = tk.Frame(page, bg=BG)
        axes.pack(fill='x', padx=28, pady=(0, 8))
        self.axis_values = []
        for caption in AXIS_CAPTIONS:
            box = tk.Frame(axes, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            box.pack(side='left', fill='x', expand=True, padx=(0, 8))
            tk.Label(box, text=caption, bg=PANEL, fg=MUTED, font=(FONT, 11)).pack(anchor='w', padx=10, pady=(8, 0))
            value = tk.Label(box, text='—', bg=PANEL, fg=MUTED, font=(FONT, 16, 'bold'))
            value.pack(anchor='w', padx=10, pady=(0, 8))
            self.axis_values.append(value)
        self.test_line = tk.Label(page, text='', bg=BG, fg=MUTED, font=(FONT, 13), anchor='w')
        self.test_line.pack(fill='x', padx=28, pady=(4, 18))

    def _button(self, parent, text: str, command, primary: bool = False) -> tk.Label:
        button = tk.Label(
            parent, text=text, padx=14, pady=8, cursor='hand2',
            font=(FONT, 13, 'bold' if primary else 'normal'),
            bg=MINT if primary else PANEL, fg=INK if primary else TEXT,
        )
        button.pack(side='left', padx=(0, 8))
        button._enabled = True

        def click(_event, target=button, action=command):
            if target._enabled:
                action()

        button.bind('<Button-1>', click)
        return button

    def show(self, name: str) -> None:
        self.page = name
        self.camera_page.pack_forget()
        self.data_page.pack_forget()
        page = self.camera_page if name == 'camera' else self.data_page
        page.pack(fill='both', expand=True)
        for key, button in self.nav.items():
            chosen = key == name
            button.configure(bg=MINT if chosen else SIDEBAR, fg=INK if chosen else MUTED)

    def refresh(self) -> None:
        snap = self.motion.snapshot()
        self._paint_motion(snap)
        self._paint_camera()
        if self.root.winfo_exists():
            self.root.after(300, self.refresh)

    def _paint_motion(self, snap: dict) -> None:
        fresh = bool(snap.get('fresh'))
        angles = snap.get('angles') or [None, None, None]
        for label, value in zip(self.angle_values, angles):
            label.configure(text=format_angle(value), fg=TEXT if value is not None else MUTED)
        now = time.monotonic()
        downs = (snap.get('left_down'), snap.get('right_down'))
        counts = (int(snap.get('left_presses') or 0), int(snap.get('right_presses') or 0))
        for index, caption in enumerate(CONTACT_CAPTIONS):
            previous = self._presses[index]
            if previous is not None and counts[index] > previous:
                self._flash[index] = now + 0.25
            self._presses[index] = counts[index]
            text, active = contact_line(caption, fresh, downs[index], counts[index], now < self._flash[index])
            self.contact_values[index].configure(
                text=text,
                bg=CHIP_ON if active else CHIP,
                fg=CHIP_TEXT if active else MUTED,
            )
        self.link_line.configure(text=snap.get('line') or 'Looking for Nano USB...')
        self.calibration_note.configure(text=snap.get('calibration_note') or 'Not calibrated. Yaw can drift.')
        progress = float(snap.get('calibration_progress') or 0)
        self.progress.configure(text=f'{progress * 100:.0f}%' if progress else '')
        self._set_enabled(self.calibrate_button, bool(snap.get('calibrate_enabled')))
        axes = snap.get('axes') or [None] * 6
        for label, value in zip(self.axis_values, axes):
            label.configure(text=format_axis(value), fg=TEXT if value is not None else MUTED)
        self.test_line.configure(
            text=(
                f"Packet errors {snap.get('packet_errors', 0)}"
                f"  ·  Tracking restarts {snap.get('tracking_restarts', 0)}"
                f"  ·  Fresh {'yes' if fresh else 'no'}"
                f"  ·  Ready {'yes' if snap.get('ready') else 'no'}"
            )
        )
        self.side_status.configure(
            text='Glove live' if fresh else 'Glove idle',
            fg=MINT if fresh else MUTED,
        )

    def _paint_camera(self) -> None:
        with self._camera_lock:
            state = dict(self._camera)
        self.camera_pill.configure(text=state['status'], fg=MINT if state['running'] else MUTED)
        self.camera_message.configure(text=state['message'])
        fps = state['fps']
        latency = state['latency_ms']
        self.camera_readouts['fps'].configure(
            text=f'{fps:.1f}' if isinstance(fps, float) else '—',
            fg=TEXT if isinstance(fps, float) else MUTED,
        )
        self.camera_readouts['latency'].configure(
            text=f'{latency:.0f} ms' if isinstance(latency, float) else '—',
            fg=TEXT if isinstance(latency, float) else MUTED,
        )
        if state['width']:
            self.camera_readouts['resolution'].configure(text=f"{state['width']} × {state['height']}", fg=TEXT)
        else:
            self.camera_readouts['resolution'].configure(text='—', fg=MUTED)
        if state['jpeg_bytes']:
            self.camera_readouts['jpeg'].configure(text=f"{state['jpeg_bytes'] / 1024:.1f} KB", fg=TEXT)
        else:
            self.camera_readouts['jpeg'].configure(text='—', fg=MUTED)
        self._set_enabled(self.start_button, not state['running'])
        self._set_enabled(self.stop_button, bool(state['running']))

    def _set_enabled(self, label: tk.Label, enabled: bool) -> None:
        label._enabled = enabled
        if label is self.start_button:
            label.configure(bg=MINT if enabled else PANEL, fg=INK if enabled else MUTED)
        else:
            label.configure(fg=TEXT if enabled else MUTED)

    def calibrate(self) -> None:
        try:
            self.motion.request_calibration()
        except ValueError as exc:
            self.calibration_note.configure(text=str(exc))

    def start_camera(self) -> None:
        limitation = camera_limitation()
        if limitation:
            self._set_camera(status='Idle', message=limitation, running=False)
            return
        if self._camera_thread and self._camera_thread.is_alive():
            return
        self._camera_stop.clear()
        self._set_camera(status='Connecting', message=f'Connecting to Synchro-Cam-BT {ADDRESS}', running=True, frames=0)
        self._camera_thread = threading.Thread(target=self._camera_loop, name='synchro-camera', daemon=True)
        self._camera_thread.start()

    def stop_camera(self) -> None:
        self._camera_stop.set()
        self._set_camera(status='Idle', message='Stopped. The radio is released when the capture thread exits.', running=False)

    def _camera_loop(self) -> None:
        connection = None
        try:
            connection = open_bluetooth()
            _status, reader = handshake(connection)
            self._set_camera(status='Live', message='Bluetooth live', running=True)
            stamps: list[float] = []
            while not self._camera_stop.is_set():
                jpeg, width, height, seconds = capture_frame(connection, reader)
                now = time.monotonic()
                stamps = [item for item in stamps if now - item <= 3] + [now]
                fps = (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) >= 2 else None
                with self._camera_lock:
                    frames = self._camera['frames'] + 1
                self._set_camera(
                    status='Live',
                    message='Bluetooth live',
                    running=True,
                    fps=fps,
                    latency_ms=seconds * 1000,
                    width=width,
                    height=height,
                    jpeg_bytes=len(jpeg),
                    frames=frames,
                )
                remaining = 1 / 15 - seconds
                if remaining > 0:
                    self._camera_stop.wait(remaining)
        except Exception as exc:
            self._set_camera(status='Error', message=str(exc), running=False)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            with self._camera_lock:
                running = self._camera['running']
            if running:
                self._set_camera(status='Idle', message='Camera stopped.', running=False)

    def _set_camera(self, **values) -> None:
        with self._camera_lock:
            self._camera.update(values)


def main() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    data = Path(root_dir / 'data')
    data.mkdir(parents=True, exist_ok=True)
    motion = MotionService(data)
    motion.start_usb()
    window = SynchroWindow(motion)
    try:
        window.root.mainloop()
    finally:
        window.stop_camera()
        motion.close()

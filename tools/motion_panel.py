"""Live orientation/contact panel; Tk widgets are updated on the UI thread."""
import time
import tkinter as tk
from tkinter import ttk

from motion_sensor import MotionSensor
from motion_pointer import PointerController


class MotionPanel:
    def __init__(self, root, port=None, transport='auto', ble_address=None):
        self.sensor = MotionSensor(port, transport, ble_address)
        self.frame = tk.Frame(root, bg='#1a262b', padx=14, pady=10)
        for column in range(3):
            self.frame.columnconfigure(column, weight=1)
        self.angle_labels = []
        for i, name in enumerate(('ROLL / X', 'PITCH / Y', 'YAW / RELATIVE')):
            tk.Label(self.frame, text=name, bg='#1a262b', fg='#aec1b9',
                     font=('Segoe UI', 9)).grid(row=0, column=i)
            label = tk.Label(self.frame, text='—', bg='#1a262b', fg='#eaf1ee',
                             font=('Segoe UI', 20, 'bold'))
            label.grid(row=1, column=i, pady=(0, 6))
            self.angle_labels.append(label)
        self.clicks = tk.Frame(self.frame, bg='#1a262b')
        self.clicks.grid(row=2, column=0, columnspan=3, sticky='ew')
        self.contact_labels = []
        self.last_counts = [None, None]
        self.flash_until = [0.0, 0.0]
        for i in range(2):
            self.clicks.columnconfigure(i, weight=1)
            label = tk.Label(self.clicks, text='Waiting for contacts', bg='#25353a', fg='#aec1b9',
                             font=('Segoe UI', 11, 'bold'), padx=10, pady=7)
            label.grid(row=0, column=i, padx=4, sticky='ew')
            self.contact_labels.append(label)
        self.status = tk.Label(self.frame, text='Looking for Nano USB...', bg='#1a262b', fg='#aec1b9',
                               font=('Segoe UI', 9), wraplength=700)
        self.status.grid(row=3, column=0, columnspan=3, pady=5)
        self.cal_button = ttk.Button(self.frame, text='Calibrate — hold still 15 s', command=self.calibrate)
        self.cal_button.grid(row=4, column=0, columnspan=2, sticky='w')
        self.progress = ttk.Progressbar(self.frame, maximum=100)
        self.progress.grid(row=4, column=2, sticky='ew', padx=4)
        self.cal_status = tk.Label(self.frame, text='Not calibrated. Yaw can drift.', bg='#1a262b',
                                   fg='#e9c583', font=('Segoe UI', 9), wraplength=700)
        self.cal_status.grid(row=5, column=0, columnspan=3, pady=(5, 0))
        self.pointer = PointerController(self.sensor)
        self.sensor.pointer = self.pointer
        self.pointer_row = tk.Frame(self.frame, bg='#1a262b')
        self.pointer_row.grid(row=6, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        self.pointer_button = ttk.Button(self.pointer_row, text='Enable pointer', command=self.toggle_pointer)
        self.pointer_button.pack(side='left', padx=(0, 5))
        ttk.Button(self.pointer_row, text='Set neutral', command=self.recenter_pointer).pack(side='left', padx=5)
        self.invert_x = tk.BooleanVar(value=False)
        self.invert_y = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.pointer_row, text='Reverse X', variable=self.invert_x,
                        command=self.configure_pointer).pack(side='left', padx=5)
        ttk.Checkbutton(self.pointer_row, text='Reverse Y', variable=self.invert_y,
                        command=self.configure_pointer).pack(side='left', padx=5)
        self.sensitivity_label = tk.Label(self.pointer_row, text='Sensitivity 1.0×', bg='#1a262b', fg='#aec1b9')
        self.sensitivity_label.pack(side='left', padx=3)
        self.pointer_speed = tk.DoubleVar(value=1.0)
        ttk.Scale(self.pointer_row, from_=0.25, to=2.0, variable=self.pointer_speed,
                  command=lambda _: self.configure_pointer(), length=85).pack(side='left')
        self.pointer_status = tk.Label(self.frame, text='Pointer off', bg='#1a262b', fg='#e9c583',
                                       font=('Segoe UI', 9), wraplength=700)
        self.pointer_status.grid(row=7, column=0, columnspan=3, pady=(4, 0))
        self.options_row = tk.Frame(self.frame, bg='#1a262b')
        self.options_row.grid(row=8, column=0, columnspan=3, sticky='ew', pady=(4, 0))
        self.auto_cursor = tk.BooleanVar(value=True)
        self.smooth_cursor = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.options_row, text='Auto cursor', variable=self.auto_cursor,
                        command=self.configure_pointer).pack(side='left', padx=4)
        ttk.Checkbutton(self.options_row, text='Stabilize', variable=self.smooth_cursor,
                        command=self.configure_pointer).pack(side='left', padx=4)
        tk.Label(self.options_row, text='Sideways axis', bg='#1a262b', fg='#aec1b9').pack(side='left', padx=4)
        self.sideways_axis = ttk.Combobox(self.options_row, values=('X', 'Y'), state='readonly', width=3)
        self.sideways_axis.current(0)
        self.sideways_axis.pack(side='left', padx=4)
        self.sideways_axis.bind('<<ComboboxSelected>>', lambda _: self.configure_pointer())
        tk.Label(self.options_row, text='MPU-only estimate · short swipes', bg='#1a262b',
                 fg='#e9c583', font=('Segoe UI', 9)).pack(side='left', padx=8)
        self.pointer_error = None
        root.bind('<Escape>', lambda _: self.pointer.disable('Pointer stopped with Esc.'))
        self.error = None
        self.pointer.start()
        self.sensor.start()

    def toggle_pointer(self):
        state = self.pointer.snapshot()
        if state['enabled'] or (state['auto_enable'] and not state['manual_pause']):
            self.pointer.disable()
            self.pointer_error = None
            return
        try:
            self.pointer.enable()
            self.pointer_error = None
        except ValueError as error:
            self.pointer_error = str(error)

    def recenter_pointer(self):
        try:
            self.pointer.recenter()
            self.pointer_error = None
        except ValueError as error:
            self.pointer_error = str(error)

    def configure_pointer(self):
        self.pointer.configure(self.pointer_speed.get(), self.invert_x.get(), self.invert_y.get(),
                               auto_enable=self.auto_cursor.get(), stabilize=self.smooth_cursor.get(),
                               sideways_axis=max(0, self.sideways_axis.current()))
        self.sensitivity_label.config(text=f'Sensitivity {self.pointer_speed.get():.1f}×')

    def calibrate(self):
        try:
            self.pointer.disable('Pointer off for calibration.')
            self.sensor.request_calibration()
            self.error = None
        except ValueError as error:
            self.error = str(error)

    def update(self):
        data = self.sensor.snapshot()
        angles = data['angles'] if data['ready'] else None
        for i, label in enumerate(self.angle_labels):
            label.config(text=f'{angles[i]:+.2f}°' if angles is not None else '—',
                         fg='#eaf1ee' if angles is not None else '#aec1b9')
        now = time.monotonic()
        for i, (side, name) in enumerate((('left', 'Index / LEFT CLICK'), ('right', 'Middle / RIGHT CLICK'))):
            count = data[f'{side}_presses']
            if self.last_counts[i] is not None and count > self.last_counts[i]:
                self.flash_until[i] = now + 0.25
            self.last_counts[i] = count
            down = data[f'{side}_down']
            text = 'NO SIGNAL' if not data['fresh'] else ('HELD' if down else
                    ('TAP' if now < self.flash_until[i] else 'released'))
            active = data['fresh'] and (down or now < self.flash_until[i])
            self.contact_labels[i].config(text=f'{name}: {text}  ·  {count} taps',
                                           bg='#285d46' if active else '#25353a',
                                           fg='#d2ffe3' if active else '#aec1b9')
        message = data['status']
        if data['fresh'] and data['ready']:
            message = (f"{data.get('transport', 'USB')}  ·  {data['sample_hz']:.0f} samples/s  ·  "
                       f"{data['temperature_c']:.1f} °C  ·  {data['tracking_restarts']} tracking restarts")
        self.status.config(text=message)
        cal = data['calibration']
        busy = cal['state'] in ('queued', 'running', 'saving')
        self.cal_button.config(state='disabled' if busy or not data['ready'] else 'normal')
        self.progress['value'] = 100 * cal.get('progress', 0)
        if busy:
            message = f"KEEP STILL — {15 * cal.get('progress', 0):.1f} / 15 seconds"
            if cal['state'] == 'saving':
                message = 'Checking and saving calibration...'
        elif cal['state'] in ('passed', 'failed'):
            message = cal.get('message', cal['state'])
        else:
            message = ('Saved gyro calibration loaded. Yaw is relative and can drift.' if data['calibrated']
                       else 'Not calibrated. Ready for a 15-second stationary measurement.')
            if not data['ready']:
                message = 'Calibration waits for live MPU readings.'
        if data.get('profile_warning'):
            message = data['profile_warning']
        reference_temp = data.get('calibration_temperature_c')
        if (not busy and data['fresh'] and reference_temp is not None and
                abs(data['temperature_c'] - reference_temp) > 5):
            message += ' Temperature changed; recalibration recommended.'
        self.cal_status.config(text=self.error or message)
        pointer = self.pointer.snapshot()
        self.pointer_button.config(text='Pause pointer' if pointer['enabled'] else
                                   ('Pause auto' if pointer['auto_enable'] and not pointer['manual_pause'] else 'Enable pointer'))
        self.pointer_status.config(text=self.pointer_error or pointer['message'],
                                   fg='#b5e5ca' if pointer['enabled'] and not pointer['suspended'] else '#e9c583')

    def close(self):
        self.pointer.close()
        self.sensor.close()

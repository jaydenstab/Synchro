"""Live orientation/contact panel; Tk widgets are updated on the UI thread."""
import time
import tkinter as tk
from tkinter import ttk
from desktop_theme import (FONT, PANEL, INSET, TEXT, MUTED, MINT, WARN, DANGER,
                           CHIP, SELECT, SELECT_TEXT, heading, wrap_labels)

from motion_ble import FULL_PACKET_MTU
from motion_sensor import MotionSensor
from motion_pointer import PointerController


class MotionPanel:
    def __init__(self, root, port=None, transport='auto', ble_address=None, connect=True, radio_hold=None):
        self.connect = connect
        self.sensor = MotionSensor(port, transport, ble_address, radio_hold)
        self.frame = tk.Frame(root, bg=PANEL, padx=18, pady=18)
        for column in range(3):
            self.frame.columnconfigure(column, weight=1)
        heading(self.frame, 'Motion & pointer', 'Connect the glove, then calibrate while holding still.').grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 18))
        self.angle_labels = []
        for i, name in enumerate(('ROLL / X', 'PITCH / Y', 'YAW / RELATIVE')):
            cell = tk.Frame(self.frame, bg=INSET, padx=10, pady=10)
            cell.grid(row=1, column=i, sticky='ew', padx=(0 if i == 0 else 4, 0))
            tk.Label(cell, text=name, bg=INSET, fg=MUTED,
                     font=(FONT, 9), anchor='w').pack(fill='x')
            label = tk.Label(cell, text='—', bg=INSET, fg=MUTED,
                             font=(FONT, 22, 'bold'), anchor='w')
            label.pack(fill='x', pady=(5, 0))
            self.angle_labels.append(label)
        self.clicks = tk.Frame(self.frame, bg=PANEL)
        self.clicks.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        self.contact_labels = []
        self.last_counts = [None, None]
        self.flash_until = [0.0, 0.0]
        for i in range(2):
            self.clicks.columnconfigure(i, weight=1)
            label = tk.Label(self.clicks, text='Waiting for contacts', bg=CHIP, fg=MUTED,
                             font=(FONT, 10, 'bold'), padx=8, pady=7, wraplength=205)
            label.grid(row=1, column=i, padx=4, sticky='ew')
            self.contact_labels.append(label)
        self.status = tk.Label(self.frame, text='Looking for Nano USB...', bg=PANEL, fg=MUTED,
                               font=(FONT, 9), anchor='w', justify='left', wraplength=440)
        self.status.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(10, 8))
        self.cal_button = ttk.Button(self.frame, text='Calibrate — hold still 15 s', command=self.calibrate)
        self.cal_button.grid(row=5, column=0, columnspan=2, sticky='w')
        self.progress = ttk.Progressbar(self.frame, maximum=100)
        self.progress.grid(row=5, column=2, sticky='ew', padx=4)
        self.cal_status = tk.Label(self.frame, text='Not calibrated. Yaw can drift.', bg=PANEL,
                                   fg=WARN, font=(FONT, 9), anchor='w', justify='left', wraplength=440)
        self.cal_status.grid(row=6, column=0, columnspan=3, sticky='ew', pady=(7, 0))
        self.pointer = PointerController(self.sensor)
        self.sensor.pointer = self.pointer
        self.pointer_row = tk.Frame(self.frame, bg=PANEL)
        self.pointer_row.grid(row=7, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        self.pointer_button = ttk.Button(self.pointer_row, text='Enable pointer', command=self.toggle_pointer, style='Primary.TButton')
        self.pointer_button.pack(side='left', padx=(0, 5))
        self.neutral_button = ttk.Button(self.pointer_row, text='Set neutral', command=self.recenter_pointer)
        self.neutral_button.pack(side='left', padx=5)
        tk.Label(self.pointer_row, text='Pause pointer to stop', bg=PANEL, fg=MUTED).pack(side='left', padx=8)
        tuning = tk.Frame(self.frame, bg=PANEL)
        tuning.grid(row=9, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        self.invert_x = tk.BooleanVar(value=False)
        self.invert_y = tk.BooleanVar(value=False)
        ttk.Checkbutton(tuning, text='Reverse X', variable=self.invert_x,
                        command=self.configure_pointer).pack(side='left', padx=5)
        ttk.Checkbutton(tuning, text='Reverse Y', variable=self.invert_y,
                        command=self.configure_pointer).pack(side='left', padx=5)
        self.sensitivity_label = tk.Label(tuning, text='Sensitivity · 25 px/°', bg=PANEL, fg=MUTED)
        self.sensitivity_label.pack(side='left', padx=3)
        self.pointer_speed = tk.DoubleVar(value=1.0)
        ttk.Scale(tuning, from_=0.25, to=2.0, variable=self.pointer_speed,
                  command=lambda _: self.configure_pointer(), length=85).pack(side='left')
        self.pointer_status = tk.Label(self.frame, text='Pointer off', bg=PANEL, fg=WARN,
                                       font=(FONT, 9), anchor='w', justify='left', wraplength=440)
        self.pointer_status.grid(row=10, column=0, columnspan=3, sticky='ew', pady=(7, 0))
        tk.Label(self.frame, text='Hold a contact to drag. Hold both contacts and tilt to scroll.',
                 bg=PANEL, fg=MUTED, wraplength=440, justify='left').grid(row=11, column=0, columnspan=3, sticky='w', pady=(10, 0))
        wrap_labels(self.frame, self.status, self.cal_status, self.pointer_status)
        self.pointer_error = None
        self.error = None
        if connect:
            self.pointer.start()
            self.sensor.start()
        else:
            def disable(widget):
                if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Scale, ttk.Combobox)):
                    widget.state(['disabled'])
                for child in widget.winfo_children():
                    disable(child)
            disable(self.frame)

    def toggle_pointer(self):
        if self.pointer.snapshot()['enabled']:
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
        self.pointer.configure(self.pointer_speed.get(), self.invert_x.get(), self.invert_y.get())
        self.sensitivity_label.config(text=f'Sensitivity · {25 * self.pointer_speed.get():.0f} px/°')

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
                         fg=TEXT if angles is not None else MUTED)
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
            self.contact_labels[i].config(text=f'{name}\n{text}  ·  {count} taps',
                                           bg=SELECT if active else CHIP,
                                           fg=SELECT_TEXT if active else MUTED)
        message = data['status']
        if data['fresh'] and data['ready']:
            message = (f"{data.get('transport', 'USB')}  ·  {data['sample_hz']:.0f} samples/s  ·  "
                       f"{data['temperature_c']:.1f} °C  ·  {data['tracking_restarts']} tracking restarts")
            # Fragmented notifications steal airtime from the camera's Classic link.
            if data.get('ble_mtu') is not None and data['ble_mtu'] < FULL_PACKET_MTU:
                message += f"  ·  BLE MTU {data['ble_mtu']}"
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
        self.cal_status.config(text=self.error or message,
                               fg=DANGER if self.error or cal['state'] == 'failed' else WARN if busy else MUTED)
        pointer = self.pointer.snapshot()
        self.pointer_button.config(state='normal' if self.connect and pointer['available'] else 'disabled')
        self.neutral_button.config(state='normal' if self.connect and pointer['available'] else 'disabled')
        self.pointer_button.config(text='Pause pointer' if pointer['enabled'] else 'Enable pointer')
        self.pointer_status.config(text=self.pointer_error or pointer['message'],
                                   fg=DANGER if self.pointer_error else MINT if pointer['enabled'] and not pointer['suspended'] else MUTED)

    def close(self):
        self.pointer.close()
        if self.connect:
            self.sensor.close()

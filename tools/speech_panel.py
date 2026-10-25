"""Visible mic controls and rolling transcript; all widgets stay on the Tk thread."""
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from speech_stream import SpeechController


class SpeechPanel:
    def __init__(self, root, listen=False):
        self.controller = SpeechController()
        self.frame = tk.Frame(root, bg='#1a262b', padx=10, pady=7)
        self.frame.columnconfigure(1, weight=1)
        self.button = ttk.Button(self.frame, text='Start mic', command=self.toggle)
        self.button.grid(row=0, column=0, padx=(0, 6))
        self.device = ttk.Combobox(self.frame, state='readonly', width=39)
        self.device.grid(row=0, column=1, sticky='ew', padx=4)
        self.devices = [None]
        try:
            import sounddevice as sd
            options = [(None, 'Default laptop microphone')]
            for item in sd.query_devices():
                if item['max_input_channels'] > 0:
                    host = sd.query_hostapis(item['hostapi'])['name']
                    if host in ('MME', 'Windows WASAPI') and item['index'] != 0:
                        options.append((item['index'], f"{item['name']} · {host}"))
            self.devices = [item[0] for item in options]
            self.device['values'] = [item[1] for item in options]
        except Exception:
            self.device['values'] = ['Microphone unavailable — install speech dependencies']
        self.device.current(0)
        ttk.Button(self.frame, text='Clear text', command=self.controller.clear).grid(row=0, column=2, padx=5)
        self.level = ttk.Progressbar(self.frame, maximum=100, length=65)
        self.level.grid(row=0, column=3, padx=5)
        self.status = tk.Label(self.frame, text='', bg='#1a262b', fg='#aec1b9',
                               font=('Segoe UI', 9), anchor='w', wraplength=760)
        self.status.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(3, 3))
        self.text = ScrolledText(self.frame, height=3, wrap='word', font=('Segoe UI', 11),
                                 bg='#10181c', fg='#eaf1ee', insertbackground='#eaf1ee',
                                 relief='flat', state='disabled', padx=7, pady=4)
        self.text.grid(row=2, column=0, columnspan=4, sticky='ew')
        self.revision = -1
        self.error = None
        if listen:
            root.after(300, self.toggle)

    def toggle(self):
        if self.controller.snapshot()['listening']:
            self.controller.stop()
            return
        try:
            index = max(0, self.device.current())
            self.controller.start(self.devices[index])
            self.error = None
        except Exception:
            self.error = 'Cannot start mic. Check the selected input and local speech dependencies.'

    def update(self):
        data = self.controller.snapshot()
        active = data['listening']
        self.button.config(text='Stop mic' if active else 'Start mic')
        self.device.config(state='disabled' if active else 'readonly')
        self.level['value'] = 100 * data['level']
        detail = self.error or data['error'] or data['status']
        if active:
            detail = ('● MIC ON · ' + detail)
        if data['latency_ms'] is not None:
            detail += f" · last decode {data['latency_ms'] / 1000:.1f}s"
        if data['dropped']:
            detail += f" · {data['dropped']} skipped clips"
        self.status.config(text=detail, fg='#b5e5ca' if active and not data['error'] else '#e9c583')
        if data['revision'] != self.revision:
            self.revision = data['revision']
            self.text.config(state='normal')
            self.text.delete('1.0', 'end')
            self.text.insert('end', data['text'])
            self.text.see('end')
            self.text.config(state='disabled')

    def close(self):
        self.controller.close()

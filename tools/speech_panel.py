"""Visible mic controls and rolling transcript; all widgets stay on the Tk thread."""
import tkinter as tk
from tkinter import ttk
from desktop_theme import FONT, PANEL, MUTED, MINT, DANGER, heading, TextPane, wrap_labels

from speech_stream import SpeechController
from jarvis_assistant import READY_MESSAGE


def conversation_text(jarvis):
    turns = jarvis.get('conversation', [])
    messages = [f'You: {question}\nJarvis: {answer}' for question, answer in turns]
    query, answer = jarvis['query'], jarvis['response']
    if query and (not turns or turns[-1] != (query, answer)):
        messages.append('You: ' + query + '\n\n' + (jarvis['error'] or jarvis['status']))
    if jarvis.get('write_status'):
        messages.append(jarvis['write_status'])
    return '\n\n'.join(messages) or jarvis['error'] or jarvis['status'] or READY_MESSAGE


class SpeechPanel:
    def __init__(self, root, listen=False, assistant=None, preview=False):
        self.preview = preview
        self.controller = SpeechController()
        self.assistant = assistant
        self.controller.assistant = None if preview else assistant
        self.frame = tk.Frame(root, bg='#15181b', padx=18, pady=18)
        self.frame.columnconfigure(1, weight=1)
        heading(self.frame, 'Microphone', 'Local transcription · Jarvis uses Gemini').grid(row=0, column=0, columnspan=5, sticky='ew', pady=(0, 14))
        self.frame.rowconfigure(5, weight=1)
        self.button = ttk.Button(self.frame, text='Start mic', command=self.toggle, style='Primary.TButton')
        self.button.grid(row=2, column=0, sticky='w', pady=(8, 0))
        self.device = ttk.Combobox(self.frame, state='readonly', width=25)
        self.device.grid(row=1, column=0, columnspan=5, sticky='ew')
        self.devices = [None]
        try:
            if preview:
                raise RuntimeError('Preview does not enumerate microphones')
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
            self.device['values'] = ['Default laptop microphone' if preview else 'Microphone unavailable — install speech dependencies']
        self.device.current(0)
        ttk.Button(self.frame, text='Clear text', command=self.controller.clear).grid(row=2, column=1, sticky='w', padx=8, pady=(8, 0))
        self.level = ttk.Progressbar(self.frame, maximum=100, length=65)
        self.level.grid(row=2, column=2, columnspan=3, sticky='ew', pady=(8, 0))
        self.noise_enabled = tk.BooleanVar(value=True)
        self.noise_control = ttk.Checkbutton(self.frame, text='Noise suppression · RNNoise', variable=self.noise_enabled)
        self.noise_control.grid(row=3, column=0, columnspan=5, sticky='w', pady=(6, 0))
        self.status = tk.Label(self.frame, text='', bg=PANEL, fg=MUTED,
                               font=(FONT, 9), anchor='w', justify='left', wraplength=440)
        self.status.grid(row=4, column=0, columnspan=5, sticky='ew', pady=(4, 10))
        self.tabs = ttk.Notebook(self.frame)
        self.tabs.grid(row=5, column=0, columnspan=5, sticky='nsew')
        transcript_pane = TextPane(self.tabs)
        reply_pane = TextPane(self.tabs)
        self.text = transcript_pane.text
        self.reply = reply_pane.text
        self.tabs.add(transcript_pane, text='Live transcript')
        self.tabs.add(reply_pane, text='Jarvis conversation')
        self.jarvis_revision = -1
        self.jarvis_results = 0
        self.jarvis_enabled = tk.BooleanVar(value=True)
        self.read_aloud = tk.BooleanVar(value=True)
        self.type_writes = tk.BooleanVar(value=True)
        controls = tk.Frame(self.frame, bg=PANEL)
        controls.grid(row=6, column=0, columnspan=5, sticky='ew', pady=(10, 0))
        self.jarvis_controls = [
            ttk.Checkbutton(controls, text='Listen for Jarvis', variable=self.jarvis_enabled, command=self.configure_jarvis),
            ttk.Checkbutton(controls, text='Read aloud', variable=self.read_aloud, command=self.configure_jarvis),
            ttk.Checkbutton(controls, text='Typing & keys', variable=self.type_writes, command=self.configure_jarvis),
        ]
        for index, control in enumerate(self.jarvis_controls):
            control.grid(row=index // 2, column=index % 2, sticky='w', padx=(0, 12))
        actions = tk.Frame(self.frame, bg=PANEL)
        actions.grid(row=7, column=0, columnspan=5, sticky='ew', pady=(8, 0))
        self.stop_reply = ttk.Button(actions, text='Stop reply', style='Danger.TButton', command=lambda: self.assistant and self.assistant.cancel())
        self.stop_reply.pack(side='left')
        self.new_chat = ttk.Button(actions, text='New chat', command=lambda: self.assistant and self.assistant.new_conversation())
        self.new_chat.pack(side='left', padx=8)
        self.jarvis_status = tk.Label(self.frame, bg='#15181b', fg='#3ddc97', font=(FONT, 9),
                                      anchor='w', wraplength=440)
        self.jarvis_status.grid(row=8, column=0, columnspan=5, sticky='ew', pady=(3, 0))
        wrap_labels(self.frame, self.status, self.jarvis_status)
        if assistant is not None:
            self.tabs.select(self.reply.master)
        self.revision = -1
        self.error = None
        if listen and not preview:
            root.after(300, self.toggle)

    def toggle(self):
        if self.preview:
            return
        if self.controller.snapshot()['listening']:
            self.controller.stop()
            return
        try:
            index = max(0, self.device.current())
            self.controller.start(self.devices[index], noise_suppression=self.noise_enabled.get())
            self.error = None
        except Exception:
            self.error = 'Cannot start mic. Check the selected input and local speech dependencies.'

    def update(self):
        data = self.controller.snapshot()
        if self.assistant is not None and not self.preview:
            self.assistant.tick(data)
        active = data['listening']
        self.button.config(text='Stop mic' if active else 'Start mic', state='disabled' if self.preview else 'normal',
                           style='Danger.TButton' if active else 'Primary.TButton')
        self.device.config(state='disabled' if active or self.preview else 'readonly')
        self.noise_control.config(state='disabled' if active or self.preview else 'normal')
        for control in self.jarvis_controls + [self.stop_reply, self.new_chat]:
            control.config(state='disabled' if self.preview else 'normal')
        self.level['value'] = 100 * data['level']
        detail = self.error or data['error'] or data['status']
        if active:
            detail = ('● MIC ON · ' + detail)
            if self.assistant is not None and not self.assistant.audio_gate()[0]:
                detail = '● MIC ON · processing paused while Jarvis responds'
            if data['noise_suppression']:
                detail += ' · RNNoise on'
        if data['latency_ms'] is not None:
            detail += f" · last decode {data['latency_ms'] / 1000:.1f}s"
        if data['dropped']:
            detail += f" · {data['dropped']} skipped clips"
        self.status.config(text=detail, fg=DANGER if self.error or data['error'] else MINT if active else MUTED)
        if data['revision'] != self.revision:
            self.revision = data['revision']
            self.text.config(state='normal')
            self.text.delete('1.0', 'end')
            self.text.insert('end', data['text'])
            self.text.see('end')
            self.text.config(state='disabled')
        if self.assistant is not None:
            jarvis = self.assistant.snapshot()
            status = jarvis['error'] or jarvis['status']
            if self.preview:
                status = 'Say “Jarvis”, then ask a question when the microphone is on.'
            elif not active:
                status = 'Start mic, then say “Jarvis” followed by your question.'
            self.jarvis_status.config(text=status, fg=DANGER if jarvis['error'] else MINT if active and jarvis['phase'] != 'waiting' else MUTED)
            if jarvis['revision'] != self.jarvis_revision:
                self.jarvis_revision = jarvis['revision']
                content = conversation_text(jarvis)
                if content == READY_MESSAGE:
                    content = 'What would you like to know?\n\nSay “Jarvis”, then ask your question. Replies and writing requests appear here.'
                self.reply.config(state='normal')
                self.reply.delete('1.0', 'end')
                self.reply.insert('end', content)
                self.reply.see('end')
                self.reply.config(state='disabled')
                if jarvis['results'] > self.jarvis_results or jarvis['phase'] == 'collecting':
                    self.tabs.select(self.reply.master)
                self.jarvis_results = jarvis['results']

    def configure_jarvis(self):
        if self.assistant is not None and not self.preview:
            self.assistant.configure(enabled=self.jarvis_enabled.get(), read_aloud=self.read_aloud.get(),
                                     type_writes=self.type_writes.get())

    def close(self):
        self.controller.close()

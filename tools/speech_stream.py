"""Continuous local microphone capture; transcribe utterances only after a pause.

Silero runs on 32 ms frames. Parakeet runs on its own worker so inference never
blocks capture, camera rendering or glove motion. Audio stays in memory.
"""
from collections import deque
from dataclasses import dataclass
import math
import queue
import re
import threading
import time

from speech_noise import NoiseSuppressionError, RNNoiseFilter

RATE = 16000
FRAME_SAMPLES = 512
FRAME_MS = 32
FRAME_BYTES = FRAME_SAMPLES * 2
PAUSE_FRAMES = 16  # 512 ms below Silero's end-of-speech threshold.
MAX_FRAMES = math.ceil(60 * RATE / FRAME_SAMPLES)


@dataclass
class SpeechChunk:
    pcm: bytes
    voice_end: float = 0.0
    assistant_token: int = 0


class Segmenter:
    """Silero probability hysteresis, pre-roll and pause-only utterance delivery."""
    def __init__(self):
        self.pre = deque(maxlen=8)
        self.frames = []
        self.active = self.overflowed = False
        self.voiced = self.silence = 0

    def feed(self, pcm, probability):
        if len(pcm) != FRAME_BYTES:
            raise ValueError('Expected a 32 ms, 16 kHz mono PCM16 frame.')
        voiced = probability >= (.35 if self.active else .5)
        if not self.active:
            self.pre.append(pcm)
            if not voiced:
                return None
            self.active = True
            self.frames = list(self.pre)
            self.pre.clear()
            self.voiced, self.silence = 1, 0
        else:
            if not self.overflowed:
                self.frames.append(pcm)
            self.voiced += bool(voiced)
            self.silence = 0 if voiced else self.silence + 1
        if len(self.frames) > MAX_FRAMES:
            # Never force transcription mid-sentence. Discard an overlong
            # utterance and wait for a pause before accepting fresh speech.
            self.frames.clear()
            self.overflowed = True
        if self.silence < PAUSE_FRAMES:
            return None
        chunk = (SpeechChunk(b''.join(self.frames))
                 if self.voiced >= 5 and not self.overflowed else None)
        self.pre.extend(self.frames[-8:])
        self.frames = []
        self.active = self.overflowed = False
        self.voiced = self.silence = 0
        return chunk


def append_transcript(previous, text, continuation=False):
    text = ' '.join(text.split())
    if continuation and previous:
        old, new = previous.split(), text.split()
        normalize = lambda word: re.sub(r'[^\w]', '', word.casefold())
        for size in range(min(8, len(old), len(new)), 0, -1):
            if [normalize(w) for w in old[-size:]] == [normalize(w) for w in new[:size]]:
                text = ' '.join(new[size:])
                break
    if not text:
        return previous
    separator = ' ' if continuation else '\n'
    return (previous + (separator if previous else '') + text)[-16000:]


class SpeechController:
    def __init__(self):
        self.lock = threading.Lock()
        self.session_lock = threading.Lock()
        self.models = None
        self.assistant = None
        self.generation = self.epoch = 0
        self.stop_event = threading.Event()
        self.clear_event = threading.Event()
        self.state = dict(listening=False, status='Mic off · Parakeet v2 + Silero · local',
                          model='parakeet-tdt-0.6b-v2', vad='silero', local=True,
                          device=None, level=0.0, voice=False, requests=0, results=0,
                          dropped=0, pending=0, latency_ms=None, error=None, text='', revision=0)
        self.state.update(last_voice_at=0.0, last_audio_at=0.0, speech_active=False, decoding=False)
        self.state['noise_suppression'] = False

    def snapshot(self, include_text=True):
        with self.lock:
            result = dict(self.state)
        if not include_text:
            result.pop('text')
        return result

    def _set(self, generation, **changes):
        with self.lock:
            if generation == self.generation:
                self.state.update(changes)

    def _result(self, generation, epoch, text, latency, chunk=None):
        with self.lock:
            if generation != self.generation or epoch != self.epoch or not self.state['listening']:
                return
            self.state['text'] = append_transcript(self.state['text'], text)
            self.state['revision'] += 1
            self.state['results'] += 1
            self.state.update(latency_ms=latency, error=None,
                              status='Listening · Parakeet v2 + Silero · pause to transcribe')
        if self.assistant is not None and chunk is not None:
            self.assistant.transcript(text, chunk.voice_end, chunk.assistant_token)

    def clear(self):
        with self.lock:
            self.epoch += 1
            self.state.update(text='', revision=self.state['revision'] + 1)
        self.clear_event.set()
        if self.assistant is not None:
            self.assistant.cancel('Text cleared. Say Jarvis to start a new request.')

    def stop(self):
        self.stop_event.set()
        with self.lock:
            self.generation += 1
            self.state.update(listening=False, voice=False, level=0, pending=0,
                              noise_suppression=False,
                              speech_active=False, decoding=False, status='Mic off. Click Start mic to resume.')
        if self.assistant is not None:
            self.assistant.cancel('Mic stopped. Start mic, then say Jarvis.')

    def start(self, device=None, noise_suppression=True):
        import sounddevice as sd
        if self.snapshot()['listening']:
            return
        info = sd.query_devices(device, 'input')
        sd.check_input_settings(device=device, samplerate=RATE, channels=1, dtype='int16')
        with self.lock:
            self.generation += 1
            generation = self.generation
            self.state.update(listening=True, status='Loading Parakeet v2 and Silero locally…',
                              device=info['name'], error=None, pending=0, noise_suppression=False)
        stop = self.stop_event = threading.Event()
        clear = self.clear_event = threading.Event()
        threading.Thread(target=self._session,
                         args=(generation, stop, clear, device, noise_suppression), daemon=True).start()

    def _session(self, generation, stop, clear, device, noise_suppression=True):
        # Serialize restarts and cache the models. A stopped inference may finish
        # internally, but cannot publish text or open a second microphone.
        while not self.session_lock.acquire(timeout=.1):
            if stop.is_set():
                return
        capture = None
        try:
            if stop.is_set():
                return
            if self.models is None:
                from speech_models import ParakeetTranscriber, SileroStream
                self.models = (ParakeetTranscriber(), SileroStream())
            if stop.is_set():
                return
            client, vad = self.models
            vad.reset()
            clips = queue.Queue(maxsize=3)
            capture = threading.Thread(target=self._capture,
                args=(generation, stop, clear, clips, device, vad, noise_suppression), daemon=True)
            capture.start()
            self._transcribe(generation, stop, clips, client)
        except Exception:
            if not stop.is_set():
                self._set(generation, listening=False, level=0, voice=False,
                          error='Local speech engine could not start. Check model downloads and speech dependencies.',
                          status='Mic stopped')
        finally:
            stop.set()
            if capture is not None:
                capture.join()  # Release RawInputStream before allowing restart.
            self.session_lock.release()

    def _capture(self, generation, stop, clear, clips, device, vad, noise_suppression=True):
        import numpy as np
        import sounddevice as sd
        raw = queue.Queue(maxsize=100)
        overflow = threading.Event()
        segmenter = Segmenter()
        muted = False
        voice_end = 0.0
        denoiser = None
        with self.lock:
            epoch = self.epoch

        def receive(data, frames, timing, status):
            if stop.is_set():
                return
            if status.input_overflow:
                overflow.set()
            try:
                gate = self.assistant.audio_gate() if self.assistant is not None else (True, 0)
                raw.put_nowait((bytes(data), time.monotonic(), gate))
            except queue.Full:
                overflow.set()

        try:
            if noise_suppression:
                denoiser = RNNoiseFilter()
            with sd.RawInputStream(device=device, samplerate=RATE, channels=1, dtype='int16',
                                   blocksize=FRAME_SAMPLES, callback=receive):
                self._set(generation, noise_suppression=denoiser is not None,
                          status='Listening · Parakeet v2 + Silero · pause to transcribe')
                while not stop.is_set():
                    if overflow.is_set() or clear.is_set():
                        segmenter = Segmenter()
                        vad.reset()
                        if denoiser is not None:
                            denoiser.reset()
                        voice_end = 0.0
                        while not raw.empty():
                            try: raw.get_nowait()
                            except queue.Empty: break
                        if overflow.is_set():
                            self._set(generation, error='Microphone audio gap; resumed with fresh audio.')
                            if self.assistant is not None:
                                self.assistant.cancel('Microphone audio gap. Say Jarvis again.')
                        overflow.clear()
                        clear.clear()
                        with self.lock:
                            epoch = self.epoch
                    try:
                        pcm, recorded_at, (record_allowed, token) = raw.get(timeout=.1)
                    except queue.Empty:
                        continue
                    allowed, current_token = self.assistant.audio_gate() if self.assistant is not None else (True, 0)
                    if not allowed or not record_allowed or token != current_token:
                        if not muted:
                            segmenter = Segmenter()
                            vad.reset()
                            if denoiser is not None:
                                denoiser.reset()
                            voice_end = 0.0
                            muted = True
                        self._set(generation, level=0, voice=False, speech_active=False,
                                  last_audio_at=recorded_at)
                        continue
                    muted = False
                    if denoiser is not None:
                        pcm = denoiser.process(pcm)
                    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
                    rms = float(np.sqrt(np.mean(samples * samples)))
                    probability = vad.probability(samples)
                    if probability >= (.35 if segmenter.active else .5):
                        voice_end = recorded_at
                    was_overflowed = segmenter.overflowed
                    chunk = segmenter.feed(pcm, probability)
                    self._set(generation, level=min(1.0, rms * 12), voice=probability >= .5,
                              last_voice_at=voice_end, last_audio_at=recorded_at,
                              speech_active=segmenter.active)
                    if segmenter.overflowed and not was_overflowed:
                        self._set(generation, dropped=self.snapshot()['dropped'] + 1,
                                  error='Speech exceeded 60 seconds without a pause. Pause, then speak again.')
                        if self.assistant is not None:
                            self.assistant.cancel('Speech exceeded 60 seconds. Pause, then say Jarvis again.')
                    if chunk:
                        chunk.voice_end, chunk.assistant_token = voice_end, token
                        if clips.full():
                            try: clips.get_nowait()
                            except queue.Empty: pass
                            self._set(generation, dropped=self.snapshot()['dropped'] + 1,
                                      error='Transcription fell behind; skipped an old utterance.')
                            if self.assistant is not None:
                                self.assistant.cancel('Transcription fell behind. Say Jarvis again.')
                        clips.put_nowait((chunk, epoch))
                        self._set(generation, pending=clips.qsize())
        except Exception as exc:
            if not stop.is_set():
                self._set(generation, listening=False, level=0, voice=False,
                          noise_suppression=False,
                          error=(str(exc) if isinstance(exc, NoiseSuppressionError) else
                                 'Microphone capture failed. Check the selected input and Windows mic access.'),
                          status='Mic stopped')
                stop.set()
        finally:
            if denoiser is not None:
                denoiser.close()
            self._set(generation, noise_suppression=False)

    def _transcribe(self, generation, stop, clips, client):
        while not stop.is_set():
            try:
                chunk, epoch = clips.get(timeout=.1)
            except queue.Empty:
                continue
            with self.lock:
                current_epoch = self.epoch
            if stop.is_set():
                break
            if epoch != current_epoch:
                self._set(generation, pending=clips.qsize())
                continue
            began = time.monotonic()
            self._set(generation, requests=self.snapshot()['requests'] + 1, pending=clips.qsize(),
                      decoding=True, status='Listening · transcribing locally after pause…')
            try:
                text = client.transcribe(chunk.pcm, stop=stop)
                self._result(generation, epoch, text, (time.monotonic()-began)*1000, chunk)
            except Exception:
                if not stop.is_set():
                    self._set(generation, error='Local transcription failed for this utterance. Try a shorter phrase.',
                              status='Listening · pause to transcribe')
                    if self.assistant is not None:
                        self.assistant.cancel('Transcription failed. Say Jarvis and try again.')
            finally:
                self._set(generation, decoding=False, pending=clips.qsize())

    close = stop


"""CPU ONNX inference for NVIDIA Parakeet TDT 0.6B v2 and Silero VAD.

Pinned converted weights are downloaded once, then loaded from local cache.
No audio, transcript or API credential is sent to any service.
"""
from pathlib import Path
import numpy as np

from speech_stream import FRAME_SAMPLES, RATE, append_transcript

PARAKEET_REPO = 'istupakov/parakeet-tdt-0.6b-v2-onnx'
PARAKEET_REVISION = '0bbb45a3365852604aef28b538a8f066f4ccaa85'
SILERO_REPO = 'istupakov/silero-vad-onnx'
SILERO_REVISION = 'b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6'


def model_file(repo, revision, filename):
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    try:
        return hf_hub_download(repo, filename, revision=revision, local_files_only=True)
    except LocalEntryNotFoundError:
        return hf_hub_download(repo, filename, revision=revision)


def session_options(threads):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    options.add_session_config_entry('session.inter_op.allow_spinning', '0')
    return options


class ParakeetTranscriber:
    def __init__(self):
        import onnx_asr
        files = ('config.json', 'vocab.txt', 'encoder-model.int8.onnx', 'decoder_joint-model.int8.onnx')
        paths = [model_file(PARAKEET_REPO, PARAKEET_REVISION, name) for name in files]
        self.model = onnx_asr.load_model('nemo-parakeet-tdt-0.6b-v2', path=str(Path(paths[0]).parent),
            quantization='int8', providers=['CPUExecutionProvider'], sess_options=session_options(4))

    def transcribe(self, pcm, stop=None):
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        text, start = '', 0
        # Subdivide long utterances only AFTER Silero finds the pause.
        limit, overlap = 20 * RATE, RATE // 4
        while start < len(samples):
            if stop is not None and stop.is_set():
                return ''
            end = min(start + limit, len(samples))
            result = self.model.recognize(samples[start:end], sample_rate=RATE)
            text = append_transcript(text, result, continuation=start > 0)
            if end == len(samples):
                break
            start = end - overlap
        return text


class SileroStream:
    """Stateful 512-sample Silero inference with 64-sample context at 16 kHz."""
    def __init__(self):
        import onnxruntime as ort
        path = model_file(SILERO_REPO, SILERO_REVISION, 'silero_vad.onnx')
        self.model = ort.InferenceSession(path, sess_options=session_options(1), providers=['CPUExecutionProvider'])
        self.reset()

    def reset(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def probability(self, samples):
        if samples.shape != (FRAME_SAMPLES,):
            raise ValueError('Silero needs exactly 512 samples at 16 kHz.')
        frame = np.concatenate((self.context, samples.reshape(1, -1)), axis=1)
        output, self.state = self.model.run(['output', 'stateN'],
            {'input': frame, 'state': self.state, 'sr': np.array([RATE], dtype=np.int64)})
        self.context = frame[:, -64:].copy()
        return float(output[0, 0])

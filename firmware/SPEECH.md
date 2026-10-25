# Local speech in the camera viewer

The viewer continuously reads the selected laptop microphone, uses **Silero VAD**
to detect a pause, then transcribes that utterance with **Parakeet TDT 0.6B v2**.
Text appears in the speech panel after each pause. This is English transcription
on this laptop, independent of the glove and camera Bluetooth connections.

Click **Start mic** to listen or **Stop mic** to release the microphone. A visible
**MIC ON** indicator, input selector and level meter show what is active.
**Clear text** clears the transcript and discards older queued/in-flight results.
Closing the viewer stops capture. **Esc** pauses the glove pointer; it does not
stop the microphone. A normal launch starts with the mic off; use `-Listen` to
start listening immediately:

```powershell
./tools/Start-Bluetooth-Camera.ps1 -Listen
```

Install with the same Python runtime used by the launcher:

```text
python -m pip install -r tools/requirements-speech.txt
```

The CPU runtime is ONNX Runtime, using the INT8 ONNX conversion of NVIDIA's
Parakeet v2 weights. The model is loaded once per viewer, reused on microphone
restarts, and uses four inference threads. Silero has one thread. This supports
the laptop's AMD hardware without requiring CUDA or PyTorch.

Model downloads happen once (about 664 MB total) into the Hugging Face cache.
Subsequent loads read the cache first, including when offline. Both model
revisions are pinned in `tools/speech_models.py`. The application does not read
the old Groq API key or call Groq. Audio and transcripts stay in memory on the
laptop; the transcription box holds up to 16,000 characters.

## Pause detection

- Input: mono PCM16, 16 kHz, 512-sample/32 ms frames.
- Silero retains recurrent state and 64 samples of context between frames.
- Speech starts at probability 0.5 and continues down to 0.35.
- 256 ms pre-roll preserves the start of words.
- 512 ms of quiet ends an utterance; at least 160 ms of detected speech is required.
- There are no periodic mid-sentence requests. Text appears after the pause plus
  local inference time, not word by word while speaking.
- Utterances over 20 seconds are split internally for bounded inference memory,
  with 250 ms overlap, only after the pause has occurred.
- After 60 seconds without a pause, the oversized utterance is discarded with a
  visible message; a pause resets capture. At most three completed utterances
  wait for inference. If processing falls behind, the oldest is skipped and
  the UI reports that count.
- Capture and inference run separately from Tk, camera and motion processing.
  Stop/Clear discard late results. Rapid restarts serialize microphone access.

The glove-mounted microphone is not implemented yet. A microphone exposed as a
computer audio input can be selected from the input dropdown later.

## Verification

The real Silero + Parakeet pipeline recognized the synthetic test phrase
“Testing the Synchro glove microphone. Speech appears in the camera viewer.”
as two utterances separated by a detected pause. Local decode took 0.112 and
0.106 seconds for 2.72 and 2.624 seconds of buffered audio on this laptop.
Model initialization took 3.16 seconds from cache. These are synthetic test
measurements, not guaranteed latency or accuracy for every speaker/environment.

Automated regressions cover pause-only segmentation, silence, hysteresis,
long-utterance limits, local PCM normalization, recurrent VAD state, and
discarding results after Stop/Clear or during model loading. The full project
suite currently passes 84 tests.

Sources and attribution:
[NVIDIA Parakeet TDT 0.6B v2, CC-BY-4.0](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2),
[ONNX conversion](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx),
[Silero VAD](https://github.com/snakers4/silero-vad),
[Silero ONNX weights](https://huggingface.co/istupakov/silero-vad-onnx),
[onnx-asr](https://istupakov.github.io/onnx-asr/usage/).


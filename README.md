# Synchro

Synchro is the local gesture application. The Mac app in `camera/synchro_mac/` is the main window: the native camera viewer plus Gestures, Test, and Settings. The browser UI in `frontend/` is the same gesture pages when you are not in that window.
**All demo-generated motion is synthetic**. Do not claim gesture accuracy on real users from the included tests. The browser cannot open the ESP32-CAM. Capture Photo only asks the already-running native viewer for a JPEG.

## Run on a Mac

Requires Python 3.10+, Node.js, and a browser.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

The hardware window for both macOS and Windows is separate from that site. A browser cannot open the camera radio or the glove. From this folder, with the virtual environment active:

```bash
python -m desktop
```

That opens one Synchro window. Camera uses the Mac layout. Data shows the Windows glove readings: roll, pitch, relative yaw, index and middle contacts, samples per second, temperature, calibration, packet errors, and the latest six axes. USB glove reads work on both systems. Bluetooth Classic camera capture from this window works on Windows. On a Mac, Python has no Bluetooth Classic socket, so the camera radio stays in `camera/synchro_mac`.

The server reads `GEMINI_API_KEY` from the environment or from a `.env` file in this folder. It does not override a variable that is already set, and it never sends the key to the browser.

```bash
cp .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY` to a key from [Google AI Studio](https://aistudio.google.com/apikey). Restart uvicorn after changing it. The default vision model is `gemini-3.8-flash`. Speech-to-text uses `gemini-3.5-transcribe`. Both can be overridden with `GEMINI_VISION_MODEL` and `GEMINI_STT_MODEL`.

Without a key, image upload and the Camera page still load. Ask AI and transcription return a missing-key error. No test in this repository calls Gemini.

For frontend development with a live reload, keep the API running and use:

```bash
cd frontend
npm run dev
```

That serves http://127.0.0.1:5173 and proxies `/api` and `/ws` to port 8000.

The previous studio page remains at http://127.0.0.1:8000/legacy. Distances are DTW distances, not confidence percentages. Recordings live in `data/visionglove.sqlite3` and `data/recordings.jsonl`. Do not delete those files to “reset” unless you intend to drop saved gestures.

Run tests:

```bash
python -m pytest -q
```

## What is real and what is mocked?

- **Real code:** Data schema validation, timestamp checks, interpolation, multivariate DTW, label templates, heuristic rejection thresholds, FastAPI routes, WebSocket transport, SQLite gesture/recording persistence, JSONL import/append, start/stop capture of the live synthetic feed, browser UI, Gemini visual question answering, and Gemini speech-to-text. The gesture engine is unchanged.
- **Mocked:** MPU6050 readings. The simulator produces mathematical gesture-like patterns with noise; these are *not* measured physics or a reliable predictor of real-world recognition. Assistant tests use fake vision and speech providers and do not call Gemini.
- **Not implemented:** Browser Bluetooth Classic, a second camera connection, physical glove streaming, gesture-to-action execution, model quantization, sensor calibration, authentication, calibrated confidence, and reliable continuous recognition. Capture Photo works only while the native viewer already holds the camera.

## Hardware input contract (send to your teammate)

At each IMU sample, send a JSON line of this shape (USB serial initially):

```json
{"t_ms":1234.0,"ax":0.1,"ay":-0.3,"az":9.8,"gx":0.02,"gy":0.4,"gz":-0.1}
```

- `t_ms`: milliseconds since device start, monotonic within a recording
- `ax,ay,az`: acceleration **m/s²**
- `gx,gy,gz`: angular velocity **rad/s**
- Sampling: nominally **50–100 Hz**, timestamps included
- Return **raw measurements** rather than gesture guesses
- Supply **one dedicated gesture recording button/contact**, and send button state as an additional field (optional initially)
- Send `source: hardware` when imported into this app, and preserve units

The original glove diagram was not electrically verified. Use a board pinout and electrical review before connecting hardware.

## REST interface

- `GET /api/status` — list labels and training state, plus gestures and any active recording
- `GET/POST /api/gestures` — list or create a custom gesture (`{"name":"flick_right"}`)
- `PATCH /api/gestures/{id}` — rename a gesture
- `DELETE /api/gestures/{id}` — delete a gesture and its SQLite recordings
- `POST /api/sessions` — create a recording session id
- `POST /api/recordings/start` — arm capture: `{"gesture_id":"...","source":"synthetic"}`
- `POST /api/recordings/stop` — save samples actually emitted while armed
- `GET /api/recordings` and `GET /api/recordings/{id}` — list/retrieve stored recordings
- `POST /api/demo/generate` — generate labeled synthetic examples: `{"label":"circle","motion":"circle","examples":10}`
- `POST /api/train` — build DTW templates and thresholds
- `POST /api/demo/predict/circle` — predict a new synthetic trial
- `POST /api/recordings` — supply real/phone/dataset samples in the schema below
- `POST /api/predict` — classify an arbitrary list of samples
- `GET /api/assistant/status` — model names and whether a key is configured; the key is not included
- `POST /api/assistant/ask` — multipart image plus question; the image is discarded after the response
- `POST /api/assistant/transcribe` — multipart audio from push-to-talk; the clip is discarded after the response
- `GET /api/camera/bridge` — whether the native viewer is publishing frames
- `GET /api/camera/capture` — one JPEG from that viewer, or 503 when it is not live
- `WS /ws/telemetry` — simulated live feed

Gesture metadata lives in `data/visionglove.sqlite3`. Raw sequences are stored as validated JSON in that database. Existing `data/recordings.jsonl` lines are imported on startup and are not deleted.

Example real recording upload:

```json
{
  "label": "flick_right",
  "source": "phone",
  "samples": [
    {"t_ms": 0, "ax":0, "ay":0, "az":9.81, "gx":0, "gy":0, "gz":0},
    {"t_ms":20, "ax":0.1, "ay":0, "az":9.81, "gx":0, "gy":0, "gz":0.2}
  ]
}
```

The short two-sample example above documents the field shape only. The API needs at least **8** samples; normal real gestures will have many more. For a phone, check whether acceleration includes gravity, device frame, and sensor units, and convert consistently before uploading.

## Camera viewer

Open the Mac app with `bash camera/synchro_mac/Start-Mac.command`. Camera uses Bluetooth Classic directly. Gestures, Test, and Settings load the local service at http://127.0.0.1:8000 and start it when it is not already running. The camera protocol does not go through the gesture engine.

While the viewer is running it listens on `127.0.0.1:8765` and can hand its latest JPEG to FastAPI. That socket does not open a second Bluetooth session. The browser Camera page uses it for Capture Photo. If the viewer is closed, upload an image instead. A frame from that socket is a real camera JPEG only after the viewer is showing a live picture. The simulated protocol tests do not measure the radio. Hardware checks are in `camera/CAMERA_TESTING.md`.

## Next milestones

1. Add a `serial_reader.py` using `pyserial` to parse the teammate's newline-delimited stream into the same dict structure.
2. Build a **real recording UI** controlled by a button held during each gesture.
3. Import **actual** phone or glove recordings; establish train/test recording-session splits.
4. Introduce an `idle` / `unknown` rejection dataset, tune thresholds on separate sessions, and report accidental activation rates.
5. Add optional scikit-learn Random Forest and a gesture-to-action map.

## About gpt-oss:20b

Use your Mac's local coding assistant to extend this Python starter. You do **not** need to ask the language model to interpret streaming IMU samples. For real-time classification, DTW/scikit-learn will be faster, cheaper, and easier to benchmark.

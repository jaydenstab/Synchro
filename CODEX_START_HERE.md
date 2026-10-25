# MASTER PROMPT — paste into Codex in the project root

You are the senior engineer and implementation agent for VisionGlove Studio, a hackathon application for **user-trainable gesture recognition**. You have permission to inspect files, edit this project's code, run local tests and run local development servers. Implement the software; do not respond with only plans or pseudocode.

CONTEXT:
- I am on macOS using a local Ollama gpt-oss:20b through Codex.
- My teammate is building the physical Arduino Nano ESP32 + MPU6050 glove; I do NOT have the hardware yet.
- This folder contains an existing runnable FastAPI starter with `app.py`, `engine.py`, `simulator.py`, `static/index.html`, `tests/test_engine.py`, and `README.md`. Read the files before changing anything.
- A gesture is an arbitrary *repeatable* time-series pattern (ax, ay, az, gx, gy, gz); labels are user-defined. No LLM is required to recognize gestures.
- The product should later accept real wrist sensor data without changing its ML/business logic. All synthetic results must be obviously labeled as synthetic, never passed off as real accuracy.

TARGET EXPERIENCE:
1. Open a polished local dashboard.
2. See six live graphs with a visible input-source indicator and connection status.
3. Create a gesture name, record/import several labeled examples, and review those recordings.
4. Train/retrain a DTW personalized recognizer, reject unfamiliar motions and display per-class distances (NOT fake confidence percentages).
5. Test recognition on separate data; inspect events and recognition history.
6. Bind recognized gestures to **safe in-app actions**, e.g., switch a demo slide, rotate a simple 3D object, or change UI panels.
7. Later choose Hardware input via a stable adapter rather than rewriting the app.

TECH CHOICES:
- Backend: Python 3.10+, FastAPI, Pydantic, NumPy, SciPy only if needed, pytest; pyserial for optional later serial interface.
- Frontend: React + TypeScript + Vite, lightweight modern responsive design; simple CSS or Tailwind if easy. Use Recharts or uPlot for telemetry, limit memory and graph update rates.
- Store metadata and labels in SQLite if needed; raw recordings as validated JSON/JSONL or NumPy files; don't expose private data over the internet.
- Default run must work locally and fully offline with **no OpenAI API key and no ESP32**. You may add an optional ML classifier later but DTW remains the baseline.

MANDATORY DATA CONTRACT:
`{"t_ms":1234.0,"ax":0.1,"ay":-0.2,"az":9.81,"gx":0.05,"gy":0.0,"gz":-0.1}`
- t_ms monotonic ms within each recording.
- Acceleration m/s², gyro rad/s, with a documented sensor axes orientation.
- Source one of synthetic / phone / public_dataset / hardware.
- Aim for 50–100 Hz actual sample frequency and use time stamps, not inferred evenly spaced sampling.
- Do not blindly remove 9.81 only from z for arbitrary real IMU orientation. The existing `engine.py` does that as a synthetic shortcut: refactor/preprocess carefully and add tests.

SYSTEM ARCHITECTURE:
`Input adapters (Synthetic/Imported CSV/USB Serial stub) -> typed sample validation + unit conversion -> session-aware recorder -> preprocessing/segmentation -> DTW trainer/evaluator -> prediction/rejection + cooldown -> action router -> REST/WebSocket -> React dashboard`

REQUIRED BEHAVIOR:
- Preserve all working existing functionality until its replacement is tested.
- Never show model 'accuracy' calculated only from synthetic generator samples as real-world performance.
- Allow a new user label to be created. It does NOT imply the system can recognize an arbitrary novel gesture without recordings.
- Support an explicit arm/record switch and manual stop. No accidental autonomous OS actions.
- Include `unknown` as an output when incoming motion is dissimilar; include negative/idle movement examples and rejection-tuning hooks.
- Include validation of sample units/finite numbers, timestamp order, duration, record limits; friendly errors.
- Separate data into training/test by recording SESSION, not shuffled overlapping windows.
- Provide real tests that exercise the backend and verify the correct source labels, model behavior, unknown rejection and API errors.
- Keep APIs backward-compatible if possible: `GET /api/status`, `POST /api/demo/generate`, `POST /api/train`, `POST /api/demo/predict/{motion}`, `POST /api/recordings`, `POST /api/predict`, `WS /ws/telemetry`.
- Add meaningful logging and clean startup/shutdown, not infinite loops accumulating leaked connections.

MILESTONE A — DO THIS FIRST AND GET IT WORKING:
1. Audit the current project. Identify the existing code and limitations. Give a concise implementation plan in your internal work, then change the files.
2. Formalize a validated IMU sample schema and introduce source/input adapter interfaces; keep the synthetic adapter working.
3. Add recording/session metadata; support a start/stop recording workflow and saving labeled recordings. For synthetic mode, say 'generated examples'; never pretend user movements were recorded.
4. Refactor preprocessing so real IMU orientation isn't hard-coded as gravity only on z. Preserve synthetic test behavior and compare before/after recognition.
5. Add a source-aware React + TypeScript dashboard with pages/tabs: Live Sensor, Gesture Library / Record, Train / Evaluate, Live Test, Actions. Use real API calls and live WebSockets, not static props.
6. Train DTW on stored examples and return readable distance-based rejection results. Include a demonstration 'unknown' movement.
7. Build a simple action router with at least two in-app actions, and show execution log. Require user arming for actionable predictions.
8. Update README with exact macOS setup/run/test commands, and distinguish hardware-free from real-data tests.
9. Run backend tests, frontend type-check/build; fix failures and report actual commands/outcomes.

MILESTONE B — AFTER A WORKING A, IF THERE IS TIME:
- CSV import with column mapping and optional unit conversion (including phone exports); include preview and rejection of malformed data.
- A serial adapter using pyserial parsing newline-delimited JSON from Nano ESP32, with configurable port/baud, graceful missing-device handling and a mock/test transport. Never require real serial hardware for tests.
- Per-user/session train/test metrics (confusion matrix, false positives per minute on idle streams, recognition latency). Never fabricate metrics.
- Gesture quality analyzer based on intra-class and inter-class DTW distances, clearly explaining uncertainty.

MILESTONE C — OPTIONAL STRETCH, ONLY AFTER A/B TESTED:
- A scikit-learn Random Forest baseline with features from recordings and a fair comparison against DTW.
- A genuinely manipulable Three.js cube or classroom presentation demo responding to gesture events.
- Model artifact versioning and explicit user-driven retraining.

IMPORTANT PROCESS RULES:
- Focus on finishing Milestone A end-to-end before attempting Milestone B or C.
- Break the work into small, runnable edits; a local 20b model can struggle with huge cross-cutting patches.
- Before making changes, inspect the codebase and capture current test results. Never silently delete original files, change hardware assumptions, or remove tests.
- Do not add API keys, unnecessary cloud services, paid AI providers or arbitrary system-command execution.
- If something is blocked, implement a working fallback and document the limitation; do not stop at a placeholder UI.
- Whenever finishing a milestone, show: implemented features, changed files, commands run, actual test outcomes, how I can manually verify it, what remains, and the NEXT exact prompt you recommend.

Begin implementing **Milestone A, steps 1–3 only** now. Run tests and confirm that the current simulated demo still works. Stop after a working, testable checkpoint and summarize. I will instruct you to continue afterward.

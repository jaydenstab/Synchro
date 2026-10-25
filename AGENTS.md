# VisionGlove Studio — project instructions for Codex

You are modifying an existing runnable Python/FastAPI synthetic gesture-recognition prototype. Read README.md, app.py, engine.py, simulator.py, static/index.html and tests/test_engine.py before changes. Do not replace a functioning application with a mockup.

## Project objective
Build a usable Mac and Windows app for the Synchro glove. Firmware, wiring, `SYNIMU1` decode, USB/BLE motion, the Windows pointer, and local speech live in this repo. Gesture recognition stays in the app but is not the current hardware milestone. Keep the FastAPI server and React UI working without a glove attached. The Mac camera radio stays in `camera/synchro_mac`. Do not replace that window with the Tk viewer in `tools/`.

## Priorities
1. Maintain a genuinely executable, testable FastAPI + DTW engine and synthetic input mode.
2. Cleanly separate input adapters from normalization, recording, training, prediction and actions.
3. Add actual recording/import/training functionality, not solely animated UI.
4. Use clear provenance for all data: `synthetic`, `phone`, `public_dataset`, `hardware`. Synthetic test results NEVER establish real-world recognition quality.
5. Build good tests, documentation, error messages, and responsive visual feedback.
6. Integrate USB serial and optional BLE/Wi-Fi adapters later, after the adapter contract is stable.

## Sensor contract
Sample object `{ "t_ms": 0, "ax": 0.0, "ay": 0.0, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.0 }`.
- `t_ms` is monotonic milliseconds within a recording.
- Acceleration in m/s^2 and angular rate in rad/s, device axes documented.
- Typical target 50–100 Hz; actual timestamps mandatory.
- Button arm/record state can be an additional optional field.
- Never assume gravity always lies entirely on the positive z-axis for real sensors. The existing engine.py subtracts 9.81 from z, which is ONLY a simulator assumption and must be isolated or replaced with an orientation-aware, testable preprocess step for real recordings.
- Handle missing/invalid units, NaN/infinity, duplicated/reversed timestamps and excessively long inputs.

## ML and safety-critical functionality
- Start with user-template DTW for rapid personal gesture learning; use limited, explicit threshold/rejection logic; label unknowns as `unknown`.
- Do not describe distance or arbitrary scores as calibrated confidence/probability. Calibrate thresholds on separately recorded examples/negative motions when possible.
- Include `idle`/negative movement samples, arming mechanism, cooldown and duplicate-event suppression.
- Evaluate by independent recording session / held-out example, never splitting overlapping windows across train and test.
- Separate intentional gestures from actions. Default actions operate INSIDE the app (e.g., change tab, rotate demo model, next simulated slide); do not run arbitrary shell commands, OS automation, or destructive actions from untrusted predictions.
- Future hardware power/wiring should not be inferred from previous illustrations; the teammate must verify board pinouts and voltage compatibility.

## Engineering expectations
- One milestone per change; don't attempt the entire product in one enormous patch.
- Inspect existing routes and preserve them, or document/migrate intentionally and update tests.
- Make meaningful changes to real files, run tests, and fix failures.
- Use consistent API schemas and environment configuration. Don't require external tokens or cloud accounts for the core app.
- Reuse current Python code first. When adding React + Vite, preserve FastAPI endpoints and supply simple commands to start both.
- Add tests for parsing, normalization, gesture engine, rejection, API validation and input-source adapters.
- At the end of a task, report changed files, commands run, passing/failing tests, what's real vs simulated, limitations, and exact next task. Never claim successful execution unless observed.

## First priority
Keep the FastAPI backend, the React frontend, and the Mac camera viewer working. Do not add a second desktop shell or restore removed checkpoints.

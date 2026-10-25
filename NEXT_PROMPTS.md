# Follow-up prompts for the SAME Codex conversation

These prompts are intentionally incremental; use one after the previous stage has been validated.

## Prompt 2 — Backend recognition and safety of inputs
Continue the VisionGlove project. Read current code and AGENTS.md. Implement Milestone A steps 4, 6 and the backend part of 7 from CODEX_START_HERE.md. Specifically: refactor gravity/preprocessing without assuming real sensor z points up; preserve DTW synthetic tests; support training on properly labeled recordings, negative/idle/unknown handling, distance-based rejection (do not call it probability), arm/disarm state, cooldown and safe in-app actions with event logs. Write tests for timestamp ordering, finite values, unknown rejection, and no action when disarmed. Run pytest and fix failures. Keep backward-compatible routes. Report changed files and test results.

## Prompt 3 — React frontend
Continue. Build the React + TypeScript + Vite dashboard specified in the master prompt and AGENTS.md. Screens: six-axis live charts with source badge, recording wizard and recording library, DTW train/evaluate, live test prediction inspector, action bindings and event history. All buttons must call working backend endpoints. Never label generated samples as recordings of my physical movements. Show loading/error/empty states; support a clean Mac local startup. Keep the existing static UI as fallback until the new frontend builds. Run backend tests and frontend npm build / TypeScript type-check, and document commands.

## Prompt 4 — Real sensor adapters
Continue. Add a serial adapter using pyserial for newline-delimited JSON samples in the documented `t_ms, ax, ay, az, gx, gy, gz` units, plus a fake serial stream used in automated tests. Add start/stop recording from incoming serial samples, source labels, port/baud selection, and disconnect/reconnect handling. Do not assume the physical glove exists. Ensure all real-data features work with a mock serial source first. Explain the exact data contract for my hardware teammate.

## Prompt 5 — Model evaluation and gesture quality
Continue. Add session-aware train/test evaluation so recordings from one session are not mixed across train and test. Show a confusion matrix, rejection rate, unknown false-positive rate, and timing measurements only when actual evaluation data exists; no fabricated scores. Add gesture quality warnings when same-class examples vary widely or overlap other classes. Build a simple CSV/phone-data importer with column mapping, unit conversion and validation. Run tests.

## Prompt 6 — Hackathon wow-factor
Continue. Add a Three.js demo scene with a rotatable cube and a demo slide deck. Bind recognized gestures to rotate, next slide, previous slide and change modes via the safe in-app action engine. Include a live action trace showing recognized gesture, distance to known templates, accepted/rejected, and action. The scene must work with synthetic input and later hardware. Keep everything offline by default. Run tests and frontend build.

## Diagnostic prompt (when Codex gets stuck)
Stop adding features. Review your last changes and list failures. Run the backend tests and frontend build, and reproduce the current error. Fix ONE error at a time. Do not rewrite the whole app, delete working files, or fabricate test results. Once tests pass, describe precisely what was changed and how I can confirm it in the UI.

## Hardware integration message to teammate
Please make the Nano ESP32 send one JSON object per line over USB serial containing `t_ms` (monotonic milliseconds), `ax,ay,az` (m/s²) and `gx,gy,gz` (rad/s) at approximately 50–100 Hz. Document your mounted sensor axis directions, actual sample rate, serial baud, and whether acceleration includes gravity. Also send optional `button_pressed`/`armed` state if available. Don't send one of the gesture names; I need raw samples for my classifier. Please verify board electrical compatibility before connecting power.

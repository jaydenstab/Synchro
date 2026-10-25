# Synchro — project instructions

You are modifying the Windows Synchro desktop app, developed on a Mac. Read README.md, tools/bluetooth_viewer.py, tools/motion_sensor.py before changes. Do not replace a functioning application with a mockup.

## Project objective
Build a usable Windows app for the Synchro glove. Firmware, wiring, `SYNIMU1` decode, USB/BLE motion, the Windows pointer, and local speech live in `firmware/` and `tools/`. Windows uses the existing native Tk viewer in `tools/bluetooth_viewer.py`. The Mac app has been removed. Use `--preview` on the Windows viewer for UI development on a Mac; it must not open hardware or invent data. The React/FastAPI web layers have been removed; do not restore them. Preserve the native Jarvis, RNNoise, read-aloud, conversation, and explicit writing-request features from test commit 721891c, as requested by the user. Jarvis is optional; core camera/glove/local speech must work without a cloud key. Exact Windows rendering and hardware acceptance require a Windows session.

Gesture recognition is out of scope until a later milestone. Do not add a DTW engine, gesture library, recording store, synthetic gesture feed, or gesture pages.

## Priorities
1. Keep the teammate hardware tree in `firmware/`, `hardware/`, and `tools/` working.
2. Keep the Windows desktop viewer and its hardware-free development preview working.
3. Use clear provenance for hardware data. A missing glove stays an empty panel. Do not fill it with simulated gestures.
4. Build good tests, documentation, error messages, and responsive visual feedback.
5. Default actions stay inside the app. Do not run arbitrary shell commands or OS automation from the UI.

## Engineering expectations
- One milestone per change; don't attempt the entire product in one enormous patch.
- Inspect existing routes and preserve them, or document/migrate intentionally and update tests.
- Make meaningful changes to real files, run tests, and fix failures.
- Use consistent API schemas and environment configuration. Don't require external tokens or cloud accounts for the core app.
- Reuse the Python in `tools/` first. The Windows viewer uses MotionSensor and the existing pointer/speech controllers directly.
- At the end of a task, report changed files, commands run, passing/failing tests, what's real vs simulated, limitations, and exact next task. Never claim successful execution unless observed.

## First priority
Keep the Windows Tk desktop app working. Mac is a development host only. Do not add a second desktop shell or restore removed checkpoints. Do not restore the gesture prototype.

# Synchro for Windows

Synchro is a native Windows desktop app built on the working Tk viewer from the
`test` branch. Firmware, wiring, USB/BLE motion, pointer control, and local speech
live in `firmware/`, `hardware/`, and `tools/`. Mac is a development host; the
separate native Mac app and its helper have been removed.

## Windows

Install 64-bit Python 3.12 with Tcl/Tk and enable Bluetooth. From this folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\bluetooth_viewer.py --address 70:4B:CA:46:52:22 --motion-transport ble
```

Replace the address for another camera. Pair Synchro-Cam-BT in Windows first;
get its PIN from the project owner. Only one computer can use the camera at a
time. The glove advertises separately as Synchro-Glove.

The camera preview sits beside Glove and Speech & Jarvis tabs. Drag the divider to resize.
Start/Stop affects the camera; glove and speech work independently. Use
Pause pointer to stop cursor movement, held buttons, and scrolling. Esc only
stops in-progress Jarvis typing; it does not stop the pointer. The header shows microphone activity on both tabs.
Save photo writes to `.local/bluetooth-photos/` with the chosen rotation.

For the PowerShell launcher, copy `bluetooth-camera.example.json` to
`.local/bluetooth-camera.json` and set `bt_address`, then run
`tools/Start-Bluetooth-Camera.ps1`. Options: `-Console`, `-MotionTransport ble`,
`-Listen`, `-PausePointer`. The last option starts with the pointer paused and
the Glove tab hidden; Show motion and cursor controls reveals it. The launcher prefers this project's .venv and opens the desktop window directly.

Glove calibration needs warmup and a 15-second stationary measurement. Click
Enable pointer after calibration while holding a comfortable neutral pose. Hold
thumb/index for left drag or thumb/middle for right drag; release to let go.
Hold both contacts and tilt up/down to scroll. Sensitivity is shown in pixels per
degree. Cursor injection and text insertion use the existing Windows implementation.

Speech uses local Parakeet/Silero models with optional RNNoise suppression.
The first microphone start downloads approximately 664 MB of model weights;
later starts use the cache. Local transcription needs no API key. Allow microphone
access when prompted, then speak and pause to see the Live transcript.
Change Noise suppression before starting the microphone.

## Jarvis

The Speech & Jarvis tab keeps both Live transcript and Jarvis conversation views.
Listen for Jarvis, Read aloud, Type writing requests, Stop reply, and New chat
retain the implementations from the latest test branch. Say “Jarvis” followed by
a question; terminal punctuation in the recognized transcript submits it.

Jarvis camera questions use a fresh, rotation-corrected camera frame and the Gemini
API. Configure your own key on Windows with
`.\.venv\Scripts\python.exe tools\gemini_secrets.py`, or set `GEMINI_API_KEY`.
Core camera, glove, and local transcription work without a cloud account.
See [firmware/JARVIS.md](firmware/JARVIS.md) for exact behavior and credential setup.

Conversation context lasts until New chat or app shutdown. Read aloud uses the
Windows voice. Explicit write/type requests can insert text into a selected
writable field; ordinary answers are not typed. The Type writing requests checkbox
controls insertion. Stop reply cancels a pending reply. These native assistant
features do not depend on a web interface or local FastAPI server.

## Preview while developing on a Mac

Install Python with working Tcl/Tk support and the project dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/bluetooth_viewer.py --preview
```

This opens the actual Windows viewer widgets, layouts, and tabs on your Mac.
The title and connection status identify it as a UI preview. No camera, glove,
microphone, pointer, cloud, playback, or typing operations are started. Hardware controls are disabled;
readings stay empty. No test feed is injected. No camera address is required.
`--preview` cannot be combined with `--listen` or `--probe`.

Tk uses the host operating system's fonts, window chrome, and scaling. A Mac
preview verifies layout and navigation; it does not reproduce Windows rendering
exactly. To test as a Windows user, run the app inside Windows in a VM on your
Mac or on a Windows PC. Run the commands in the Windows section there, first
without hardware, then with devices connected to that Windows environment.
Windows on ARM needs compatible device drivers; virtualized Bluetooth/USB can
also differ from a physical Windows laptop. Final radio/driver acceptance needs
real hardware on a supported Windows installation.

## Tests

```bash
.venv/bin/python -m unittest discover -s tools -p 'test_*.py' -q
```

Use `.venv\Scripts\python.exe` on Windows. To include the native Tk layout/control check, set
`SYNCHRO_TEST_DESKTOP=1` (`$env:SYNCHRO_TEST_DESKTOP='1'` in PowerShell).
These tests use packet fixtures and simulated protocol bytes; they do not prove
physical radio performance. Runtime readings stay empty without hardware.

Next acceptance task: connect real camera/glove hardware on Windows, verify
USB/BLE freshness and calibration, then verify Windows cursor movement, dragging,
scrolling, and pause. Test microphone/RNNoise, Jarvis replies and read-aloud,
Stop reply/New chat, and writing into an explicitly selected test field. Windows DPI/layout and launcher execution must also
be checked on Windows.

## Source layout

- `tools/bluetooth_viewer.py`: native Windows app, including `--preview`.
- `tools/desktop_theme.py`: consistent colors, controls, and type styles.
- `tools/motion_*.py`: original sensor, transport, calibration and pointer stack.
- `tools/speech_*.py`: local speech, RNNoise, and UI.
- `tools/jarvis_assistant.py`, `tools/text_writer.py`: native Jarvis and Windows writing.
- `firmware/`, `hardware/`: firmware, protocol documentation and wiring.
- `HANDOFF.md`: hardware context and historical bring-up notes.

Hardware baseline: `jaydenstab/Synchro`, `test` commit
`721891c2278a04de3098fd94961e0acaa670fd8e`. Hardware processing modules and firmware
remain unchanged. The Windows presentation has been updated for consistency.
Private credentials, captures, calibration profiles and model caches stay local.

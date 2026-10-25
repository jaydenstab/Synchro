# Synchro for Windows

Synchro is a native Python/Tk desktop app for the Synchro glove and Bluetooth
camera. It combines camera video, USB/BLE motion, calibration, Windows pointer
control, local transcription, and an optional Jarvis voice assistant.

Windows is the product target. Mac is a development host with a hardware-free
preview of the same interface. There is no separate Mac app, browser interface,
FastAPI server, or packaged Windows installer in this source tree.

## Install and run on Windows

Install 64-bit Python 3.12 with Tcl/Tk and enable Bluetooth. From the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools\bluetooth_viewer.py --address 70:4B:CA:46:52:22 --motion-transport auto
```

That address belongs to the demo camera; replace it for another unit. Pair
**Synchro-Cam-BT** in Windows first and obtain its PIN from the owner. Only one
viewer should connect to the camera at a time. The glove advertises separately
as **Synchro-Glove**. Auto motion transport prefers a connected Nano USB device,
then tries BLE. Use `--motion-transport ble` to require BLE explicitly.

A missing glove or camera leaves its readings empty and reports connection
status. Camera connection warnings are expected during speech-only use. The
microphone starts off unless `--listen` is supplied. No cloud key is required
for camera viewing, motion, pointer control, or local transcription.

For the PowerShell desktop launcher, create a local camera configuration:

```powershell
New-Item -ItemType Directory -Force .local
Copy-Item bluetooth-camera.example.json .local\bluetooth-camera.json
.\tools\Start-Bluetooth-Camera.ps1 -MotionTransport auto
```

Edit `bt_address` and `bt_channel` in that file for your camera. The launcher
prefers `.venv`, with the owner's bundled Python as a fallback. `-Console` shows
logs, `-Listen` starts the microphone, and `-PausePointer` starts with the pointer
paused and Speech & Jarvis selected. Both main tabs remain visible.
The direct Python command accepts `--address` without a local config file.

## Use the desktop app

The camera is beside permanent **Glove** and **Speech & Jarvis** tabs. Drag the
central divider to resize the panels. Camera Start/Stop affects the camera only;
glove and speech run independently. The header keeps microphone activity visible.
The Speech & Jarvis tab keeps both Live transcript and Jarvis conversation views.
Listen for Jarvis, Read aloud, Typing & keys, Stop reply, and New chat stay
available. Say “Jarvis” followed by a question; terminal punctuation in the
recognized transcript submits it.

- **Camera:** start/stop, rotate 180°, and save the latest received photo to
  `.local/bluetooth-photos/`. Saving uses the selected rotation. After Stop, the
  labeled last frame can still be saved; reconnecting clears stale previews.
- **Glove:** live roll/pitch/relative yaw, contact states, tap counts, sample rate,
  temperature, calibration progress, and Windows pointer controls.
- **Speech & Jarvis:** microphone selection, level meter, RNNoise suppression,
  live transcript, conversation, reply playback, and explicit writing requests.

Camera readouts show frame-completion rate, request round trip, and resolution.
The current round-trip measurement includes requesting/receiving the JPEG and
its decoding; it excludes subsequent UI rendering. It is not exposure time or
an end-to-end camera-to-screen latency measurement. The current firmware uses
640×480 JPEG with quality setting 16. Resolution/quality presets and adaptive
streaming are not implemented. `--fps` is a request-rate cap, not guaranteed FPS.

Conversation context lasts until New chat or app shutdown. Read aloud uses the
Windows voice. Every Jarvis request goes to Gemini, including exact dictation and
keyboard commands. Gemini returns a reply and an ordered list of literal text or
supported key actions. For example, say “Jarvis, type a generic search query and
then press Enter,” or “Jarvis, select all and copy.” The app types the generated
query, then presses Enter, or runs Ctrl+A followed by Ctrl+C. Enter has its normal
effect in the selected app, including submitting a search or message.

Click the destination text box before speaking and keep it selected until the
sequence finishes. Typing is paced one character at a time. Focus changes, failed
input, Esc, or Stop reply stop the remaining actions; partial sequences are never
automatically retried. The **Typing & keys** checkbox disables all input while
still showing Gemini's planned actions. Ordinary answers are not typed, and key
names inside dictated text remain literal. These native assistant
features do not depend on a web interface or local FastAPI server.

## Calibrate and control the pointer

With the glove connected, allow at least 10 seconds of sensor warmup. Keep the
sensor completely still and select **Calibrate — hold still 15 s**. Calibration
is saved on that computer; a failed measurement preserves the previous profile.

Hold a comfortable neutral pose and select **Enable pointer**. **Set neutral**
sets the current pose as neutral at screen center. Sensitivity is in pixels per
degree. Reverse X/Y changes direction; Reverse Y also affects scrolling.

Hold thumb/index for left drag or thumb/middle for right drag; release to let go.
Hold both contacts and tilt up/down to scroll, then release both to resume
pointing. **Pause pointer** stops movement/scrolling and releases held buttons.
**Esc does not stop the pointer**; it stops in-progress Jarvis typing only.
See [firmware/MOTION.md](firmware/MOTION.md) for behavior and limitations.

## Speech, Jarvis, and data handling

Speech uses local Parakeet v2, Silero VAD, and optional RNNoise suppression.
The first microphone start downloads roughly 664 MB of model weights; later
starts use the cache. Allow microphone access when prompted, speak, and pause
to see the transcript. Stop the microphone before changing its input or noise
suppression. See [firmware/SPEECH.md](firmware/SPEECH.md).

Jarvis listening, read-aloud, and typing preferences are checked by default;
the microphone still starts off. Uncheck **Listen for Jarvis** to use local
transcription without assistant requests. Camera questions require a fresh frame
and a Gemini key. Configure your own key on Windows with:

```powershell
.\.venv\Scripts\python.exe tools\gemini_secrets.py
```

The key is encrypted for the current Windows user in `.local/`.
`GEMINI_API_KEY` is an environment override. Say “Jarvis”, then ask a question;
terminal punctuation in the recognized transcript submits it. Cloud requests
include the request, previous successful conversation text, and a current JPEG
when available. Raw microphone audio is not sent to Gemini.

Explicit writing and key requests can act in a selected writable field. Ordinary
answers are not typed. **Typing & keys** controls text and key actions, **Read aloud**
controls Windows speech, **Stop reply** cancels a reply, and **New chat** clears
conversation history. Exact dictation also goes to Gemini. Enter has its normal
effect when the plan includes it. Conversations and microphone audio are not
saved by the app; manually saved camera photos persist locally. See
[firmware/JARVIS.md](firmware/JARVIS.md) for precise controls and limits.

## Develop on a Mac

Install Python with working Tcl/Tk and the project dependencies, then run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/bluetooth_viewer.py --preview
```

Preview uses the actual desktop widgets with hardware/Jarvis actions disabled.
It opens no camera, glove, microphone, cloud, playback, or typing operations.
Readings remain empty; there is no simulated runtime feed. No camera address is
required. `--preview` cannot be combined with `--listen` or `--probe`.

The host determines window chrome, fonts and scaling. Mac preview verifies UI
layout/navigation, not exact Windows rendering or hardware compatibility. For
Windows testing, run inside Windows in a VM or on a PC. Windows on ARM needs
compatible drivers; VM device passthrough can differ from physical hardware.

## Verify and troubleshoot

Run the software suite from the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py" -q
```

To include the native desktop layout/control checks in an interactive session:

```powershell
$env:SYNCHRO_TEST_DESKTOP = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py" -q
Remove-Item Env:SYNCHRO_TEST_DESKTOP
```

On Mac use `.venv/bin/python`; prefix the command with
`SYNCHRO_TEST_DESKTOP=1` for desktop checks. Test doubles and packet fixtures do
not establish radio performance, recognition accuracy, or accessibility for a
particular user. Windows-only/native-library checks may be skipped on Mac.

- **Camera unavailable:** check power, pairing, address/channel, and other open
  viewers. Use `-Console` for logs. Pairing the glove does not pair the camera.
- **No glove readings:** check firmware/wiring and the selected transport. For
  USB, use a data cable and `--mpu-port COM5` with the actual port; for multiple
  BLE gloves use `--mpu-ble-address` with the intended device address.
- **Calibration unavailable:** wait for live readings and sensor warmup, then
  keep the board still. Recalibrate after replacing the sensor or changing its
  mounting; yaw remains relative and can drift.
- **Microphone fails:** check Windows microphone permissions and the selected
  input, install requirements, or stop the mic and disable RNNoise if its native
  library cannot load. Speech and camera connections are independent.
- **Jarvis fails:** check the key/internet and the visible error. Camera questions
  need a live frame; general writing can work without one. If no request starts,
  check Listen for Jarvis and the recognized terminal punctuation.

For a real camera-only probe on Windows, stop other viewers first and use your
camera's address (or the demo address below). This opens the radio and saves a
report plus first/last JPEGs; it is not a simulated test:

```powershell
.\.venv\Scripts\python.exe tools\bluetooth_viewer.py --address 70:4B:CA:46:52:22 --probe 12 --output .local\camera-probe
```

## Hardware, source, and remaining work

Read [HANDOFF.md](HANDOFF.md) for the hardware/runtime overview and
[firmware/README.md](firmware/README.md) for wiring and historical bring-up.
Normal use does not require reflashing. Camera programming through NanoCamBridge
replaces the Nano's motion firmware temporarily; restore NanoMotionAngles after
programming. `Upload-Camera.ps1` defaults to the historical Wi-Fi sketch; current
Bluetooth camera flashing requires explicit `-Sketch SynchroCamBluetooth` and
prepared build files. Read the hardware instructions before using that helper.

- `tools/bluetooth_viewer.py`, `tools/desktop_theme.py`: desktop UI and preview.
- `tools/motion_*.py`: sensor transport, angle fusion, calibration, pointer and UI.
- `tools/speech_*.py`: local speech, noise suppression, and UI.
- `tools/jarvis_assistant.py`, `tools/text_writer.py`: Jarvis and Windows writing.
- `firmware/`, `hardware/`: firmware, protocol documentation, and wiring assets.

The hardware baseline is `test` commit
`721891c2278a04de3098fd94961e0acaa670fd8e`; the Windows UI and docs have evolved
on `main`. The core hardware/Jarvis processing remains based on that version.
A source ZIP can be created with
`python tools/package_project.py --output .local/Synchro-Source.zip` using a new
output filename. This produces source, not an installer. It excludes `.local`,
credentials, media, model caches, environments, and build outputs; the receiving
computer must install dependencies and supply its own credentials.

Next acceptance task: install on a clean Windows computer and verify DPI/layout,
USB/BLE reconnects, calibration, pointer dragging/scrolling/pause, microphone and
RNNoise, Jarvis playback/cancellation, and typing into a selected test field.
Historical hardware measurements are recorded separately from current software
checks in HANDOFF.md. Battery runtime, long-term drift, and wearable comfort
remain uncharacterized. Dwell click, drag lock, personalized movement ranges,
saved user profiles, and additional camera controls are proposals, not current
features. Gesture recognition remains outside the current milestone.

# Synchro project handoff

Snapshot: 25 October 2026, America/New_York. This document records the working
project context rather than the entire chat. It excludes personal conversation,
credentials and private captured media. For current behavior and wiring, this
handoff and MOTION.md take precedence over older bring-up notes in firmware/README.md.

Latest addition: **Jarvis voice + vision assistant**, documented in
firmware/JARVIS.md. After “Jarvis”, once the transcript ends in `.`, `?` or `!`, the app sends the
recognized request text and one fresh camera frame to Gemini 3.5 Flash-Lite,
shows the answer and speaks it with Windows TTS. Its key is encrypted locally
and excluded from Git/share packages. A receiving computer needs its own key.
Jarvis sends every activated request to Gemini, including exact dictation and
key commands. Gemini returns an ordered, validated plan of text and key actions,
so “type a generic search query and then press Enter” works as one request.
The “Typing & keys” toggle controls execution; focus changes or input failures
stop the remaining actions without retry. Typing uses paced individual characters
to address reported repeats. All questions and answers share
one in-memory conversation until New chat or app shutdown. The full test suite
passes, and real Gemini writing plus a follow-up memory check passed.

## Purpose and design choices

A wearable glove provides hand motion and conductive finger contacts for a
computer pointer, a camera view, and speech transcription. The current working
name is Synchro; alternative speech-friendly names were discussed but no rename
was implemented.

The build uses **one MPU6050/GY-521 on the back of the hand**, not the wrist.
Earlier discussion of a second sensor on the index finger or three sensors did
not become the current implementation. Custom trained gestures are a future
idea, not implemented. Pinch detection comes from touching copper strips, not
from inferring finger motion with the MPU.

The owner prefers insulated soldered wire splices over a large breadboard.
Copper contact pads are roughly 1 × 2 cm, with an insulated backing and wires
secured against pulling. The battery was intended for the back of the hand;
final mounting still needs practical checks. PowerBoost pin headers and its
USB-A output socket have been soldered on.

## Hardware and runtime wiring

| Part | Specific device |
| --- | --- |
| Main controller | Arduino Nano ESP32 with headers (ESP32-S3) |
| Motion sensor | One MPU-6050 / GY-521 |
| Camera | Inland ESP32-CAM, original ESP32 with Bluetooth Classic; observed OV3660 sensor |
| Click contacts | Grounded thumb, index left click, middle right click |
| Power | Adafruit PowerBoost 1000C |
| Battery | PKCELL LP803860, 3.7 V nominal, 2000 mAh LiPo |
| Current microphone | Laptop microphone array, not a glove-mounted microphone |
| Power cable | PowerBoost USB-A output to Nano USB-C |
| Computer | Windows app; Mac development preview via --preview |

Disconnect power before rewiring. These are printed pin labels, not physical
pin positions or raw ESP32 GPIO numbers.

| From | To |
| --- | --- |
| Battery JST plug | PowerBoost battery JST socket; verify polarity |
| PowerBoost USB-A output | Nano USB-C via USB-A-to-USB-C cable |
| PowerBoost 5V output | Camera 5V |
| PowerBoost GND | G1 ground splice |
| Camera plain GND | G1 ground splice |
| Nano GND near D2 | G1 ground splice |
| Nano other GND near VIN | G2 ground splice |
| MPU GND | G2 ground splice |
| MPU AD0 | G2 ground splice (I2C address 0x68) |
| Thumb copper contact | G2 ground splice |
| Nano 3V3 | MPU VCC |
| Nano A4 | MPU SDA |
| Nano A5 | MPU SCL |
| Nano D4 | Index copper contact |
| Nano D5 | Middle copper contact |

G1 joins three wire ends; G2 joins four. Both Nano grounds are internally
connected; USB also carries ground. Insulate soldered junctions and add strain
relief. Copper pads must directly contact each other to trigger clicks.

In normal operation leave camera **IO0, U0T, U0R and GND/R disconnected**.
GND/R on this board has not been verified as a ground. Also leave Nano VIN/VUSB
headers and MPU INT/XDA/XCL unused. Do not reconnect the earlier Nano VUSB to
camera 5V wire when the camera is powered by the PowerBoost.

The drawing in hardware/ includes the two blue UART lines used **only when
programming the camera**. They are not runtime connections. The full circuit
table in the older firmware README also lists them; this distinction is essential.

To connect the Nano to the laptop, move its USB cable off the PowerBoost output
and use the laptop's USB data connection. Keep the camera separately powered
if needed. Do not join laptop USB 5V to the booster's output.

There is no installed power switch. Unplug the battery and any USB power inputs
to turn everything off. PowerBoost EN open means on; an optional switch from
EN to GND can disable the boosted output. That switch is not part of the demo.
Use the PowerBoost micro-USB input for charging and charge off the body.

## Software architecture and implemented behavior

Firmware is Arduino C++. The full desktop app and processing are Python.
The earlier native Mac camera prototype has been removed. Use --preview on the Windows viewer for Mac interface development.

- **NanoMotionAngles** samples all six MPU axes at 1 kHz using the FIFO,
  400 kHz I2C, ±4 g acceleration and ±500 degrees/s gyro range. It debounces
  the copper contacts for 25 ms and sends sample packets plus tap counters.
- **USB or BLE** carries raw motion samples to the laptop. The Nano is not a
  standalone Bluetooth HID mouse. Keep the desktop app running.
- **motion_core.py** performs double-precision quaternion fusion on the laptop.
  Roll/pitch use gravity; yaw has no magnetometer reference and drifts.
- **motion_sensor.py** owns the sensor transport and local calibration.
  **motion_panel.py** shows roll/pitch/yaw, contact states, counts and controls.
- **motion_pointer.py** injects Windows mouse movement, held buttons and wheel events.
  Thumb/index holds left; thumb/middle holds right. Hold to drag, release to let go.
  Both contacts together use pitch changes to scroll while the pointer stays still.
  Release both to resume pointing. Pause pointer releases buttons and stops
  movement/scrolling; Esc does not affect pointer control.
- **SynchroCamBluetooth** sends JPEG frames over Bluetooth Classic RFCOMM.
  **bluetooth_viewer.py** requests one frame at a time, displays it, and rotates
  it 180 degrees by default. This is a custom camera app, not an OS webcam.
- **speech_stream.py** continuously captures the selected laptop mic.
  **speech_models.py** runs Silero VAD and Parakeet TDT 0.6B v2 locally.
  A ~512 ms pause ends an utterance, then text appears in **speech_panel.py**.
  The active path no longer uses Groq or Whisper. The earlier user spelling
  “b2” was interpreted as model version “v2”.
- **speech_secrets.py** retains the historical Groq credential utility. Its
  DPAPI helper is reused by **gemini_secrets.py**, but the old Groq key is unused.
  **jarvis_assistant.py** owns wake requests, fresh snapshots, Gemini and TTS.

Speech displays recognized text in the viewer; Jarvis also displays/speaks its
answer. Explicit write/type/draft/compose requests insert generated writing into
the focused editable field, using tools/text_writer.py. “Write exactly” inserts
the recognized payload without an LLM rewrite. Current-field checks prevent typing
after switching focus; New chat clears the shared conversation. See JARVIS.md.
A glove-mounted microphone is still a future hardware choice; none is installed.

## Current cursor design and limitations

The owner requested restoring the cursor code from before the sideways hand
movement experiment. The controller, panel and pointer tests were recovered
from that earlier edit history.

- X: roll mapped to horizontal screen position; Y: pitch to vertical position.
- Both axes default to 25 pixels/degree after a 0.5-degree dead zone.
  Holding a tilt holds the target position; sensitivity scales both axes.
- Enable pointer: captures neutral and starts control manually.
- Set neutral: captures the current tilt as neutral at screen center.
- Pause pointer: releases held buttons and stops movement/scrolling until enabled.
- Esc does not stop movement, dragging or scrolling.
- Hold one contact to drag; hold both and tilt up/down to scroll. Release both to
  jump to the current tilt's pointer position with the original neutral and screen
  anchor preserved. Quick single-contact taps still click.
- The earlier orientation filter and brief-interruption recovery remain.

The sideways cursor, auto-activation, extra cursor smoothing and pinch freeze
introduced with the experiment are removed. Translation helpers remain in the
source but do not affect the cursor. Final mounting and sensitivity need a
physical user trial. Jarvis writing/conversation and held-button/scroll gestures
were added after this cursor restoration; the camera firmware is unchanged.

## Known devices and connection details

| Link | Current demo identity |
| --- | --- |
| Camera | Synchro-Cam-BT, 70:4B:CA:46:52:22, RFCOMM channel 1 |
| Glove | Synchro-Glove, BLE address 20:6E:F1:31:64:3D |
| BLE service | 8870a001-49a5-4a7c-8d92-a1f003b7d601 |
| BLE notification characteristic | 8870a002-49a5-4a7c-8d92-a1f003b7d601 |
| BLE identity characteristic | 8870a003-49a5-4a7c-8d92-a1f003b7d601 |

These addresses belong to the existing hardware. Use another unit's own address.
The camera pairing PIN is omitted; request it separately from the owner.
Changing a PIN in an example header alone does not change already-flashed hardware.
Close other viewers before handing the camera/glove connection to another laptop.

Optional local camera config can be created from bluetooth-camera.example.json:

```powershell
New-Item -ItemType Directory -Force .local
Copy-Item bluetooth-camera.example.json .local\bluetooth-camera.json
```

The standalone CLI --address option works without this config.

## Calibration on the receiving computer

Calibration is on the laptop, not in Nano flash, and this archive excludes the
owner's device-specific profile. With the glove connected, wait at least 10
seconds for warm-up, rest the MPU completely still, and click
**Calibrate — hold still 15 s**. Do not start until someone can leave it still.

A successful run checks 15,000 samples, gyro variance, gravity, temperature and
continuity, validates on held-out samples, and saves the bias. A failed run
preserves the previous profile. It does not eliminate future yaw drift or
calibrate all accelerometer scale/offset errors.

The Python calibration CLI talks to the running viewer through an authenticated
localhost endpoint; it does not open a competing sensor connection:

```powershell
.\.venv\Scripts\python.exe tools\calibrate_motion.py
.\.venv\Scripts\python.exe tools\calibrate_motion.py --start
```

The second command starts the measurement. Do not share .local/motion-control.json;
it is generated per local app session.

## Camera programming versus normal Nano operation

The Nano can temporarily serve as a USB-to-UART adapter using **NanoCamBridge**.
That overwrites the motion firmware; after camera programming, restore
**NanoMotionAngles** to regain the MPU and click telemetry.

Programming-only wiring: Nano D2 (bridge RX) to camera U0T (TX), Nano D3 (bridge
TX) to camera U0R (RX), and common ground. Camera serial signals are 3.3 V logic.
The camera remains powered from the separate appropriate 5 V source.

Ground camera IO0 and reset the camera to enter the bootloader. After upload,
remove IO0-GND and reset/power-cycle the camera. Disconnect power to change
wires. Remove the two UART lines again for normal glove operation.

Known build targets from the existing successful build metadata:

| Sketch | Target |
| --- | --- |
| NanoMotionAngles | arduino:esp32:nano_nora |
| NanoCamBridge | arduino:esp32:nano_nora |
| SynchroCamBluetooth | esp32:esp32:esp32cam:FlashMode=dio,FlashFreq=40 |

The camera uses Espressif Arduino core **2.0.17**, DIO, 40 MHz flash, 4 MB,
and original ESP32 Bluetooth Classic support. The Nano uses the Arduino Nano
ESP32 board package and the default Arduino pin numbering/TinyUSB arrangement.
Do not compile the camera firmware for the Nano ESP32-S3.

Before a camera build, copy firmware/SynchroCamBluetooth/secrets.example.h to
secrets.h and choose the pairing PIN. For the old Wi-Fi sketch, copy its own
secrets.example.h and choose an AP password. Neither private header is included.

Use Arduino IDE/CLI to compile each sketch for its matching board. Existing
Upload-Camera.ps1 expects compiled files in .build/SynchroCamBluetooth and
installed core 2.0.17 tool paths. Its default sketch is the OLD Wi-Fi sketch:
for current camera firmware explicitly use **-Sketch SynchroCamBluetooth** and
the detected COM port. Read the script and firmware/README.md before flashing.
The current working hardware does not need reflashing merely to use another PC.

## Verification and open issues

Observed on the owner's Windows laptop:

- Camera Bluetooth VGA capture and 180° display worked. A simple-scene test
  decoded 120 frames at 12.17 fps; interactive tests also ran around 4–5 fps.
  Scene detail, radio conditions and decoding change performance. The user
  accepted the current resolution/quality; it is not high-quality video.
- USB and BLE motion, stationary calibration, and individual copper contact
  states passed earlier live checks.
- Previous tilt-position mouse and left/right clicks were exercised.
- Current tilt positioning, held-button dragging, two-finger scrolling, release
  positioning and Esc behavior pass simulated regressions. The earlier sideways
  translation/auto-activation experiment is no longer used by the pointer.
- The current automated suite passed **140 tests** before the GitHub update.
- Real local Parakeet + Silero recognized a synthetic two-sentence fixture;
  decode times were 0.112 and 0.106 s after pause detection.
- The subsequent live laptop microphone session reached **34 successful
  transcriptions, zero reported errors/skipped clips**, with the latest decode
  about 109 ms. Recognition accuracy still depends on speech and noise.
- A live dictation command inserted 12 characters into Notepad, confirmed in the
  app status, visible document and user response. Recognition accuracy still
  depends on speech and background noise; generated writing and follow-up
  conversation context also passed a real Gemini API check.
- USB and subsequent battery-powered BLE motion were verified at about 1,002
  samples/s with no packet/I2C errors or BLE queue drops during the check.
  Launch with `--motion-transport auto` to select USB when present and fall back
  to BLE. Camera Bluetooth video remained available in the viewer.
- The product targets Windows. Mac is a development host only; --preview opens
  the real interface without hardware, cloud requests, playback, or text insertion.
- Battery runtime, simultaneous load margin, final wearable mounting, long-term
  drift and physical pointing consistency have not been fully characterized.

Useful next steps: test the friend's mic setup; transfer one Bluetooth connection
at a time; calibrate on that computer; set a comfortable neutral pose and tune
tilt sensitivity / axis reversal; then choose a glove microphone and test writing
in the friend's target app.

## File and history notes

The archive includes all authored source, tests and hardware diagrams.
NanoMotionTest is the early sensor diagnostic, NanoCamBridge the temporary
camera programmer, SynchroCam the historical Wi-Fi/AP camera viewer, and
SynchroCamBluetooth the current camera firmware.

Older README sections preserve historical test runs and may say cursor control
is not implemented or show UART wires retained. The current implementation and
runtime connections are described above. Old .local evidence paths are references
to private test files on the owner's machine and are not expected in this ZIP.

The earlier Mac viewer and packaging helper have been removed. See the root
README for the Windows app and Mac development-preview commands.

Private API keys (including the previous Groq key), Bluetooth/Wi-Fi secrets,
encrypted credentials, recorded media, private logs, calibration data, control
tokens, original flash backups, model caches and build binaries were excluded.
Reinstall dependencies and fetch model weights on the receiving machine.
The ZIP does not send anything itself or grant access to online accounts.

Model attribution and license links are in firmware/SPEECH.md. No new license
for the project's original code is asserted by this handoff.


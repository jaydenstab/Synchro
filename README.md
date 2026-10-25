# Synchro — start here

This is the complete shareable source project for the glove demo, packaged on
**25 October 2026**. Read [HANDOFF.md](HANDOFF.md) for the project context, hardware
wiring, current status and next steps.

The glove firmware, motion processing, pointer, and local speech are unchanged.
The app window is the React UI in `frontend/`, on both Windows and Mac.
`tools/bluetooth_viewer.py` remains the Bluetooth camera protocol and the original Tk test viewer.

## Run

Install **64-bit Python 3.12** and Node.js. Enable Bluetooth. On Windows, pair **Synchro-Cam-BT** first.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-web.txt
cd frontend && npm install && npm run build && cd ..
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. On a Mac, the camera radio stays in `camera/synchro_mac` (`bash camera/synchro_mac/Start-Mac.command`, then Start). On Windows, this process opens the camera and the glove.

`tools/Start-Bluetooth-Camera.ps1` starts that same page. `-MotionTransport ble` and `-Listen` still select the glove link and start the microphone.

That address belongs to the existing demo camera. Substitute `SYNCHRO_BT_ADDRESS` for a different camera. Speech can run while the camera and glove are off. Press **Esc** or pause the pointer while testing speech.

The first microphone start downloads approximately 664 MB of Parakeet/Silero
model weights. Later starts load the local cache. No API key is needed.
Allow the app microphone access if your computer asks. Speak, pause for about
half a second, and look for text in the lower panel.

For camera video, first pair the powered **Synchro-Cam-BT** with Windows.
Get the current camera PIN separately from the project owner; it is intentionally
not included in this shareable archive. Only one laptop should use the camera
at a time, so stop the owner's viewer before connecting from another laptop.
The glove advertises as **Synchro-Glove** over BLE and is a separate connection.

For glove mouse control on a new computer, keep the MPU still and perform the
15-second calibration in the viewer. Calibration is saved on that computer.
**Auto cursor** can activate after calibration and a stable resting pose;
**Esc** pauses both movement and finger clicks.

## Verify the source

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py" -q
```

The packaging validation runs this suite from the extracted ZIP with the existing
project Python runtime. Installing dependencies and connecting the hardware on a
fresh friend's computer still need to be tested there.

## Where things are

| Location | Contents |
| --- | --- |
| [HANDOFF.md](HANDOFF.md) | Full project context and current runtime wiring |
| [firmware/MOTION.md](firmware/MOTION.md) | Sensor protocol, angle fusion, calibration and cursor behavior |
| [firmware/SPEECH.md](firmware/SPEECH.md) | Parakeet v2 + Silero behavior, limits and model attribution |
| firmware/NanoMotionAngles/ | Current Nano acquisition firmware |
| firmware/SynchroCamBluetooth/ | Current 640×480 camera firmware |
| frontend/ | App UI for Windows and Mac |
| tools/bluetooth_viewer.py | Camera protocol and original Tk viewer tests |
| tools/motion_*.py | Motion transport, filtering, and OS cursor |
| tools/speech_*.py | Local speech capture, VAD, and transcription |
| hardware/ | Wiring diagram PNG and editable SVG |
| camera/synchro_mac/ | Mac Bluetooth Classic camera window |
| tools/mac-camera/ | Earlier Mac camera-only source |
| firmware/README.md | Detailed build notes and historical bring-up |
| tools/Upload-Camera.ps1 | Camera-only flashing helper, for a prepared build |

The original PowerShell launch/calibration helpers target the owner's bundled
Codex Python runtime. On another computer, use the portable Python commands
above and `.\.venv\Scripts\python.exe tools\calibrate_motion.py` instead.
No Codex account or installation is required for the Python application.

Private keys, pairing PINs, camera photos, microphone audio, raw logs, personal
calibration profiles, local control tokens, firmware flash backups, Git history,
build outputs, virtual environments and downloaded model weights are omitted.
See PACKAGE-CONTENTS.txt and SHA256SUMS.txt inside the archive for the file inventory.


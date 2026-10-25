# Synchro camera on a Mac

Native Bluetooth Classic viewer for the existing Synchro-Cam firmware. The picture is rotated 180° by default. Uncheck **Rotate 180°** to show the camera's orientation. The saved JPEG is always the original bytes.

Hardware steps are in `../CAMERA_TESTING.md`. Protocol tests in `Tests/` are simulated and are not camera measurements.

The window is the whole Synchro app. Camera is this native viewer. Gestures, Test, and Settings open the local service in the same window, without a second sidebar. The browser at http://127.0.0.1:8000 still has those pages, including a camera page that cannot connect to Bluetooth.

## Run

macOS 12 or later and Apple's Command Line Tools. From this folder:

```bash
bash Start-Mac.command
```

Allow Bluetooth, then press **Start**. The status line should show `Bluetooth live`, the frame size, and an increasing frame count. **Stop** releases the radio so another computer can connect.

The panel adds current FPS, a 3-second average FPS, JPEG size, resolution, request-to-frame latency, session maximum latency, local JPEG decode time, and counters for received frames, rejected frames, timeouts, and connection errors. **Save Original JPEG**, **Export Performance CSV**, and **Reset Statistics** operate on this session. Start clears statistics. Stop does not, so you can export after disconnecting.

Request-to-frame time runs from the `CAPTURE` write until `JPEG_END` is validated. It is not sensor exposure time.

Commands sent to the camera are only `STATUS` and `CAPTURE`. The camera still speaks `JPEG_BEGIN` / `JPEG_END`. There is no resolution or autofocus control in this protocol. The viewer also serves its latest JPEG on `127.0.0.1:8765` for the browser. That listener does not send any camera command of its own.

The known target is Synchro-Cam-BT, address `70:4B:CA:46:52:22`, RFCOMM channel 1, firmware `bluetooth-2`, OV3660, 640×480 JPEG, at most 15 captures per second. The pairing PIN is only in the gitignored `PAIRING.txt` next to this file.

# Camera subsystem

This directory is the ESP32-CAM side of VisionGlove. It does not import the gesture engine, SQLite store, or sensor APIs. A later integration should sit beside those pieces, for example by saving a JPEG or posting a frame over localhost, rather than calling `engine.py` from the viewer.

The Mac app speaks **Bluetooth Classic RFCOMM** to the existing Synchro-Cam firmware. It does not use a Wi-Fi CameraWebServer.

## What the original viewer does

The checkpoint in `synchro_mac/original/` is the unmodified teammate drop.

- Device address `70:4B:CA:46:52:22`, display name Synchro-Cam-BT, RFCOMM channel 1.
- After the channel opens, the Mac sends `STATUS\n`.
- The camera answers with one JSON line. The viewer accepts `firmware` of `bluetooth-1` or `bluetooth-2` and `camera_ready: true`.
- The Mac sends `CAPTURE\n`, then reads `JPEG_BEGIN <length> <width> <height>\n`, exactly `length` bytes, then `\nJPEG_END\n`.
- Allowed sizes are 640×480 and 320×240. A JPEG must start with `FF D8` and end with `FF D9`.
- The next `CAPTURE` is sent only after that frame is finished, and never sooner than 1/15 s after the previous request.
- Incoming bytes are appended to one buffer. There is no queue of stale frames. The cost is that a bad frame used to drop the whole link.
- `NSBitmapImageRep` decoded each JPEG on the main thread. Rotation built a new drawing-backed `NSImage` every frame.
- The status line FPS is `(frames in the last 3 seconds - 1) / span`. It is a completion rate, not a calibrated capture-time measurement.
- `Info.plist` includes `NSBluetoothAlwaysUsageDescription` and `NSBluetoothPeripheralUsageDescription`. The launcher ad-hoc signs the app so macOS can attach a Bluetooth privacy prompt to it.
- `Start-Mac.command` checks Darwin and the Command Line Tools, compiles into a local `.app`, and ad-hoc signs that bundle. It does not delete user files or flash the ESP32.

`PAIRING.txt` stays on this Mac and is gitignored. It is not in the checkpoint.

## What the Mac can change, and what it cannot

The viewer can pace requests, reassemble fragments, reject bad JPEGs, decode off the main thread, and time the round trip. It cannot see the sensor exposure interval. Request-to-frame time includes the command, firmware capture, JPEG compression, and Bluetooth transfer together.

Firmware would have to change before any of these are possible: a smaller or quality-selected JPEG, 320×240 on demand, more than one frame in flight, an exposure timestamp, or autofocus. Those commands are not part of this protocol, and the viewer does not invent them.

## Local frame handoff

The current viewer listens on `127.0.0.1:8765` after it launches. `GET /status` reports whether its existing RFCOMM session is live. `GET /frame.jpg` returns the latest JPEG from that session, or 503 when the session is down or the frame is stale. The browser calls FastAPI, and FastAPI calls this socket. Nothing in that path opens Bluetooth. The checkpoint in `original/` does not listen on this port. Quit the viewer to release the radio, the same as before.

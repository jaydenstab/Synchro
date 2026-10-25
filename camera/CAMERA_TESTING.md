# Testing the Synchro camera

The ESP32-CAM is a separate machine from this repository. Numbers in `camera/synchro_mac/Tests/` are **simulated** RFCOMM bytes. A FPS or latency number is a camera measurement only after the Mac viewer shows `Bluetooth live` against the powered camera and you export a CSV whose first lines say `origin: mac-viewer` and `simulated: false`.

The pairing PIN is in `camera/synchro_mac/PAIRING.txt` on this Mac. That file is gitignored. Do not copy the PIN into a screenshot, commit, or public note.

Only one program may hold the camera. Quit the Windows viewer before the Mac viewer.

## 1. Build and launch the Mac viewer

Requirements: macOS 12 or later, Apple Command Line Tools (`xcode-select --install` if `xcode-select -p` fails).

From the repository root:

```bash
bash camera/synchro_mac/Start-Mac.command
```

The script compiles `Synchro Camera.app` next to itself, ad-hoc signs that bundle, and opens it. Allow the Bluetooth prompt. If macOS already denied Bluetooth, allow **Synchro Camera** in System Settings > Privacy & Security > Bluetooth, then relaunch.

Simulated protocol tests, with no radio:

```bash
bash camera/synchro_mac/run-tests.sh
```

## 2. Pair the ESP32-CAM

1. Power the ESP32-CAM from the PowerBoost 5V and GND. Leave camera IO0 unconnected. The Nano is not in the video path.
2. Keep the Mac near the camera.
3. In System Settings > Bluetooth, pair **Synchro-Cam-BT**. Use the PIN from the local `PAIRING.txt`.
4. Pairing alone does not show video and does not make the board a system webcam.

Read-only check that Bluetooth sees the board (this does not start video):

```bash
system_profiler SPBluetoothDataType | grep -A 20 -E "Synchro-Cam-BT|70-4B-CA-46-52-22|70:4B:CA:46:52:22"
```

If that prints nothing, the camera is unpaired, off, or out of range. Do not record a FPS number from that state.

## 3. Confirm frame reception

Press **Start**. The link indicator should move from Connecting to Connected, then to Live. The line under the picture should contain `Bluetooth live`, a size of `640 × 480` or `320 × 240`, and a frame count that increases. Move the camera and confirm the picture changes.

Press **Stop** when you want the Mac to release the radio.

## 4. Capture an original JPEG

After at least one live frame, press **Save Original JPEG**. The file is the JPEG bytes from the camera, before the on-screen 180° rotation. Uncheck **Rotate 180°** only to change the preview.

## 5. Measure FPS and transfer latency

The panel separates two clocks:

- **Current FPS** is the gap between the last two frames that decoded.
- **Average FPS (3s)** matches the original viewer's rolling window: `(frames in the last 3 seconds - 1) / span`. The status line uses this average once it is non-zero.
- **Request-to-frame** starts when `CAPTURE` is written and stops when `JPEG_END` has been checked. It includes firmware capture, compression, and Bluetooth. It is **not** the image sensor's exposure time. The firmware does not send an exposure timestamp, so the Mac cannot split those parts.
- **Mac JPEG decode** is local ImageIO time after the bytes are complete.

The first frame has no FPS yet. The panel shows `—` until a second frame arrives. Timeout and connection errors increment when the link fails. A framed JPEG that fails validation increments **Rejected / invalid frames** and the viewer requests another frame. A broken header or a bad `JPEG_END` still closes the link, because the byte stream is no longer aligned.

## 6. Stationary sharpness

1. Put the camera on a table, aimed at high-contrast printed text.
2. Leave **Rotate 180°** as you prefer for viewing, then save an original JPEG.
3. Open that file in Preview and look at the edges. Soft edges here are focus, motion, or JPEG quantization in the firmware. The Mac app cannot focus the OV3660 or change its resolution.

## 7. Motion and lag

1. Note **Request-to-frame** while the scene is still.
2. Wave a hand across the view. Watch how long the picture takes to follow the hand, and whether the latency number jumps.
3. The visible delay is at least one request-to-frame interval, plus local decode. The viewer does not keep a stack of old frames to display later. It asks for the next frame only after the current JPEG has arrived, and it will not ask more often than 15 times per second.

## 8. Export benchmark results

Press **Export Performance CSV** before you press Start again. Start and **Reset Statistics** clear the in-memory log. Stop does not.

The CSV header must say `# origin: mac-viewer` and `# simulated: false` when it came from this app. Simulated unit tests write `# origin: simulated` if they call the same exporter. Do not mix those files when you compare a hardware run.

## 9. Hand a frame to the browser

Start this viewer and press Start so the picture is live. Then open the Synchro Camera page at http://127.0.0.1:8000 and press Capture Photo. The page should show the same scene. The browser does not pair with the camera. If Capture Photo says the bridge is unavailable, the viewer is not running or its session is not live. The simulated tests check the localhost handoff with fake bytes; they do not prove the radio works.

## What a failed start usually means

- Timeout on connect: power, pairing, distance, or the Windows viewer still holds the link.
- "Camera firmware is not ready": the status JSON was missing, `camera_ready` was not true, or `firmware` was not `bluetooth-1` or `bluetooth-2`.
- "Invalid camera image": the length header and `JPEG_END` did not agree. Press Start to resync.
- Build error: install the Command Line Tools and run the launcher again. Do not flash firmware from this repository. The firmware source is not here.

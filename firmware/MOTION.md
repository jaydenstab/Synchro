# MPU angles and contacts in the camera viewer

Run commands from the project root unless a section says otherwise.

The Windows camera viewer now combines the camera's existing Bluetooth video
with USB or Bluetooth Low Energy telemetry from the Nano ESP32. The camera firmware is unchanged.
The separate Mac app has been removed. Use `--preview` on a Mac to inspect the
Windows interface without opening hardware; both main tabs remain visible.

## Wiring and programs

Connect the Nano directly to laptop USB for flashing or USB telemetry. For
wireless operation, power the Nano from the PowerBoost's USB-A output through
its existing USB-A-to-USB-C cable. The camera may run independently from the
PowerBoost. Keep its programming UART wires removed.
Do not connect the Nano to the booster USB output at the same time as laptop USB.

| Nano | Glove connection |
| --- | --- |
| 3V3 | MPU VCC |
| A4 | MPU SDA |
| A5 | MPU SCL |
| GND | MPU GND and AD0 (0x68), thumb copper pad, using the existing shared ground wiring |
| D4 | Index copper pad / left contact |
| D5 | Middle copper pad / right contact |

MPU INT/XDA/XCL remain unused. Pin names are the Nano's printed Arduino labels.

- `NanoMotionAngles/NanoMotionAngles.ino`: raw sensor acquisition and contact
  debouncing on the Nano; replaces `NanoMotionTest` when uploaded.
- `../tools/motion_core.py`: double-precision quaternion angle estimator and
  calibration checks on the laptop.
- `../tools/motion_sensor.py`: USB/BLE reader, saved calibration, local control API.
- `../tools/motion_panel.py`: roll/pitch/relative yaw, held/released/TAP indicators,
  cumulative press counts, sample rate, and calibration progress in the viewer.
- `../tools/Calibrate-Motion.ps1`: readiness/calibration entry point.

The indicators only display contacts; the separate pointer controller generates
Windows button events when pointer control is enabled. Counts are debounced press
edges since Nano boot; both press and release debounce is 25 ms. A latched
counter catches taps between UI refreshes. A tap shorter than the debounce
interval is intentionally rejected. Stale data is shown as unavailable.

## Rate, precision, and accuracy

The MPU is configured for 1,000 fresh combined accelerometer/gyro samples per
second, 400 kHz I2C, +/-4 g and +/-500 degrees/s. DLPF setting 2 limits bandwidth
to 94 Hz accel / 98 Hz gyro (about 3 ms sensor delay). The FIFO preserves all
sample order across USB batching. Six signed 16-bit sensor values are sent in
CRC32-protected binary packets, with timestamps, sequence counters, temperature,
contact counts, FIFO-reset count and I2C-error count. Serial output is native
USB CDC; the nominal 115200 baud setting does not impose a UART speed limit.
No polling of the same accelerometer reading at 8 kHz is presented as new data.

Every sample is processed on the laptop with Python IEEE-754 64-bit doubles.
The estimator uses quaternion gyro integration plus gravity correction for
roll/pitch, avoiding internal Euler singularities. The reported Euler pitch
still has the usual +/-90-degree ambiguity; roll/yaw can jump at that pose.
The UI refreshes about 33 times/second, independent of sensor and video rate.
Two displayed decimal places are formatting, not a measured accuracy claim.

Angles follow the MPU's physical axes: roll=X, pitch=Y, relative yaw=Z for a
level board. Initial roll/pitch come from gravity; yaw starts at zero. The
camera's image rotation does not rotate the sensor coordinate system.
Sample integration uses the configured 1 ms sensor interval, not irregular
USB arrival times. MPU oscillator tolerance remains a rate-scale limitation.

Accelerometer correction fades when acceleration magnitude differs from 1 g
by 0.05–0.20 g. It cannot distinguish all sustained linear acceleration from
tilt. A single stationary pose cannot determine the accelerometer's full
offset/scale calibration; six known poses and angle-reference testing would
be needed to assess absolute angle accuracy. Doubles do not increase the
sensor's 16-bit measurement resolution.

**Yaw has no absolute reference on an MPU-6050 and will drift.** This is not a
compass. The filter does not hide drift by forcing small angular rates to zero.
Data gaps, CRC failures, FIFO resets, and range saturation invalidate continuous
tracking and restart the orientation reference rather than integrating stale
data. The current sensor range can clip very fast hand motions above 500 deg/s.

## Run and calibrate

Open the updated viewer with `tools/Start-Bluetooth-Camera.ps1` from PowerShell.
Auto mode selects a single Nano ESP32 USB port if present, otherwise scans
for **Synchro-Glove** over BLE. On USB disconnection it reconnects via BLE;
heading resets on transport changes, but gyro calibration follows the board's
identity. A live BLE connection stays on BLE even if USB is subsequently plugged
in. To force Bluetooth even with a USB power cable attached:

```powershell
.\tools\Start-Bluetooth-Camera.ps1 -MotionTransport ble
```

The viewer's motion status explicitly says **USB** or **Bluetooth LE**. The
camera remains **Synchro-Cam-BT**, a separate Bluetooth Classic connection.
No Wi-Fi or laptop USB data cable is required in BLE mode. Initial connection
is automatic in this local demo (no PIN or OS pairing dialog). Keep only one
viewer connected to the glove. If multiple gloves advertise, use
`--mpu-ble-address` to choose one. Radio performance depends on the laptop and
interference; packet loss is detected and invalidates calibration.

BLE transfers the same 1kHz raw samples in roughly 10ms batches. Its advertised
custom service is `8870a001-49a5-4a7c-8d92-a1f003b7d601`; notification data is
`...a002...`, board identity is `...a003...`. Frames are fragmented to the
negotiated MTU. An independent bounded transmit queue prevents Bluetooth
congestion from blocking I2C acquisition; drops are counted, not hidden.

For manual USB selection,
run `python tools/bluetooth_viewer.py --mpu-port COM5` with Pillow and pyserial
installed in that Python environment; Bluetooth additionally needs `bleak`.
The existing launcher uses the bundled Python where these dependencies are installed.

Check readiness without starting a measurement:

```powershell
.\tools\Calibrate-Motion.ps1
```

After at least 10 seconds of warm-up, put the mounted MPU on a stable surface.
It can be tilted; it must not move. Keep all wires slack and do not touch the
glove during the measurement. Once ready, run:

```powershell
.\tools\Calibrate-Motion.ps1 -Start
```

Alternatively press the viewer's **Calibrate — hold still 15 s** button once
ready. Neither opening the viewer nor the readiness command starts calibration.
The command-line script uses an authenticated loopback control connection to
the viewer; it never competes for its COM port. No internet is involved.

15,000 consecutive samples (nominally 15 seconds) estimate three gyro biases.
The last 3 seconds validate the bias from the first 12 seconds before all 15
seconds are used for the final saved estimate. Checks reject excessive motion,
noise, temperature change, lost samples, abnormal gravity magnitude, slow
acquisition, or unstable bias. No stationary algorithm can reliably detect
constant slow rotation about gravity; keeping the board physically still is
essential. Failed checks preserve the previous calibration.

Successful calibration is applied to the running filter and saved under
`.local/mpu-calibration-<USB-identity-hash>.json`, loaded on subsequent launches.
Raw samples and the JSON quality report are saved in
`.local/motion-calibrations/<run-id>/`. The report includes raw per-axis drift
and held-out residual drift, in degrees/minute. These are bias-rate diagnostics,
not a guarantee of future heading accuracy. Calibration resets relative yaw.
Profiles identify the Nano USB serial, not the MPU chip (which has no unique
identity exposed here); recalibrate after replacing the sensor or changing
mounting/operating temperature. A >5 C change produces a reminder in the UI.

Calibration is stored on the laptop, not in the Nano's flash. Angle fusion
requires this laptop application over USB or BLE. Standalone onboard angle
output is a separate addition. The same calibration works over either transport.

## Restored roll/pitch tilt cursor (Windows)

The cursor controller and panel are restored from the edit history immediately
before the sideways hand movement experiment. Keep the viewer running, hold a
comfortable neutral pose, and click **Enable pointer**. No firmware upload is needed.

1. Roll / X tilt controls left/right. Pitch / Y tilt controls up/down.
   Use **Reverse X** or **Reverse Y** to match the board's mounting.
2. Both angles map directly to screen positions: holding a tilt holds the target
   position. Sensitivity defaults to 25 pixels/degree after a 0.5-degree dead zone.
   The sensitivity slider scales both axes.
3. **Set neutral** captures the current pose and centers its target on the screen.
4. Thumb/index holds the left mouse button; thumb/middle holds the right button.
   Keep a contact touching while tilting to drag, and separate it to release.
   Quick taps still click. A held contact does not repeat clicks.
5. Touch both index and middle contacts to the thumb to scroll. Upward pitch
   changes scroll up; downward changes scroll down. The pointer stays still and
   neither button is held during scrolling. Holding a fixed tilt stops scrolling.
   Release both contacts to jump to the position indicated by the current tilt.
   Scrolling preserves the original neutral pose and screen anchor.
   **Reverse Y** reverses scrolling too; sensitivity scales it. The default is
   one wheel notch per 3 degrees. An 80 ms grace period lets nearly simultaneous
   fingers form the chord without an unintended click.
6. **Pause pointer** stops movement, scrolling and held buttons. Esc does not
   affect pointer control. Click **Enable pointer**
   to resume. Startup and sustained connection outages require an explicit enable.

This restoration removes the experimental sideways cursor mapping, automatic
activation, extra cursor smoothing and pinch freeze added alongside that mode.
The existing orientation filter and angle dead zone remain. Held buttons and
two-finger scrolling were added after restoring tilt control.
Translation helpers remain in the source but are not used by the cursor.

The pointer loop runs independently of camera video at up to 100 updates/sec.
Brief interruptions freeze movement and clicks, then recover automatically.
Near-vertical pitch temporarily pauses control until the hand is lowered.
Touches made while paused are discarded. Regression tests cover held-angle
position, return to neutral, reversal, tracking recovery, hold/release dragging,
scroll direction and noise, chord transitions, and releasing buttons on lost data.

## Verification and historical evidence

The observations below came from earlier hardware-branch sessions. Test counts
refer to those revisions, not the present suite. Local evidence files are not
included in source packages. The current implementation requires **Pause pointer**;
older references to Esc stopping the pointer describe superseded behavior.
Run the root README's test commands for the current source. Desktop tests use
fixtures and stubbed OS input; a passing Mac run is not Windows hardware acceptance.

The earlier direct-position and automatic-recovery update passed **55 automated
tests** at that revision. Regressions cover held-angle position, linear sensitivity, return to
neutral after reaching screen edges, reference preservation through tracking
resets, near-vertical recovery, and preventing queued clicks on resume. Sensor
clipping now resets the filter once per episode instead of once per clipped
sample, and remains an explicit invalid-reading/calibration-failure condition.

The earlier finger-click update passed 47 automated tests, including one click per
held touch, brief taps, pause/re-enable, stale data, counter wrap/reset, and the
Windows press/release structures and failure handling. Native click tests use
a stubbed SendInput function; they do not inject real desktop clicks. The updated
viewer was reopened with fresh calibrated Bluetooth readings at about 1,002
samples/sec. Physical finger-to-desktop clicks still need a user trial.

The Windows pointer feature passed all 36 automated motion tests (including
12 pointer tests for mapping, neutral, axis reversal, rate limits and stop
conditions). With the saved gyro calibration loaded, a live 20-second BLE check
received 40/40 fresh status readings at about 1,002 samples/sec. Windows pointer
updates succeeded and the sampled cursor readback contained 14 distinct positions.
In that older revision, pressing Esc disabled control and stopped movement.
The current revision deliberately does not stop the pointer on Esc.
Evidence: `.local/motion-pointer-verification.json` and
`.local/motion-pointer-stop-verification.json`. Direction comfort and sensitivity
can be adjusted with the viewer controls for the final glove mounting.

Live hardware checks on 2026-10-24 (before stationary calibration): USB on COM5
received 5,994 samples in approximately 6 seconds at 1,001.89 samples/s. BLE
at `20:6E:F1:31:64:3D` received 10,035 samples in approximately 10 seconds at
1,002.00 samples/s, with negotiated MTU 247. Both runs had zero packet CRC
errors, sample gaps, I2C errors, or FIFO resets during the capture. BLE reported
zero transmit-queue drops. BLE identity `206EF131643C` matches the Nano USB
serial, so both transports use the same saved bias profile. Evidence is in
`.local/motion-usb-verification.json` and `.local/motion-ble-verification.json`.
These checks verify acquisition/transport, not calibrated angle accuracy.
The updated viewer was also visually checked with live BLE angles and increasing
left/right tap counters; all controls fit the laptop screen. After the camera
was powered, live 640x480 Bluetooth video was observed at about 5 fps alongside
the BLE motion panel. A subsequent 5-second check had 20/20 fresh motion readings
at 1001.99–1002.51 samples/s with no additional packet errors, BLE queue drops,
or tracking restarts. Evidence: `.local/camera-motion-concurrent-verification.json`.
Stationary calibration was left idle at the user's request. All 24 automated
tests passed.

The Nano's TinyUSB `Serial` boolean was false despite an active CDC data link
on this Windows driver. The firmware therefore uses `tud_cdc_connected()`.
`tools/Restart-Nano.py --serial 206EF131643C` sends a scoped DFU DETACH after
upload when the bundled uploader leaves the previous application running.

`python -m unittest discover -s tools -p 'test_*.py' -v` tests binary corruption
and fragmentation, signed readings, tap counts, known tilts and rotations,
quaternion normalization, drift compensation, acceleration rejection, stale
data, and rejection of synthetic moving/drifting calibration runs. These tests
do not substitute for the user's stationary calibration or an angle-reference
accuracy measurement. Physical calibration must be explicitly started.

Sensor rates/registers: [InvenSense MPU-6050 register map](https://www.invensense.com/wp-content/uploads/2015/02/MPU-6000-Register-Map1.pdf).
Wiring: [Arduino Nano ESP32 manual](https://docs.arduino.cc/tutorials/nano-esp32/cheat-sheet/).

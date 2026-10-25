# Latency changes and Windows acceptance

Implementation base: main `dd91658a47345ed5590efa13553789f214a5e199`.
No firmware update is required for these changes.

## What changed

- The Bluetooth receiver checks JPEG framing and immediately hands the bytes to
  a decoder worker. One JPEG may be decoding and only one additional JPEG may
  wait; a newer pending JPEG replaces an older one. The decoded-output queue is
  also bounded to one. Stop/disconnect closes the decoder, invalidating late work.
  Reconnection messages and decoded frames carry a session number.
- Camera FPS cap is selectable while running: 5, 10, 15, 20 or 30. A custom CLI
  `--fps` value is also retained in the selector. The default remains 15. It is a
  request cap, not a guarantee. Changing it takes effect on subsequent requests;
  an already-started request or pacing wait is not interrupted.
- One capture may transfer while the previous JPEG is decoding. If that decode
  is still busy and one JPEG is already waiting, the next `CAPTURE` waits.
  Waiting is interrupted by Stop and by closing the decoder.
- `CAPTURE_ERROR` does not drop the RFCOMM session. The following command stays
  aligned. Five capture failures in a row close the session. A bad trailer,
  invalid JPEG, or any other unexpected header still closes it, because the
  byte stream is no longer aligned. Silence longer than 2 seconds on one
  `recv` also closes it. The connect timeout stays 12 seconds. A slow frame
  that keeps delivering bytes is not treated as silence.
- After a session that connected, the first reconnect waits 1 second, matching
  the socket linger. If that reconnect is refused, later attempts wait 2, 4,
  and then 8 seconds. A camera that never accepts the connection uses that
  same cold schedule. Stop during the wait returns immediately.
- The latency readout's second line, `show`, is the time from JPEG receipt
  until the preview widget is updated. It is not monitor scanout time. Previews
  of the same pixel size reuse one Tk image.
- A known glove address reconnects with `BleakClient` and does not scan. The
  first glove search waits while the camera socket is open. BLE reconnects
  that fail during that time wait 2, 4, then 8 seconds. USB motion is
  unchanged. The glove status shows BLE MTU when it is below 241 bytes.
- `DECODED FPS` measures decoded frames consumed by the UI using receive timestamps.
  It is not a direct measurement of displayed FPS. `REQUEST → DECODE` includes
  request/transfer, decoder queue waiting and decoding, but excludes preview
  resize, Tk image creation, monitor scanout, and camera exposure age. Frame
  freshness now starts at JPEG receipt, rather than after decoding. Each Frame
  also records transfer and decode seconds for diagnostics.
- Gemini's client is lazy and reused. A changed key replaces it. Requests are
  serialized; closing the app prevents new requests and releases the client after
  any in-flight call. Stop reply invalidates results but does not abort an SDK
  request already in flight; a later request may wait for that call to finish.
- Windows read-aloud keeps one PowerShell process and SpeechSynthesizer for normal
  replies. Base64 UTF-8 lines carry reply data, not executable code. Cancel kills
  that worker; the next reply starts a fresh one. App shutdown also kills it.
- The rotated cloud JPEG is cached by frame identity and rotation. New frames,
  rotation changes, and clear invalidate the cache. Freshness is checked even on
  cache hits. Rotated frames are re-encoded at quality 75 and the original size.
- Typing uses one lazy worker, which creates, reuses and releases COM/UI Automation
  objects on the same thread. Every character still checks destination identity,
  editability, cancellation, Esc and modifiers. The 12 ms character pacing and
  complete action-plan validation remain. Partial actions are never retried.

## Automated checks

Install the project's requirements in a Python 3.12 environment on Windows.
From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py" -q
$env:SYNCHRO_TEST_DESKTOP = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tools -p "test_*.py" -q
Remove-Item Env:SYNCHRO_TEST_DESKTOP
```

The new `test_latency.py` checks transfer/decode overlap with synchronization
barriers, replacement of pending work, stop invalidation, decode failure, FPS
changes, receive timestamps, cache invalidation/expiry, pooled API lifecycle,
speech reuse/cancel/shutdown, and UI Automation worker ownership. Existing tests
still cover protocol fragmentation/corruption, plan validation, focus changes,
partial input failure, Unicode and character pacing. Desktop checks use actual
Tk widgets and image conversion, with hardware and cloud calls replaced by test
doubles. They exercise the FPS selector at 980x720 and 1280x860.

Observed on this Mac development host with Python 3.12: 192 tests, 14 skipped,
no failures, with desktop checks enabled. Tested versions: Python 3.12.14,
Pillow 12.3.0, NumPy 2.3.5, google-genai 2.33.0, sounddevice 0.5.6 on macOS 26.2
ARM64. Windows native INPUT/DPAPI and optional
checks remain skipped. These results do not establish Bluetooth FPS, Windows
COM behavior, real speech playback, model accuracy or cloud latency.

Integration check in the renamed `/Users/jaydenlam/Desktop/Projects/Synchro`
folder: 196 tests, 14 skipped, no failures using its Python 3.12.15 environment,
with desktop checks enabled. This includes the pre-existing local preview,
branding and camera tests; unrelated local edits are outside the latency commit.

## Camera acceptance and performance comparison

1. Test the base revision and modified source in separate folders/environments,
   using identical hardware, scene, camera position, pairing and app settings.
   Run only one viewer at a time. Start each without microphone/pointer load, then
   repeat with the glove, pointer, microphone, and Jarvis active. The microphone
   starts without RNNoise.
2. Launch the modified viewer with your camera address:

   ```powershell
   .\.venv\Scripts\python.exe tools\bluetooth_viewer.py --address YOUR_CAMERA_MAC --fps 15
   ```

3. Warm up for 30 seconds. Select 5, 10, 15, 20 and 30 FPS while video is running.
   Spend at least 60 seconds at each cap; repeat each run three times. Confirm
   the selector never opens another connection and video continues. A low cap
   should bound the rate; a high cap may provide no gain if transfer is limiting.
   Record decoded FPS, request-to-decode time, CPU use and responsiveness.
4. Measure visible latency separately: point the camera at a millisecond timer
   beside the preview and take screenshots/photos showing both readings, or use
   a recording that captures the source and display together. Collect at least
   100 observations per setup; compare median and p95. The on-screen decode
   metric is not camera-to-screen latency. Confirm higher FPS does not increase
   visible frame age or produce growing memory use.
5. Toggle rotation and resize continuously while streaming. Save photos in both
   orientations and compare them with the preview. Stop must keep the labeled
   last frame saveable, while Jarvis must no longer receive it as a live frame.
   Restart must clear the old preview. Repeat Stop/Start ten times, including
   during transfer; there must be no old frames reappearing after reconnect.
6. Power off the camera during transfer. Verify an unavailable state, bounded
   memory, working glove/speech, and automatic recovery after power-on. Close the
   app while receiving/decoding; verify no continuing camera requests.

The existing `--probe` remains a synchronous protocol/transport diagnostic. Its
FPS is not a benchmark of the new viewer pipeline. Compare the actual viewer
for overlap benefits. There is no claimed FPS improvement until measured here.

## JPEG preparation benchmark and visual accuracy

Save representative camera JPEGs: ordinary objects, small labels, low light and
busy scenes. The local benchmark performs no cloud calls:

```powershell
.\.venv\Scripts\python.exe tools\benchmark_vision_jpeg.py .local\bluetooth-photos\YOUR_PHOTO.jpg --repeat 30 --output-dir .local\vision-variants
```

It reports median/p95 preparation time, dimensions and bytes for quality 90,
quality 80, quality 75 at a 480-pixel maximum edge, and quality 70 at 320 pixels.
Saved variants are rotated 180 degrees, matching the default viewer orientation;
use a raw, unrotated capture when comparing orientation. Without `--output-dir`,
no images are written. Outputs should go in a fresh directory: matching variant
filenames are overwritten. The tool does not alter runtime image settings.

For a small software-only sanity run, a synthetic 640x480 textured fixture on
this Mac produced 206,156 / 150,410 / 64,255 / 20,725 bytes respectively. Median
preparation was approximately 1.37 / 1.22 / 3.62 / 2.75 ms (30 iterations). This is
not a camera scene, Windows timing or an upload/answer benchmark. Resizing can
cost more CPU even when it reduces bytes.

Before adopting a smaller cloud image, compare identical questions against all
variants using the configured model and the same conversation context. Include
small text, colors, orientation and spatial references. Score correctness and
unreadable details, and measure complete request latency across repeated runs.
A smaller file is not sufficient evidence of a better setting. Keep the default
unless the accuracy/performance tradeoff is acceptable.

## Jarvis, read-aloud and typing acceptance

1. Supply your normal encrypted Gemini key. Ask a short visual question, then
   several follow-ups. Verify conversation context, one image per request, and
   the same image orientation as the preview. Test with camera off, Jarvis off,
   Read aloud off, and Typing & keys off. Core local features must still work.
2. For playback, compare first and subsequent short replies. Task Manager should
   show one retained speech PowerShell child between successful replies. Stop
   reply during a long answer; audio must stop, old text must not be played on
   the next reply, and the next request must work with a new speech worker.
   Repeat cancellation ten times, then close during playback. No speech child
   should remain. Force-end the speech child once; a later reply should recover.
3. Compare perceived reply-to-first-audio time for at least ten cold and ten warm
   replies. Network answer time and playback startup are different stages.
   A first reply still pays process startup; reuse benefits subsequent replies.
4. Use disposable fields in Notepad and a browser. Dictate exact mixed-case text,
   repeated letters, punctuation, accents and emoji. Check the resulting text
   character-for-character. Test text then Enter, and select-all then copy.
5. During a long typing action, switch to another field in the same window, then
   another app. Remaining characters and subsequent Enter must stop. Repeat with
   Esc, a held modifier, Stop reply, Typing & keys off, and app shutdown. Test a
   read-only field, password field and terminal: input must be refused.
6. Test two consecutive requests without restarting. Worker reuse must not reuse
   the previous field identity: click a new field before the second request and
   verify only that new target receives its authorized text. Run repeated writes
   and cancellations for ten minutes; check CPU, memory and thread/process counts
   settle rather than growing with each request.

Accept only if there are no stale frames/actions, repeated/lost characters,
or orphan speech workers, and camera latency/FPS are no worse under matched
conditions. Record Windows version, Python/dependency versions, device addresses
(without keys), settings and actual results separately from software fixtures.

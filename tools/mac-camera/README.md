# Synchro camera test on a Mac

This native macOS viewer connects directly to the existing camera over
Bluetooth Classic RFCOMM. No camera reflash, Wi-Fi network, browser, Python,
or third-party packages are needed. The image is rotated 180 degrees by
default; uncheck Rotate 180° to show the camera's original orientation.

**Validation status:** prepared on Windows using Apple's documented
IOBluetooth APIs. It has not yet been compiled or hardware-tested on a Mac.
The same camera and packet protocol have been tested on the Windows viewer.

## Before connecting

1. Power the ESP32-CAM from the PowerBoost's 5V/GND output and battery.
   Leave camera IO0 unconnected. The Nano is not needed to carry the video.
2. Click Stop or close the Windows camera viewer. Only one viewer should
   connect to this camera at a time.
3. Keep the Mac near the camera. In System Settings > Bluetooth, pair with
   **Synchro-Cam-BT**. The pairing PIN is in the included `PAIRING.txt`.
   Pairing alone does not display video or make this a system webcam.

## Build and run

Requires macOS 12 or later and Apple's Command Line Tools (or Xcode).
The build uses the Mac's own processor architecture, including Apple Silicon.

1. Extract the whole ZIP into a normal writable folder.
2. If Apple's developer tools are not installed, open Terminal and run:

   ```sh
   xcode-select --install
   ```

   Finish Apple's installation dialog before continuing.
3. In Terminal, type `bash ` (including a space), drag `Start-Mac.command`
   from the extracted folder into the Terminal window, then press Return.
   The script compiles and opens **Synchro Camera.app** in that same folder.
4. Allow the app's Bluetooth request, then click **Start**. The status below
   the image should show `Bluetooth live`, frame dimensions, and a growing
   frame count. Move the camera to check the picture updates.
5. Click **Stop** to release the camera when finished. Later, open the built
   app directly; rebuilding is only needed after source changes.

If the build fails, share the first compiler error. If connection times out,
check battery power and pairing, close other viewers, and press Start again.
If Bluetooth access was denied, the Mac owner can review the app's access in
System Settings > Privacy & Security > Bluetooth. Do not disable macOS security
features. This is a locally built demo app, not a signed/notarized installer.

## Known test target

- Camera: `Synchro-Cam-BT`, Bluetooth address `70:4B:CA:46:52:22`, channel 1.
- Firmware: `bluetooth-2`, OV3660, 640 x 480 JPEG.
- One requested frame at a time, at most 15 requests per second. Actual fps
  depends on scene detail and Bluetooth conditions.
- Tests video only; does not implement MPU mouse control or copper-pad clicks.

API references: [Apple IOBluetooth](https://developer.apple.com/documentation/iobluetooth),
[RFCOMM connection](https://developer.apple.com/documentation/iobluetooth/iobluetoothdevice/openrfcommchannelasync(_:withchannelid:delegate:)),
[Bluetooth permission description](https://developer.apple.com/documentation/bundleresources/information-property-list/nsbluetoothalwaysusagedescription).

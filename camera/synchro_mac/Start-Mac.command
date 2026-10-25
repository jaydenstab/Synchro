#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Run this launcher on the Mac that will view the camera."
    exit 1
fi
if ! xcode-select -p >/dev/null 2>&1; then
    echo "First install Apple's Command Line Tools: xcode-select --install"
    echo "After installation finishes, run this file again."
    exit 1
fi
camera_app="$PWD/Synchro Camera.app"
mkdir -p "$camera_app/Contents/MacOS"
cp Info.plist "$camera_app/Contents/Info.plist"
echo "Building the Mac camera viewer locally..."
sources=()
while IFS= read -r file; do
    sources+=("$file")
done < <(find Sources -name '*.swift' | sort)
sources+=("SynchroDisplay.swift" "SynchroShell.swift" "SynchroCamera.swift")
xcrun swiftc -swift-version 5 -O -framework AppKit -framework IOBluetooth \
    -framework ImageIO -framework CoreGraphics -framework QuartzCore \
    -framework UniformTypeIdentifiers -framework WebKit \
    "${sources[@]}" -o "$camera_app/Contents/MacOS/SynchroCamera"
codesign --force --sign - "$camera_app"
root="$(cd "$PWD/../.." && pwd)"
echo "Opening Synchro. Camera is the native viewer. Gestures, Test, and Settings use the local service."
echo "Allow its Bluetooth prompt, then press Start on the Camera page."
echo "Request-to-frame time is the full CAPTURE round trip, not sensor exposure."
open "$camera_app" --args --root "$root"

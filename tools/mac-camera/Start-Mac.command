#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Run this launcher on your partner's Mac."
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
xcrun swiftc -swift-version 5 -O -framework AppKit -framework IOBluetooth \
    SynchroCamera.swift -o "$camera_app/Contents/MacOS/SynchroCamera"
codesign --force --sign - "$camera_app"
echo "Opening the viewer. Allow its Bluetooth prompt, then press Start."
open "$camera_app"

#!/bin/bash
# Compiles and runs the simulated RFCOMM tests. No Bluetooth and no camera.
set -euo pipefail
cd -- "$(dirname -- "$0")"
if ! xcode-select -p >/dev/null 2>&1; then
    echo "Apple's Command Line Tools are required: xcode-select --install" >&2
    exit 1
fi
out="$(mktemp -t synchro-simulated-tests)"
trap 'rm -f "$out"' EXIT
xcrun swiftc -swift-version 5 \
    -framework ImageIO -framework CoreGraphics \
    Sources/SynchroBuffer.swift \
    Sources/SynchroProtocol.swift \
    Sources/SynchroStats.swift \
    Sources/SynchroImage.swift \
    Sources/LocalFrameBridge.swift \
    Tests/SimulatedProtocolTests.swift \
    -o "$out"
"$out"

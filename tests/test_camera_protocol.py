"""Hardware-free checks for the Synchro camera viewer.

The Swift suite feeds synthetic RFCOMM bytes. It does not measure the ESP32-CAM.
"""

import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMERA = ROOT / "camera" / "synchro_mac"


def test_simulated_camera_protocol_suite():
    assert platform.system() == "Darwin", "the camera suite compiles with the macOS Swift tools"
    script = CAMERA / "run-tests.sh"
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "SIMULATED" in result.stdout
    assert "not ESP32-CAM measurements" in result.stdout
    assert "failed: 0" in result.stdout


def test_original_viewer_checkpoint_is_intact():
    original = (CAMERA / "original" / "SynchroCamera.swift").read_text()
    assert "openRFCOMMChannelAsync" in original
    assert "JPEG_BEGIN" in original
    assert "JPEG_END" in original
    assert 'send("STATUS\\n")' in original
    assert 'send("CAPTURE\\n")' in original
    assert not (CAMERA / "original" / "PAIRING.txt").exists()


def test_pairing_secret_is_not_copied_into_source_or_docs():
    pairing = CAMERA / "PAIRING.txt"
    secret = ""
    for line in pairing.read_text().splitlines():
        if "PIN" in line and ":" in line:
            secret = line.split(":", 1)[1].strip()
    assert secret
    roots = [
        ROOT / ".gitignore",
        ROOT / "README.md",
        ROOT / "camera" / "README.md",
        ROOT / "camera" / "CAMERA_TESTING.md",
        CAMERA / "README.md",
        CAMERA / "SynchroCamera.swift",
        CAMERA / "Start-Mac.command",
    ]
    assert "PAIRING.txt" in (ROOT / ".gitignore").read_text()
    for path in roots:
        if secret in path.read_text():
            raise AssertionError(f"{path.relative_to(ROOT)} contains the Bluetooth pairing PIN")
    for path in (CAMERA / "original").iterdir():
        if secret in path.read_text(errors="ignore"):
            raise AssertionError(f"checkpoint {path.name} contains the Bluetooth pairing PIN")
    for path in CAMERA.rglob("*.swift"):
        if "original" in path.parts:
            continue
        if secret in path.read_text(errors="ignore"):
            raise AssertionError(f"{path.relative_to(ROOT)} contains the Bluetooth pairing PIN")

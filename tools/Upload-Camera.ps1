param(
    [string]$Port = 'COM5',
    [ValidateSet('SynchroCam', 'SynchroCamBluetooth')]
    [string]$Sketch = 'SynchroCam'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDirectory = Join-Path $projectRoot ('.build\' + $Sketch)
$arduinoPackages = Join-Path $env:LOCALAPPDATA 'Arduino15\packages'
$esptoolPath = Join-Path $arduinoPackages 'esp32\tools\esptool_py\4.5.1\esptool.exe'
$bootAppPath = Join-Path $arduinoPackages 'esp32\hardware\esp32\2.0.17\tools\partitions\boot_app0.bin'
$bootloaderPath = Join-Path $buildDirectory ($Sketch + '.ino.bootloader.bin')
$partitionsPath = Join-Path $buildDirectory ($Sketch + '.ino.partitions.bin')
$firmwarePath = Join-Path $buildDirectory ($Sketch + '.ino.bin')
foreach ($requiredPath in @($esptoolPath, $bootAppPath, $bootloaderPath, $partitionsPath, $firmwarePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required file missing: $requiredPath" }
}
New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot '.local') | Out-Null
$uploadLog = Join-Path $projectRoot '.local\camera-upload.log'
# ESP32 is the camera. The Nano bridge is an ESP32-S3, so keep --chip explicit.
# IO0 must be grounded and the camera manually reset before this command.
& $esptoolPath --chip esp32 --port $Port --baud 230400 --before no_reset --after no_reset_stub write_flash -z --flash_mode dio --flash_freq 40m --flash_size 4MB 0x1000 $bootloaderPath 0x8000 $partitionsPath 0xe000 $bootAppPath 0x10000 $firmwarePath 2>&1 | Tee-Object -FilePath $uploadLog
if ($LASTEXITCODE -ne 0) { throw "Camera upload failed (exit $LASTEXITCODE). See $uploadLog" }
Write-Output 'UPLOAD_COMPLETE: disconnect USB, remove camera IO0-GND jumper, then reconnect USB to run the firmware.'

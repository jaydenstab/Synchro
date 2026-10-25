param([string]$Port = 'COM5', [int]$WaitSeconds = 30)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$btBootstrapPort = [System.IO.Ports.SerialPort]::new($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$btBootstrapPort.DtrEnable = $true
$btBootstrapPort.RtsEnable = $true
$btBootstrapPort.NewLine = "`n"
$btBootstrapPort.ReadTimeout = 1000
$btBootstrapPort.WriteTimeout = 3000
try {
    $btBootstrapPort.Open()
    $btBootstrapTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $lastQuery = -2
    while ($btBootstrapTimer.Elapsed.TotalSeconds -lt $WaitSeconds) {
        if ($btBootstrapTimer.Elapsed.TotalSeconds - $lastQuery -ge 2) {
            $btBootstrapPort.WriteLine('STATUS')
            $lastQuery = $btBootstrapTimer.Elapsed.TotalSeconds
        }
        try { $line = $btBootstrapPort.ReadLine().Trim() } catch [System.TimeoutException] { continue }
        if ($line) { Write-Output $line }
        if (-not $line.StartsWith('{')) { continue }
        $device = $line | ConvertFrom-Json
        if ($device.firmware -notin @('bluetooth-1', 'bluetooth-2')) { throw 'Camera is still running different firmware.' }
        if (-not $device.camera_ready -or -not $device.bluetooth_ready) { throw 'Camera/Bluetooth initialization failed.' }
        if ([int]$device.bt_channel -lt 1) { continue }
        if ($device.bt_address -notmatch '^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$') { throw 'Invalid camera Bluetooth address.' }
        New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot '.local') | Out-Null
        $device | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot '.local\bluetooth-camera.json') -Encoding utf8
        Write-Output 'BLUETOOTH_READY: saved camera identity for pairing and the laptop viewer.'
        return
    }
    throw 'No Bluetooth camera status response received.'
} finally {
    if ($btBootstrapPort.IsOpen) { $btBootstrapPort.Close() }
    $btBootstrapPort.Dispose()
}

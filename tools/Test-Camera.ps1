param(
    [string]$Port = 'COM5',
    [int]$WaitForBootSeconds = 120,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\.local\camera-test')
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$cameraSerial = [System.IO.Ports.SerialPort]::new($Port, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
$cameraSerial.DtrEnable = $true
$cameraSerial.RtsEnable = $true
$cameraSerial.NewLine = "`n"
$cameraSerial.ReadTimeout = 1000
$cameraSerial.WriteTimeout = 5000
try {
    $cameraSerial.Open()
    Write-Output "Listening on $Port; waiting for SynchroCam to boot."
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $lastQuery = -2
    $status = $null
    while ($timer.Elapsed.TotalSeconds -lt $WaitForBootSeconds) {
        if ($timer.Elapsed.TotalSeconds - $lastQuery -ge 2) {
            $cameraSerial.WriteLine('STATUS')
            $lastQuery = $timer.Elapsed.TotalSeconds
        }
        try { $line = $cameraSerial.ReadLine().Trim() } catch [System.TimeoutException] { continue }
        if ($line.Length -gt 0) { Write-Output $line }
        if ($line.StartsWith('{') -and $line.Contains('"camera_ready"')) {
            $status = $line | ConvertFrom-Json
            break
        }
    }
    if ($null -eq $status) { throw 'No SynchroCam status response received.' }
    $status | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'status.json')
    if (-not $status.camera_ready) { throw 'Camera initialization failed.' }
    if (-not $status.http_ready) { throw 'HTTP server initialization failed.' }

    $cameraSerial.WriteLine('HTTPTEST')
    $httpResults = @{}
    $timer.Restart()
    while ($timer.Elapsed.TotalSeconds -lt 35 -and $httpResults.Count -lt 3) {
        try { $line = $cameraSerial.ReadLine().Trim() } catch [System.TimeoutException] { continue }
        if ($line.Length -gt 0) { Write-Output $line }
        if ($line -match '^HTTP_TEST (\S+) code=(\d+) bytes=(-?\d+) valid=(true|false)$') {
            $httpResults[$Matches[1]] = ($Matches[2] -eq '200' -and [int]$Matches[3] -gt 0 -and $Matches[4] -eq 'true')
        }
    }
    foreach ($route in @('/', '/status', '/capture')) {
        if (-not $httpResults.ContainsKey($route) -or -not $httpResults[$route]) { throw "HTTP self-test failed: $route" }
    }

    for ($frameIndex = 1; $frameIndex -le 3; $frameIndex++) {
        $cameraSerial.WriteLine('CAPTURE')
        $frameLength = 0
        $frameWidth = 0
        $frameHeight = 0
        $timer.Restart()
        while ($timer.Elapsed.TotalSeconds -lt 30) {
            try { $line = $cameraSerial.ReadLine().Trim() } catch [System.TimeoutException] { continue }
            if ($line -match '^JPEG_BEGIN (\d+) (\d+) (\d+)$') {
                $frameLength = [int]$Matches[1]
                $frameWidth = [int]$Matches[2]
                $frameHeight = [int]$Matches[3]
                break
            }
            if ($line -eq 'CAPTURE_ERROR') { throw 'The sensor failed to capture a JPEG.' }
        }
        if ($frameLength -lt 4 -or $frameLength -gt 2000000) { throw "Invalid JPEG length: $frameLength" }
        $frameBytes = [byte[]]::new($frameLength)
        $received = 0
        $cameraSerial.ReadTimeout = 15000
        while ($received -lt $frameLength) {
            $received += $cameraSerial.Read($frameBytes, $received, $frameLength - $received)
        }
        $cameraSerial.ReadTimeout = 1000
        $endMarker = $cameraSerial.ReadLine().Trim()
        if ($endMarker -eq '') { $endMarker = $cameraSerial.ReadLine().Trim() }
        if ($endMarker -ne 'JPEG_END') { throw 'JPEG transfer did not finish cleanly.' }
        if ($frameBytes[0] -ne 255 -or $frameBytes[1] -ne 216 -or $frameBytes[-2] -ne 255 -or $frameBytes[-1] -ne 217) {
            throw 'JPEG start/end markers are invalid.'
        }
        $framePath = Join-Path $OutputDirectory "frame-$frameIndex.jpg"
        [System.IO.File]::WriteAllBytes([System.IO.Path]::GetFullPath($framePath), $frameBytes)
        Write-Output "CAPTURE_OK frame=$frameIndex bytes=$frameLength size=${frameWidth}x${frameHeight} file=$framePath"
        Start-Sleep -Milliseconds 300
    }
    Write-Output 'PASS: camera initialization, 3 local HTTP endpoints, and 3 JPEG transfers. External Wi-Fi/browser viewing still requires a client test.'
} finally {
    if ($cameraSerial.IsOpen) { $cameraSerial.Close() }
    $cameraSerial.Dispose()
}

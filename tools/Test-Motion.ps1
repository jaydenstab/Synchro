param(
    [string]$Port = 'COM5',
    [ValidateRange(2, 45)][int]$Seconds = 12,
    [ValidateSet('initial', 'still', 'moving', 'clicks')][string]$Phase = 'initial'
)
$ErrorActionPreference = 'Stop'
$culture = [Globalization.CultureInfo]::InvariantCulture
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputFolder = Join-Path $projectRoot ('.local\motion-' + $Phase + '-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $outputFolder -Force | Out-Null
$serial = [IO.Ports.SerialPort]::new($Port, 115200, [IO.Ports.Parity]::None, 8, [IO.Ports.StopBits]::One)
$serial.DtrEnable = $false
$serial.RtsEnable = $false
$serial.NewLine = "`n"
$serial.ReadTimeout = 500
$samples = [Collections.Generic.List[object]]::new()
$lines = [Collections.Generic.List[string]]::new()
$diagnostics = [Collections.Generic.List[string]]::new()
$badRows = 0
$timedOutReads = 0
$timer = [Diagnostics.Stopwatch]::new()
try {
    $serial.Open()
    # Assert DTR before RTS after opening. The Nano's TinyUSB core treats
    # RTS-before-DTR as part of its reboot handshake, suppressing CDC output.
    $serial.DtrEnable = $true
    $serial.RtsEnable = $true
    $timer.Start()
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        try { $line = $serial.ReadLine().Trim() }
        catch [TimeoutException] { $timedOutReads++; continue }
        if (-not $line) { continue }
        if ($line.StartsWith('#')) { $diagnostics.Add($line); continue }
        if ($line.StartsWith('ms,address,')) { continue }
        $fields = $line -split ','
        if ($fields.Count -ne 12 -or $fields[0] -notmatch '^\d+$' -or $fields[1] -ne '0x68') {
            $badRows++
            $diagnostics.Add('UNRECOGNIZED: ' + $line)
            continue
        }
        if ($fields[2] -notin @('0', '1') -or $fields[10] -notin @('0', '1') -or $fields[11] -notin @('0', '1')) {
            $badRows++
            continue
        }
        try {
            $values = foreach ($column in 3..9) { [double]::Parse($fields[$column], $culture) }
            if ($fields[2] -eq '1' -and @($values | Where-Object { [double]::IsNaN($_) -or [double]::IsInfinity($_) }).Count) {
                throw 'Non-finite sensor reading'
            }
            $sample = [pscustomobject]@{
                ms = [uint32]::Parse($fields[0], $culture)
                ready = $fields[2] -eq '1'
                ax = $values[0]; ay = $values[1]; az = $values[2]
                gx = $values[3]; gy = $values[4]; gz = $values[5]
                temperature_c = $values[6]
                left = [int]$fields[10]; right = [int]$fields[11]
            }
            $samples.Add($sample)
            $lines.Add($line)
        } catch { $badRows++ }
    }
} finally {
    $timer.Stop()
    if ($serial.IsOpen) { $serial.Close() }
    $serial.Dispose()
}

$header = 'ms,address,imu_ready,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_c,left_down,right_down'
@($header) + $lines.ToArray() | Set-Content -LiteralPath (Join-Path $outputFolder 'samples.csv') -Encoding utf8
$diagnostics.ToArray() | Set-Content -LiteralPath (Join-Path $outputFolder 'diagnostics.log') -Encoding utf8
$valid = @($samples | Where-Object ready)
$channelStats = [ordered]@{}
foreach ($name in @('ax', 'ay', 'az', 'gx', 'gy', 'gz', 'temperature_c')) {
    if ($valid.Count) {
        $m = $valid | Measure-Object -Property $name -Minimum -Maximum -Average
        $channelStats[$name] = @{ minimum = $m.Minimum; maximum = $m.Maximum; mean = $m.Average }
    }
}
$normStats = $null
if ($valid.Count) {
    $m = $valid | ForEach-Object { [Math]::Sqrt($_.ax * $_.ax + $_.ay * $_.ay + $_.az * $_.az) } |
        Measure-Object -Minimum -Maximum -Average
    $normStats = @{ minimum = $m.Minimum; maximum = $m.Maximum; mean = $m.Average }
}
$transitions = @{ left = @{ presses = 0; releases = 0 }; right = @{ presses = 0; releases = 0 } }
$clockBackwards = 0
$maxGapMs = 0
for ($i = 1; $i -lt $samples.Count; $i++) {
    $previous = $samples[$i - 1]
    $current = $samples[$i]
    if ($current.ms -lt $previous.ms) { $clockBackwards++ }
    else { $maxGapMs = [Math]::Max($maxGapMs, [long]$current.ms - [long]$previous.ms) }
    foreach ($contact in @('left', 'right')) {
        if ($previous.$contact -eq 0 -and $current.$contact -eq 1) { $transitions[$contact].presses++ }
        if ($previous.$contact -eq 1 -and $current.$contact -eq 0) { $transitions[$contact].releases++ }
    }
}
$sampleHz = $null
if ($samples.Count -ge 2 -and $clockBackwards -eq 0) {
    $span = [long]$samples[-1].ms - [long]$samples[0].ms
    if ($span -gt 0) { $sampleHz = 1000.0 * ($samples.Count - 1) / $span }
}
$report = [ordered]@{
    phase = $Phase
    port = $Port
    collected_utc = [DateTime]::UtcNow.ToString('o')
    elapsed_seconds = $timer.Elapsed.TotalSeconds
    sample_count = $samples.Count
    valid_imu_samples = $valid.Count
    missing_imu_samples = $samples.Count - $valid.Count
    malformed_rows = $badRows
    timed_out_reads = $timedOutReads
    sample_hz = $sampleHz
    clock_backwards_events = $clockBackwards
    maximum_sample_gap_ms = $maxGapMs
    acceleration_magnitude_g = $normStats
    channels = $channelStats
    contacts = $transitions
    first_contact_states = if ($samples.Count) { @{ left = $samples[0].left; right = $samples[0].right } } else { $null }
    last_contact_states = if ($samples.Count) { @{ left = $samples[-1].left; right = $samples[-1].right } } else { $null }
    diagnostics = $diagnostics.ToArray()
    output_folder = $outputFolder
}
$json = $report | ConvertTo-Json -Depth 7
$json | Set-Content -LiteralPath (Join-Path $outputFolder 'report.json') -Encoding utf8
Write-Output $json
if ($samples.Count -eq 0) { throw 'No motion-test CSV samples received. Verify Nano firmware and USB data connection.' }

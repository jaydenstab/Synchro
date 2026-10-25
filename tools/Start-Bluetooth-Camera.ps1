param([switch]$Console, [ValidateSet('auto', 'usb', 'ble')][string]$MotionTransport = 'auto', [switch]$Listen, [switch]$PausePointer)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonName = if ($Console) { 'python.exe' } else { 'pythonw.exe' }
$venvPython = Join-Path $projectRoot ('.venv\Scripts\' + $pythonName)
$bundledPython = Join-Path $env:USERPROFILE ('.cache\codex-runtimes\codex-primary-runtime\dependencies\python\' + $pythonName)
if (Test-Path -LiteralPath $venvPython) { $pythonPath = $venvPython }
elseif (Test-Path -LiteralPath $bundledPython) { $pythonPath = $bundledPython }
else { throw 'Python was not found. Create .venv and install requirements.txt (Python with Tcl/Tk).' }
$viewerPath = Join-Path $PSScriptRoot 'bluetooth_viewer.py'
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.local\bluetooth-camera.json'))) {
    throw 'Camera address is missing. Copy bluetooth-camera.example.json to .local\bluetooth-camera.json and set bt_address.'
}
[string[]]$speechArgs = @()
if ($Listen) { $speechArgs += '--listen' }
if ($PausePointer) { $speechArgs += '--pause-pointer' }
if ($Console) { & $pythonPath $viewerPath --motion-transport $MotionTransport @speechArgs }
else {
    $viewerProcess = Start-Process -FilePath $pythonPath -ArgumentList ('"' + $viewerPath + '" --motion-transport ' + $MotionTransport + ' ' + ($speechArgs -join ' ')) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
    Write-Output ('Synchro desktop process: ' + $viewerProcess.Id)
}

param([switch]$Console, [ValidateSet('auto', 'usb', 'ble')][string]$MotionTransport = 'auto', [switch]$Listen)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $venvPython) { $pythonPath = $venvPython }
elseif (Test-Path -LiteralPath $bundledPython) { $pythonPath = $bundledPython }
else { throw 'Python was not found. Create .venv and install requirements-web.txt.' }
$env:SYNCHRO_MOTION_TRANSPORT = $MotionTransport
if ($Listen) { $env:SYNCHRO_SPEECH_LISTEN = '1' }
Start-Process 'http://127.0.0.1:8000'
& $pythonPath -m uvicorn app:app --host 127.0.0.1 --port 8000

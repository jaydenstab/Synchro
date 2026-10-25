param([switch]$Start)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$scriptPath = Join-Path $PSScriptRoot 'calibrate_motion.py'
if ($Start) { & $pythonPath $scriptPath --start }
else { & $pythonPath $scriptPath }
exit $LASTEXITCODE

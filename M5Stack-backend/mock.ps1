param([string]$Url = 'ws://127.0.0.1:8765/ws/device', [switch]$Demo)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $PSScriptRoot
$arguments = @('-m', 'fire_backend.mock_device', '--url', $Url)
if ($Demo) { $arguments += '--demo' }
& '.\.venv\Scripts\python.exe' @arguments
exit $LASTEXITCODE

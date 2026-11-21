$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$bundle = Join-Path $PSScriptRoot 'dist\FIREBackend\FIREBackend.exe'
$python = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (Test-Path -LiteralPath $python) {
    Start-Process -FilePath $python -ArgumentList '-m','fire_backend.desktop_entry' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
} elseif (Test-Path -LiteralPath $bundle) {
    Start-Process -FilePath $bundle -WorkingDirectory (Split-Path -Parent $bundle) -WindowStyle Hidden
} else {
    throw 'Kjør start.ps1 én gang først, eller installer en godkjent Windows-pakke.'
}

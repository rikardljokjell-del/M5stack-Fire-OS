param([switch]$Shortcut)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Kjør start.ps1 én gang for å opprette Python-miljøet.' }
& $python -m pip install -r requirements-windows-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke installere pakkebyggeren.' }
& $python -m PyInstaller --noconfirm FIREBackend.spec
if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke bygge Windows-programmet.' }
if ($Shortcut) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $linkPath = Join-Path $desktop 'FIRE Backend.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($linkPath)
    # Use the installed trusted interpreter on this development PC. Its Windows
    # Application Control policy can reject an unsigned freshly built exe.
    $link.TargetPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
    $link.Arguments = '-m fire_backend.desktop_entry'
    $link.WorkingDirectory = $PSScriptRoot
    $link.Description = 'FIRE Backend – status, OpenAI og M5Stack-tilkobling'
    $link.Save()
}
Write-Host 'Klar: dist\FIREBackend\FIREBackend.exe'

param([switch]$Mock)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    )
    $basePython = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $basePython) { $basePython = (Get-Command python -ErrorAction Stop).Source }
    & $basePython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
}
$lockFile = Join-Path $PSScriptRoot 'requirements.lock.txt'
$stamp = Join-Path $PSScriptRoot '.venv\fire-dependencies.sha256'
$projectFile = Join-Path $PSScriptRoot 'pyproject.toml'
$fingerprint = (Get-FileHash -LiteralPath $lockFile -Algorithm SHA256).Hash + (Get-FileHash -LiteralPath $projectFile -Algorithm SHA256).Hash
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $dependencyHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($fingerprint))).Replace('-', '') }
finally { $hasher.Dispose() }
$installedHash = if (Test-Path -LiteralPath $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { '' }
if ($installedHash -ne $dependencyHash) {
    & $python -m pip install -r $lockFile -e .
    if ($LASTEXITCODE -ne 0) { throw 'Could not install backend dependencies.' }
    Set-Content -LiteralPath $stamp -Value $dependencyHash -Encoding ascii
}
if ($Mock) { $env:FIRE_AI_MODE = 'mock' }
& $python -m fire_backend
exit $LASTEXITCODE

# Local official Cloudflare CLI; no PATH/service/account changes.
$ErrorActionPreference = 'Stop'
$cloudflareDirectory = Join-Path $PSScriptRoot '..\workspace\tools\cloudflared'
$cloudflareProgram = Join-Path $cloudflareDirectory 'cloudflared.exe'
$cloudflareManifest = Join-Path $cloudflareDirectory 'manifest.json'
if (-not (Test-Path -LiteralPath $cloudflareProgram) -or -not (Test-Path -LiteralPath $cloudflareManifest)) {
    throw 'Cloudflare-verktøyet mangler. Bruk den offisielle, SHA256-kontrollerte Windows-utgivelsen fra cloudflare/cloudflared.'
}
$cloudflareMetadata = Get-Content -LiteralPath $cloudflareManifest -Raw | ConvertFrom-Json
if ($cloudflareMetadata.sha256 -notmatch '^[a-f0-9]{64}$' -or
    $cloudflareMetadata.source -notmatch '^https://github\.com/cloudflare/cloudflared/releases/download/[0-9.]+/cloudflared-windows-amd64\.exe$') {
    throw 'Ugyldig kontrollinformasjon for Cloudflare-programmet.'
}
$cloudflareHash = (Get-FileHash -LiteralPath $cloudflareProgram -Algorithm SHA256).Hash.ToLowerInvariant()
if ($cloudflareHash -ne $cloudflareMetadata.sha256 -or
    (Get-Item -LiteralPath $cloudflareProgram).Length -ne $cloudflareMetadata.size_bytes) {
    throw 'Cloudflare-programmet er endret eller ufullstendig. Det blir ikke startet.'
}
[string[]]$cloudflareArguments = @($args)
if ($cloudflareArguments.Count -eq 0) { $cloudflareArguments = @('--help') }
& $cloudflareProgram @cloudflareArguments
exit $LASTEXITCODE

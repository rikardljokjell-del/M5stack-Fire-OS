# Cloudflare for the existing FIRE backend

Both hostnames reach the same existing backend on `127.0.0.1:8765`.
Studio uses Cloudflare Access; FIRE uses its existing device-scoped bearer
credential over HTTPS/WSS. No second backend, additional credential store,
reverse proxy or device Access login is needed.

## Configure the existing Windows profile

Run from `M5Stack-backend/`. Preview validates without changing settings:

```powershell
.\.venv\Scripts\python.exe scripts\configure_public.py `
  --web-origin https://firestudio.ljoekjell.no `
  --device-host fire-device.ljoekjell.no `
  --access-issuer https://empty-king-bc41.cloudflareaccess.com `
  --access-audience 104f0a516bae2741b93291e7fea019a76a9482cb551cf42162db314e4e8e8d21 `
  --transport direct
```

Add `--save` only when ready to activate. This updates only the public fields
in the existing `DesktopStore`; it does not rewrite Windows Vault credentials,
model selections, usage limits or app data. `--transport direct` explicitly
disables the PC's old LAN reverse-TCP bridge for the public WSS connection;
its saved reverse address and identity remain available. Omit `--transport`
to preserve the current transport choice. Finish active work, then restart
the existing Windows application once so it reads the saved settings.

The dashboard-managed `fire-pc` tunnel should contain:

| Hostname | Local service | HTTP Host Header | Cloudflare Access |
|---|---|---|---|
| `firestudio.ljoekjell.no` | `http://127.0.0.1:8765` | `firestudio.ljoekjell.no` | Required; owner's email policy |
| `fire-device.ljoekjell.no` | `http://127.0.0.1:8765` | `fire-device.ljoekjell.no` | Off; FIRE bearer authentication remains required |

Do not apply an Access browser challenge to the device hostname. Keep
certificate verification enabled. The backend independently validates Access
JWT signature, issuer, audience and expiry; a forged email/proxy header grants
no access. Browser mutations also require the existing session, Origin and
CSRF protections. The public hostnames cannot reach `/desktop` controls.

## Reuse the existing tunnel service

Check only service state; never copy its arguments or token into logs:

```powershell
Get-Service -Name Cloudflared | Select-Object Name,Status,StartType
```

If already running automatically, do not install another connector or replace
its token. `scripts\cloudflare.ps1` already implements verification against
the local official-release manifest. These equivalent read-only terminal
commands do not require PowerShell script-file execution:

```powershell
$folder = (Resolve-Path -LiteralPath .\workspace\tools\cloudflared).Path
$metadata = Get-Content -LiteralPath (Join-Path $folder manifest.json) -Raw | ConvertFrom-Json
$program = Join-Path $folder cloudflared.exe
if ((Get-FileHash -LiteralPath $program -Algorithm SHA256).Hash.ToLowerInvariant() -cne $metadata.sha256 -or
    (Get-Item -LiteralPath $program).Length -ne $metadata.size_bytes) { throw 'Cloudflare file verification failed' }
& $program --version
```

Only if no connector exists, use the installation command provided by the
Cloudflare dashboard locally, as the final setup step. Never paste the tunnel
token into chat, source, device messages, screenshots or a committed file.
The official current Windows service installer stores its token in a protected
token file and configures automatic service startup. `pc.yml.example` is an
alternative example for a **locally managed** tunnel; do not apply it alongside
the dashboard-managed tunnel.

## Automatic backend startup

Use one owned current-user Windows Run entry for the existing Pythonw backend:

```powershell
.\.venv\Scripts\python.exe scripts\backend_startup.py --status
.\.venv\Scripts\python.exe scripts\backend_startup.py --install
```

Installation is idempotent. It writes only the `FIRE Backend` value under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, refuses a foreign value
with the same name, and does not start or stop the application during
installation. Its command contains quoted absolute paths to this checkout's
existing `.venv\Scripts\pythonw.exe` and the small startup helper `--run`.
No credentials are passed in the command.

At sign-in, the transient helper checks the existing local listener and FIRE
health, then starts exactly the same `pythonw -m fire_backend.desktop_entry`
entry used by `start-ui.ps1`, with the same working directory and user profile.
A short launch mutex prevents concurrent startup launches; the backend's
existing `WorkspaceLock` remains the final guard. The helper exits when the
existing backend becomes ready; it is not another persistent agent or backend.
No PowerShell execution-policy change, administrator rights or desktop-agent
installation is required. Installation rejects commands longer than Windows'
260-character Run limit before writing anything. Windows may delay logon
startup; it is not a guarantee that the backend is ready at the instant of
sign-in. To remove only this entry:

```powershell
.\.venv\Scripts\python.exe scripts\backend_startup.py --remove
```

This starts the backend **when the same Windows user signs in**, preserving
that user's existing Vault and workspace. It is not a second SYSTEM service
and does not claim backend availability before Windows sign-in. Cloudflared
can run before sign-in, but the backend PC must be awake, online and signed
in for this setup to serve FIRE. Do not silently enable Windows auto-login or
store a Windows password to change this behaviour.

## Verify before declaring live

Offline, without paid model calls:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_public_setup.py tests\test_browser_access.py tests\test_browser_lifecycle.py
.\.venv\Scripts\python.exe scripts\web_smoke_test.py
```

After activation, unauthenticated Studio should redirect to the owner's
Access login; the device hostname must not redirect to Access. Missing or
wrong device credentials must fail; a valid device credential must reach
the existing authenticated protocol. Neither hostname may expose desktop
controls. Verify Studio sign-in and normal CSRF-protected operations with the
user's actual OTP session, without recording OTP/JWT/cookies.

Set FIRE's existing backend address to `fire-device.ljoekjell.no`, port `443`,
keeping its existing device token. The native HTTPS/WSS client uses its shared
CA bundle and normal session/reconnect rules. Verify source-bound HELLO,
fresh inventory and reconnect from the device; test another Wi-Fi/hotspot
before claiming that physical away-from-home use has been demonstrated.
Testing a public hostname while still on home Wi-Fi proves public routing,
not a different network. Cloudflare may restart WebSocket connections, so
automatic authenticated reconnection must remain enabled and tested.

## Official references

- [Dashboard-managed tunnel setup](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
- [Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [Origin Host Header and Access settings](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/)
- [WebSocket support and reconnect expectations](https://developers.cloudflare.com/network/websockets/)
- [Pinned cloudflared Windows service implementation](https://github.com/cloudflare/cloudflared/blob/2026.11.2/cmd/cloudflared/windows_service.go)
- [Windows current-user Run entries and limitations](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)

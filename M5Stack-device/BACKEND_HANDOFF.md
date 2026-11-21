# FIRE OS AI Developer – hardware-first handoff

Dette dokumentet er den praktiske arbeidsinstruksen mellom firmware og
`M5Stack-backend/`. M5Stack FIRE-firmware og fysisk verifikasjon er fasit.
Backend skal ikke anta at en tjeneste finnes fordi den finnes i en simulator.

## Faktisk device-baseline

- M5Stack FIRE, ESP32-D0WDQ6-V3, 240 MHz, 16 MB flash og PSRAM.
- 320×240 ILI9342C LCD via M5Unified/M5GFX.
- Tre knapper: A=GPIO39, B=GPIO38, C=GPIO37.
- RGB-strip: GPIO15, 10 LED-er.
- Mikrofon: GPIO34. Høyttaler: GPIO25.
- IMU, RTC, Wi-Fi, BLE, SD og strømstyring eies av FIRE OS.
- Lua-runtime er lokal og begrenset til `fire.display`, `fire.buttons`,
  `fire.rgb`, `fire.imu` og `fire.time`.
- Lua får ikke GPIO-, fil-, radio-, flash-, OTA- eller OS-tilgang.
- AI-apper er SD/Lua-pakker. De skal aldri installeres som `.bin`, OTA eller
  firmware.
- Stabil standardbygning bruker `m5stack-fire-ble` og `default_16MB.csv`.

## Protokollkrav

Bruk `docs/PROTOCOL-v0.2.md` som kontrakt. Device sender WebSocket-eventer med
`protocol_version=0.2`, `event_id`, `device_id`, `boot_id` og, etter handshake,
`session_id`.

Første device-handshake skal annonsere kun faktisk tilgjengelige tjenester:

```json
{
  "api_version": "fire-lua-0.1",
  "services": ["display", "buttons", "rgb", "imu", "time"],
  "max_memory": 131072,
  "max_runtime_ms": 10000,
  "audio_input": false,
  "audio_output": false
}
```

`audio_input` og `audio_output` skal først settes til `true` etter at fysisk
opptak, WAV-opplasting, avspilling og kvitteringer er testet på FIRE.

## Backend-konfigurasjon via mobil/QR

FIRE OS tilbyr en midlertidig, passordbeskyttet konfigurasjons-AP fra
`Settings → AI settings → Backend config`:

- SSID: `FIRE-Setup`
- Passord: `fire-connect-2026`
- Enheten viser også en QR-kode for manuell reservekonfigurasjon.

Backendens Windows-app skal generere en vanlig HTTP-QR-kode med følgende URL
etter at brukeren har koblet mobilen til `FIRE-Setup`:

```text
http://192.168.4.1/provision?host=<url-encoded-pc-address>&port=<port>&device=<url-encoded-device-id>&backend_token=<url-encoded-device-token>
```

`/provision` aksepterer bare forespørsler mens AI-backend-oppsettet er aktivt.
Den validerer PC-adresse, port, enhets-ID og token, lagrer verdiene atomisk via
FIRE OS sin eksisterende backend-konfigurasjon og avslutter deretter
oppsett-AP-et. `device_id` kan brukes som alias for `device`. En eventuell
`token`-parameter kan brukes som ekstra setup-tokenkontroll, men er ikke
nødvendig når mobilen allerede er koblet til det passordbeskyttede
`FIRE-Setup`-nettet.

Backend-tokenet skal aldri logges eller legges i firmwarekilde, Git eller
pakken. QR-koden skal bare vises lokalt i backendens kontrollpanel.

## Backend-agentens neste arbeid

1. Oppdater `fire_backend/data/FIRE_DEVICE_CONTEXT.md` til nåværende firmware-
   baseline. Skill tydelig mellom kildekodefakta og fysisk verifisering.
2. Behold capability-forhandling: generer og valider bare API-er som device
   faktisk annonserer.
3. Ikke krev lyd i første handshake mens firmware fortsatt annonserer lyd som
   ikke implementert. Backend skal returnere en klar status hvis AI Developer
   åpnes uten lydkapabilitet.
4. Behold mock- og emulatorflytene som regresjonstester, men merk dem alltid
   `physical_verified=false`.
5. Når firmware annonserer lyd, test fysisk:
   `listen_start` → WAV POST → `transcript` → `audio_ready` →
   `audio_playback_started/finished`.
6. Verifiser deretter fysisk:
   `build_proposal` → `build_confirm` → `install_request` →
   `device_install_result` → `run_confirm` → `run_request` →
   `app_started` → `app_healthy`.
7. Ikke oppdater `current`, installasjonsstatus eller kjørestatus basert på
   PC-simulering eller manglende device-kvittering.

## Firmware-agentens neste arbeid

1. Korriger handshakeverdier og capability-annonsering.
2. Implementer push-to-talk med begrenset PCM16 mono 16 kHz-opptak i PSRAM.
3. Last opp WAV autentisert til backend i begrensede chunker.
4. Stream `audio_ready` til høyttaler uten å laste hele filen i SRAM.
5. Send playback-kvitteringer og koble REST/LISTEN/THINK/TALK til reell status.
6. Test SD-pakke, SHA256, manifest, installasjon og Lua-kjøring fysisk.
7. Test feil, avbrudd, reconnect, stopp og rollback på faktisk enhet.

## Viktige begrensninger

- OpenAI API-nøkkel skal bare finnes på PC-backend.
- Backend skal ikke be FIRE om firmwarebygging, OTA, `.bin`-flashing eller
  vilkårlig kode.
- Wi-Fi/BLE/SD/mikrofon/høyttaler må brukes gjennom OS-tjenester, aldri direkte
  fra generert Lua.
- Ved uenighet mellom simulator, dokumentasjon og fysisk enhet gjelder fysisk
  device-observasjon; oppdater kontrakten etterpå.

## Nåværende lydstatus

HTTP/WAV-transporten og UI-state-maskinen er lagt til. Mic-capture bruker nå en
minimal direkte I2S-adapter med M5Unifieds faktiske FIRE-mic-konfigurasjon;
standardbygget går rent med BLE/Wi-Fi/Lua aktivt. Device annonserer
`audio_input=true`, men dette må fortsatt verifiseres fysisk med backend. Audio
output er fortsatt `false` til playback er implementert og testet.

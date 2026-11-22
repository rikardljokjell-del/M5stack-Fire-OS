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
  "audio_input": true,
  "audio_output": true
}
```

`audio_input` og `audio_output` er satt til `true` i produksjonsprofilen.
Fysisk tale/ASR/TTS er rapportert i siste backend-handoff; full auditmatrise
er fortsatt ikke ferdig verifisert.

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

## Reverse TCP fra PC til FIRE

FIRE OS åpner en begrenset mottaker på TCP-port `8766` når lagret backend-
konfigurasjon finnes og Wi-Fi er tilgjengelig. Dette er en transportvariant;
WebSocket-, HTTP-, Lua- og bekreftelsesprotokollene er uendret.

PC-broen kobler til FIRE og sender først én newline-avsluttet UTF-8-linje:

```json
{"type":"reverse_open","version":1,"device_id":"m5stack-fire-01","token":"<device-token>"}
```

FIRE leser maksimalt 1024 byte, med 4 sekunders autentiseringsfrist, og
avviser feil ID, feil token, feil versjon eller ugyldig JSON-felt. Tokenet
skrives aldri til serielloggen. Ved godkjenning svarer FIRE:

```json
{"type":"reverse_ready","version":1,"device_id":"m5stack-fire-01"}
```

Alle byte etter newline beholdes i TCP-bufferen. Deretter brukes forbindelsen
som rå bytekanal. FIRE sender dagens `GET /ws/device` og WebSocket-handshake
over en reservert forbindelse. WAV-opplasting og Lua-pakkenedlasting reserverer
hver sin forbindelse ved behov og slipper den etter HTTP-operasjonen.

Første versjon har maksimalt fire samtidige reverse-forbindelser, inkludert
WebSocket og HTTP-operasjoner. En forbindelse bytter ikke rolle midt i en
operasjon. Hvis ingen godkjent reverse-forbindelse er ledig, bruker FIRE den
eksisterende direkte forbindelsen til konfigurert backendadresse.

Backend-broen må derfor:

1. Lytte lokalt på eksisterende backend-port `8765`.
2. Opprette reverse TCP-forbindelser til FIRE på `8766`.
3. Sende `reverse_open`, vente på `reverse_ready`, og koble rå bytes videre
   til den lokale backendforbindelsen.
4. Holde WebSocket-forbindelsen separat og bruke nye reverse-forbindelser for
   HTTP-pakkenedlasting og WAV-opplasting.
5. Begrense poolen til fire forbindelser og opprette ny forbindelse etter
   brudd.

Device status bruker `Backend connected (Reverse TCP)` eller
`Backend connected (Direct)` når kontrollforbindelsen er etablert. Fysisk
reverse-forbindelse er ikke verifisert før Windows-broen faktisk har koblet
til en M5Stack FIRE.

## AI Developer: nytt prosjekt eller eksisterende app

AI Developer må starte med et eksplisitt prosjektvalg før første taleomgang:

- `New app`: FIRE sender `session_start` uten `project_id`; backend oppretter
  et nytt prosjekt.
- `Continue app`: FIRE viser installerte Lua-apper fra SD-kortet. Valgt app-ID
  sendes som `project_id` i `session_start`, slik at backend gjenbruker riktig
  samtale, prosjekt og tidligere kode.

Backend må aldri velge prosjekt basert på appnavn alene. Den skal validere
`project_id`, beholde historikk per prosjekt og sørge for at build/run alltid
bruker valgt prosjekt.

## Lokal sletting og versjoner

Brukeren kan slette en Lua-app fra FIRE OS App Manager. Sletting på enheten må
ikke slette backendens immutable build, prosjektlogg eller versjonshistorikk.
Ved neste `session_start`/snapshot må backend behandle appen som ikke installert
på denne enheten inntil ny `device_install_result` er mottatt. Backend skal ikke
automatisk installere appen på nytt.

Device bevarer tidligere validerte Lua-versjoner på SD-kortet når en app
oppdateres, og rollback skal bare godkjenne en versjon som faktisk finnes lokalt.
Backend må skille mellom:

- prosjektets immutable builds og historikk,
- installert versjon på denne enheten,
- faktisk kjørende/healthy versjon,
- lokal sletting eller manglende SD-kort.

En fremtidig eksplisitt `app_deleted`-event må først legges til i den versjonerte
protokollkontrakten før den sendes fra firmware. Inntil da skal backend bruke
ny session-status og manglende fysisk installasjonskvittering uten å anta at
appen fortsatt finnes.

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
timerstyrt direkte ADC-task på GPIO34 og separat asynkron lydtransport;
standardbygget går rent med BLE/Wi-Fi/Lua aktivt. Device annonserer
`audio_input=true` og `audio_output=true`.

## Samordnet conversation-audit status

Dette er en device-agent handoff, ikke en pÃ¥stand om at alle fysiske matriser er
bestÃ¥tt.

- Firmware-SHA for denne leveransen: \`5886b20\` (device source).
- Backend-SHA lest fra GitHub: \`3bd4f83\`.
- Standardbygget \`m5stack-fire-ble\`: bestÃ¥tt, 1,4 % RAM og 25,2 % flash.
- Async lyd-HTTP, session-resume/heartbeat, chat/develop/appvalg, input-retry,
  cancel, fragmenterte tekstframes, command-expiry, app-inventory/app_deleted,
  manifestkontroll, Lua-restart/runtime-limit, installasjonsbeskyttelse og
  per-pixel RGB-rendering er lagt inn i device-koden.

Backendens siste GitHub-handoff rapporterer to fysiske direkte-ADC-opptak:
72 717 / 72 940 samples, omtrent 4,55 s av 4,81 s eventintervall, ASR-tekst
og kvittert AI-lydsvar. Dette var fÃ¸r siste async transport-/auditendringer og
beviser ikke full matrise eller korrekt norsk bestilling.

Lokal backend-test kunne ikke kjÃ¸res fordi \`M5Stack-backend/.venv\`/Python
ikke finnes i dette arbeidsmiljÃ¸et. Backend-agentens GitHub-status rapporterer
194 bestÃ¥tte regresjonstester; dette er ikke kjÃ¸rt om igjen av device-agenten.

Ikke fysisk verifisert i denne leveransen: 20 taleomganger, alle
avbruddsfaser, 100-syklus soak, delvise HTTP-writes, rollback/strÃ¸mtap,
full New/Update/build/install/run/healthy-flyt og SD-inventory etter
offline-sletting. Disse mÃ¥ gjennomfÃ¸res mot kjÃ¸rende backend fÃ¸r FIRE OS
kan rapporteres som ferdig auditert.

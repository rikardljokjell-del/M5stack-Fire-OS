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
  "max_runtime_ms": 0,
  "audio_input": true,
  "audio_output": true,
  "firmware_storage": true,
  "firmware_max_bytes": 4194304,
  "firmware_version": "fire-os-0.2+storage-dev"
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

## App repair / unlimited app lifetime update

Implementert mot backend `main` `d7d3811` og
`M5Stack-backend/docs/APP_REPAIR_HANDOFF.md`.

- Device handshake annonserer nå `capabilities.max_runtime_ms=0`.
- `manifest.max_runtime_ms=0` betyr kjør til brukerens Home/Back-exit.
- Positive runtimeverdier beholdes som eksplisitte legacygrenser opptil 10000 ms.
- Manglende runtimefelt behandles konservativt som legacy 10000 ms.
- Callbackbudsjett på 12 ms, instruksjonsgrense på 200000 og Lua-minnegrense på
  131072 byte er beholdt. Ingen auto-close-timer brukes for unlimited-profilen.
- Manifestkontrollen godtar 0, men avviser minne-/runtimeverdier utenfor
  devicegrensene.
- Backend-installerte apper får en persistent app-ID → package-ID-mapping.
  `app_inventory` inkluderer package-ID når den er kjent.
- Lokal start fra Apps bruker mappingen og sender `app_diagnostic` ved
  load/init/update/on_button-feil. Meldingen sendes etter cleanup og lagres i
  en begrenset én-post outbox ved offline backend. Ingen falsk `run_id` brukes.
- Backend-startede apper beholder `app_started`, `app_healthy`, `app_failed` og
  `app_stopped` med faktisk run/package-korrelasjon.
- Home/Back og backend-requested stop sender normal stop-status; de rapporteres
  ikke som diagnostikkfeil.

### Verification

- Source base: `d7d3811` plus uncommitted device changes in this handoff.
- Firmware environment: `m5stack-fire-ble`.
- Build: passed; RAM 1.4% (62836 / 4521984), flash 25.4%
  (1663837 / 6553600).
- Firmware binary SHA256:
  `b8be7027cef82392d5bdd6d39f4ddaa8e3452b6fcf1d4c6fcd2d893b8c4b3b93`.
- `git diff --check`: passed.
- Not yet physically verified: five-minute unlimited run, Home/Back restart,
  held-button profiles, callback/instruction/memory fault injection, local
  diagnostic delivery through the running Windows backend, and reconnect/outbox
  recovery. These remain required acceptance tests.

## Urgent runtime / voice follow-up

Implemented against the latest GitHub handoff revision `5b7d6ee`.

- A failed `startLuaApp` load now resets `luaRuntimeReady_` after closing the
  Lua VM. A retry or another app can start without reboot.
- Lua load errors are separated into `vm_not_initialized`, `source_empty`,
  `source_size`, `source_hash`, `source_syntax`, `init_error`,
  `memory_error` and `load_error` where applicable.
- Runtime phases are separated: source load (1000 ms guard), top-level/init
  (250 ms guard per phase), and update/on_button (12 ms callback guard).
  The 200000-instruction hook and 131072-byte Lua allocator cap remain active.
  `max_runtime_ms=0` remains independent and still means user exit only.
- Lifecycle diagnostics now include bounded phase, elapsed time, callback
  duration, free/minimum heap, Lua bytes, source bytes and frame count. They are
  sent only at lifecycle/error transitions, never once per frame.
- `audio_playback_failed` is implemented with correlated audio/turn IDs,
  bounded error messages and phase diagnostics. Download waits for an active
  upload to finish, verifies length/hash, reports speaker/playRaw failures and
  returns the UI to BUILD or new-speech state without leaking the PCM buffer.
- Existing text/proposal/build controls remain available after audio failure.

### Latest build

- Source base: local `d7d3811`; latest handoff read from GitHub `5b7d6ee`.
- Environment: `m5stack-fire-ble`.
- Build passed: RAM 1.4% (62836 / 4521984), flash 25.5%
  (1671673 / 6553600).
- Firmware binary SHA256:
  `afce75420556233d45c576f3d7e65f015ac53974084df2778db1623d197b9e48`.
- Firmware flashed to COM3; boot log reached `FIRE OS started` without reset.
- Physical verification still required: measured init-failure retry, forced
  playback failure with BUILD/B recovery, five-minute unlimited run, Home/Back
  restart, fast upload/download overlap and backend receipt inspection.

Dette er en device-agent handoff, ikke en pÃ¥stand om at alle fysiske matriser er
bestÃ¥tt.

- Firmware-SHA for denne leveransen: \`1a7e398\` (device source).
- Backend-SHA lest fra GitHub: \`3bd4f83\`.
- Standardbygget \`m5stack-fire-ble\`: bestÃ¥tt, 1,4 % RAM og 25,2 % flash.
- Async lyd-HTTP, session-resume/heartbeat, chat/develop/appvalg, input-retry,
  cancel, fragmenterte tekstframes, command-expiry, app-inventory/app_deleted,
  manifestkontroll, Lua-restart/runtime-limit, installasjonsbeskyttelse og
  per-pixel RGB-rendering er lagt inn i device-koden.

## Firmware storage handoff

Implementert i `src/fire_firmware_storage.h/.cpp` mot
`M5Stack-backend/docs/FIRMWARE_STORAGE_HANDOFF.md` og den avtalte
display-kontrakten. Device:

- annonserer `firmware_storage=true`, `firmware_max_bytes=4194304` og
  `fire-os-0.2+storage-dev` som kjørende firmwareprofil;
- godtar kun `firmware_store_request` med trygg hash-avledet
  `fire-<16-hex>.bin`, eksakt `/firmware/`-bane, backend-relativ URL, gyldig
  SHA-256 og størrelse på maksimalt 4 MiB;
- strømmer HTTP-svaret til `/firmware/<filename>.bin.part` med 2 KiB-blokker,
  beregner SHA-256 fortløpende og aktiverer endelig `.bin` først etter eksakt
  størrelses- og hashkontroll;
- overskriver aldri eksisterende ferdig fil, sletter bare egen uferdig `.part`,
  bruker direkte eller reverse-TCP HTTP, logger ikke token/headers/rådata og
  bruker ingen firmwarestor RAM-buffer;
- sender `firmware_store_result` etter lagring og behandler samme
  `transfer_id` idempotent i samme boot;
- har `Settings -> Firmware` som viser kjørende firmware separat fra `.bin`
  kandidater i `/firmware`. Overføringen flasher, rebooter eller endrer aldri
  bootvalg/Lua-versjoner. Dette gjelder backendens lagringsrequest; lokal
  OTA-installasjon skjer kun etter brukerens eksplisitte bekreftelse.

PC-backendens Firmware-side er fortsatt push-handlingen: velg kandidat og
bruk “Send valgt fil til /firmware”. “Refresh SD files” på enheten oppdaterer
bare den lokale filoversikten; protokoll 0.2 har ingen device-initiert
firmwarekatalogkommando.

Firmware-menyen har nÃ¥ ogsÃ¥ eksplisitt OTA-installasjon av lokale og GitHub-
bygg. Device validerer image, checksum og inaktiv OTA-slot fÃ¸r reboot. En
boot-vakt prÃ¸ver Ã¥ gÃ¥ tilbake til forrige OTA-slot etter gjentatt reset i et
15 sekunders stabilitetsvindu. GitHub-katalogen hentes fra repoets faste
`firmware/index.json` over HTTPS.

### Verifikasjon av firmwarelagring

- `m5stack-fire-ble`: bygg bestått. RAM 1,4 % (62 836 / 4 521 984), flash
  25,8 % (1 689 933 / 6 553 600).
- Firmware-binær SHA-256:
  `cc3c4e1d9c3a9d30cd6a2a6f0a5482bf14d547cdb65727d9e24bba7696fb653c`.
- `git diff --check`: bestått.
- Direkte/reverse fysisk overføring, korrekt/feil hash, duplikat, timeout,
  manglende/fjernet/full SD og reconnect etter overføring er ikke fysisk
  verifisert ennå. Byggresultat er ikke fysisk integrasjonstest.
- Legacy-miljøet `m5stack-fire` er ikke produksjonsbygget; det mangler allerede
  Lua-flagget `LUA_32BITS` og bruker nyere, inkompatibel ESP-IDF/mbedTLS-API.
  Produksjonsmiljøet er `m5stack-fire-ble`.

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

## fire-lua-0.2 hardware adapter update

Implementert mot [HARDWARE_API_HANDOFF.md](../M5Stack-backend/docs/HARDWARE_API_HANDOFF.md)
og eksportert kontrakt `0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40`.
FIRE annonserer nå `fire-lua-0.2` med tjenestene `display`, `buttons`, `rgb`,
`imu`, `time`, `jobs`, `gpio`, `pwm`, `i2c` og `uart`, samt dette begrensede
ressursregisteret:

```json
{"gpio_read":[26,35,36],"gpio_write":[26],"pwm":[26],"i2c":[0],"i2c_write_addresses":[64],"uart":[2]}
```

Implementert i runtime/OS:

- `display.fill_rect`, `fill_circle`, `pixel` og batchbasert `grid` uten
  framebuffer-flush per celle;
- appbundne fire jobber med poll/result/cancel/close og bounded resultater;
- GPIO mode/read/write/release med pinne-allowlist og leases;
- PWM configure/write/stop på GPIO26 med LEDC;
- I²C scan/read/write på OS-bus 0, med write-allowlist 0x40 og korte
  hovedloop-transaksjoner;
- UART2 open/read/write/close på GPIO36 RX / GPIO26 TX, med bounded buffers;
- Lua 0.2-kontrakthash, safe string/table-hjelpere og lokal manifestkontroll.

Tetris-/callbackkontroll har per-callback I/O- og tekstbudsjett, og jobber
forlater ikke Lua-callbacken blokkert. Ressurser og jobber frigjøres ved appstopp.
Fysisk GPIO/PWM/I²C/UART-loopback og Tetris-soak må fortsatt måles på FIRE;
PC-simulatoren og dette bygget er ikke fysisk verifikasjon.

## App Manager: backendkatalog, nedlasting og backend-sletting

Implementert mot `M5Stack-backend/docs/DEVICE_APP_MANAGER_HANDOFF.md`:

- `Settings -> App Manager` holder sessionen aktiv, henter paginert
  `app_catalog` og fletter backendapper med lokale Lua-apper. Eksterne `.bin`
  apper beholdes som lokale FIRE-apper.
- Backendapper viser `Cloud`, `Both` eller `Locked`. Versjonsdialogen henter
  `app_versions` og sender bare eksplisitt `app_download`; nedlasting starter
  ikke appen automatisk.
- Eksisterende `install_request`/ZIP-staging brukes for nedlasting. Etter ekte
  installasjon sendes `device_install_result`, inventory oppdateres, og App
  Manager blir stående åpen.
- Lokal sletting sender `app_deleted` først etter faktisk SD-sletting.
- Backend-sletting bruker `app_backend_delete_prepare`, konkret bekreftelse og
  `app_backend_delete_confirm`; backend-historikk slettes ikke ved vanlig
  lokal sletting.
- `app_inventory_request`, `app_catalog`, `app_versions`, `event_ack`,
  `app_backend_delete_ready` og `app_backend_deleted` behandles uten å åpne AI
  Developer eller starte/kjøre apper.

Backend-agentens siste GitHub-kode inneholder allerede serverkontrakten og
testene for denne flyten. Backend-testene kunne ikke kjøres lokalt fordi
`M5Stack-backend/.venv` mangler i dette miljøet. Device-build:
`m5stack-fire-ble` bestått, RAM 1,4 %, flash 28,2 %. Fysisk App Manager-
katalog/nedlasting/sletting må fortsatt verifiseres mot kjørende backend og SD.
## fire-lua-0.2 adapter follow-up

Register hash: `0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40`.

The device now wires the register-backed display, jobs, GPIO, PWM, I2C, UART,
ADC, DAC, SPI, SD and RTC adapters. `power.sleep`, Wi-Fi/BLE Lua adapters and
Lua mic remains unadvertised. Speaker is implemented in the follow-up section
below; its physical audio matrix is still outstanding.

Build/flash verification: `m5stack-fire-ble` passed (RAM 1.4%, flash 28.7%),
binary SHA-256 `00cf8e17b55dd056330ff64336be69d96e707dfa68d338dea72bf458ad2225ae`.
The final image was flashed to COM3 and reached `FIRE OS started`; physical
Lua I/O, loopback, SD-result and Tetris-soak tests remain outstanding.
## Lua speaker / app-audio follow-up

Implemented against `PRIKKJAKT_ANALYSIS.md` and the audio addition in
`DEVICE_EXPERIENCE_HANDOFF.md`.

- `fire-lua-0.2` now advertises `speaker` in addition to the existing `jobs`
  and `sd` services. The API exposes the registry methods `speaker.tone`,
  `speaker.play` and `speaker.stop`.
- Tone and WAV playback are bounded asynchronous jobs. WAV files are restricted
  to app-private SD storage, RIFF/WAVE PCM16 mono, 8/16/24 kHz and 512 KiB;
  file loading is chunked outside Lua callbacks.
- App gain is applied through the dedicated M5Unified speaker channel. The OS
  master volume remains authoritative: OS volume 0 produces silence, volume
  changes apply while a sound is playing, and app `speaker.stop` cannot stop
  AI/system audio on other channels. Conversation capture/playback returns
  `busy` to Lua.
- Lua has no `power.brightness` service, and the speaker adapter never calls
  `M5.Display.setBrightness`; OS background brightness therefore remains
  unchanged by app audio.
- Stop, close, cancel, Home/Back cleanup and buffer-release handling prevent
  speaker buffers from being freed while M5Unified is still reading them.

### Verification

- `m5stack-fire-ble` build passed: RAM 1.4%, flash 28.8%
  (`1887377 / 6553600`).
- Physical audio matrix still needs to be run on FIRE with a real Lua package:
  melody playback, app mute/stop, master volume 0 and live volume changes,
  AI audio conflict, repeated start/stop and brightness preservation. Boot and
  compile success are not reported as physical speaker verification.
Final firmware binary SHA-256: `c3612cd607c74691b1d026483dee17f02dfcd27afd0b788400db4b8d4036c1f0`.
## App-exit safe cleanup

All Lua-app exits now pass through a single cleanup boundary. Home, Back,
runtime failure, rollback, remote stop and OS navigation via configurable
double-click shortcuts stop the Lua runtime and release GPIO/PWM/DAC/SPI/UART,
cancel jobs, stop the Lua speaker channel, close pending audio/SD state and
release microphone capture resources. Lua RGB output is cleared after exit.
The OS master speaker channel and display brightness are not reset or changed
by app cleanup; only app-owned resources are released.

Build/flash verification: `m5stack-fire-ble` passed (RAM 1.4%, flash 28.8%),
binary SHA-256 `953701aa461986e369c6a8e56414637fb3077bb2965b831cd3d47b66f836c0e4`.
The image was flashed to COM3 and reached `FIRE OS started` without reset.
## Firmware menu and catalog update

- Running firmware is now reported as `fire-os-1.1` and shown separately from
  candidate files.
- Settings -> Firmware now has separate GitHub firmware files and SD firmware
  files views. GitHub rows show `Cloud` or `Both`; SD rows show `Local`.
- GitHub refreshes its catalog when opened. Existing files require an explicit
  `Overwrite existing` or `Cancel` choice before download.
- GitHub downloads clamp initial response bytes to Content-Length, stage to a
  `.part` file, verify exact size/SHA256, and only then replace an existing
  file.
- Public catalog now contains `firmware/fire-os-1.1.bin`, size `1896432`,
  SHA-256
  `95376ff07b7ce1a9abe14bd7e0b459443448a12546537ee826019aa1e0297b65`.

The firmware image was built with `m5stack-fire-ble`, flashed to COM3 and
reached `FIRE OS started` without reset. GitHub download and OTA flashing
still require a physical network/SD interaction test.
## Lua app carousel and shortcut metadata

Menu Layout now has `Show selected apps`. Lua apps are selected by stable
manifest `id`, not by version or array position; the carousel always starts
the current installed version for that ID. The same installed app IDs are
available as configurable double-click shortcut targets. If an app is deleted
or its ID cannot be resolved, its shortcut is disabled and its carousel entry
is deselected without affecting FIRE OS.

Backend app packages should provide a short human-readable manifest `name`
(ideally no more than 14 characters for the 320x240 carousel). The device
uses that name as the label and a consistent standard app icon when no icon
asset is supplied. Backend-generated icons/assets must remain optional and
app-private; missing or invalid icon metadata must never block installation or
menu recovery.

## APP ERROR repair flow

Implemented against `M5Stack-backend/docs/DEVICE_FIX_ERROR_HANDOFF.md`.

- Runtime failures preserve app ID, manifest name/version, package ID, Lua
  source SHA256, run ID and bounded diagnostics before Lua/runtime cleanup.
- APP ERROR now shows the failed app identity and selects `Fiks feil` by
  default. One B press sends `app_repair_prepare`; the first matching
  `awaiting_confirmation` status automatically sends `build_confirm` with both
  `repair_id` and `proposal_id`. Repeated presses do not create parallel jobs.
- Repair status/progress is rendered on the same error page. Home/Back leaves
  the page without cancelling the backend job. Reconnect requests status for
  the same repair ID.
- A ready repair offers `Kjor rettet app`. The device uses the existing
  package download path, sends `device_install_result`, and only then sends
  `run_confirm` for the new package ID.
- Small rotating snapshots are written only after a failed app has stopped to
  `/logs/ai-developer/error-0.json` through `error-7.json`, capped at 4 KiB.
  No SD write occurs in a Lua callback or per frame.
- Lua RGB writes now update an OS-owned buffer and flush one bounded strip
  outside the Lua callback at controlled cadence. The 12 ms callback limit was
  not increased.
- IMU freshness uses the existing 50 Hz OS-owned `M5.Imu.update()` loop.
- APP ERROR shows live Wi-Fi and backend connection state and keeps retrying
  through the normal OS connection loop. After Fix is pressed, the action
  label changes to `VENT...` immediately.
- Debug microphone testing now reuses the stable AI Developer voice-test
  capture/playback lifecycle instead of a separate direct I²S lifecycle.
- Backend and repair progress labels are normalized to complete one-line texts
  such as `Lager app`, `Tester app`, `Laster ned rettet app` and `App klar`;
  long raw backend messages are never cut mid-sentence on the 320x240 display.

Verification on 2026-11-23: `m5stack-fire-ble` built successfully (RAM 1.4%,
flash 29.2%, binary 1,922,768 bytes, SHA256
`21b81d790ff1678afbf617a8cb352bad24f7d9b7a4770f98a5fa8dfefedcaf8e`). The
image was flashed to COM3 at 921600 baud after one interrupted upload attempt;
flash hashes were verified and the device reached `FIRE OS started` without a
reset loop. The complete physical crash -> repair -> download -> install
receipt -> run flow, reconnect and double-press matrix still require a real
crashing Lua package and running backend; they are not claimed as physically
verified.

## Build continuation, boot recovery and completion notices

Implemented against `M5Stack-backend/docs/DEVICE_BUILD_CONTINUATION_HANDOFF.md`.

- Boot/Auto backend sync now remains demanded until `build_jobs` is received or
  a bounded 15-second timeout expires. Missing job responses are retried up to
  two times with a five-second request timeout; the UI loop is never blocked.
- `build_jobs` uses a string-aware bounded JSON object scanner, preserves job
  error text/diagnostics/resume flags, and prefers a running/building job over
  a queued job when several jobs are returned.
- Same-job continuation preserves the build ID and accepts the valid
  `failed -> queued -> building -> ready` sequence. Old failure text is cleared
  when the same job resumes. `build_resumed` accepts both top-level
  `progress_percent` and nested progress objects.
- Resume counts reject older delayed events. A selected job does not suppress a
  ready notice for another build ID; notices are deduplicated after local ACK.
- The completion notice is rendered once as a final overlay on every normal OS
  screen with `Åpne`/`Avbryt` hints. It does not auto-install or auto-run.

Verification on 2026-11-23:

- Firmware commit: `03bf3e2`.
- `m5stack-fire-ble` build: passed; RAM 1.4%, flash 29.5%, binary
  1,937,584 bytes.
- Firmware SHA-256:
  `B16B114807D892F88F016610BE91FDC7CEBA5C8605843FD1DEB44CFBA52001F0`.
- Flash to COM3 at 921600 baud: passed; esptool hash verification passed.
- Serial boot: passed through `M5.begin OK`, `RGB OK`, `SD OK`, `buttons OK`,
  `DateTime OK`, `settings OK` and `FIRE OS started`; no reset loop observed.
- Not physically verified in this run: live backend job during reboot, failed
  job retry with same build ID, two simultaneous jobs, offline completion
  notice, and `Åpne`/install/Run/Avbryt against a running backend. These remain
  explicit physical acceptance tests and are not reported as complete.

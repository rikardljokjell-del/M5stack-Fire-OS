# Device-agent: utvidet maskinvare i AI Developer

Oppdatert kildestatus: dae75bf / 74ac26a har nå de første native adapterne for display/buttons/rgb/imu/time/jobs/gpio/pwm/i2c/uart. Det opprinnelige implementeringsoppdraget nedenfor beskriver kontrakten; resten av driverne gjenstår. Les også [DEVICE_EXPERIENCE_HANDOFF.md](DEVICE_EXPERIENCE_HANDOFF.md) for nyeste OS-/knappe-/lydfunn. Fysisk maskinvareverifikasjon er fortsatt separat.

22. november 2026. Kun backend er endret. Device-kilde lest fra GitHub `932ba8f`.

## Oppgaven og status

Brukeren skal kunne lage en electronics toolbox med I²C-skanner, GPIO-test, PWM og UART-terminal, og apper med Wi-Fi, Bluetooth, RGB, mikrofon, høyttaler, SD og øvrig tilgjengelig FIRE-maskinvare. Backendens faste liste med fem tjenester er erstattet med et versjonert API-register, kapabilitetskontroll og PC-simulering. **Native adaptere finnes fortsatt ikke i inspisert firmware. Ikke bare legg navnene til handshaken.**

Les device-handoffen, PROTOCOL-v0.2.md, LUA_API.md, DISPLAY_QUALITY.md og TETRIS_RUNTIME_REPORT.md. Eldre dokumenters femtjenestersgrense gjelder fire-lua-0.1.

## Én kontrakt og eksplisitt forhandling

Kilden er [HARDWARE_API-v0.2.json](../fire_backend/data/HARDWARE_API-v0.2.json). [Eksporten](../contracts/HARDWARE_API-v0.2.json) inneholder `api_contract`, SHA256 av kanonisk register-JSON. Bruk hashverdien fra eksporten; ikke lag en separat kontrakt. Registeret har argumentnavn, typer, grenser, avhengigheter, resultatformer og semantikk.

- Behold transportprotokoll `0.2`. Lua-versjon er separat: `api_version=fire-lua-0.2` og eksakt `api_contract` i capabilities og nye manifester. Avvis ukjent versjon/hash før installasjon/start, også lokal start fra SD.
- Gamle enheter beholder `fire-lua-0.1` og sine fem tjenester. Legacy-manifester får ikke nytt hashfelt. Backend støtter begge profiler.
- Annonser bare implementerte tjenester og deres avhengigheter (`jobs`, eventuelt `sd`). En tjeneste må ha alle bindingene i registeret. Fysisk manglende/opptatt ressurs eller ikke-støttet radiomodus gir vanlig `unavailable`/`busy`, ikke falske målinger.
- `hardware` inneholder allowlists: `gpio_read`, `gpio_write`, `adc`, `dac`, `pwm`, `i2c`, `i2c_write_addresses`, `uart`, `spi`. Ikke annonser alle ESP32-pinner ukritisk. Backend sporer brukte ressurser gjennom testprofilene og avviser fysisk levering ved manglende ressurser.
- Samtalens `audio_input/audio_output` gir aldri automatisk Lua-tillatelse til `mic/speaker`.
- Manglende adapter: backend bevarer eksakt ønske i `project.pending_hardware_request`, sender vanlig assistant_message og ekstra `capability_required` med missing_services. Vis kort status og behold krav/samtale. Ikke foreslå en uvedkommende IMU-demo. Etter oppgradering kan samme ønske fortsettes; BUILD/RUN krever fortsatt bekreftelse.
- Windows-knappen «Maskinvareutkast på PC» bruker syntetiske målinger. Den gir ikke fysisk støtte. Backend blokkerer installasjon på feil firmwareprofil.

## Native implementering, i rekkefølge

1. Utvid `FireLuaRuntime::Host`, `registerApi` og OS-adapterne i `src/fire_lua_runtime.*` / `src/fire_os.*`. Behold begrenset Lua 5.4 og eksisterende kilde-/pakkevalidering. Ingen rå M5/ESP-objekter, pekere eller registerskrivinger i Lua.
2. Oppdater capability-håndtering i `src/fire_backend_client.*`, manifest og `src/fire_lua_package_manager.*`. Kontroller versjon/hash/permissions også ved lokal SD-start. Eksponer bare manifestets tjenester; argumentkontroll må skje i faktiske C-bindinger, også gjennom aliaser.
3. Implementer OS-eid ressursmegler for pinner, busser, LEDC, audio og radio. Claim/release skal være atomisk og appinstansbundet. Behold LCD/SD/PSRAM/IMU og AI-transport. Ved konflikt returneres busy, ikke stjål ressursen.
4. Implementer ikke-blokkerende jobbkø og workers/state machines utenfor Lua/UI-tasken. Nettverk, scanning, SD, opptak og avspilling må aldri vente inne i Lua-callback. Normal I/O-feil må ikke krasje skjermen eller forbindelsen.
5. Ved stopp/feil/ny start: avbryt jobber, lukk håndtak og frigjør pinner/lyd/buffere uten callbacks inn i død VM. Gjenopprett trygg OS-tilstand. Fysiske hjem/back-knapper skal virke under alle jobber.
6. Implementer `display.grid` som ett row-major-batchkall i OS-spriten, inklusive bakgrunnsceller. OS presenterer én gang. Behold komplett scene hver update, `rect/circle` som outlines og nye `fill_rect/fill_circle` som fylte former. Ingen skjermflush per celle.
7. API 0.2 får kun registerets bounded string/table-hjelpere. Ingen `string.rep/format/gsub`, generelle biblioteker, loaders, debug, pcall eller fri OS-tilgang. Lukk også strengmetatabell-/aliasveier.
8. Start med display/buttons/jobs/i2c/gpio/pwm/uart, så øvrige drivere. Annonser kun testede implementeringer. Nåværende NimBLE-oppsett gir ikke automatisk klassisk Bluetooth SPP; velg riktig stack, eller returner unavailable for ikke-støttet modus. PC-simulering beviser ingen radiostack.

## Ressurser og FIRE-pinner

- Grove A bruker normalt GPIO21/22 på I²C. Lua-busser er OS-logiske håndtak. Del intern IMU-/strømbuss med låsing og korte transaksjoner. Skanning skal ikke skrive vilkårlige konfigurasjonsregistre. I²C-skriving krever `i2c_write_addresses`; beskytt OS-eide adresser.
- Grove B GPIO26/36 kan brukes når ledige. GPIO34..39 er input-only uten interne pullups/pulldowns. Mic=34, speaker=25, RGB=15, knapper=39/38/37. Disse er OS-reserverte med mindre riktig adapter megler bruken.
- **GPIO16/17 er koblet til PSRAM på FIRE.** Grove C-merking er ikke tillatelse til UART mens PSRAM brukes. Backend avviser dem i ressursprofilen. Remapp UART til faktisk ledige/tilgjengelige pinner; ikke slå av PSRAM i det skjulte.
- Beskytt flash GPIO6..11 og LCD/SD-/startpinner. Håndter ADC2/Wi-Fi-konflikt, UART0-loggport, LEDC/DAC/audio og SD-CS. UART/SPI-pinner må også finnes i riktige gpio_read/write-lister.
- FIRE har ikke innebygd GPS. GNSS-test trenger ekstern UART-modul, riktig baud og ledige pinner. Ikke presenter PC-fixturen som satellittdata.
- RTC kan være OS-klokke på varianter uten separat chip. Strøm-/sensoradaptere må bruke faktisk brettrevisjon og returnere feil ved manglende komponent.

Offisielle kilder: [FIRE](https://docs.m5stack.com/en/core/Fire), [FIRE v2.6](https://docs.m5stack.com/en/core/Fire_v2.6), [M5Stacks FIRE-dokument](https://github.com/m5stack/m5-docs/blob/master/docs/en/core/fire.md). Kontroller faktisk revisjon før fysisk pinne annonseres.

## Jobber, returdata og feil

- Fire uavsluttede jobber per app. Unike appinstansbundne ID-er 1..65535. Full kø: `nil,"busy"`. Poll/result venter aldri. Resultat konsumerer ikke jobben; `close` må alltid kalles.
- `poll`: `{state="pending"|"ready"|"failed"|"cancelled",done=boolean,error_code=string}`. `result`: `{ok=true,...}` eller `{ok=false,error_code=...}`. Før ferdig: not_ready; ukjent ID: invalid_handle. Ukjent close/cancel: false.
- Cancel stanser videre arbeid, gir cancelled-resultat og beholder slot til close. Den kan ikke angre allerede utført ekstern skriving. Close avbryter også uferdig arbeid og frigjør slot.
- Fullfør/feil innen 3000 ms, opptak innen duration_ms+3000 ms. Ingen spin-wait eller lang blokkering. Hold appen responsiv under timeout/frakoblet modul.
- Argument-/permission-/ressursbrudd kan stoppe appen med presis diagnostikk. Vanlige feil gir nil,error_code eller failed-jobb. Ikke be brukeren hente logger fra FIRE.
- Maks 64 I/O-kall og 2048 innsendte payloadbyte per callback; resultatpayload maks 512 byte. Scan-/filresultater har egne antallsgrenser i registeret. Bluetooth maks fire apphåndtak, lukk ved exit. Ingen ubegrensede HTTP/UART/BLE-/lydbuffere.
- SD er privat under `/apps/<id>/appdata/`. Avvis absolutt sti, `..`, NUL, backslash og kolon. Ingen andre apper, firmware, systemfiler eller nøkler. Behold appdata ved versjonsoppdatering. WAV valideres og strømmes, ikke lastes helt i RAM.
- Wi-Fi connect bruker OS-lagret profilnavn, aldri passord. Returner aldri tokens/API-nøkler. HTTP(S): verifisert TLS, størrelses-/tidsgrense, ingen interne provisioning-/nøkkelendepunkter. Connect/disconnect/sleep kan avvises busy når OS trenger forbindelsen.
- Samtaleopptak/talesvar har prioritet over Lua-mic/speaker. Bruk audio-tasken og returner busy ved konflikt. Lyd skal kunne stoppes med OS-knapper.

## Verifikasjon før «fungerer på FIRE»

1. Bygg korrekt firmware, verifiser API/hash/ressursprofil og bakoverkompatibilitet. Ikke omgå parser eller permissions for å få en pakke til å starte.
2. Bruk [toolbox.lua](../fire_backend/data/toolbox.lua) som lesbar kontraktfixture, ikke universell pinnefasit. På FIRE: finn fysisk I²C-enhet, mål GPIO/PWM og test ekstern UART-loopback. Test også frakoblet modul og opptatt port.
3. Test øvrige tjenester fysisk. Wi-Fi/BLE/SPP mens AI-forbindelsen er oppe; lytt til opptak og høyttaler; kontroller SD-privathet, klokke og strømdata. PC må ikke etablere fysisk verifisering.
4. Test timeout, cancel/close, full kø, feil inngangsdata, SD-/modulfjerning, hurtig appbytte, gjentatte starter og hjem/back under jobb/lyd. Ingen pinne-/heap-/slot-/radiollekkasje.
5. Kjør eksakt toolbox-dialog fra AI Developer til BUILD, installasjon, RUN og senere lokal start fra Apps. Manglende nødvendig tjeneste skal stoppe levering presist, uten annen demo eller falsk suksess.
6. Mål callbacktid/minne/framepresentasjon på FIRE. Les Tetris-rapporten. Ikke øk/fjern watchdog for å skjule treg tegning. Backend release-v4 kjører sju input-/tidsprofiler og tre ekstra I/O-feilprofiler for utvidede hardwareapper; disse er syntetiske tester.
7. Oppdater device-handoff med faktisk firmwareversjon, hash/profil, boardrevisjon, fysisk test per tjeneste og gjenstående driver-/stackbegrensninger. Backendagenten endrer eller flasher fortsatt ikke device.

Én app_healthy etter første update er en tidlig kvittering, ikke bevis på lang stabil kjøring. Videre runtimefeil skal fortsatt rapporteres med korrekt pakke og diagnostikk.

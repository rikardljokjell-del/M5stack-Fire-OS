# FIRE OS AI Developer backend 0.2

[Device-handoff: bakgrunnsbygg og Resume](docs/DEVICE_BACKGROUND_BUILD_HANDOFF.md)
samler knapper, status mellom tid/dato, ferdigvarsel, jobbavbrudd og hele
appbiblioteket i AI Developer. Backend viderefører bekreftede bygg ved FIRE-reboot
og nettbrudd. Device-skjermene implementeres og verifiseres av device-agenten.

[Standard for hørbar lyd](docs/AUDIO_GAIN_STANDARD.md): primærlyd bruker kanal-gain
255/255 under OS-mastervolumet. Skjult ekstra demping som44/255 skal ikke være
standard. Lydnivå inngår i kontrollen før levering.

[Melodiappens avhengighetsfeil](docs/MELODY_DEPENDENCIES_FIX.md) er rettet:
speaker får automatisk jobs+sd i manifest og permissions, også for tone-only.
Manglende avhengigheter stoppes før levering; samme kontrakt brukes ved generering
og validering.

[Toolbox-bygg og forebygging](docs/TOOLBOX_BUILD_RECOVERY.md): samlet byggetid er
tilpasset hele rettingsløkken, og nye hardwareapper må ha testsekvenser som faktisk
starter instrumentene. Menyvisning alene teller ikke som test av I/O.

[Prikkjakt-analyse og nye generelle regler](docs/PRIKKJAKT_ANALYSIS.md): spillstart i testene, mindre native rasterbelastning, begge RGB-barer, behagelig spillmusikk med ekte mute og respekt for OS mastervolum/bakgrunnslys. Spilllyd krever fortsatt native Lua-lydadapter; nye spill leveres ikke som stille erstatning for dette kravet.

Felles [FIRE-standard for knapper, skjerm, spillmenyer og feilretting](docs/FIRE_EXPERIENCE_STANDARD.md)
er nå obligatorisk i nye livebygg. A=forrige/opp, B=velg/bekreft, C=neste/ned;
spill får effektinnstillinger før start og en utvidet, kildebundet UX-kontroll.
[Firmwareoppfølging](docs/DEVICE_EXPERIENCE_HANDOFF.md) beskriver faktiske funn
om OS-knappeierskap, lyd, typografi og tapsfri feilmelding.

Fast standard for alle nye apper/oppdateringer: [fungerende første levering og
gjennomført grafisk design](docs/FIRST_DELIVERY_QUALITY.md). Etter kjøretidstestene
gjør AI en separat kontroll av krav, kode og utforming. Konkrete funn rettes
automatisk før pakking; uavklarte feil gir ingen ny leverbar pakke.

Backend har nå et versjonert [maskinvare-API med 20 tjenestegrupper](docs/HARDWARE_API_HANDOFF.md), ressurskontroll og PC-simulering. Bruk «Maskinvareutkast på PC» under Apper for å forberede slike apper. Nyeste firmwarekilde har første adaptere for I²C/GPIO/PWM/UART; fysisk verifikasjon gjenstår. Wi-Fi/Bluetooth/lyd/SD med flere krever fortsatt egne Lua-adaptere. Appønsket beholdes når en adapter mangler; det erstattes ikke med en annen demo.

[Analyse av den første Tetris-feilen og ny ytelsesport](docs/TETRIS_RUNTIME_REPORT.md).

Settings → App Manager kan nå hente backendkatalog/versjoner, be om nedlasting
og bekrefte sletting av egne backendversjoner. Backenddelen er implementert;
device-agenten kobler menyen til [DEVICE_APP_MANAGER_HANDOFF.md](docs/DEVICE_APP_MANAGER_HANDOFF.md).

Windows-appen har nå [én rad per app, versjonsvalg, sletting per versjon og
AI-dialog uten tilkoblet FIRE](docs/DESKTOP_APPS.md). Egen Firmware-meny viser
rapportert kjørende versjon og importerer firmwarefiler. SD-overføring til
/firmware er backendklar, men krever ny mottaker i device:
[FIRMWARE_STORAGE_HANDOFF.md](docs/FIRMWARE_STORAGE_HANDOFF.md).

Fast skjermregel for alle nye/reparerte apper: [DISPLAY_QUALITY.md](docs/DISPLAY_QUALITY.md).
Release-v4 avviser kjente blanke mellomrammer og feil tegnerekkefølge før levering.
Regelen følger dagens firmware: tegn en komplett scene ved hver update.

Siste runtime-/lydfunn og liten device-feedback: [URGENT_RUNTIME_VOICE.md](docs/URGENT_RUNTIME_VOICE.md).
Backend lagrer korte livssyklusrapporter, skiller transport fra avspilling og
beholder byggeforslaget ved lydfeil. Release-v2 begrenser arbeid per callback.
Bekreftet firmwarefeil ved nytt Lua-startforsøk er fortsatt en device-oppgave;
PC-tester alene bekrefter ikke at en app kjører riktig på FIRE.

Ny kvalitetsport og reparasjonsflyt: [APP_REPAIR_HANDOFF.md](docs/APP_REPAIR_HANDOFF.md).
Feilrapport for valgt app henter kilde/diagnostikk automatisk; sju releaseprofiler
og et varig feilregister beskytter neste bygging. Windows-appen har Reparer valgt app.
Device-agenten må også følge instruksen der for feillogger fra lokalt startede apper
og fjerning av automatisk ti-sekunders lukking. Backend støtter levetid 0=til brukerexit;
firmware må annonsere/støtte profilen før den brukes.

Lokal Python/FastAPI-backend for Windows, én backendprosess, filbasert lagring og
direkte OpenAI API. Ingen Docker, database eller avhengighet av desktopappen ved
kjøring. All backendutvikling skjer i denne mappen. `M5Stack-device/` leses for
integrasjon, men endres/bygges/flashes ikke av backendarbeidet.

Ekte OpenAI-dialog og kodegenerering er nå testet frem til Lua-validert ZIP.
Fysisk reverse TCP/WebSocket er observert. **Full tale → installert/kjørende
app på FIRE er fortsatt ikke verifisert.** Se [oppdatert ende-til-ende-status](docs/E2E_STATUS.md)
og [målt lydstatus](docs/VOICE_HANDOFF.md). Norsk talesvar er fysisk bekreftet.
Nyeste ADC-opptak har bedre tidsforhold, men talegjenkjenning og knappflyt må
fortsatt forbedres på enheten. Backend støtter nå Kun samtale, avbrytelse og
robust gjenoppkobling; se [samtalekontrakten](docs/CONVERSATION-v0.2.md).
**Device-agent: start med [arbeidsordren med 37 konkrete funn](docs/DEVICE_CONVERSATION_AUDIT.md).**
Ny app / endre valgt versjon og kontrollert backend-sletting følger
[app-livssyklusen](docs/APP_LIFECYCLE.md).
Se [leveranserapport](docs/DELIVERY.md), [enhetskontrakt](docs/PROTOCOL-v0.2.md),
[Lua-kontrakt](docs/LUA_API.md) og [drift](docs/OPERATIONS.md).

## Start med én kommando

**Enkel Windows-bruk:** åpne **FIRE Backend** fra skrivebordsikonet eller start-ui.ps1.
Ikonet bruker installert pythonw.exe uten terminal; Windows Application Control
blokkerte siste usignerte exe-pakke. Programmet har start/stopp, API-nøkkel,
modellinnstillinger, LAN-oppsett, enhetsstatus, fremdrift og tekst til en
tilkoblet FIRE. Nøkler lagres i Windows legitimasjonsbehandling.
Se [Windows-veiledningen](docs/WINDOWS_APP.md). `start-ui.ps1` åpner også programmet.
**USB-nettdeling:** velg PC → FIRE under Tilkobling og oppgi FIREs Wi-Fi-adresse.
Dette krever firmware med [reverse TCP v1](docs/REVERSE_TCP-v1.md); direkte nett støttes fortsatt.
Bygg pakken med `build-windows.ps1 -Shortcut`; hele dist/FIREBackend-mappen følger med.

Kommandolinjeutgaven for utvikling:

Fra denne mappen:

```powershell
.\start.ps1 -Mock
```

Serveren bruker `http://127.0.0.1:8765`. Første oppstart lager `.venv` og
installerer `requirements.lock.txt`. Endret avhengighetsfil eller pyproject
utløser ny installasjon. Python 3.11+ kreves; separat Python 3.13 er installert
på denne PC-en. Hvis lokal skriptpolicy blokkerer oppstart:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Mock
```

Fra repo-roten kan du bruke `.\M5Stack-backend\start.ps1 -Mock`.
Kontroller [health](http://127.0.0.1:8765/health). Stopp med Ctrl+C.

I en annen terminal:

```powershell
.\mock.ps1 -Demo
```

Skriv `/build` etter forslaget, `/run` etter ferdig pakke, `/quit` for å avslutte.
Denne eldre klienten bruker protokoll 0.1 og **kun PC-simulering**. Den registrerer
aldri installasjon eller fysisk kjøring. MockProvider bruker faste, tydelig merkede
eksempler: sirkel, Snake, RGB og IMU. Den gjør ingen OpenAI-kall.

## Ekte API og fysisk enhet

Kopier `.env.example` til `.env`, fyll inn verdier lokalt og start uten `-Mock`.
Miljøvariabler har forrang over `.env`; fjern eventuell FIRE_AI_MODE=mock i en
gjenbrukt terminal før produksjonsstart.

```dotenv
OPENAI_API_KEY=din_egen_nokkel_kun_pa_pc
FIRE_AI_MODE=openai
FIRE_BACKEND_HOST=127.0.0.1
FIRE_BACKEND_PORT=8765
FIRE_BACKEND_TOKEN=et_eget_langt_tilfeldig_admin_token
FIRE_DEVICE_TOKENS={"m5stack-fire-01":"et_annet_langt_tilfeldig_enhetstoken"}
FIRE_AUDIO_ENABLED=true
```

Hver fysisk enhet bruker sitt eget token og kan bare opptre som sin egen ID.
Admin-tokenet gir lesing/administrasjon, men kan ikke starte en fysisk sesjon ved
å utgi seg for å være enheten. LAN-binding krever admin-token med minst 24 tegn;
enhetstoken er separat og minst 24 tegn. Autorisasjon sendes i headeren
`Authorization: Bearer TOKEN`, aldri URL. Ikke bruk OpenAI-nøkkelen som enhetstoken.

Firmwarekilden på gjennomgått commit df06c65 har nå WebSocket-klient,
Lua-runtime og SD-pakkehåndtering. Backend følger handoffens faktiske profil:
display/buttons/rgb/imu/time, 131072 byte, 10000 ms, audio_input=true og
audio_output=false. Nyeste kilde har WAV-opplasting/I2S-capture; fysisk test
gjenstår. Eldre profil med begge lydflagg false er også gyldig. Backend bruker
hver lydretning bare når den er annonsert og backendlyd er aktivert. Tekst kan brukes.
Se [oppfølging av handoff](docs/DEVICE_HANDOFF_RESPONSE.md) for kildefunn som må
avklares i firmware og testes fysisk. AI-genererte Lua-apper bruker aldri .bin/OTA.

## Miljøvariabler

| Variabel | Standard | Bruk |
| --- | --- | --- |
| OPENAI_API_KEY | tom | Bare PC; påkrevd for ekte API-kall |
| OPENAI_REALTIME_MODEL | gpt-realtime-2.1 | Tekstdialog med validert dialog_reply-funksjon |
| OPENAI_CODE_MODEL | gpt-6.2-astra | Responses med strukturert Lua-output |
| OPENAI_TRANSCRIBE_MODEL | gpt-transcribe | Opptaksfil til tekst |
| OPENAI_SPEECH_MODEL | gpt-realtime-2.1-mini | Tekst til PCM gjennom Realtime |
| OPENAI_SPEECH_VOICE | marin | Talesvar |
| FIRE_AI_MODE | openai | openai eller eksplisitt mock |
| FIRE_BACKEND_HOST / PORT | 127.0.0.1 / 8765 | HTTP og WebSocket |
| FIRE_BACKEND_TOKEN | tom | Admin-/PC-token; kreves på LAN |
| FIRE_DEVICE_TOKENS | {} | JSON: enhets-ID til unikt token |
| FIRE_REVERSE_HOST / PORT / DEVICE_ID | tom / 8766 / tom | Valgfri PC → FIRE-bro; lokal FIRE-adresse og konfigurert ID |
| FIRE_WORKSPACE | workspace | Lokal filbasert lagring |
| FIRE_BUILD_TIMEOUT_SECONDS | 180 | Hele byggejobben |
| FIRE_AI_TIMEOUT_SECONDS | 90 | Én dialog-/lydoperasjon |
| FIRE_MAX_WORKSPACE_MB | 256 | Diskgrense med reserve til feilmetadata |
| FIRE_MAX_BUILD_KB | 512 | Grense per byggemappe |
| FIRE_PROGRESS_INTERVAL_SECONDS | 10 | Heartbeat under bygg |
| FIRE_MAX_SESSIONS | 8 | Maks sesjoner; ett bygg om gangen |
| FIRE_SESSION_RESUME_SECONDS | 600 | Frist for gjenoppkobling |
| FIRE_COMMAND_TIMEOUT_SECONDS | 30 | Start/stopp/rollback-kvittering |
| FIRE_AUDIO_ENABLED | false | Aktiver egne lydruter |
| FIRE_AUDIO_MAX_INPUT_BYTES | 524288 | WAV inkl. header, maksimalt 15 sekunder |
| FIRE_AUDIO_MAX_OUTPUT_BYTES | 1440000 | PCM, maksimalt 30 sekunder |
| FIRE_AUDIO_TTL_SECONDS | 300 | Kort levetid for lydfiler |

`/health` bekrefter prosesshelse og konfigurasjon, ikke modelltilgang eller fysisk
integrasjon. AudioEnabled betyr aktivert backendkode, ikke bekreftet mikrofon.

## API og protokoll

| Metode/rute | Formål |
| --- | --- |
| GET /health | Prosesshelse, versjon, modus og funksjonsflagg |
| GET /device/context | Gjennomgått hardware-/OS-kontekst og kontrakt |
| WS /ws/device | Én forbindelse for kontroll og hendelser |
| POST /session/start, /session/stop | Opprett/avslutt sesjon |
| GET /sessions/{id} | Sesjon, fremdrift og enhetsstatus |
| POST /build/confirm | session_id, proposal_id og event_id for 0.2 |
| POST /run/confirm | session_id, package_id og event_id for 0.2 |
| POST /device/events | Samme kontrollerte event-dispatch som WS |
| GET /devices/{id} | Rapportert status og versjonshistorikk |
| GET /projects, /projects/{id} | Eierskapsbegrenset prosjektoversikt |
| DELETE /projects/{id} | Slett uten aktive sesjoner eller beholdte enhetsversjoner |
| GET /builds/{id}, /builds/{id}/log | Status og redigert logg |
| GET /packages/{id}, /packages/{id}/download | Manifest/size/SHA256 og ZIP med Range/ETag |
| POST /sessions/{id}/audio/{turn_id} | Autentisert, begrenset WAV-opplasting |
| GET /audio/{id} | Kortlivet PCM-svar, avgrenset til riktig enhet |

Protokoll 0.2 bruker event_id, session_id, boot_id, kapabiliteter og korrelerte
install_id/run_id/stop_id/rollback_id. Duplikater starter ikke nye operasjoner;
gjenbruk med endret innhold avvises. Avbrutt hendelsesbehandling gir unknown,
slik at klienten avstemmer status i stedet for å starte på nytt.

En testet pakke blir først installert etter device_install_result. run_confirm
sender run_request og venter på app_started. app_healthy etablerer siste fungerende
versjon per enhet/prosjekt. PC-testen oppdaterer bare last_simulated_package_id.
Ved kontaktbrudd er faktisk kjørestatus unknown. En ukjent gammel kjøring må
stoppes og kvitteres før ny start. Ingen blind automatisk appstart ved reconnect.

Lyd følger listen_start/listen_stop, WAV-opplasting, transcript, normal dialog og
audio_ready. Inn: PCM16 mono/16 kHz i WAV. Ut: PCM16 LE mono/24 kHz i blokker.
Bruk små avspillingsbuffere. Vanlige kontrollruter beholder 8192-byte-grensen.
Mock-opptak gir fast transkripsjon og en testtone, ikke ekte talegjenkjenning/TTS.
Alle bygge-/kjøregodkjenninger forblir eksplisitte, også når bestillingen er talt.

## Filstruktur og pakker

`fire_backend/` viderefører app.py, service.py, ai.py, builds.py, lua_worker.py,
models.py, config.py og storage.py. Nye avgrensede moduler: auth.py, protocol.py,
devices.py og audio.py. `contracts/` inneholder JSON-skjemaer. `scripts/` har
smoke-/API-kontroller; `tests/` har eksisterende og nye integrasjonstester.

`workspace/` inneholder projects, builds, packages, logs, context, templates,
sessions, devices, commands, events og audio. Det er lokalt og ignorert av Git.
Historikk, kvitteringer og kommandoer skrives atomisk til JSON. Oppstart feiler
avbrutte bygg, utløper gamle kommandoer og fjerner gamle lydfiler. Prosesslås
hindrer to vanlige serverstarter i samme workspace.

En app er en deterministisk ZIP_STORED med fire oppføringer under apps/<app_id>/:
manifest.json, main.lua, assets/ og appdata/. Bare Lua genereres. Manifestets
checksum er SHA256 av main.lua; ytterarkivets hash ligger i pakkemetadata.
Samme lagrede kode og manifest kan gjenskapes uten et nytt API-kall:

```powershell
.\.venv\Scripts\python.exe -m fire_backend.reproduce build-ID
```

Hvert bygg beholder bekreftet bestilling, kontekst, kildekodeforsøk, simulator-
resultat og byggemanifest. Høyst tre automatiske korrigeringer etter første
kodeforsøk; alle deler samme timeout. Mislykkede bygg tilbys aldri som pakke.

Lua kjører uten OS/Python/loader-/nett-/flash-API-er, med allocator-, instruksjons-
og kjøretidsgrenser. Simulatoren registrerer tegning/RGB og gir syntetiske knappe-
og IMU-verdier. Den beviser ikke ESP32-heap eller faktisk maskinvarekompatibilitet.
Den native Lua-tolken er ikke en full OS-isolasjonsgrense for ubetrodde eksterne
brukere. Firmware må håndheve hele kontrakten selv.

## Tester

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_test.py --all-examples
```

For enhetsprotokolltesten, konfigurer fire-01 med eget token i .env og aktiver lyd
før serverstart. Klienten bruker FIRE_DEVICE_TOKENS, alternativt en lokal
FIRE_MOCK_DEVICE_TOKEN, uten token som kommandolinjeargument:

```powershell
.\.venv\Scripts\python.exe scripts\device_smoke_test.py --device-id fire-01 --all-examples --audio
```

Dette er **enhetsemulering på PC**, ikke fysisk integrasjon. Den sender eksplisitte
testbekreftelser, validerer ZIP, simulerer Lua, kvitterer installasjon/start og
tester lydtransport. Rapporter lagres i workspace/logs.

Etter API-nøkkeloppsett kan ekte leverandørtilgang kontrolleres med betalte kall:

```powershell
.\.venv\Scripts\python.exe scripts\check_openai.py --live --speech --wav opptak.wav
```

Uten nøkkel rapporterer den not_run. Denne sjekken installerer eller kjører ingen
app på FIRE. Den verifiserer heller ikke alle fysiske akseptansekriterier.

API-implementasjonen følger offisiell dokumentasjon for
[Realtime](https://developers.openai.com/api/docs/guides/realtime-conversations),
[transkripsjon](https://developers.openai.com/api/docs/guides/speech-to-text) og
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

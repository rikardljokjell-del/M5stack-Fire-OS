# FIRE OS AI Developer backend

Fast plassering i repoet: `M5Stack-backend/`. All videre backendutvikling skjer
her. `M5Stack-device/` er reservert for brukerens device-prosjekt og skal stå urørt.
Se også `../AGENTS.md` og `../STATUS.md`.

Separat, lokal backend for Windows med Python 3.11+, FastAPI, Uvicorn,
WebSocket, Pydantic og OpenAI Python SDK. Ingen Docker, database, firmwarebygging
eller avhengighet av ChatGPT-/Codex-appen ved kjøring. Én backendprosess og
kortlivede Lua-testprosesser. Python 3.13 er installert separat på denne PC-en.

FIRE OS-koden er ikke endret. Første leveranse er en **PC-prototype**.
Lua-kontrakten er foreslått; den finnes ennå ikke på M5Stack.

## Start med én kommando

I denne mappen, i PowerShell:

```powershell
.\start.ps1 -Mock
```

Dette starter på `http://127.0.0.1:8765` uten API-kall eller nøkkel. Første
oppstart oppretter `.venv` og installerer versjonene i `requirements.lock.txt`.
Hvis lokal PowerShell-policy blokkerer skript:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -Mock
```

Åpne en annen terminal i samme mappe:

```powershell
.\mock.ps1 -Demo
```

Klienten sender «Lag en animasjon med en sirkel som beveger seg.» og viser
serverens JSON-events. Skriv **`/build`** etter byggeforslaget, deretter
**`/run`** etter `package_ready`. `/run` bekrefter kun PC-simulering.
`/quit` avslutter. `/ping` viser gjeldende state.
Knapp B eller tekst som «bygg nå» gir ikke byggeautorisasjon.

Mock-modus bruker fire faste, tydelig merkede Lua-eksempler og er ikke en AI.
Prøv også «Lag Snake», «Lag en RGB-effekt» og «Lag en enkel IMU-graf».

## Aktiver ekte OpenAI-dialog

Stopp mock-serveren med Ctrl+C. Kopier `.env.example` til `.env` og sett nøkkelen
lokalt. Ikke send den til M5Stack, legg den i klientkode eller sjekk den inn.

```dotenv
OPENAI_API_KEY=din_egen_api_nokkel
OPENAI_REALTIME_MODEL=gpt-realtime-2.1
OPENAI_CODE_MODEL=gpt-6.2-astra
FIRE_AI_MODE=openai
FIRE_BACKEND_HOST=127.0.0.1
FIRE_BACKEND_PORT=8765
```

Start i en ny terminal med ` .\start.ps1 ` uten `-Mock`. Dersom du tidligere
brukte `FIRE_AI_MODE=mock` som miljøvariabel i samme terminal, fjern den eller
sett den til `openai`; miljøvariabler har forrang over `.env`.
`/health` svarer også uten nøkkel, men dialog gir da en tydelig feil og bygger
ingenting. `openai_configured=true` viser bare at en nøkkel er satt, ikke at
kontotilgang, kreditt eller modelltilgang er bekreftet.

Backend bruker direkte:

- `wss://api.openai.com/v1/realtime` for én vedvarende tekstsamtale per sesjon.
  Taleopptak og lydtransport er bevisst ikke implementert i første leveranse.
- `POST https://api.openai.com/v1/responses`, SDK `responses.parse`, for strukturert
  Lua-generering og korrigeringer. `store=false`, ingen shell-/fil-/nettverktøy
  eller tilkobling til firmwareprosjektet gis til modellen.

Modellnavnene kan endres via miljøvariablene. Implementasjonen følger
[offisiell Realtime-dokumentasjon](https://developers.openai.com/api/reference/python/resources/realtime/methods/connect)
og [offisiell Structured Outputs-dokumentasjon](https://developers.openai.com/api/docs/guides/structured-outputs).

## Miljøvariabler

| Variabel | Standard | Betydning |
| --- | --- | --- |
| `OPENAI_API_KEY` | tom | Kun på PC; kreves i OpenAI-modus |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-2.1` | Tekstdialog nå, tale senere |
| `OPENAI_CODE_MODEL` | `gpt-6.2-astra` | Strukturert kodegenerering |
| `FIRE_BACKEND_HOST` | `127.0.0.1` | Lokal binding; bruk PC-ens LAN-IP senere |
| `FIRE_BACKEND_PORT` | `8765` | HTTP og WebSocket |
| `FIRE_AI_MODE` | `openai` | `openai` eller eksplisitt `mock` |
| `FIRE_WORKSPACE` | `workspace` | Filbasert lagring |
| `FIRE_BACKEND_TOKEN` | tom | Bearer-token; minst 24 tegn ved LAN-binding |
| `FIRE_BUILD_TIMEOUT_SECONDS` | `180` | Total byggefrist inklusive korrigeringer |
| `FIRE_AI_TIMEOUT_SECONDS` | `90` | Frist for én dialog-/API-operasjon |
| `FIRE_MAX_WORKSPACE_MB` | `256` | Total lagringsgrense, med feilreserve |
| `FIRE_MAX_BUILD_KB` | `512` | Grense for én byggemappe |
| `FIRE_PROGRESS_INTERVAL_SECONDS` | `10` | Heartbeat under lange byggeoperasjoner |
| `FIRE_MAX_SESSIONS` | `8` | Maks samtidige sesjoner; ett bygg om gangen |

For LAN: sett host og et langt tilfeldig backend-token. REST- og WS-klienter
sender `Authorization: Bearer <FIRE_BACKEND_TOKEN>`. Dette er et eget lokalt
token, aldri OpenAI-nøkkelen. Token i URL støttes ikke. WebSocket med browser
Origin avvises; den leverte PC-klienten setter Authorization-header.
Standardtransporten `ws://` er for eget, betrodd lokalnett; TLS må legges til
før bruk over andre nett. Ingen brannmur- eller oppstartsendringer er aktivert.

## Filstruktur

```text
start.ps1 / mock.ps1       Oppstart og interaktiv PC-klient
.env.example              Konfigurasjon uten hemmeligheter
requirements.lock.txt     Testede, låste avhengigheter
fire_backend/
  app.py                  REST, WebSocket, inputgrenser og autentisering
  service.py              Dialog-state, bekreftelser, byggejobber og rollback
  ai.py                   Direkte OpenAI og eksplisitt offline-provider
  builds.py               Validering, arbeidermappe, pakking og checksum
  lua_worker.py           Begrenset Lua 5.4-tolk i egen prosess
  reproduce.py            Gjenskap eksakt pakke uten nye API-kall
  storage.py              Filbasert lagring og restart-recovery
  data/FIRE_DEVICE_CONTEXT.md
  data/{circle,snake,rgb,imu}.lua
scripts/smoke_test.py      Test mot en faktisk kjørende backend
tests/                    Flyt-, SDK-kontrakt- og sikkerhetstester
docs/PROTOCOL.md           Meldinger og state-maskin
docs/DELIVERY.md           Testresultater og gjenstående integrasjon
workspace/                Opprettes automatisk; holdes utenfor Git
  projects/               Prosjekter; current/previous/backup
  builds/<build_id>/      Bekreftet bestilling, kodeforsøk, simulering, manifest
  packages/               Kun vellykkede ZIP-er og pakkemetadata
  logs/                   stdout/stderr og feil per bygg/sesjon
  context/                Kopi av den injiserte hardwareprofilen
  templates/              Reservert for lokale maler
  sessions/               Statussnapshot; starter ikke automatisk igjen
```

## API

Alle ruter unntatt `/health` krever backend-token når det er konfigurert.

| Metode | Rute | Resultat |
| --- | --- | --- |
| GET | `/health` | Prosesshelse, modus og om nøkkel er satt |
| GET | `/device/context` | Kompakt hardware-/OS-/Lua-kontrakt |
| WS | `/ws/device` | Én forbindelse for alle enhetsevents |
| POST | `/session/start` | `{device_id, project_id?}` → sesjon |
| POST | `/session/stop` | `{session_id}` → avbryt og lukk |
| POST | `/build/confirm` | `{session_id, proposal_id}` → 202 og build-ID |
| POST | `/run/confirm` | `{session_id, package_id}` → PC-simulering |
| GET | `/projects` | Prosjektliste |
| GET/DELETE | `/projects/{id}` | Les/slett; stopp sesjonen før sletting |
| GET | `/builds/{id}` | Byggestatus og feil |
| GET | `/builds/{id}/log` | Full begrenset og redigert byggelogg |
| GET | `/packages/{id}` | Manifest, tester, modus og kontrollsummer |
| GET | `/packages/{id}/download` | ZIP etter ny integritetskontroll |

REST-start binder ikke en eksisterende WS-forbindelse. Mock-enheten starter
sesjonen på WS og kan bruke HTTP-bekreftelser med sesjons-ID-en den får der.

## Pakker, testing og reproduserbarhet

Hvert bygg får egen mappe og midlertidig arbeidsmappe. Bare Lua-tekst genereres.
Lua-syntaks kompileres i minne med Lua 5.4; PlatformIO brukes ikke.
API-validering og 180 simulerte frames tester appen før ZIP opprettes:

```text
apps/<app_id>/manifest.json
apps/<app_id>/main.lua
apps/<app_id>/assets/
apps/<app_id>/appdata/
```

Manifestet inneholder alle påkrevde felt. `checksum` er SHA256 av `main.lua`,
som er eneste payload-fil i v0.1. Arkivets SHA256 ligger i pakkemetadata utenfor
ZIP-en. ZIP-medlemsliste, manifest, CRC og payload-hash kontrolleres separat.
Faste filrekkefølger og tidsstempler gir identisk ZIP fra samme manifest/kode.
Generering fra modellen er ikke deterministisk; gjenskaping bruker lagret kode.

```powershell
.\.venv\Scripts\python.exe -m fire_backend.reproduce build-ID_FRA_SERVEREN
```

Dette revaliderer og lager `workspace/builds/<id>/reproduced.zip`, og krever at
SHA256 er identisk. Behold `requirements.lock.txt` og byggemappen for samme miljø.
Hardwareprofil og modellnavn fryses i `request.json`; hvert kodeforsøk beholdes.

En første generering kan etterfølges av **maks tre automatiske korrigeringer**,
altså høyst fire kodeforsøk. Valideringsfeil og forrige kode sendes tilbake til
kodeagenten. Nett-/konto-/API-feil feiler direkte; de utløser ikke skjulte nye
API-forsøk. Hele jobben har en felles timeout. Ingen mislykket ZIP tilbys.

`current` endres først etter eksplisitt `run_confirm` og vellykket PC-test.
`previous` og `backup` roteres da. `app_failed` for gjeldende pakke ruller
registeret tilbake; ingen gammel app startes automatisk. Ved omstart feiles
avbrutte bygg, gamle bekreftelser forkastes og ingen apper starter av seg selv.
OS-fillås på arbeidsmappen hindrer to vanlige backendstarter i å skrive samtidig.
Bruk `start.ps1` eller `python -m fire_backend`, ikke flere Uvicorn-workers.

## Lua-begrensninger og praktiske grenser

Appen får et eget Lua-miljø med bare de deklarerte `fire.*`-tjenestene og et lite
utvalg rene funksjoner. Ingen Python-objekter eller Python-callbacks eksponeres.
Arbeideren arver ikke API-nøkkel eller andre kontoopplysninger. Den har 256 KiB
Lua-allokeringsgrense, 200 000 instruksjoner per callback, 20 000 API-operasjoner
og åtte sekunders prosessfrist. Apper må ha `init()` og `update(dt_ms)`.
Rå OS-, IO-, loader-, debug-, GPIO-, nett-, flash-, OTA- og restart-API-er mangler.
Brudd avvises. Fullt Lua-standardbibliotek er ikke tilgjengelig.

PC-simuleringen registrerer tegne-/RGB-kommandoer og gir syntetiske IMU- og
knappeverdier. Den er ikke en skjermemulator eller et bevis på faktisk ESP32-heap,
elektrisk oppførsel eller firmwarekompatibilitet. Prosessfristen og Lua-miljøet
er praktiske prototypetiltak, **ikke en OS-sikkerhetsgrense mot en ukjent feil i
den native Lua/Lupa-tolken**. OS-isolasjon kreves før eksponering for ubetrodde
eksterne brukere. FIRE må selv håndheve alle grenser og tillatelser senere.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_test.py --all-examples
```

Den siste kommandoen krever en kjørende mock-server og sender eksplisitte
bekreftelser som del av testen. Den verifiserer at `current` og ferdig pakke
ikke finnes før riktige bekreftelser, laster ned ZIP og kjører PC-simulering.
Rapport: `workspace/logs/smoke-report.json`. Ekte API-test kan kjøres med
`--live` etter nøkkel-/modelloppsett; den bruker betalte API-kall.

Se `docs/DELIVERY.md` for faktisk teststatus og gjenstående M5Stack-arbeid.

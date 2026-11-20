# Leveranse og verifisering – 20. november 2026

Implementert i `C:\Users\Rikard\Documents\ChatGPT\M5stack fire\M5Stack-backend`.
Repo: https://github.com/rikardljokjell-del/M5stack-Fire-OS.
All videre backendutvikling skjer i `M5Stack-backend/`; `M5Stack-device/` er reservert og skal stå urørt.
FIRE OS-prosjektet er ikke tilgjengelig ennå og er ikke endret.

## Levert

- Separat Python-backend, én prosess, uten database/Docker.
- FastAPI-rutene i bestillingen, pluss trygg ZIP-nedlasting og byggelogg.
- Én WebSocket med dialog, knappeevents, bekreftelser og status-events.
- Direkte OpenAI Realtime for tekst og Responses for kode, konfigurerbare modeller.
- Fast kompakt hardwareprofil i hver kodeforespørsel, inkludert korrigeringer.
- Serverhåndhevet build_confirm/proposal_id og run_confirm/package_id.
- Lua 5.4-validering og begrenset PC-simulering i separat prosess uten nøkkelmiljø.
- Reproduserbar ZIP, payload-/arkivkontrollsummer, versjonshistorikk og rollback.
- Timeout, diskgrenser, restart-recovery, logging og heartbeat.
- Interaktiv mock-klient og fire faste offline-prototyper: sirkel, Snake, RGB, IMU.

## Observerte testresultater

`python -m pytest -q --junitxml=test-results.xml`: **35 bestått**.
Én deprecation-advarsel kommer fra Starlettes testklient som bruker httpx;
den påvirker ikke den kjørende backendprosessen. Testene dekker:

- health, kontekst, autentisering, LAN-tokenkrav og inputgrenser;
- full WS-dialog → forslag → bekreftelse → pakke → bekreftet PC-kjøring;
- ingen bygg uten riktig proposal_id; knapp B er ikke en bekreftelse;
- ingen kjøring uten riktig package_id; nye meldinger ugyldiggjør forslag;
- tre korrigeringer, timeout, heartbeat, avbrudd og umiddelbar kansellering;
- én global byggejobb, workspace-grense og gjenoppretting etter omstart;
- feil blir lagret også når en byggemappe treffer diskgrensen;
- ZIP-integritet, manipulert arkiv, current/previous/backup og rollback;
- bevegelig sirkel, Snake, RGB og IMU med 180 simulerte frames;
- nektede OS-/Python-/debug-/loader-API-er, uendelig løkke og minnepress;
- redigering av hemmeligheter fra kode, ZIP, metadata, logger og HTTP-feil;
- OpenAI-SDK-forespørsel med modell, kontekst, siste feil, JSON-schema og store=false;
- Realtime-tekstformat og ren feil når OpenAI-nøkkel mangler.

Mot en faktisk lokal server bestod i tillegg `scripts/smoke_test.py --all-examples`:
**4 av 4**. Alle fire fikk kontrollert ZIP-nedlasting og bekreftet PC-simulering.
IDs, manifester, kontrollsummer og progressfaser ligger i
`workspace/logs/smoke-report.json`. Kilde og stdout/stderr ligger i de tilhørende
byggemappene og loggene. `test-results.xml` inneholder den maskinlesbare testrapporten.

Startskriptet `start.ps1 -Mock` er kjørt på denne PC-en. `/health` svarte OK i
mock-modus. En samtidig ekstra start ble avvist av arbeidsmappens prosesslås.
Sirkelpakken ble gjenskapt med `fire_backend.reproduce` med identisk SHA256.
`pip check` fant ingen avhengighetsfeil.
Den faktiske interaktive `mock.ps1 -Demo`-klienten er også kjørt med `/build`,
`/run` og `/quit`: sirkelappen fullførte 180 frames og 361 API-operasjoner.

**Ekte OpenAI-kall er ikke verifisert**, fordi OPENAI_API_KEY ikke var satt.
SDK-/protokolltestene bruker simulerte OpenAI-svar. Ingen mock-resultater er
fremstilt som live AI-generering. Nøkkel, kreditt og faktisk modelltilgang må
bekreftes ved første ekte API-test. Backend har ingen avhengighet av denne chatten.

## Før M5Stack-integrasjon

1. Les det eksisterende FIRE OS-prosjektet når det blir tilgjengelig. Bekreft
   M5Unified/M5GFX-versjoner, native API-er, knappelogikk, layout og reelt ledig minne.
2. Avtal Lua-kontrakten mot eksisterende OS. Dagens `fire.*`-API er foreslått og
   implementert bare i PC-simulatoren, ikke i firmwaren.
3. Implementer Lua-runtime på FIRE med separat miljø per app, instruksjonshook,
   minnegrense, korte callbacks, stopprettighet for OS og et reservert exit-signal.
4. Koble display/buttons/RGB/IMU/time til OS-tjenestene. Mic/speaker/Wi-Fi/BLE/SD
   er reservert; de skal senere få begrensede OS-adaptere og eksplisitte tillatelser.
5. Implementer WebSocket-klient, nettverksoppsett og lokalt backend-token på FIRE.
   OpenAI-nøkkelen skal fortsatt bare finnes på PC.
6. Implementer trygg pakkeoverføring til SD med checksum, midlertidig mappe,
   atomisk aktivering og device-bekreftelse. Ingen firmware-.bin, OTA eller flashing.
7. Koble faktisk app_failed/app_stopped til watchdog og device-rollback. Dagens
   rollback er backend-metadata og beviser ikke device-rollback.
8. Test sirkel, Snake, RGB og IMU på fysisk enhet før lyd. Legg til mikrofon-/lyd-
   transport og Realtime-audio først etter at mock-/tekstflyten og hardware-runtime
   fungerer. Legg til OS-isolasjon hvis backend senere skal håndtere ubetrodde brukere.

Automatisk Windows-oppstart og brannmuråpning er ikke aktivert. Prosessen kan
kjøres fra startskriptet så lenge PC-en er på. Egen driftstjeneste kan settes opp
senere med ønsket restart-/innloggingspolicy.

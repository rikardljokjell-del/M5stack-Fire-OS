# Backend 0.2 – leveranse og verifisering

Arbeidsområde: `M5Stack-backend/` i rikardljokjell-del/M5stack-Fire-OS.
Eksisterende FastAPI-/WebSocket-/OpenAI-/Lua-/ZIP-arkitektur er videreført.
`M5Stack-device/` er lest fra Git, men ingen enhetsfiler er endret, bygget eller flashet.

## Endrede områder

- models.py/config.py: protokoll 0.2, kapabiliteter, scoped token, lydgrenser.
- auth.py/protocol.py: autentisert enhetsidentitet, eierskap, varige event-ID-er og felles dispatch.
- service.py/storage.py: gjenopptakelse, historikk, restart-recovery og migrering av gammel PC-current.
- devices.py: installasjons-, start-, stopp- og rollback-kvitteringer; separat fysisk historikk per enhet/prosjekt.
- ai.py: validert Realtime-funksjon, lokal samtalehistorikk ved reconnect, prosjektkode ved endringer, transkripsjon og talesyntese.
- audio.py: autentisert WAV-opplasting, validering, deduplisering, avbrudd, kortlivet PCM og opprydding.
- builds.py/lua_worker.py: faktiske kapabilitets-/minnegrenser, tidligere kildekode som utgangspunkt, atomisk pakkelevering og presiserte Lua-argumenter.
- FIRE_DEVICE_CONTEXT.md: faktisk gjennomgått firmware, OS-knapper, bibliotekkrav og kjente adapterbegrensninger.
- start.ps1: ny installasjon ved endret prosjektmetadata, fortsatt én kommando.
- contracts/, PROTOCOL-v0.2.md, LUA_API.md, OPERATIONS.md, README og rootstatus/instruksjoner.
- Nye enhets-/lyd-/SDK-/recovery-tester og scripts/device_smoke_test.py, scripts/check_openai.py.
- Handoff 069ea09e: sentral capability-policy, oppstart uten lyd med tekststatus,
  uavhengige lydporter, faktisk sesjonskontekst og implisitt offline reconnect.
  Native feilkvittering kan ha tom/observert SHA uten at suksesskrav svekkes.
  Oppdatert konservativ Lua-simulator og dokumenterte adapterbegrensninger.

## Kontrakt

Tidlig publisert protokollcommit: b9849c24ef507475c28d153db1798eb0d0c4b33e.
Den oppdaterte autoritative kontrakten er PROTOCOL-v0.2.md med genererte skjemaer
i contracts/. Lua-kontrakten er LUA_API.md og den injiserte hardwareprofilen.

Backend skiller testet, installert, startet og bekreftet fungerende pakke.
`current` for fysisk enhet endres først ved korrelert app_healthy etter app_started.
PC-simulering oppdaterer kun last_simulated_package_id. Gamle prototypeverdier
for current/previous/backup migreres til uttrykkelig simulert historikk.

## Faktisk verifisert

`pytest -q --junitxml=test-results.xml`: **95 bestått**, inkludert den eksisterende
testdekningen tilpasset korrigerte current-semantikker. Én advarsel gjelder
Starlettes overgang fra httpx i testklienten; ingen test feiler.

24 nye handoff-kontroller dekker nøyaktig native profil med begge lydflagg false,
synlig oppstartsstatus, tekst/bygg/install/run, uavhengige lydretninger, avvisning
før lydstrøm/provider brukes, bevart forslag ved lydforsøk, offline reconnect
uten resume-hint, restart, blokkert socket-overtakelse, nye boot-ID-er, native
feilkvitteringer uten hash og uendrede hashkrav for suksess. Heltallsargumenter,
syntetisk boot-uptime og pressed-callback kontrolleres også. physical_verified=false.

Nye kontroller dekker scoped identitet/eierskap, kvitterings-ID-er, feil checksum,
gamle boot-ID-er, duplikate bekreftelser, endret payload med samme event-ID,
gjenopptakelse/restart/utløp, ukjent resultat etter avbrutt eventbehandling,
naturlig appstopp, sene stoppkvitteringer, supersedert installasjon, rollback,
versjonshistorikk per prosjekt og avvisning av manglende hardwaretjenester.
Et leveringsavbrudd beholder en allerede validert pakke; install_retry kan gi ny
installasjonskommando uten en ny AI-generering. Prosjektendringer gjenbruker
lagret samtale, bekreftet plan, manifest og forrige kode. Skjemaeksport kontrolleres.

Lydtestene dekker større autentiserte opptak enn den ordinære HTTP-grensen,
format/sampling/kanaler/lengde/stillhet, strømmede overstore opplastinger,
gjentatt turn-ID, tekstfallback ved talefeil, avbrudd og sletting av lyddata.
SDK-kontrakttester bruker faktisk installert OpenAI SDK og simulerte HTTP/Realtime-
svar, inkludert multipart-transkripsjon, funksjonsresultater og PCM-deltaer.

Mot en faktisk kjørende lokal backend:

- **4/4** eldre PC-smoke-flyter bestod: sirkel, Snake, RGB og IMU.
- **5/5** enhetsemulerte flyter bestod: de samme fire og en syntetisk lydflyt.
- Emulert klient lastet ned og validerte størrelse/SHA256/ZIP, sendte
  installasjonskvittering, egen kjørebekreftelse og start/healthy/stopp-kvitteringer.
- Lua ble simulert også hos testklienten etter run_confirm.
- Opplastet mock-lyd ga mock-transkripsjon og en testtone; PCM-hash/nedlasting og
  avspillingskvitteringer ble kontrollert. Dette var ikke ekte talegjenkjenning.
- Oppstart via start.ps1 oppgraderte lokalt til backend 0.2.0.
- `pip check`: ingen avhengighetsfeil.

Lokale rapporter: test-results.xml, workspace/logs/smoke-report.json og
workspace/logs/device-smoke-report.json. Disse runtime-dataene er ikke lagt i Git.

## Ikke verifisert / gjenstående eksterne avhengigheter

**Ekte OpenAI-kall er ikke utført.** OPENAI_API_KEY mangler. Kjøring av
check_openai.py --live rapporterte not_run, live_verified=false. Modell-/konto-
tilgang, faktisk norsk transkripsjon og talesyntese må verifiseres når nøkkel er satt.

**Fysisk M5Stack-integrasjon er ikke fullført.** Inspektert firmwarecommit 069ea09e
har nå klient, Lua-runtime og SD-pakkehåndtering. Begge lydflagg er false.
Backend har fulgt BACKEND_HANDOFF.md og bruker den annonserte profilen som grense.
Kildelesing avdekket gjenstående avvik i Lua-stakk/budsjetter, ZIP-header,
HTTP-header, SD-versjonering og stopp/rollback/lyd. Konkrete funn og videre
enhetsarbeid står i [DEVICE_HANDOFF_RESPONSE.md](DEVICE_HANDOFF_RESPONSE.md).

Deretter må ekte opptak/avspilling, maskinvareadaptere, minne, OS-navigasjon,
SD-avbrudd, fysisk appstart og rollback testes på FIRE. En autentisert emulert
klients kvitteringer er testdata, ikke bevis på kjøring på maskinvare.

Full-dupleks tale, Lua-tilgang til mic/speaker/nett/SD og vilkårlige assets er ikke
del av kontrakt 0.2/fire-lua-0.1. Første versjon bruker avgrensede taleopptak og
Lua-apper med maksimalt ti sekunders faktisk kjøretid per start.

Automatisk Windows-oppstart og brannmuråpning er dokumentert, men ikke aktivert.

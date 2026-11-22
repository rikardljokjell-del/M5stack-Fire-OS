# Arbeidsordre til device-agenten: stabil tale, samtale og appflyt

## Omfang og fasit

Revidert mot GitHub `a3f861a9e14c7de0d88841bff5323e7ce247d5a9` (22. november 2026).
Linjer nedenfor viser denne revisjonen; bruk funksjonsnavn når filen har flyttet seg.
Backend-agenten har bare lest firmware. Ingen device-fil er endret, bygget eller
flashet som del av denne revisjonen. Dette dokumentet beskriver **arbeid device-agenten
må utføre**, ikke feil som allerede er rettet i firmware.

Les også `PROTOCOL-v0.2.md`, `APP_LIFECYCLE.md`, `VOICE_HANDOFF.md` og backendens nye
samtalekontrakt før implementering. Nyeste backendkode er fasit for de additive
protokollfeltene nedenfor. Ikke gjeninnfør automatisk bygging eller kjøring ved tale,
reconnect, snapshot eller gammel kvittering.

Gjennomgått i detalj: produksjonens `fire_backend_client.*`, `fire_reverse_transport.*`,
`fire_audio_capture.*`, `fire_lua_package_manager.*`, `fire_lua_runtime.*`, `main.cpp`,
AI-, knapp-, SD/app-, konfigurasjons-, Wi-Fi-/strøm- og lydrutene i `fire_os.*`.
Byggefil, bibliotekfilter, README og BACKEND_HANDOFF er sammenholdt med disse.
Rescue/POC-kilder og miljøavgrensning er kontrollert som separate kjørbare innganger.
Dette er ikke en ny linje-for-linje sikkerhetsrevisjon av den vendorerte Lua-kjernen,
ESP-IDF, M5Unified eller NimBLE, og ingen fysisk måling er utført av revisjonsagenten.
UI-/radio-/filutforskerkode uten påvirkning på denne flyten har lavere revisjonsdybde.

Målet er en robust, målbar opplevelse. Ikke rapporter «feilfri» kun fordi en build
eller ett opptak lykkes. Fullfør akseptansetestene og oppgi resterende begrensninger.

## Prioritert rekkefølge

1. Rett minne-/datatap, lydavbrudd og blokkerende arbeid (D01–D09, D23).
2. Implementer én samlet samtaletilstandsmaskin, moduser, korrelasjon og reconnect
   (D10–D19). Gjør knappene riktige før animasjon/polering.
3. Mål og rett mikrofonens klokke/signal/behandling (D20–D22).
4. Fullfør installasjon, versjoner, kjøring, inventar og sletting (D23–D34),
   samt konfigurasjons-/strøm-/radiosamspill (D35–D37).
5. Kjør feilsimulering og fysisk matrise, oppdater handoff og merk firmware-revisjon.

## Samtalekontrakt med ny backend

- `session_start` kan sende `conversation_mode: "chat" | "develop"`.
  Utelat feltet ved vanlig resume for å beholde valgt modus. Ny legacy-sesjon bruker
  `develop`. `chat` betyr **Kun samtale**, uten byggeforslag/byggautorisasjon.
- `mode_select` med `conversation_mode` bytter modus, avbryter pågående tale/dialog
  og fjerner gammelt forslag. Bruk ikke modusbytte som stopp av installasjon/kjøring.
- Eksplisitt ny app bruker `app_mode: "new"`; endring bruker `app_mode: "update"`
  og riktig app/prosjekt/base. Reconnect er ikke et nytt valg og skal ikke sende
  `app_mode="new"` på nytt. `conversation_mode` og `app_mode` er forskjellige valg.
- `listen_start` med **ny** `turn_id` avbryter gammel transkripsjon/dialog/TTS på
  backend. Device må først stanse lokal høyttaler/nedlasting. Eventuelt send
  `cancel_turn` med gammel `turn_id`, så `listen_start` med ny. En gammel cancel
  skal aldri treffe den nye omgangen. `cancel_turn` uten turn er legacy-støtte.
- Backend sender `turn_cancelled` med gammel `turn_id`. Stans bare tilsvarende
  arbeid, aldri en nyere omgang. Ingen ny playback-interrupted-event er nødvendig.
- Gamle playback-kvitteringer, listen_stop og opplastinger for avbrutt turn skal
  ikke starte noe igjen. Device må likevel filtrere lokalt før dyrt arbeid.
- `transcript` kommer før svaret. Vis dette som **Jeg hørte: …**, separat fra AI-svar.
  Brukeren kan trykke B og rette bestillingen; bygging krever fortsatt eksakt
  `proposal_id` og eksplisitt A BUILD. Tale som «bygg nå» er ikke autorisasjon.
- Ved stille/uforståelig input sender backend `input_retry` med
  `code="no_speech"`, trygg `message`, aktuell `turn_id`, `recoverable=true` og
  `action="listen_start"`. Uteblitt WAV gir `code="audio_upload_missing"`.
  State/activity går til idle og historikk/modus/sesjon beholdes. En legacy
  `error` med samme code kan også komme: dedupliser visningen, ikke lag en ny
  FAILED-deadend. Vis «Prøv igjen – B» og behold CONNECTED hvis den er reell.
  En sen retry for gammel turn må ikke nullstille et nyere opptak.
- Snapshots inneholder valgt `conversation_mode`. Hent gjeldende state, activity,
  forslag, pakke, fremdrift og pending commands etter reconnect; ikke anta tom sesjon.

## Knapper og visuell flyt som skal implementeres

Ved åpning: **Kun samtale**, **Ny app**, **Endre app**, **Tilbake**. La brukeren
velge før første opptak. Ved Endre app vises kort appnavn og valgt basisversjon.

| Tilstand | A kort | B kort | C kort |
| --- | --- | --- | --- |
| Klar i Kun samtale | Vis samtale/meny | Start opptak | Tilbake/avslutt |
| Klar i utvikling | Vis detaljer | Start opptak | Tilbake/avslutt |
| Tar opp | Ingen bygg | Stopp og send | Forkast opptaket |
| Transkriberer/AI tenker | Ingen bygg | Avbryt og start nytt opptak | Avbryt til Klar |
| AI-svar lastes ned/spilles | Ingen bygg | Stopp lyden og start nytt opptak | Stopp lyden til Klar |
| Forslag klart | BUILD for synlig proposal | Legg til/rett med tale | Forkast forslaget |
| Bygger/installerer | Ingen ny bekreftelse | Vis status, ingen skjult handling | Bare dokumentert avbrudd; vis om det ikke kan avbrytes |
| Installert og kjørbar | RUN for synlig package | Ny tale/endring etter gyldig modusvalg | Avslutt visning |
| Kjørende Lua | Appens knapper | Appens knapper | Appens knapper; OS-langtrykk beholdes |

Lang A=Home, lang B=Quick Settings og lang C=Back følger nåværende OS-kode.
Oppdater motstridende README. Ikke la dobbeltklikkforsinkelse/slike snarveier
overstyre B som opptak/avbrudd inne i samtalen. En enkel knapp må gi øyeblikkelig
visuell respons, med korrekt footer fra **samme tilstandsmodell** som handleren.

Vis alltid modus, tilkobling, hva som skjer og neste handling. Liten ansiktsanimasjon
kan beholdes, men ikke på bekostning av full forståelig tekst. Vis flere linjer
med rulling/sideskift for transkripsjon og AI-oppsummering. Ikke avkort brukerens
forståelsesbekreftelse til 31 tegn. Vis gjerne mikrofonnivå og faktisk opptakstid.

## Konkrete funn: lyd, UI og tilstand

### D01 – P0: aktiv høyttalerbuffer kan frigis før avspilling er stoppet

`fire_os.cpp:2916–2975`, `audio_ready`: `free(aiAudioOutputBuffer_)` skjer straks
en ny melding kommer. Gammelt playRaw kan fortsatt bruke denne bufferen. Det
finnes heller ikke duplikatkontroll på `audio_id`. Avbryt/vent på at M5-høyttaleren
har sluttet å lese, invalider gammel operasjon og frigjør deretter. All tilgang
til buffer og playback-eierskap må ha én eier/task. Test dobbelt audio_ready og
nytt svar mens gammelt spiller; ingen klikk, reset eller bruk av frigitt minne.

### D02 – P1: downloadAudio blokkerer knapper og WS i opptil 25 sekunder

`fire_os.cpp:2937–2939` kaller `FireBackendClient::downloadAudio` synkront inne i
WebSocket-callback. `fire_backend_client.cpp:167–209` venter inntil 5 s header +
20 s body med delay(1), uten `pollButtons`, WS-drenering eller cancel-kontroll.
Flytt HTTP til en egen begrenset task eller kooperativ chunk-state-maskin med
cancel-token og hard timeout. Callback skal kun validere og køe operasjonen.
Behold størrelsesgrense/SHA256 før PCM avspilles. Første versjon kan fortsatt
bufferlagre hele den korte PCM-filen i PSRAM; ikke innfør uverifisert streaming
som spiller før hashkontroll uten en ny avtalt streamingkontrakt.

### D03 – P1: uploadAudio har samme blokkeringsproblem

`fire_os.cpp:2663–2664`, `fire_backend_client.cpp:90–137`: hele WAV sendes i en
synkron løkke. Writes håndteres som alt/ingenting, connect mangler eksplisitt
timeout og WS/knapper står. Implementer send-offset, delvise writes, cancellation,
bounded arbeid per tick og transportfrist. Behold samme turn og bytes ved retry;
ikke generer nytt event-ID for en retransmisjon av samme semantiske hendelse.
Les HTTP JSON-feilens trygge code/message; «2xx» alene er ikke hele statusmodellen.

### D04 – P1: B avbryter ikke AI-svar eller THINK, og virker ikke ved forslag

`handleAiDeveloperButton:2483–2515` har B-kode kun for workflow 0 og 1. TALK setter
state 2, og forslag state 3, så B gjør ingenting. Implementer tabellen over.
Stopp speaker/download **lokalt først**, kanseller gammel turn og start ny med
ny turn_id uten å vente på at gammel TTS blir ferdig. Ikke send session_stop.

### D05 – P1: C-footer lover CANCEL under bygging som handleren ikke utfører

Footer `5509–5513` sier CANCEL i state 4; handler `2529–2535` aksepterer bare 3/5.
Det finnes heller ikke opptakscancel i state 1. Skill «forkast denne taleomgangen»
fra «avbryt bekreftet build/install». Ikke si at en fysisk install er avbrutt før
arbeidet faktisk er stoppet. Footer og handler må genereres fra samme modell.

### D06 – P1: startAiRecording kan ta opp høyttaleren, med knappepip

`startAiRecording:2558–2604` kontrollerer ikke `aiAudioOutputActive_` og stopper
ikke `M5.Speaker`. `onButton:1821` spiller tone før opptakshandleren;
`playButtonSound:2066–2069` er ubetinget ved aktivert lyd. Hold mikrofon og
høyttaler gjensidig utelukkende i samtaleflyten, med kort målt settling-tid ved
ADC-start hvis maskinvaren trenger det. Ikke spill knappelyd i opptak eller over
AI-avspilling. Vis bekreftelse med skjerm/LED i stedet.

### D07 – P1: lydfeil rydder ikke konsekvent kontrolltilstand og ressursflagg

Etter `listenStart`-sendefeil (`2595–2598`) er aiAudioCaptureActive_ allerede true.
Feilgren setter det ikke tilbake. Ved captureFailed setter updateAiAudio finished,
og slutten av rutinen kan likevel sende listen_stop uten gyldig WAV. Ved Home/Back
stoppes verken mikrofon, PCM eller turn; updateBackend kobler bare socket fra.
Lag én idempotent `cancelConversationTurn(reason)` som stopper/joiner capture,
stopper speaker, lukker HTTP, nuller korrelerte ID-er/flagg og sender cancel
når sesjonen er gyldig. Bruk den ved knapp, navigering, feil og valg av ny modus.

### D08 – P1: start/status/ack forveksles med ferdig semantisk operasjon

confirmBuild/confirmRun returnverdier ignoreres (`2518`, `2538`), mens UI umiddelbart
går BUILDING/RUNNING. sendFrame-suksess er heller ikke server-ack. Behold pending
event-ID og vis «Sender …» til ack eller autoritativ state. Timeout/retry av samme
event-ID skal ikke gi dobbelt bygge-/kjørehandling. RUNNING krever app_started.

### D09 – P1: lydhash er valgfri ved feil/manglende hash

`2940` hasher bare hvis expectedHash.length()==64. Ellers kan audio_ready likevel
spilles. Krev korrekt 64 hex, format pcm_s16le, mono/24k, lik faktisk bytecount og
gyldig current turn/session før nedlasting. Avvis expired lyd. Duplikat skal
hverken frigjøre aktiv buffer eller spille samme svar igjen.

### D10 – P1: ingen «Kun samtale» og feil semantikk for Ny app/reconnect

Picker `2444–2476`, `5316–5338` har bare New app/installert app/Back. Startmelding
`fire_backend_client.cpp:431–443` sender bare prosjekt-ID. Legg til nye modusfelt
og app_mode-valg beskrevet over. Ellers kan tom project_id for Ny app bli tolket
som resume av gammel samtale på samme boot. Behold eksplisitt brukerens valg
gjennom reconnect; velg ikke ny app automatisk ved nettbrudd.

### D11 – P1: session_snapshot ignoreres; to uavhengige state-maskiner driver UI

`handleBackendMessage:2863–3117` har ingen snapshot-gren. session_started setter
bare CONNECTED; workflowstate fra server og lokal audio-overgang overskriver
hverandre. `updateAiAudioOutput:2695–2697` nuller alltid workflow etter lyd og kan
skjule gyldig BUILD. Parse snapshot og gjenopprett gjeldende forslag/package/
fremdrift/modus; skill samtaleaktivitet fra appworkflow. Playback finished skal
ikke på egen hånd bestemme prosjektets state. Serveren kan gjenta samme forslag
etter playback; dette skal gjenopprette samme autorisasjon, ikke skape en ny.

### D12 – P1: ingen systematisk session/turn/seq-filtrering eller JSON-parser

`FireBackendClient::handleFrame:556–561` tar session_id fra enhver tekstmelding
med en enkel substring-søk. `fire_os.cpp:242–276` søker feltnavn hvor som helst,
kan plukke nøkkel fra nestet objekt/tekst og dekoder ikke `\uXXXX` riktig.
En gammel meldingshale kan overskrive ny turn/UI og et snapshot kan lese feil
felt. Bruk bounded ekte JSON-parser, valider toppnivå type/session/protokoll og
seq. Bare forventet session_started kan etablere ny sesjon. Husk seq-baseline per
sesjon/connection, ikke på tvers av nye sesjoner. Transkripsjon og AI-svar må
beholdes separat; ikke la én `aiAssistantText_` ødelegge «Jeg hørte»-bekreftelsen.

### D13 – P1: connected vises før sessionReady

`handleHandshake:428–443` setter State::Connected før session_started. Appen kan
si CONNECTED mens semantiske eventer fortsatt avvises. Skill TCP/WS-open fra
session-ready i UI/callback. B kan vise «Kobler til …» og eventuell køet start,
men skal aldri sende tom session_id. Behold tidligere gyldig resume-ID separat.

### D14 – P1: handshake kan bli hengende for alltid

`handleHandshake:415–426` har ingen deadline og ingen gren for død client eller
full 4096-byte buffer uten headeravslutning. Resultat: aldri ny Offline-retry.
Sett frist, grensefeil og liveness-sjekk. Kontroller RFC6455 status, Upgrade,
Connection og Sec-WebSocket-Accept mot egen nonce før Connected.

### D15 – P1: ingen aktiv heartbeat/liveness etter halvåpent nettbrudd

ping()-metoden finnes, men ingen periodisk kall/ack-timeout. TCP connected alene
er utilstrekkelig ved NAT/AP-tap. Send begrenset ping med tid, observer pong eller
annen mottatt kontroll, lukk og reconnect ved utløp. Bruk backoff med jitter og
signed elapsed arithmetic; dagens millis()<reconnectAt_ (`375`) er sårbar for
32-bit rollover. Ikke koble automatisk fra en gyldig samtale fordi Quick Settings
midlertidig åpnes (`updateBackend:2799–2807`). Behold ønsket samtale som demand.

### D16 – P1: disconnect mister session-ID og ingen outbox for kritiske kvitteringer

`disconnect:72` nuller sessionId_, ny start sender ikke resume_session_id.
Backend har legacy implicit resume, men firmware kan ikke stole på dette etter
alle feilsituasjoner. Behold resume-ID og send eksplisitt. Lagring/install/run/
playback callbacks ignorerer sendefeil; install kan lykkes uten at backend får
kvittering. Kø kritiske korrelerte kvitteringer med samme event_id inntil ack,
bundet til boot/session/operasjon, med begrenset størrelse og varighet. Ved reboot
er gamle kommandoautorisasjoner utløpt; ikke replay gammel app_started som ny run.

### D17 – P1: WebSocket-fragmentering og kontrollrammer valideres ikke

`readFrames:464–465` ignorerer FIN/RSV; continuation opcode 0 håndteres ikke.
Fragmentert JSON kan bli levert halvveis og resten forkastet. Maskerte
serverrammer aksepteres, control-frame-lengde/FIN kontrolleres ikke, og hverken
fragment eller delvis frame har frist. Implementer RFC6455 korrekt eller bruk
vedlikeholdt klient med bounded minne/arbeid. Håndter interleaved ping i en
fragmentert tekstmelding. Maks8192 gjelder samlet melding, ikke hvert fragment.

### D18 – P2: reverse pool fallback kan blokkere selv om riktig bro snart er klar

`service:378–393`, uploadAudio og downloadAudio prøver umiddelbart direct connect
når ingen Ready reverse-slot finnes. På telefon-NAT er direct kjent utilgjengelig.
Kø en kort, avbrytbar vent på pool-refill når reverse er valgt/aktiv. Ikke reserver
HTTP-slot lenge før bruk; hold WS separat. Poolens auth-loop er bounded, noe som
skal beholdes. Gi både connect, write og read eksplisitte tidsfrister og sørg for
at alle feilstier slipper slot. Maks fire samtidige forbindelser må respekteres.

### D19 – P2: firmwareversjon og capabilities er ikke faktisk kjørende profil

Handshake annonserer alltid input/output=true, 5 tjenester og fire-os-0.2 (`433`),
selv i miljø uten FIRE_AUDIO_CAPTURE_ENABLED eller manglende hardware-adapter.
Bruk faktisk bygget/initialisert støtte og en revisjonsmerket firmware_version.
Ikke bruk isEnabled alene som bevis på forståelig ADC-lyd. Oppdater BACKEND_HANDOFF
som fortsatt sier output=false, README med gamle knapper og mic-beskrivelse, samt
bygginstruks som anbefaler annet miljø enn default. Ikke endre Lua-API uten avtale.

## Mikrofonkvalitet: konkret arbeid og måling

### D20 – P1: direkte ADC-task har tidsjitter, catch-up-bursts og kvantisert baseline

`fire_audio_capture.cpp:24` bruker 1000000/16000=62 µs, ikke 62,5. Tasken på core0
kan bli preemptet av radio og sover hver 1024 sample (`51`); den tar så samples
hurtigere frem til nesteSampleUs er ajour. Først >100 ms etterslep resynkes klokken
(`56`). Et korrekt totalsampleantall alene beviser derfor ikke korrekt talelyd.
`baseline += (raw-baseline)>>8` (`41`) har heltallsdeadband/asymmetri, initialiseres
alltid på 2048, og gain32 kan klippe oppstarten. Bruk målt DC-baseline og en
presis fixed-point-filterakkumulator eller tilsvarende, kontrollert gain og
ikke-hørbar oppstart. Ikke sample sent i bursts for å late som tapte samples ble
målt. Velg dokumentert stabil ADC/DMA/timerløsning etter faktisk klokkemåling.
Ikke gjeninnfør den gamle DMA-varianten som ga ~5,4x feilrate og feil raw>>4.

### D21 – P1: ingen capture-feildiagnose eller trygg join

adc1_get_raw-resultatet valideres ikke (`40`), capture.failed settes aldri true
av tasken, og volatile alene beskytter ikke cross-core strukturtilstand.
fireReleaseMicCapture venter maks250ms men returnerer uten å angi at tasken
fortsatt eier bufferen (`107–112`). Innfør eksplisitt ownership, atomics/critical
section og task-finished notification. Oppgi om stop/join lyktes før gjenbruk.
Rapporter driverfeil og målte tall uten rå lyd/nøkler i logger.

### D22 – P1: bruker får ingen informasjon om dårlig nivå før ASR-feilen

Vis RMS/peak-meter, timer og «Snakk nær mikrofonen» ved lavt nivå. Finn fysisk
akseptabel avstand, orientering og lydnivå med norsk tale. Mål lokal elapsed_us,
sample_count, faktisk rate, maks/percentiler av sample-jitter, overruns/gaps,
DC/RMS/peak og clippingandel. Test med BLE både på/av, aktiv Wi-Fi og SD.
Fem sekunder skal gi omtrent80000 **sammenhengende** samples. Lytt til kort
testopptak under en eksplisitt fysisk kvalitetstest før ASR evalueres; støy
skal ikke behandles som gyldig bestilling bare fordi en modell finner ord.
«Ingen forståelig tale» er en normal recoverable inputtilstand, ikke bevis på
manglende nett eller grunn til å starte hele sesjonen på nytt. Behold samtalen,
vis kort veiledning og la B prøve igjen. Ikke gjett eller skjul feil bestilling.

## App, SD, versjoner og runtime

### D23 – P0: installasjonsfeil kan slette eneste fungerende gamle versjon

`fire_lua_package_manager.cpp:411–414`: hvis fjerning av ny staging/appdata feiler,
kalles removeTree(previousPath) etter at finalPath allerede ble flyttet dit.
Dette sletter den gamle appen og dataene i en feilgren. Gjenopprett gammel mappe
til finalPath og behold journal/staging for recovery; slett aldri den fungerende
versjonen for å håndtere feil i ny staging. Feilinjiser hver mkdir/write/rename/
remove, særlig her, og kontroller gammel kilde og appdata byte for byte.

### D24 – P1: runtime kan bare initialiseres én gang etter første stopp

`startLuaApp:2705–2717` kaller begin bare når luaRuntimeReady_ er false.
`stopLuaApp:2772` kaller runtime.stop som lukker lua_ (`fire_lua_runtime.cpp:334–343`),
men luaRuntimeReady_ nulles ikke. Neste start går til loadSource uten lua_ og
feiler. Lag ny VM ved hver appstart og ved feil/restart, eller gjør stop-semantikken
konsistent. Test app1→Home→app1, app1→app2, runtimefeil→ny app, og remote run→stop→run.

### D25 – P1: rollback melder suksess uten å gjenopprette gammel versjon

`fire_os.cpp:3087–3103` sjekker bare at lagret lp_<package> finnes. Alle versjoner
kan peke til samme /apps/<app>/main.lua etter oppdatering. Koden velger ingen
gammel kilde, bytter ingen mappe og validerer ikke gammel checksum. Implementer
immutable lokal versjonsmappe/indeks, atomisk faktisk restore og hashkontroll.
Send rollback_result=ok først etter at akkurat ønsket pakke er aktiv på SD.
Den ene .previous-<app>-mappen er ikke en komplett versjonshistorikk. Rollback
skal aldri automatisk starte programmet; ny A RUN kreves.

### D26 – P1: kommandoers boot/expiry/kjede kontrolleres ikke fullt

install_request sjekker bare eventuell boot; run_request sjekker ikke expires_at,
stop_request sjekker ikke boot/expiry, rollback_request aksepterer tom boot og
sjekker ikke expiry. Bruk server_time + lokal monotonic for UTC-frister (RTC kan
være uinnstilt). Krev korrekte ID-er, hash, device/session/boot og gyldig pending
kommando før handling. Lagr consumed-run før kjøring; replay må returnere **samme
opprinnelige kvittering**, ikke appStarted for en tidligere starting/healthy/stopped
tilstand. Returner ikke uriktig appFailed hvis kommandoen aldri var gyldig.

### D27 – P1: SD-manifest og kjørende kilde valideres ikke ved direkte appstart

`scanLuaApps:1533–1538` sjekker bare at manifest/main finnes, navnet blir foldernavn.
`startLuaApp` leser kun main.lua, ingen manifest/checksum/limits. Valider manifest,
API, tjenester, minne, tid og hash også ved start fra Apps og remote run. Vis
manifest.name og versjon, behold folder-ID som identitet. Et endret SD-kort må
ikke kunne kjøre kilde under gammel attestert package/hash. Ikke la persistente
lp/lh-nøkler alene overstyre reell filkontroll.

### D28 – P1: install journal, duplikat-ZIP og power-loss recovery mangler

extractStoredZip bruker flagg mainFound/manifestFound og FILE_WRITE uten å avvise
duplikatnavn; mangler journal/recovery ved boot mellom final→previous og staging→final.
Krev eksakt tillatt entry-sett, bounded navnelengde/entrycount/totalsize, null
encryption/descriptor/ukjente flagg, og avvis duplikater før diskmutasjon.
Kontroller alle seek/read/write og trunker stagingfil eksplisitt. Verifiser
central-directory/end-of-directory-konsistens eller dokumenter og håndhev en
streng backendpakkeprofil. Recover gammel app ved reboot/SD-reset på hvert steg;
skjul halvferdige mapper i picker. Rydd staging etter feil uten å røre gammel app.

### D29 – P1: installer kan blokkere UI og mangle avbrytelse

startDownload direkte connect (`103`) mangler eksplisitt timeout. Download-loop
(`162–172`) kan tømme hele socketstrømmen i ett OS-kall, og extract/hash/rename
kjører synkront i Verify. Begrens arbeid per service eller bruk serialisert SD-task.
Kontroller SD-tilgjengelighet og skrivfeil også for prefetched body (`149–153`),
ikke bare senere chunker. Hvis startDownload avvises (`fire_os.cpp:3004–3012`),
send en korrelert failed-kvittering i stedet for bare lokal DOWNLOAD REJECTED.
Kontrollsocket og knapper må fortsatt betjenes under store nedlastinger.

### D30 – P1: sletting/inventar implementerer ikke backendkontrakten

deleteLuaApp (`1569–1585`) sender ingen app_deleted og app_inventory_request har
ingen handler. Apps Settings kobler vanligvis backend fra via backendDemand.
Implementer vedvarende, bounded deletion-outbox og full SD-inventory ved neste
tilkobling/etter endring. Rapporter storage_ready/complete korrekt; 16-app picker-
grensen er **ikke** et komplett inventar hvis flere apper finnes. Ingen SD eller
avbrutt scan må aldri bety at alle apper er slettet. Backend kan først tillate
PC-sletting etter ferskt fraværsbevis fra samme tilkobling/boot. Se APP_LIFECYCLE.

deleteLuaApp fjerner bare main/manifest og rmdir på assets/appdata; ikke-tomme
mapper etterlater en delvis slettet app og kan miste metadata før feilmelding.
Bruk sikker, scoped rekursiv sletting av valgt app, stopp eventuell aktiv run,
bevar eller eksplisitt velg hva som skjer med brukerdata, og rapporter først
etter verifisert resultat. Rydd NVS/versjonsindeks konsistent. Sletting via
File Explorer må også oppdages av inventar, ikke bare App Manager-knappen.

### D31 – P1: lokal stopp/runtimegrense kvitteres ikke korrekt

stopLuaApp (`2767–2777`) nuller luaRunId uten app_stopped for Home/Back. Ti-sekunders
grensen (`runtime.cpp:366–367`) blir generell app_failed(runtime_error), ikke
normal runtime_limit. Behold run/package-ID før rydding, send korrelert
app_stopped reason=user_exit/runtime_limit når passende. Feil i on_button
(`1877–1879`) stopper lokalt uten app_failed. Backend må ikke sitte med stale
running. Unngå dobbel kvittering ved stop_request som allerede har stop_id.

Ikke fjern 10000ms-kontraktgrensen ensidig for å skjule feilen. Vis begrensningen
som forventet demonstrasjonsstopp, eller forhandle en eksplisitt ny runtimeprofil
med backend og relevante tester hvis brukeren skal ha langvarige apper.

### D32 – P1: per-pixel RGB-API gir faktisk all-pixel utdata

`luaRgbSet:3159–3175` lagrer luaRgbValues[index], men renderer bruker
writeFireRgbRaw/allColor som setter **alle** LED-er til siste pikselfarge.
Dette bryter `fire.rgb.set(index,r,g,b)` som backend/simulator genererer for.
Implementer faktisk array-renderer via OS-driver eller endre kontrakten eksplisitt;
ikke hevde at mønster/én LED fungerer før fysisk sett. Test indeks0 og9 med
ulike farger, øvrige av. Rydd RGB til OS-eid tilstand når appen stopper.

### D33 – P2: Lua allocator og next-wrapper avviker fra Lua-kontrakten

allocator (`runtime.cpp:23–52`) bruker oldSize ved pointer==nullptr. Lua bruker
da oldSize som type-tag, ikke tidligere allokerte bytes, så minnebudsjettet
underrapporteres. Normaliser oldSize=0 når pointer er null og test allokasjon,
realloc-feil og peakgrense. next-wrapper (`131–134`) mangler standardens
lua_settop(state,2), slik at next(table) uten eksplisitt nil ikke har korrekt key.
Normaliser argumentstakken og test next(t), next(t,nil), pairs og ipairs på
tom/fylt tabell. Revider også callback-stackbalanse og feilopprydding ved gjentak.

### D34 – P2: byggprofil og servicegrenser må gi samme faktiske funksjonalitet

Runtime registrerer alle fem tjenester uansett manifest, bruker faste globale
minne-/runtimegrenser, og start leser ikke manifest. Backend validerer generert
kode, men firmware må håndheve den annonserte/pakkens effektive policy lokalt.
Ikke registrer annet enn tillatte API-er. Statiske sourcechecks er ikke nok.
Legacy .bin-/OTA-rutene finnes separat i Apps og POC; behold AI-Lua-kjeden
strengt adskilt, slik at ingen backendkommando kan trigge installExternalApp.
Pin produksjonsavhengigheter/revisjoner for reproduserbart ADC-/Lua-/radiobygg;
`m5stack-fire`-miljøet mangler lydflagget selv om handshake i koden lover lyd.

### D35 – P2: konfigurasjon valideres forskjellig og kan lagres delvis/feil

`saveBackendSetupFields:3813–3838` konverterer port til uint16_t **før** sjekk,
så for eksempel70000 kan bli4464. `/save` validerer ikke samme host/device/token-
grenser som `/provision`; felt lagres fortløpende og Saved-side kan vises selv
om input ikke var gyldig. Parse alle felt til en midlertidig struktur, valider
fullt heltall1–65535 før cast, ID mot protokollens mønster/lengde, host uten
URL/controltegn og tokenlengde/tegn, og lagre én konsistent konfigurasjon.
Avvis CR/LF/NUL før bruk i HTTP-headere. Vis forståelig feltfeil uten token.
Bekreft HTTP-resultatet før AP stenges; `/save` stenger i dag AP gjennom save-
rutinen før den avsluttende send(200), i motsetning til `/provision`.
Gi setup en eksplisitt inaktivitetsfrist og ikke gjør GET med token til vanlig
permanent URL eller logg. Brukerens enkle token-QR i PC-programmet skal beholdes.

### D36 – P1: automatisk strømstyring tar ikke hensyn til aktivt arbeid

`manageDisplayPower:4427–4444` bruker bare lastActivity_ fra knapper og kan
slukke/powerOff midt i opptak, AI-svar, installasjon eller kjørende Lua når
sleepOption er aktiv. Innfør tydelig aktivitet/wakelock for aktiv capture,
speaker, kritisk SD-commit og brukerens aktive samtale/app; frigjør ved slutt.
Ikke utsett eksplisitt bruker-request om Power Off uendelig, men avbryt/journalfør
ordentlig før avslutning. Test med kortest dim/off/shutdown-tider under lang
build/SD-installasjon. Skjermvåkningens første trykk skal fortsatt ikke utilsiktet
autorisere BUILD/RUN.

### D37 – P2: BLE-callback skriver String samtidig med OS-løkka

`FireBluetoothServerCallbacks:189–200` endrer bluetoothPeripheralAddress (Arduino
String) og tilhørende flagg fra BLE-callback, mens update (`778–795`) leser og
kopierer disse uten synkronisering. Under radio/capture-belastning er dette en
reell data-race-risiko, selv om ingen bestemt crash er målt i denne revisjonen.
Send en liten bounded callbackmelding til OS-task eller beskytt hele snapshotet
med riktig lås; ikke hold lås under NVS-/UI-arbeid. Ikke logg vilkårlig BLE-RX-
innhold (`206`) som kan inneholde brukerdata; bruk type/lengde/resultat ved behov.
Behold asynkron BLE-scan og test til-/frakobling samtidig med tale uten watchdog.

## Obligatorisk testmatrise før «ferdig»

Logg testet firmware-SHA, backend-SHA, modus, transport og pass/feil. Ikke logg
token/API-nøkler eller hele rå lydopptak. Bruk korte, eksplisitte testopptak når
lydkvalitet skal lyttes til, og slett dem etter kvalitetstesten.

1. **20 taleomganger:** norsk, korte/lange setninger, stille rom/normal bakgrunn,
   omtrent1/5/14s. Vis original transkripsjon og la brukeren kontrollere riktig
   hensikt. Tom/støy/for kort klipp gir retry uten mistet samtale eller appforslag.
2. **Avbryt i alle faser:** recording, upload, ASR, AI, TTS generation, PCM download,
   mid-playback, svar ferdig, proposal. B gir ny turn; C gir Klar. 20 raske
   gjentak uten busyfeil, stale lyd, nytt prosjekt eller økende heapbruk.
3. **Kun samtale:** velg ved åpning, samtal minst10 runder, avbryt, reconnect,
   bytt til utvikling og tilbake. Ingen build/install/run i chat selv om brukeren
   sier «bygg nå». Ingen skjult context fra annen app.
4. **Forståelsesfeedback:** riktig «Jeg hørte», korrekt AI-oppsummering og synlig
   BUILD gjelder samme nyeste turn. Ny tale invaliderer gammelt proposal; sent
   gammelt svar/audio_ready kan ikke gjenopprette det.
5. **Nettbrudd:** Wi-Fi av/på, PC-backend restart, brorestart, halvåpen TCP,
   tap etter listen_start, mellom listen_stop/WAV, etter WAV202, før playback
   started/finished og før/etter installkvittering. Automatisk tilbake til
   session-ready uten reboot; behold gjeldende app/modus/historikk etter kontrakt.
6. **Transport:** direct og reverse pool; ingen ledig slot, langsomme/fragmenterte
   HTTP-headere/body, delvise writes, 404/409/429/500, ugyldig/utløpt PCM, hashfeil,
   ping under fragmentert WS, header uten avslutning, maksramme og malformed JSON.
7. **Respons:** mål knapp→stopp av høyttaler/visuell respons. Mål p50/p95 for
   knappfeedback, upload, ASR, første tekst og hørbart svar. Målverdi lokalt
   knappfeedback under100ms og lydstopp under150ms under normal belastning;
   rapporter reell måling, ikke bare intensjon. Nettverks-/AI-latens kan variere.
8. **100 sykluser/soak:** opptak→svar→avbrudd/nytt opptak med BLE/Wi-Fi aktivt,
   Quick Settings og retur. Ingen watchdog, bufferlekkasje, voksende NVS-outbox
   eller tap av input. Måling av fri/largest heap og PSRAM over tid.
9. **App:** New→build-confirm→ZIP→hash/install→run-confirm→started→healthy.
   Oppdater samme app, velg eldre basis, kjør andre gang etter stop, bytt app.
   Ingen handling dupliseres av retry/snapshot; nytt appnavn/folder er kort og riktig.
10. **Rollback/recovery:** injiser write/rename/remove-feil og strømtap på hvert
    installsteg. Gammel app og appdata beholdes; rollback gjenoppretter eksakt gammel
    SHA. Ikke meld ok for bare en filsti. Kjør først etter ny eksplisitt RUN.
11. **Sletting:** slett fra App Manager og File Explorer både online/offline.
    Send fravær etter reconnect; backend PC-delete åpnes bare med ferskt inventar.
    Ingen SD/partiell scan/mange apper må markere alle som borte. Ingen auto-reinstall.
12. **Knapper/API:** forventet footer i hver tilstand, OS-langtrykk bevart,
    ingen opptaks-pip; RGB-indeks fysisk riktig, IMU-tegn/enheter, knappstatus,
    safe Lua minne-/callbackbudsjett og forventet runtime_limit.

## Leveranse fra device-agenten

- Implementer firmwareendringene og relevante enhets-/parser-/state-maskintester.
- Oppdater `M5Stack-device/BACKEND_HANDOFF.md` med faktisk feltskjema, firmware-SHA,
  målt mic-/speakerstatus, avbrudd/reconnect og appinventar/rollback-støtte.
- Legg ved testresultater per gruppe over, målte latency/jitterverdier og
  eventuelle ikke fullførte punkter. Build/flash/boot alene er ikke ende-til-ende.
- Gjør én samordnet fysisk gjennomgang mot kjørende backend til slutt. Bevar
  korte forståelige appnavn og eksplisitte BUILD/RUN. Ikke endre telefon/ruter
  eller innfør ADB/kabelkrav; nåværende reverse TCP skal fortsatt fungere.

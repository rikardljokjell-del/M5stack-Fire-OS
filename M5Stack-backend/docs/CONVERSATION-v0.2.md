# Samtale, avbrudd og gjenoppkobling

Additiv utvidelse av PROTOCOL-v0.2. Device-arbeidsordren med kildefunn,
knappematrise og fysiske tester finnes i [DEVICE_CONVERSATION_AUDIT.md](DEVICE_CONVERSATION_AUDIT.md).
Firmware er gjennomgått mot `a3f861a9e14c7de0d88841bff5323e7ce247d5a9`.
Dette dokumentet beskriver backendimplementasjonen; firmware må implementere sin del.

## Modus

`session_start.conversation_mode` er valgfritt: `chat` (Kun samtale) eller
`develop` (Lag/endre app). Ny sesjon uten feltet bruker develop. Reconnect
utelater feltet for å beholde modus. Et eksplisitt, forskjellig modusfelt ved
resume avvises; bytt med mode_select etter session_started i stedet.
Vanlig appvalg med app_select setter develop. Installering av lagret pakke
er også et eksplisitt valg av apputvikling.

Bytte i en klar samtalesesjon:

```json
{"type":"device_event","protocol_version":"0.2","event":"mode_select",
 "device_id":"m5stack-fire-01","boot_id":"boot-example","session_id":"session-example",
 "event_id":"event-mode-1","conversation_mode":"chat"}
```

Byttet avbryter tale/AI, lukker providerforbindelsen, fjerner forslag og tømmer
dialoghistorikk, slik at konteksten ikke lekker mellom modusene. Lagrede apper
og versjoner beholdes. Modusbytte avviser aktive bygg, installasjoner eller
kjørende/stoppende apper. `conversation_mode` sendes i session_started,
session_snapshot, pong og mode_select-kvittering; et `conversation_mode`-event
varsler også UI. Chat har ingen byggeforslag og backend avviser BUILD/RUN.

## En taleomgang

1. Vent på session_started og gyldig session_id. Klar betyr idle, aldri et
   påstått aktivt mikrofonopptak.
2. Ved B: stans først lokal avspilling og tidligere nedlasting/opptak.
   Send listen_start med ny unik turn_id og vis umiddelbart opptaksfeedback.
3. Ved neste B eller automatisk maksimum: stopp capture, send listen_stop
   med samme turn_id, last opp WAV til /sessions/{id}/audio/{turn_id}.
4. Backend validerer riktig session/turn, WAV og omfang. WAV må være
   PCM16 mono 16000Hz, 0,1–15s, med faktisk antall sammenhengende samples.
5. Backend sender transcript med turn_id og nøyaktig gjenkjent tekst. Vis
   «Jeg hørte: …», slik at brukeren ser hva AI bygger videre på.
6. assistant_message og eventuelt build_proposal har turn_id. Forslaget
   oppsummerer hensikt, innstillinger og kontroller; det er ingen igangsatt bygging.
7. audio_ready kommer når en hel, størrelsesbegrenset PCM-fil er klar. Filen
   er scoped til device/session/turn, har kort TTL og SHA256. Download/avspilling
   må være asynkron og avbrytbar på device. Returner playback-kvitteringer.
8. B kan legge til eller rette krav. A BUILD må bekrefte akkurat det synlige
   proposal_id; A RUN må senere bekrefte akkurat den testede pakken.

Denne leveransen beholder WAV/HTTP og hel PCM-fil. Den er ikke en ny streaming-
audio-protokoll; hørbart svar kommer etter full TTS-generering og nedlasting.
Korte svar og mindre dialogkontekst reduserer arbeid, men internett-/AI-latens
må måles fysisk. Backend endrer ikke modellvalget som er lagret i Windows-appen.

## Avbrytelse og gamle meldinger

listen_start med ny turn_id avbryter automatisk forrige ASR/dialog/TTS, lukker
dialogforbindelsen og frigjør gamle HTTP-opplastinger fra reverse-poolen. Den
avbrutte WAV/PCM-filen slettes, og gamle forslag invalideres. Backend sender
turn_cancelled med den gamle turn_id. Device må avbryte lokalt straks knappen
trykkes; ikke vent på nettverkskvitteringen for å stoppe høyttaleren.

C kan sende cancel_turn, gjerne med den aktuelle turn_id. Dersom denne ID-en
allerede er avbrutt, er handlingen ignorert. Et gammelt avbrudd kan derfor
ikke stoppe ny tale. Backend beholder en bounded liste over de siste 32
avbrutte turn-ID-ene i en aktiv sesjon. Ikke gjenbruk en turn_id.

Sene listen_stop og playback-kvitteringer for disse ID-ene kvitteres ignored.
Sene HTTP-opplastinger får cancelled og transkriberes ikke. Gjentatt listen_start
for det aktive opptaket og gjentatt listen_stop kvitteres uten å starte nye ting.
Event-idempotens gjelder fortsatt. Ukjente IDs/feil identitet eller feil hash
avvises; disse kontrollene svekkes ikke for å skjule firmwarefeil.

## Mislykket opptak

Tom transkripsjon eller manglende signal starter ingen AI-bestilling. Historikken
beholdes, activity blir idle og native state blir idle. Backend sender:

```json
{"type":"input_retry","code":"no_speech","turn_id":"turn-example",
 "message":"Jeg fikk ikke tak i ordene. Trykk B og prøv igjen nær mikrofonen. Samtalen er beholdt.",
 "recoverable":true,"action":"listen_start"}
```

En legacy error med samme kode/tekst sendes for dagens firmware. Ny firmware
må vise én retry-status, ikke to dialoger. Manglende WAV etter 25s gir tilsvarende
audio_upload_missing. Korrupte pakker, auth- og scope-feil er fortsatt faktiske feil.
Tekniske målinger av sampleantall, RMS, gain, klipping og forhold mellom lyd og
eventtid vises i status; rå lyd logges ikke. Rå WAV slettes etter behandling.
Tidsavvik brukes som diagnose, aldri som grunnlag for å gjette tale eller endre
samplerate. Backend kan ikke rekonstruere samples firmware aldri tok opp.

## Gjenoppkobling

Samme autentiserte device, boot, capabilities og prosjekt kan erstatte en gammel
WebSocket selv om dens disconnect ikke har nådd serveren. Gammel socket lukkes,
kan ikke sende nye handlinger og kan ikke gjøre den nye forbindelsen offline.
Start/stop/detach serialiseres per device. HTTP kan ikke overta en aktiv device-WS.
Gjentatt identisk session_start etter mistet session_started kobles til den
opprinnelige sesjonen og får ferske snapshots; prosjektet opprettes ikke igjen.

Et virkelig nettbrudd avbryter ufullført tale, beholder samtalehistorikken og
lagrede pakker og lukker providerforbindelsen. Etter backendrestart gjenopptas
ingen fiktiv mikrofon eller avspilling. Firmware må stanse lokal capture/playback,
vente på session_started, lese snapshot og bruke ny turn_id. Ikke replay
listen_start/listen_stop som var knyttet til en avbrutt fysisk capture.

Ingen ny build/install/run autoriseres av reconnect. Utløpte kommandoreservasjoner
frigjøres uten å påstå at en fysisk handling lyktes eller ble stoppet. Det kreves
fortsatt korrelerte receipts og ferskt SD-inventar. En ny boot er en ny identitet
for fysisk arbeid; tidligere kommandoer må ikke kjøres på nytt.

## Windows-appen

Aktivitet har Kun samtale, Lag/endre app og Avbryt AI-svar. Lokal admin-endpoint
POST /desktop/sessions/{id}/conversation tar enten {"conversation_mode":"chat"}
eller {"action":"cancel"}; samme scoped dispatch benyttes som for device.
Original transkripsjon og lyd-/opptakstid vises før brukeren bekrefter bygging.
Appen kan klargjøre modusen nå; FIREs egen startmeny og knappeavbrudd krever
device-arbeidsordren. Ingen API-/adminnøkler sendes til FIRE.

## Verifisering og gjenværende grenser

Samlet pytest: **193 bestått**, én eksisterende Starlette/httpx-avviklingsadvarsel.
pip check: ingen brutte avhengigheter.
Regresjoner dekker ASR/dialog/TTS-avbrudd, samtidige/stagnerte gamle opplastinger,
gammel playback/stop, tomt/stille signal, chat selv ved feilaktig providerplan,
gjenoppkobling, tapt startmelding, gammel socket-detach, samtidige starter,
stop/reopen og restarts. Mock-/emulator- og opprinnelige lifecycle-regresjoner
beholdes. check_voice.py --live har også passert med ekte OpenAI: AI-generert
norsk testtale → korrekt tekst → talesvar → validert Lysblink-pakke. Det er ikke
en fysisk mikrofontest.

37 firmwarefunn og den fysiske akseptansematrisen er fortsatt arbeid for
device-agenten. Ingen fysisk knappelatens, støyrobusthet, sømløs avbrytelse eller
feilfri fullflyt kan rapporteres verifisert før disse er implementert og målt.
Behold workspace-kvoten: mange historiske filer øker fortsatt filskanningstiden.
Unødvendig dobbeltlagring per state/activity er fjernet, men kvote-/fsync-
kontroll er ikke deaktivert for ytelse. Hel PCM-transport og historisk filvekst
er dokumenterte ytelsesgrenser, ikke løfter om konstant svartid.

Providerreferanser: [OpenAI Realtime](https://developers.openai.com/api/docs/guides/realtime-conversations),
[OpenAI talegjenkjenning](https://developers.openai.com/api/docs/guides/speech-to-text).

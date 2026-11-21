# Tale til lagret FIRE-app – status 22. november 2026

Siste oppdatering: **158 tester består**. Norsk OpenAI-lydsvar ble lastet ned
og spilt av på ekte FIRE, og brukeren bekreftet at det var forståelig.
WAV fra mikrofonen når nå backend, men måling viser bare ca. 20 % av nødvendig
samplemengde i forhold til opptakstiden. Det gir tom transkripsjon. Se
[VOICE_HANDOFF.md](VOICE_HANDOFF.md) for tallene og konkret device-arbeid.
Full fysisk tale → app er fortsatt ikke verifisert.
Etter den nye DMA-rettingen 2ac854f rapporterte brukeren «Microphone capture
unavailable», som oppstår i firmware før opplasting. Device-agenten er varslet.

Backend følger `docs/NEXT_STEPS_REVERSE_TCP.md` og
`M5Stack-device/BACKEND_HANDOFF.md`, med kildegjennomgang til GitHub main `2d47b0a`.
Device-kilde er bare lest; ingen device-filer er endret, bygget eller flashet.

## Målet og brukerflyten

1. FIRE er tilkoblet; API-nøkkelen finnes bare i Windows-programmet.
2. Trykk B på FIRE, beskriv appen og avslutt opptaket. Maksimum er fem
   sekunder i den opprinnelig testede kilden; cd67c07 utvider til 15 sekunder,
   som også er backendkontraktens grense. Sammenhengende capture må fortsatt rettes.
3. Backend transkriberer opptaket og AI lager et kort, konkret forslag.
   Tekst under **Aktivitet** kan brukes for å teste resten separat fra mikrofonen.
4. Trykk **A BUILD** på FIRE eller **Bekreft bygging** i Windows.
5. AI genererer faktisk Lua-kode innenfor enhetens annonserte tjenester og
   grenser. Backend validerer og tester koden, med inntil tre feilrettinger.
6. FIRE henter ZIP, validerer størrelse/SHA256/manifest og lagrer
   `/apps/<app-ID>/manifest.json`, `main.lua`, `assets/` og `appdata/` på SD.
7. Installasjonskvitteringen gjør **A RUN / Bekreft kjøring** tilgjengelig.
   Kjøring starter bare etter denne nye, eksplisitte bekreftelsen.
8. `app_started` og `app_healthy` bekrefter start og de første rammene.
   Lagret app finnes fortsatt på SD etter at samtalen lukkes; den kan startes
   fra FIREs filutforsker. **Apper** i Windows viser pakker og mottatte kvitteringer.

Dette gjelder begrensede Lua-apper for display/buttons/rgb/imu/time.
Gjeldende kontrakt tillater høyst ti sekunder per appstart og gir ingen Lua-
tilgang til nettverk, filer eller mikrofon. Modellen må forklare ønsker utenfor
denne profilen; den kan ikke love enhver tenkelig app. Samtalelyd er separat.
Enheten annonserer audio_input=true og audio_output=false; svar vises som tekst.

## Ferdigstilt og testet på backend

- Fire autentiserte reverse-strømmer, WebSocket, separat ZIP/WAV og reconnect.
- Korte norske forslag med fornuftige standardvalg, uten unødvendige designspørsmål.
- HTTP-kompatibilitet med nåværende FIRE: `Content-Length` sendes med den
  skrivemåten firmware krever. H11 brukes i begge startmåter; faktisk HTTP
  gjennom reverse-broen testes, også Range/206. ZIP-formatet endres ikke.
- Lydopplasting håndterer at kontroll- og HTTP-strømmene kan komme i ulik
  rekkefølge. Manglende WAV feiler etter 25 sekunder; brutt/ugyldig opplasting
  gir synlig feil og tillater nytt opptak. Ingen evig PROCESSING ved manglende upload.
- Windows **Aktivitet** viser neste handling, fremdrift og siste feil.
  **Apper** viser navn, versjon, SD-mappe og kvittert installasjon/helse/kjøring.
  Den utgir seg ikke for å lese SD-kortet eller bekrefte skjerminnhold.
- **Apper → Installer valgt app på FIRE** gjenbruker en testet pakke, også
  etter reboot. Ingen nye AI-kall eller implisitt kjøring; eier, ZIP og den
  nye sesjonens kapabiliteter valideres før prosjektet byttes.
- Fast navneregel: lesbart formålsnavn på høyst 32 tegn; nye appmapper har
  høyst 24 små ASCII-tegn, for eksempel `/apps/sprettsirkel/`.
  Nedlastingsnavn: `sprettsirkel-v0.1.1.zip`. Samme app beholder mappen ved
  oppdatering. To forskjellige apper får eventuelt -2, -3. Eksisterende gamle
  SD-stier flyttes ikke i en vanlig oppdatering; interne prosjekt-/pakke-ID-er
  brukes fortsatt til autorisasjon og kvitteringer.
- **158 pytest-tester består**; `pip check` uten feil. Mock- og emulatorflyt
  beholdes, inkludert ZIP/WAV større enn én nettverksbuffer og binærintegritet.

## Ekte OpenAI – observert

`python scripts/check_pipeline.py --live` brukte Windows-profilens lagrede
modeller og nøkkel: Realtime-dialog → konkret forslag → Responses-generert
«Sprettsirkel» → begrenset Lua-simulering → SHA256-kontrollert ZIP på 2380 byte.
Manifestet holdt 131072 byte / 10000 ms og krevde bare display/buttons.
Ingen fysisk installasjons- eller kjørekvittering ble fabrikkert.
Testen brukte tekst; norsk talegjenkjenning fra ekte mikrofon er ikke verifisert.

Testdata ligger lokalt under `%LOCALAPPDATA%\FIRE Backend\verification\`.
Kjør skriptet uten `--live` for en helt lokal mock-variant. Valgfri `--wav`
tester en reell norsk PCM16 mono 16-kHz fil. Testen endrer ikke den kjørende
backendprofilen eller FIRE. API-feil gjør testen mislykket, aldri til mock.

## Fysisk status og gjenstående arbeid

FIRE har tidligere autentisert alle fire kanaler og opprettet ekte
`session_start` med baseline-kapabiliteter. Opptaksforsøk sendte listen_start
og listen_stop med rundt 50–60 ms mellomrom; ingen WAV nådde backend.
Det viser at opptaksflyten ble avbrutt tidlig, men beviser ikke alene årsaken.
Ved siste kontroll etter backendoppdateringen svarte ikke FIRE på
`10.5.1.163:8766`; programmet kjører og prøver igjen automatisk.

En ny fysisk test etter oppdateringen opprettet forslag og mottok eksplisitte
BUILD/RUN-hendelser fra FIRE. Ekte OpenAI genererte «Sprettende sirkel», ZIP på
1949 byte, pakke `build-9c2221532bd94cf684a8`, app-ID `app-6fd647e1057044858557`.
FIRE kvitterte `device_install_result=ok` med korrekt SHA256. RUN svarte deretter
`app_failed`, error_code=not_installed, «Package is not installed on FIRE».
Ingen app_started/app_healthy ble mottatt fra denne starten; current ble ikke satt.
Brukeren startet samme app manuelt fra Apps og rapporterte at den kjørte frem til
«Lua app runtime limit exceeded». Dette bekrefter lagring og manuell start,
men ikke den automatiserte RUN-flyten eller riktig tidsavslutning.

Ny device-kilde `011e8f6` retter ZIP-header/CRC og Lua-stack, og `2d47b0a` legger
til stop/rollback. NVS-nøklene er forkortet i 6d97989 og kildeimplementasjon for
ADC-opptak/PCM-playback er lagt til. WAV når nå backend, men opptakets kontinuitet
er fortsatt blokkeringen. Historiske observasjoner over gjelder de tidligere testene.
Se [presis handoff til device-agenten](DEVICE_E2E_ACTIONS.md).
Full fysisk tale → installasjon → fungerende app er derfor **ikke ferdig
verifisert**. Fysisk markering kan ikke utledes fra emulatorens kvitteringer.
Ingen kode setter physical_verified=true på grunnlag av disse PC-testene.

Appvalg og kontrollert sletting er implementert etter APP_LIFECYCLE.md, med
11 nye kontroller for eier, valgt basisversjon, stigende versjonsnummer,
sletting under bygg, restart/reconnect, fersk SD-rapport, ugyldig inventar og
bakoverkompatibel event-deduplisering. Fem nye lydkontroller dekker idle før
opptak, DC/gain, fragmenterte PCM-samples og feil ved manglende capture-samples.
Device må sende den nye slettings-/inventarkontrakten før Windows kan aktivere
backend-sletting; manglende støtte eller offline tilstand åpner aldri sperren.

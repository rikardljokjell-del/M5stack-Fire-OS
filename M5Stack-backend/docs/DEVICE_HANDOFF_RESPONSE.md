# Oppfølging av BACKEND_HANDOFF.md

Backendgjennomgang 2026-11-21 av GitHub main på
`069ea09e5ea88ddc5fab65c81fa73611ea94a111`. Lest: handoff, platformio.ini,
README, fire_backend_client.*, fire_lua_runtime.*, fire_lua_package_manager.*
og relevante AI Developer-/maskinvareadaptere i fire_os.*.
Ingen enhetsfiler er endret, bygget eller flashet.

## Tillegg ved Windows-leveransen

Nyeste gjennomgåtte GitHub-kilde er nå
`df06c656b1b56de4df6383baa060bc1bb69c4729`. Handoffen og diffen i
fire_backend_client.*, fire_audio_capture.*, fire_os.* og platformio.ini er lest.
Kilden har nå avgrenset WAV/HTTP-opplasting og direkte I2S-capture. Handshake
annonserer audio_input=true, audio_output=false. Dette overstyrer den eldre
lydbeskrivelsen i baselinepunktene nedenfor; fysisk integrasjon er fortsatt ikke
bekreftet. Backendens uavhengige lydflagg støtter begge profiler uten endret
protokoll. Windows-programmets lydtransport er aktivert som standard, mens
sesjonens input/output fortsatt avgjør hva som faktisk forsøkes.

Ny input-only-test dekker listen_start/stop, WAV-opplasting, mock-transkripsjon
og forslag uten talesvar eller automatisk bygg. Dialog/modell er ikke fysisk testet.
I2S-adapteren returnerer false ved cfg.use_adc; bekreft at faktisk FIRE-mic-konfig
passer adapteren under hardwaretesten. Dette er et kontrollpunkt fra kildelesing,
ikke en konstatert fysisk feil. Kildeimplementasjon alene gir physical_verified=false.

Punktene under gjelder gjennomgangen av 069ea09e; lydpunkt 7 har nå delvis
kildeimplementasjon som beskrevet over. De øvrige kildefunnene er ikke endret i
de to nye lydcommittene. Enhetskode er fortsatt urørt av backendarbeidet.

## Backend følger nå enheten

- Handshake: fire-lua-0.1, display/buttons/rgb/imu/time, 131072 byte,
  10000 ms, audio_input=false, audio_output=false, fire-os-0.2.
- Ingen lyd er gyldig oppstart. Tydelig tekststatus sendes i capability_status
  og assistant_message som dagens UI allerede leser. Mikrofonforsøk avvises
  uten å slette gjeldende forslag; HTTP-opplasting avvises før lyd leses.
  Input/output styres uavhengig av enhetsflagg OG backendinnstilling.
- Kontekst og generering bruker faktisk sesjonsprofil. PC-tjenester gir ingen
  ekstra enhetsrettigheter. Budsjettene videreføres til validering og manifest.
- Offline gjenoppkobling med samme boot/profil gjenopptar samtalen også uten
  resume_session_id, slik dagens native klient sender session_start.
  Aktiv tilkobling overtas ikke; nye boot-ID-er arver ingen kjøretillatelse.
- Mislykket installasjon kan rapportere tom/manglende/observert SHA256.
  Vellykket installasjon krever fortsatt nøyaktig forventet hash og operasjons-ID.
- Kontekst beskriver nå eksisterende native runtime, stabile default_16MB.csv,
  Lua 32-bit-tall, heltallsargumenter, konturer, uniform RGB-strip, native uptime
  og pressed-callback. PC-simulator krever også heltall, gir syntetisk uptime
  fra 60000 ms og sender bare pressed-callback; den beviser ingen fysisk atferd.
- Mock-RGB-eksemplet bruker samme farge på hele stripen. Alle PC-/mock-resultater
  og kapabilitetsoversikter merkes physical_verified=false.

## Konkrete funn for enhetsarbeidet

Funnene er fra kildelesing og er ikke observert på fysisk FIRE i dette arbeidet.
De bør håndteres i enhetsmappen av firmwarearbeidet før full fysisk godkjenning.

1. **Lua update-stakken:** update() legger dt på stakken før callVoid() legger
   funksjonen øverst. lua_pcall(...,1,...) forventer funksjon FØR argumentet;
   dagens rekkefølge ser ut til å forsøke å kalle tallet. Flytt funksjonen under
   argumentene eller legg funksjon og argument i korrekt rekkefølge. Test init,
   første update, app_started/app_healthy og feilstopp fysisk.
2. **Initialisering og budsjetter:** instruksjoner/frameStarted nullstilles i
   update, men ikke tilsvarende før toppnivå/init/button. Sett callback-budsjett
   før hver beskyttede kjøring. Allokatoren teller bruk uten full hard cap;
   manifestets max_memory og totale max_runtime_ms må håndheves på enheten.
   Backendens PC-grenser erstatter ikke dette. Native 32-bit Lua og desktop Lua
   er ikke numerisk identiske.
3. **ZIP-header:** extractStoredZip() hopper over fire byte DOS-tid/dato etter
   method, men leser deretter CRC32 som compressed size. ZIP-local-header har
   ytterligere fire CRC32-byte før compressed/uncompressed size. Backend lager
   standard ZIP_STORED; korriger parserens offset og valider CRC/listen/manifest
   uten å endre backend til et feilformatert arkiv.
4. **HTTP-header:** nedlastingen søker case-sensitivt etter Content-Length:.
   Standard HTTP tillater små bokstaver; serveren kan sende content-length.
   Normaliser navn i klienten. Test faktisk nedlasting, avbrudd og retry.
5. **SD-aktivering:** rmdir(finalPath) fjerner normalt ikke en ikke-tom eksisterende
   appmappe. Bruk sikker versjonert staging/aktivering med bevaring av appdata og
   current/previous/backup. Test andre installasjon og strømtap, ikke bare ny app.
6. **Resterende protokoll:** nåværende UI håndterer ikke stop_request,
   rollback_request eller audio_ready. Fullfør korrelerte stopp-/rollback-kvitteringer,
   klokke/utløp og varig deduplisering av run_id før kommando utføres. Ikke omgå
   backendens eksplisitte build/run-bekreftelser eller kvitteringskontroller.
7. **Lyd og UI:** B sender listen_start/stop selv om audio_input=false; opptak,
   WAV-opplasting og fysisk PCM-avspilling er ikke implementert i gjennomgått
   flyt. Vis capability_status og sperr lydknappen når funksjonen mangler.
   Dagens assistant_message setter lokalt TALK-ansikt også for tekst; knytt dette
   til faktisk avspilling i stedet. Sett hvert lydflagg true først etter fysisk test.
8. **Adapterbegrensninger:** drawCircle/drawRect er konturer; RGB-setter maler
   hele stripen selv om per-pixel-data lagres; on_button får bare pressed;
   time.millis er OS-uptime. Backend lover nå bare dette delsettet. Utvid kontekst
   og testene når firmware faktisk utvider og fysisk verifiserer atferden.

## Statusgrenser

Backend registrerer installert/startet/current bare fra korrelerte kvitteringer;
current krever app_started fulgt av app_healthy. En emulator med enhetstoken kan
også sende disse: registrert kvittering er ikke uavhengig fysisk verifisering.
physical_verified=false beholdes til en faktisk fysisk testrapport foreligger.
Ekte OpenAI er fortsatt ikke testet uten lokal API-nøkkel. Lydflagg, simulator og
kildelesing skal aldri brukes som erstatning for faktiske hardwaretester.

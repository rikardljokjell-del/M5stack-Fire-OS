# Til device-agenten: nødvendige rettinger før fysisk ende-til-ende-test

Nyere oppfølging: [VOICE_HANDOFF.md](VOICE_HANDOFF.md). NVS-nøklene er nå
forkortet i 6d97989, og et norsk talesvar er fysisk bekreftet. Målt
mikrofonopptak mangler fortsatt ca. 80 % av samples over opptakstiden.
Punktene under beskriver eldre funn og må leses sammen med den nye oppfølgingen.

Oppdatert etter GitHub main `2d47b0a` og fysisk installasjons-/kjøretest.
Backend-agenten endrer kun `M5Stack-backend/`. Denne filen er en handoff,
ikke en påstand om utførte firmwarerettelser. Transport/protokoll 0.2 beholdes.

## 1. ZIP og Lua – rettet i ny kilde, verifiser regresjon

Tidligere `FireLuaPackageManager::extractStoredZip` leste lokalheaderen feil. Dette er rettet med CRC32-lesing i `011e8f6`. Den gamle feilen var: Etter
signature/version/flags/method hopper den over fire byte for tid/dato og leser
deretter CRC32 som `compressed`, compressed-size som `uncompressed`, og
uncompressed-size som name/extra-length. CRC32-feltet på fire byte er ikke hoppet
over/lest. Les standardens komplette 30-byte lokalheader i korrekt rekkefølge,
valider CRC32, metoder, størrelser, grenser, filnavn og eksakt filsett.
Ikke be backend generere en ugyldig ZIP for å omgå parserfeilen.

Den tidligere FIRE-parseren søkte bokstavelig `Content-Length:`. Backend har
en testet kompatibilitetstilpasning og bruker H11. I `011e8f6` er også firmware-
parseren gjort case-insensitive, slik normal HTTP krever.

## 2. Lua-update – kildefeil rettet i 011e8f6

Tidligere `FireLuaRuntime::update` pushet `dt_ms` før `callVoid("update", 1)`.
`callVoid` pusher så funksjonen. Lua krever funksjon under argumentene, men
stacken er nå `[dt_ms, update]`; `lua_pcall(...,1,...)` forsøker å kalle tallet.
Dette er rettet med lua_insert før pcall i `011e8f6`. Test init, flere update-kall og on_button på virkelig
Lua 5.4 med samme stackrekkefølge. En backend-simulering beviser ikke denne delen.

## 3. Opptak stopper uten WAV

Backend har sett `listen_start` og `listen_stop` med 50–60 ms mellomrom,
men ingen WAV-opplasting. `updateAiAudio` kaller også finishAiRecording ved
capture-feil og sender ingen WAV i den grenen. Logg en kort, hemmelighetsfri
feilkode lokalt så capture-feil kan skilles fra upload-feil.

`fireRecordMic` returnerer false ved `cfg.use_adc` eller manglende I2S-pinner.
Kontroller den FAKTISKE FIRE-mikrofonkonfigurasjonen (GPIO34/ADC kontra digital
I2S) og driverkonflikt med M5Unified. Dette er en kildebasert mistanke, ikke en
måling av ADC-konfigurasjonen. Bruk fungerende board-tilpasset capture, mål
opptaksvarighet/sampleantall og test ekte tale. Ikke annonser lydutgang.

Send listen_stop før WAV POST; backend tåler nå to sekunders kryssende
HTTP/WS-rekkefølge og varsler etter 25 sekunder dersom WAV aldri kommer.
Sørg for at B kan starte et nytt opptak etter avklaring/feil, og at en
workflowtilstand «listening» ikke forveksles med et faktisk pågående opptak.

## 4. AKTIV BLOKKERING: start fra AI Developer / NVS-nøkler

Fysisk test nå: ekte AI-generert `build-9c2221532bd94cf684a8` ble lastet ned og
kvittert installert. RUN feilet med `not_installed` / «Package is not installed on FIRE».
Brukeren kunne deretter starte den samme appen manuelt fra Apps. Dette skiller
vellykket installasjon fra feilen i AI Developer-oppstart.

I packageResult lagres `lua_path_<package_id>` i Preferences. Vanlige genererte
package-ID-er er lengre enn ESP32 NVS-nøkler tillater. Det samme gjelder `lua_hash_<package_id>` og `run_consumed_<run_id>` i nyeste
kilde. For denne testen er lua_path-nøkkelen 35 tegn; NVS tillater 15.
Kontroller returverdier fra putString og getString; bruk korte nøkler/SD-indeks med full ID i verdien. Run må slå
opp den faktisk installerte pakken etter reboot også, uten mistet sti.

I `011e8f6` er den gamle `SD.rmdir(finalPath)`-aktiveringen erstattet med previous/staging og appdata-flytting.
Implementer staging/atomisk aktivering og fungerende versjonsbevaring uten
å slette appdata eller gammel fungerende versjon ved feil/strømbrudd.
Bevar `/apps/<app-ID>/` og filutforsker-start etter at AI Developer lukkes.

Brukeren observerte også «Lua app runtime limit exceeded» etter en stund ved
manuell start. Ti sekunder er gjeldende grense, men dette skal være en normal
stopp med reason=runtime_limit og tydelig norsk UI, ikke app_failed.

`2d47b0a` legger til stop/rollback. Dens appStopped sender reason=stopped eller
already_stopped, som ikke er gyldige verdier i protokoll 0.2. Ved stop_id: bruk
reason=requested eller utelat reason. Naturlig stopp bruker completed/user_exit/runtime_limit.
Rollback må faktisk gjenopprette riktig versjon, ikke bare bekrefte at en sti finnes.

Send app_started etter vellykket init, app_healthy etter faktisk vellykket
update, og korrelert app_stopped ved home/back/runtime-limit. Implementer
stop/rollback-kommandoer og håndhev manifestets runtime/minnegrenser.
Backend skal fortsatt bare oppdatere installert/current etter riktige kvitteringer.

## Konkret testrekkefølge

1. Rett ZIP og Lua-stack først. `python scripts/check_pipeline.py` fra
   backendmappen lager en kjent, validert mock-pakke uten OpenAI-kall. ZIP og
   kode beholdes under Windows-brukerens FIRE Backend/verification-mappe.
2. Åpne AI Developer. Send en enkel sirkelbestilling fra Windows Aktivitet.
   A BUILD → separat HTTP-download → /apps-filer → installasjonskvittering.
3. A RUN → app_started → flere animerte frames → app_healthy. Kontroller
   faktisk skjerm, Home/Back, gjenåpning fra filutforsker og ny versjon av samme app.
4. Rett mikrofon og gjenta med ekte tale, WAV, transkripsjon og AI-generert kode.
5. Test brudd under WAV/ZIP, restart, feil hash, gammel/duplikat kommando og rollback.

Backendens nye **Apper → Installer valgt app på FIRE** kan sende den allerede
testede pakken til en ny boot/sesjon uten AI-generering. Ikke forutsett at
manifest.id=project_id: nye apper får korte, stabile mappenavn som `sprettsirkel`
(<=24 tegn), mens project_id og package_id er interne, uendrede kvitterings-ID-er.
Runtimefilen heter fortsatt main.lua og ZIP følger samme fire filnavn som før.

Ingen fullført fysisk ende-til-ende-status før disse observasjonene foreligger.

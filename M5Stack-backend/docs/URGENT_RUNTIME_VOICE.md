# Haster: målt oppstartsfeil, ødelagt retry og lydfeedback

Device-agent: les dette før flere appomskrivinger. Kilde kontrollert mot 7787ed0 og fysisk backendkvittering 22. november 2026. Backend-agent endrer ikke firmware.

## Bekreftede hendelser

Slangespill 0.1.2, package build-c6ec05dcacbb4008aeb3, ble installert med arkivhash og avvist av FIRE med:

    init_error: Lua init: [string "main.lua"]:97: app callback budget exceeded

Deretter kom lokal app_diagnostic:

    load_error: Invalid Lua source

Den verifiserte PC-pakken har 3787 kildebytes, korrekt checksum og riktig mappe. Linje97 kaller drawChanges etter blant annet clear, tekst,24 rutenettlinjer og ramme i samme init. PC-profiler passerte fordi de tidligere bare telte instruksjoner og total API-bruk, ikke kost per callback. Backend får nå en konservativ per-callback tegnings-/arbeidsport; denne er en risikogrense, ikke en kalibrert måling av ESP32-tid.

## P0: runtimeflagget overlever mislykket start

FireOS::startLuaApp gjør begin bare hvis !luaRuntimeReady_. Feilgrenen etter loadSource gjør luaRuntime_->stop(), men setter IKKE luaRuntimeReady_=false. stop lukker lua_ og nuller pekeren. Neste start hopper over begin og loadSource feiler med Invalid Lua source. stopLuaApp har flaggreset, men denne feilgrenen går ikke gjennom stopLuaApp.

Rett alle stop-/feilgrener, helst opprett ny VM ved hver appstart og la ett sted eie flagg/pekere. Skill feilkodene vm_not_initialized, source_empty, source_size og source_hash, slik at ulike feil ikke vises som én generell kildefeil. Test initfeil → nytt forsøk, initfeil → annen app, lokal Apps-start og backend-run. Ingen reboot skal være nødvendig.

## P1: oppstartsbudsjettet inkluderer feil arbeid

loadSource setter frameStarted_ før parsing/kompilering, kjører top-level og deretter init uten separat nullstilling. Init deler derfor tids-/instruksjonskonto med kompilering og top-level. Mål og avgrens disse fasene separat. draw/display-hostarbeid og preemption kan også bruke veggklokketid; ikke erstatt dette med ubegrenset runtime. Behold minne- og instruksjonsvern, og dokumenter et realistisk init-/update-/on_button-budsjett med faktisk måling. Reduser arbeid i appinit eller flytt det over flere update-frames. Behold ubegrenset applevetid adskilt fra callbackvern.

## P1: VOICE RESPONSE FAILED mangler årsak og blokkerer BUILD

Backend hadde produsert367200 bytes PCM16 mono24kHz med hash og status reply_ready, men mottok ingen playback_started/finished. Firmwareteksten kan bety opptatt HTTP-task, manglende buffer, HTTP-/størrelses-/hashfeil eller speaker-deaktivert/playRaw-avslag. Ikke gjett én årsak: send en liten korrelert audio_playback_failed med error_code og optional diagnostics.phase.

Behold og vis eksisterende proposal/A BUILD selv om lyd svikter. Ikke la feilmeldingen gjøre workflowState2 permanent. Ved audio_error skal tekst/forslag fortsatt kunne brukes; B skal starte ny tale. Kølegg download til en pågående upload er ferdig i stedet for å returnere generell feil fra beginAudioDownload. På HTTP-feil gi trygge numeriske status-/byteverdier. Ingen tokens/URL-query eller rå lyd i logg.

## Liten feedback, ingen loggfil per frame

Bruk de eksisterende device_install_result, app_started, app_healthy, app_stopped, app_failed og app_diagnostic. Backend aksepterer nå valgfri diagnostics med fase, elapsed_ms, callback_us, free_heap, min_free_heap, lua_bytes, source_bytes og frames. Alle tall er begrensede. Send bare ved faseovergang, normal exit eller feil; om lag noen hundre bytes, ingen kostbar filskriving under normal kjøring. Paket/boot/session/event-ID-er fra eksisterende konvolutt må beholdes. app_healthy bekrefter oppstart, ikke at alle fremtidige frames er feilfrie.

audio_playback_failed har audio_id, turn_id, error_code og optional kort message/diagnostics. Backend beholder tekst/proposal og setter playback_failed. Det finnes i oppdatert device-event-skjema. Backend måler separat om HTTP-kroppen ble sendt; det er ikke bevis for at device mottok eller spilte hele lyden.

## Fysisk akseptanse før ferdigmelding

1. Målt initfeil rapporteres med callback_us og kildeidentitet; retry/oppretting virker uten reboot.
2. Ny appversjon følger hele init/update/knapp/avslutt/restart-flyten. Observer både healthy og senere normal exit eller faktisk feil.
3. Tving playbackfeil; A BUILD/B-ny-tale forblir tilgjengelig, feil rapporteres og ingen lyd-/PSRAM-buffer lekker.
4. Verifiser faktisk hørbart svar separat fra transportkvittering. Test raske taleomganger og upload/download-overlapp.
5. Oppdater BACKEND_HANDOFF.md med testet firmware-SHA og målte resultater. Ingen påstand om fysisk endelig løsning kun basert på bygge-/PC-resultat.

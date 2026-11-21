# Tale – fysisk status og neste device-retting, 22. november 2026

Gjennomgått device-commit: `6d979894d6e04d7f46e538f6b5ef2a7188017600`.
Backend-agenten endrer ingen device-filer og bygger/flasher ikke firmware.

## Bekreftet fungerende: talesvar

Backend brukte den lagrede OpenAI-profilen til et norsk svar om en RGB-blinker.
Ekte FIRE lastet ned 415200 byte PCM16 mono 24000 Hz gjennom reverse HTTP og
sendte både audio_playback_started og audio_playback_finished. Brukeren bekreftet
at svaret var forståelig. Dette verifiserer denne konkrete høyttalerflyten.
Nå annonserer enheten audio_input=true og audio_output=true. Eldre profiler
uten lyd støttes fortsatt, og backend overstyrer aldri flaggene.

En separat PC-test med ekte OpenAI genererte norsk testtale med
«Lag en app som blinker med RGB-lys», transkriberte den korrekt, laget et norsk
lydsvar og genererte/validerte `/apps/rgb-blink/` innenfor buttons/rgb-profilen. Testen finnes som
`python scripts/check_voice.py --live`; input der er eksplisitt AI-generert,
ikke en påstått fysisk mikrofontest. Den endrer ikke den kjørende FIRE-sesjonen.

## Målt blokkering: sammenhengende mikrofonopptak

WAV-opplasting når nå backend og passer format/størrelsesvalideringen.
Men OpenAI finner ingen forståelig tale. Tidsmålinger fra de faktiske
listen_start/listen_stop-eventene sammenholdt med antall WAV-samples:

| Opptakstid på veggklokken | Lydlengde ved oppgitt 16000 Hz | Andel samples |
| --- | --- | --- |
| 6,749 s | 1,376 s | 20,4 % |
| 6,799 s | 1,392 s | 20,5 % |
| 7,832 s | 1,600 s | 20,4 % |
| 1,086 s | 0,224 s | 20,6 % |

Det første instrumenterte opptaket hadde DC-offset 9, AC-peak 28311,
AC-RMS 1312,7 og ingen klipping. Volum/DC er derfor ikke den tydeligste
forklaringen på akkurat dette opptaket. Ingen rå lyd lagres i logger.

Kildelesing: `fireRecordMic` sampler bare 256 samples per kall i
`FireOS::updateAiAudio`, som kjøres én gang per OS-løkke. Tidsstyringen
starter på nytt for hver chunk; rendering, Wi-Fi, BLE og øvrig arbeid skjer
mellom chunkene. Tallene og koden peker sterkt mot at store deler av
mikrofonsignalet aldri blir samplet. Dette kan ikke backend rekonstruere ved
å strekke lydfilen eller gjette ordene.

Tillegg etter kildegjennomgang av `7319492` og `cd67c07`: ADC-signalets
sentrering/gain og maksimalt opptak er endret, men `updateAiAudio` kaller
fortsatt bare 256 samples per OS-løkke. En lengre maksimumsbuffer retter ikke
kontinuiteten. Kontroller sample_count mot elapsed_ms i den samme målingen.

Device-agent: flytt capture til kontinuerlig ADC/DMA eller dedikert task med
ringbuffer/PSRAM, med korrekt sampling over hele opptaket. Hold UI responsiv,
unngå driverkonflikt med M5Unified, og sammenlign sample_count/16000 med faktisk
opptaksvarighet. Et 5-sekunders opptak må gi omtrent 80000 sammenhengende samples.
Kontroller også at mikrofoninngangen faktisk er GPIO34 og signalet er tale.

## Backendrettelser som følger leveransen

- Fysisk sesjon starter i idle, ikke listening. Bare faktisk listen_start
  setter listening. Dette unngår at FIRE tolker readiness som et aktivt opptak
  og sender listen_stop med tom turn_id ved første B-trykk. Avbrudd går også til idle.
- Ugyldige eventer viser trygge feltnavn som session_id, uten å logge input,
  nøkler eller hele rå meldinger.
- ADC-WAV får DC-fjerning og avgrenset gain (maks 8x), med numerisk måling av
  varighet, RMS, peak og klipping. Opprinnelige wire-bytes brukes fortsatt til deduplisering.
- Tom transkripsjon gir forståelig feil og faktisk lydlengde; ingen tekst
  eller bestilling fabrikeres. Opptaket slettes etter behandling som før.
- HTTP sender eksplisitt Content-Length på PCM/ZIP. Hash, scope, TTL og
  playback-kvitteringer håndheves. Fragmenterte PCM-samples tåles mellom
  provider-chunker, men ufullstendig siste sample avvises.
- Etter ferdig talesvar vises det eksisterende build_proposal på nytt med
  samme ID, slik at A BUILD ikke forsvinner når playback-UI går tilbake til idle.
  Dette er ingen automatisk bygging eller ny autorisasjon.

## UI-kontrakt som device fortsatt må følge

La B starte ny tale også når et ubekreftet build-forslag vises, og behold
A BUILD som separat, eksplisitt bekreftelse. Listen_start ugyldiggjør forrige
forslag. Kjøring krever senere A RUN for riktig pakke.

Nyeste picker sender foreløpig tom project_id for New app. En tom ID alene
kan ikke skille brukerens nye app fra automatisk reconnect med samme boot.
Bruk `session_start` med `app_mode="new"` ved et bevisst nytt valg, eller
`app_select` etter start. Ved reconnect utelates app_mode (eller bruk resume-ID).
Update kan sende app_id eller project_id; backend løser også dagens SD-mappe-ID
sendt som project_id, men aldri appnavn. Se APP_LIFECYCLE.md for versjoner og
app_deleted/inventory. Backend-sletting krever fersk bekreftelse på fravær fra
en tilkoblet FIRE; frakobling alene er aldri nok.

Full fysisk tale → AI-app → installasjon → kjøring er fortsatt ikke verifisert.
Høyttalerbekreftelsen må ikke presenteres som bevis på fungerende mikrofon.

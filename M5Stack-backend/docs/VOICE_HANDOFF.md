# Tale – fysisk status og neste device-retting, 22. november 2026

Gjennomgått device-commit: `6d979894d6e04d7f46e538f6b5ef2a7188017600`.
Backend-agenten endrer ingen device-filer og bygger/flasher ikke firmware.

## Siste måling: 15 sekunders WAV fra 2,8 sekunders opptak

Under feilsøkingen kom også `fad4294`: device-agenten erstatter I2S DMA med
timerstyrt direkte ADC i egen task. Råskiftet nedenfor gjelder derfor den
forrige DMA-implementasjonen og er fjernet i nyeste kode. Ny boot er observert,
men det foreligger ennå ingen lydopplasting fra denne booten. Tidsforhold og
forståelig tale må bekreftes på nytt; målingene nedenfor er fra før omstarten.

Etter at driverstarten er rettet mottar backend WAV igjen. Fire påfølgende
fysiske opplastinger har hver 240000 samples (15,000 s ved oppgitt 16000 Hz),
mens listen_start → listen_stop målt på serveren tar henholdsvis 2,804,
2,801, 2,815 og 2,763 s. Forholdet er 5,33–5,43. Siste opptak:
AC-RMS 131,7, AC-peak 1136, DC 16, ingen registrert klipping, gain 8.
OpenAI returnerer tom transkripsjon. Hele WAV-opplastingen mottas; det er
ikke samme symptom som den tidligere manglende opplastingen.

Dette er serverens eventintervall, ikke en måling av ADC-klokken. Synkroniser
derfor med lokal capture-start/slutt i firmware. Dersom også lokal tid er
omtrent 2,8 s, fylles 240000-samplebufferen med omtrent 86000 samples/s,
selv om WAV-headeren sier 16000. Ikke rett dette ved vilkårlig å endre
WAV-header eller strekke lyd i backend; mål faktisk klokke/slot-format,
kontroller dupliserte samples og få 5 s opptak til å gi omtrent 80000
sammenhengende, korrekt dekodede PCM-samples.

GitHub-kode lest: `2367d00` flytter DMA-drenering til egen task. Dette
retter den tidligere hovedløkke-begrensningen i kildekoden, men enhetens
annonserte firmwareversjon inneholder ikke commit-ID, så backend kan ikke
bevise at akkurat dette bygget kjørte i målingen.

Et konkret ekstra kodeavvik å kontrollere: tasken bruker `raw[index] >> 4`
før sentrering. ESP-IDF 4.4.3 dokumenterer ESP32 ADC type1 som 12 databits
i **[11:0]** og kanal i **[15:12]**. Det offisielle legacy-I2S ADC-eksemplet
maskerer de øvre fire bitene (`raw & 0x0fff`), fremfor å skifte data fire
biter ned. Dagens skift taper fire signalbits og kan blande kanalinfo inn
i signalet. Verifiser råformatet i den faktisk brukte driveren; logg kun
numeriske kanal-/min-/maks-/rateverdier, ikke rå lyd eller hemmeligheter.

Kilder: [ESP-IDF ADC type1](https://github.com/espressif/esp-idf/blob/v4.4.3/components/hal/include/hal/adc_types.h#L109-L114),
[offisielt I2S ADC-eksempel](https://github.com/espressif/esp-idf/blob/v4.4.3/examples/peripherals/i2s/i2s_adc_dac/main/app_main.c#L158-L166).

Backend viser nå både lydlengde og opptakstid i Aktivitet. Ved tom ASR og
stort overskudd av samples kommer en egen melding om feil tidsforhold,
fremfor å be brukeren gjenta samme setning. Målingen er diagnostikk:
backend resampler ikke etter upresise nettverkstider og forkaster heller
ikke en ellers gyldig transkripsjon bare på grunn av eventintervallet.
22 relevante lydtester består, inkludert det konkrete 15 s / 2,8 s-tilfellet,
vanlig tidsavvik og tilnærmet samtidige events. Rå WAV slettes etter behandling.

## Tidligere blokkering: driverstart

**Tidligere fysisk forsøk, etter DMA-commit 2ac854f:** brukeren fikk
«Microphone capture unavailable». Denne strengen kommer fra
FireOS::startAiRecording når firePrepareMicCapture feiler, før listen_start
og WAV-opplasting. Logg hvilken ESP-IDF-operasjon som feiler og dens returkode;
undersøk særlig om M5Unified allerede eier I2S-porten. Dette er en mistanke
fra kildelesing, ikke en målt driverfeilkode. Backend står klar og prøver ikke
å omgå capture-feilen ved å fabrikere tale.

Den første DMA-endringen var et steg mot kontinuerlig capture, men updateAiAudio drenerte
fortsatt bare 256 samples per hovedløkkekall. Etter at driveren starter må også
forbrukerens throughput/ringbuffer verifiseres mot faktisk opptakstid. Ved
vedvarende lav dreneringsrate trengs en egen task eller større, løpende drenering.

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

## Tidligere målt blokkering: sammenhengende mikrofonopptak

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

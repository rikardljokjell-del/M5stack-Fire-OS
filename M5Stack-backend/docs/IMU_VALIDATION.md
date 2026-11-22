# IMU-apps: digitalt vater, 2026-11-22

Det rapporterte bygget `build-19acdb88ea9646549283` stoppet etter fire
kandidater. Første kandidater hadde faktiske callback-/måleproblemer. Siste
kandidat ble avvist fordi normal måling ikke var testet: simulatoren leverte
`(sin(t), cos(t), 1)`, med lengde sqrt(2) g. Appens kontroll av tyngdevektoren
avviste dermed samtlige ordinære målinger. Alle profiler viste feilskjermen,
ingen tegnet måletall. Kvalitetskontrollen avviste dette korrekt; å fjerne
kontrollen ville skjult manglende dekning.

Simulatoren leverer nå en bevegelig enhetsvektor. Alle bygg med `imu` får
i tillegg disse isolerte testprofilene, også uten live OpenAI:

| Profil | Sensor og handling |
|---|---|
| imu_flat | (0,0,1), ingen knappetrykk |
| imu_tilt | (-0.5,0.5,sqrt(0.5)), pitch30°, roll≈35.264° |
| imu_vertical | (1,0,0), B etter1s; beholdes loddrett |
| imu_zero | (0,0,0), B etter1s; beholdes ugyldig |
| imu_calibration | kjent helling, B etter1s |
| imu_recovery | helling → nullvektor ved2s → loddrett ved4s → helling ved6s; B ved1/3/5s |
| imu_tolerance | pitch2°, A ved1s, C ved3/5s |

Faktiske utdata fra update registreres ved første frame etter400,1400,3400,
5400 og7400ms: inntil12 tekster, to grid-bilder (maks384 celler hver), fire
fylte sirkler og tilstanden til alle10 LED-er. Grid-celler kodes som ASCII48
pluss palettindeks. Dette er begrenset testobservasjon, ikke skjermbilder
eller bevis på fysisk målenøyaktighet. Kortere kjøretider gir færre observasjoner.
Profilene har ingen generelle krav til appens tekster, farger eller nullstilling;
review vurderer dem mot den konkrete appens avtalte funksjon.

Den gjenbrukte vater-kandidaten er optimert ved å dekode sifferbitmaps én gang,
slik at dynamiske måletall holder instruksjonsbudsjettet. Utkastets ukjørte
testkode i kommentarer er fjernet. Backend bruker utførte tester som bevis.

Ti minutters soak behandler37500 komplette scener. Denne profilen har30s
begrensning på PC-prosessen; vanlige profiler har fortsatt8s. Per-callback
instruksjons-, output-, raster- og minnegrenser er beholdt. Den lengre
vertsfristen gjelder begge worker-variantene, også pakket Windows-program.

Enhetens kode, firmware og globale innstillinger er ikke endret. PC-tester og
kildegjennomgang innebærer ikke fysisk verifisering av vater eller IMU.

Verifisert lokalt: 390 automatiske tester bestått, inkludert 11 nye IMU-tester.
«Digitalt vater» 0.1.1 bestod 21 profiler og separat OpenAI-kildekontroll;
13 konkrete utdata-kontroller bekreftet bitmap-tall, bobleposisjoner, alle ti
LED-er, toleranseendring og bevart referanse etter ugyldig nullstilling.
Pakken er lagt i Windows-biblioteket, ikke automatisk installert eller startet
på FIRE. Ti minutters test fullførte alle 37500 frames. Resultater og kilder
beholdes lokalt under `%LOCALAPPDATA%\FIRE Backend\verification\vater-*`.

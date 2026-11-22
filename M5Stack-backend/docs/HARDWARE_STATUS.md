# Status: maskinvareapper og Tetris

Nyere kildestatus: dae75bf / 74ac26a implementerer første native delmengde display/buttons/rgb/imu/time/jobs/gpio/pwm/i2c/uart. Dermed er den tidligere implementeringsstatusen nedenfor historisk. Fysisk støtte er fortsatt ikke bevist av kilde/PC-test. [FIRE_EXPERIENCE_STANDARD.md](FIRE_EXPERIENCE_STANDARD.md) og [DEVICE_EXPERIENCE_HANDOFF.md](DEVICE_EXPERIENCE_HANDOFF.md) beskriver nyeste krav og funn.

22. november 2026. Backendens maskinvarekontrakt er utvidet fra fem til 20
tjenestegrupper / 67 metoder, med eksakt versjon/hash, argument-/ressurskontroll,
ikke-blokkerende jobbmodell og syntetisk PC-host. OpenAI får den forhandlede
kontrakten, ikke en fast liste over fem mulige tjenester. Manglende native
adaptere bevarer brukerens appkrav uten å foreslå en helt annen app.

Windows-programmet har «Maskinvareutkast på PC» under Apper. Målingene er tydelig
merket simulerte. Slike pakker kan ikke installeres på en eldre eller ulik
firmwareprofil. Vanlig appdialog bruker fortsatt faktisk annonsert deviceprofil.

Første lagrede Fallbrikker/Tetris feilet fysisk på callbackbudsjett. Den gamle
PC-porten overså mer enn 500 tekstbyte per bilde. Release-v4 fanger denne kilden;
den reparerte kilden klarer idle-profilen i 60 simulerte sekunder med 220 byte.
Ingen eksisterende appkilde eller pakke-zip er endret.

Backendtester dekker versjon/hash, legacy, ressurser, pinner/busser, kø/cancel,
I/O-feil/timeouts, miljø-/minnegrenser, rendering, bevarte appkrav, eksplisitt
BUILD og pakker som avvises på inkompatibel firmware. Toolbox-fixturen kjøres i
ti releaseprofiler. Testsuksess er PC-verifikasjon, ikke fysisk maskinvarebevis.

Verifikasjon: 317 tester i hele suiten og to ekstra tester av trygg retesting
har bestått. Ekte OpenAI-dialog/kodegenerering er også kjørt isolert med
brukerens toolbox-ønske: «Elektronikkbenk» ble pakket som fire-lua-0.2 med
display/buttons/i2c/gpio/pwm/uart/jobs etter ti releaseprofiler. Brukte ressurser
ble sporet (I²C 0, UART 2, GPIO26/36, PWM26). Ingen native kommando, fysisk
installasjon eller kjøring ble sendt. Testpakken ligger i lokal verification,
ikke i brukerens appbibliotek eller GitHub.

To tidligere usperrede pakker besto retesting, inkludert Fallbrikker 0.1.2 i
alle sju profiler. En eldre versjon ble sperret for blanke mellomrammer. Allerede
påviste feilversjoner ble hoppet over og beholdt sperret. Arkiv/kilde/versjon er
uendret; bare validerings-/kvalitetsmetadata ble oppdatert.

Fysisk I²C/GPIO/PWM/UART/Wi-Fi/BT/SD/mic/speaker fra Lua er **ikke verifisert eller
implementert i inspisert firmware 932ba8f**. Device-agenten må følge
[HARDWARE_API_HANDOFF.md](HARDWARE_API_HANDOFF.md), implementere driverne, annonsere
korrekt delmengde og fysisk teste den. Backendagenten har ikke endret, bygd eller
flashet device. Se også [Tetris-rapporten](TETRIS_RUNTIME_REPORT.md).

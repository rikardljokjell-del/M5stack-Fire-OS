# FIRE OS firmware

Aktuell **testkandidat: fire-os-1.2.0-rc9**. Etter versjonsvalg under
**Settings → Firmware → Oppdater fra GitHub** kan du velge:

- **Installer direkte fra GitHub**: oppdaterer inaktiv OS-slot og starter om.
- **Last ned til SD**: lagrer og kontrollerer filen uten installering eller omstart.
- **Tilbake**.

Samme kjørende versjon vises som **Reinstaller** ved direkte installasjon.
SD-valget henter hele den signerte filen til PSRAM, kontrollerer lengde/hash
og avslutter socket/TLS helt før SD åpnes. SD-filen leses tilbake; både egen
signert katalog ved filen og global katalog for eksisterende recovery kontrolleres.
Tidligere kopier beholdes som backups. Ingen OTA-slot eller oppstartsmetadata
endres av bare nedlasting til SD. For lite arbeidsminne gir en trygg avvisning.
RC9 frigjør overflødig bufferkapasitet før TLS og holder nødvendige katalogbytes
i samme worker-eide PSRAM-allokering som firmwarefilen.

[CI 45575157747](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45575157747)
på kilde [b77c579](https://github.com/rikardljokjell-del/M5stack-Fire-OS/commit/b77c579bec4b4986680f9f3be82a4afbe76f59e8)
bestod **16 tester og tre bygg**. Signert pakke og ny USB-utpakking er kontrollert.
Privat kandidat har bestått to faktiske GitHub→SD-lagringer av signert
RC8, inkludert readback, backupkopier og uendret innhold i begge fulle OS-slotter
og alle oppstartsmetadata. Endelig RC9-produksjonstest avventes.
Se [fysisk SD-rapport](../M5Stack-device/PHYSICAL_SD_2026-11-25.md).

| Gjeldende RC9-fil | Bruk |
| --- | --- |
| [Normal firmware](fire-os-1.2.0-rc9.bin) | Direkte oppdatering eller SD-kopi fra enheten |
| [USB-arkiv](fire-os-1.2.0-rc9-usb.zip) | Førstegangsmigrering på en annen enhet |
| [Kontrollsummer](fire-os-1.2.0-rc9-SHA256SUMS.txt) | Eksakte filhashes |
| [Utgivelsesbevis](fire-os-1.2.0-rc9-evidence.json) | CI, komponentkilder og faktisk teststatus |

Normal RC9 er ny; fysisk testet RC2-bootloader, partisjonstabell og recovery
beholdes uendret med separat kildeopphav. Alle eldre utgivelsesfiler beholdes.

## Historisk RC8

RC8 beholdes med [original signert katalog](fire-os-1.2.0-rc8-catalog.json),
[binær](fire-os-1.2.0-rc8.bin), [USB-arkiv](fire-os-1.2.0-rc8-usb.zip),
[kontrollsummer](fire-os-1.2.0-rc8-SHA256SUMS.txt) og
[utgivelsesbevis](fire-os-1.2.0-rc8-evidence.json).
[CI 45569401808](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45569401808)
på `02b3905beb48841df9915fe93b6c2037636faa7b` bestod 16 tester og tre bygg.
Første private RC8-baserte test stoppet ved TLS-allokering før SD-skriving.
Ekstra privat katalogkopi og produksjonens beholdte bufferkapasitet ble
håndtert samlet i RC9-kandidaten; testen isolerte ikke hver årsak. Bruk
nyeste anbefalte utgave øverst. Den eldre FatFS-feilens rotårsak er ikke fastslått.

## Historisk RC7

RC7 beholdes med [original signert katalog](fire-os-1.2.0-rc7-catalog.json).
Denne versjonen støttet bare direkte GitHub-installasjon. Følgende er
tidligere kontroll og bruk av den:

RC7: velg
**Settings → Firmware → Oppdater fra GitHub → utgave → Installer direkte fra GitHub**
og bekreft med B. Oppdateringen bruker ikke SD-kort eller backend.
GitHub-valget har bare installering og tilbake; SD-nedlasting er fjernet.
Under arbeidet vises status og fremdrift. A kan avbryte før aktivering.

Alle 15 tester og tre bygg er bestått på kilde
[7eb40b7](https://github.com/rikardljokjell-del/M5stack-Fire-OS/commit/7eb40b7e0effca647d101031c777832aa672a010),
[CI 45496282327](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45496282327).
FIRE har fysisk hentet denne RC7-filen fra GitHub, avbrutt ved én prosent
uten endret oppstartsvalg og fullført etter ett eksplisitt nytt forsøk.
Tilbakeavlest app1 matcher CI-filen; sekvens 10 er VALID med gyldig CRC.
Begge OS-plasser inneholder ren RC7, og testutgaven er fjernet.
125 sekunders drift og 45 sekunders vanlig omstart ga ingen panic/watchdog;
maks løkkegap var 85/86 ms. Backend bekreftet de samme sju appidentitetene.
Se [samlet fysisk bevis](../M5Stack-device/PHYSICAL_USB_2026-11-24.md).
Full brukerprøve av Home, tale, AI/appkjøring og fysisk strømbrudd gjenstår.
Normal RC7 er ny; de fysisk testede RC2-bildene for bootloader,
partisjonstabell og recovery beholdes uendret i USB-pakken.

| Gjeldende RC7-fil | Bruk |
| --- | --- |
| [Normal firmware](fire-os-1.2.0-rc7.bin) | Direkte, signert GitHub-oppdatering |
| [USB-arkiv](fire-os-1.2.0-rc7-usb.zip) | Førstegangsmigrering på en annen enhet |
| [Kontrollsummer](fire-os-1.2.0-rc7-SHA256SUMS.txt) | Eksakte filhashes |
| [Utgivelsesbevis](fire-os-1.2.0-rc7-evidence.json) | CI, komponentkilder og faktisk teststatus |

## Historisk RC6

RC6 beholdes uendret med [original katalog](fire-os-1.2.0-rc6-catalog.json).
Denne kandidaten tilbød direkte installasjon
fra GitHub til inaktiv OS-slot, uten SD-kort eller backend. Velg
**Settings → Firmware → Oppdater fra GitHub → utgave → Installer direkte fra GitHub**
og bekreft med B. FIRE kontrollerer signatur, størrelse, nettverksdata og
tilbakeavlest flash før ny firmware velges og enheten starter om.
Den tilbød også **Lagre pa SD**, som er fjernet i RC7.

Alle 15 tester og tre bygg er bestått på kilde
[55a8584](https://github.com/rikardljokjell-del/M5stack-Fire-OS/commit/55a8584e8216a2760781d562b88be42679ddf387),
[CI 45492728362](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45492728362).
Den private fysiske RC6-testen krasjet i FatFS under SD-skriving før direkte
OTA ble prøvd. Årsaken er ikke fastslått og tilskrives ikke maskinvare.
Normal RC6 er ny, mens USB-pakken bevarer de fysisk testede
RC2-bildene for bootloader, partisjonstabell og recovery med separat opphav.

| Historisk RC6-fil | Bruk |
| --- | --- |
| [Normal firmware](fire-os-1.2.0-rc6.bin) | Direkte, signert GitHub-oppdatering |
| [USB-arkiv](fire-os-1.2.0-rc6-usb.zip) | Førstegangsmigrering på en annen enhet |
| [Kontrollsummer](fire-os-1.2.0-rc6-SHA256SUMS.txt) | Eksakte filhashes |
| [Utgivelsesbevis](fire-os-1.2.0-rc6-evidence.json) | CI, komponentkilder og faktisk teststatus |

## Historisk RC5

RC5 beholdes uendret med [original katalog](fire-os-1.2.0-rc5-catalog.json).
SD-skrivefeilen er gjenskapt på fysisk FIRE, og installasjonsbekreftelsen hadde
en separat feil. Bruk nyeste anbefalte utgave øverst. Følgende er de tidligere USB-målingene:

RC5 ble fysisk installert på
Rikards FIRE og helsegodkjent. Målt maksimal løkkeavstand ved oppstart og
appinventering var 88 ms, og 86 ms etter vanlig omstart; tidligere RC2 nådde
1 391 ms. Ingen krasj eller ekstra reset ble sett i de avgrensede opptakene.
Dette er ikke full produksjonsgodkjenning av Home, tale, apper og GitHub-OTA.

| Fil | Bruk |
| --- | --- |
| [RC5 USB-arkiv](fire-os-1.2.0-rc5-usb.zip) | Signert førstegangsmigrering med fire bilder og alle åtte nødvendige filer |
| [RC5 normal firmware](fire-os-1.2.0-rc5.bin) | Direkte oppdatering etter migrering, sammen med signert katalog |
| [index.json](index.json) | Signert schema 2-katalog med nyeste kandidat først |
| [Kontrollsummer](fire-os-1.2.0-rc5-SHA256SUMS.txt) | SHA256 for normalbinær og USB-arkiv |
| [Utgivelsesbevis](fire-os-1.2.0-rc5-evidence.json) | Eksakte filhashes, komponentkilder, CI og avgrensede fysiske resultater |

Start med [samlet oppsett](../SETUP.md) og [fysisk test](../docs/PHYSICAL_CHECK.md).
Under den historiske RC5-testen kjørte Rikards enhet i B / app1. Forrige
private testversjon i A og separat factory recovery var beholdt. En ny enhet
bruker [USB-veiledningen](../M5Stack-backend/docs/USB_MIGRATION.md); pakken
er også klargjort lokalt i
`M5Stack-backend/workspace/migration/fire-os-1.2.0-rc5/`.

RC5 retter gjentatt bytevis SD-lesing ved appoversikt, konsistent rapportering
av pakkeidentitet, ventende nettverkssvar i Auto, skjermrammebudsjett og
bytevis TCP/WebSocket-lesing. Første normalmåling var 125 sekunder, etterfulgt
av flashlesing som bekreftet VALID og en 45-sekunders vanlig omstart.
[Fysisk USB-rapport](../M5Stack-device/PHYSICAL_USB_2026-11-24.md) har scope og mellomresultater.

Normalbildet er fra kilde
[958415d](https://github.com/rikardljokjell-del/M5stack-Fire-OS/commit/958415d20029939a0e105f4ee23aa6008a7ab567),
[CI 45477480676](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45477480676),
med 13 tester og tre grønne bygg. Den distribuerte pakken **gjenbruker de
fysisk testede RC2-bildene for bootloader, partisjonstabell og recovery**;
normal RC5 er ny. De separate komponentkildene står i utgivelsesbeviset.
Alle fire eksakte bilder er bundet av den signerte migreringsplanen.
Det er ikke påstått at alle fire kommer fra samme kildecommit.

Etter engangsmigreringen bruker du **Settings → Firmware** på FIRE.
FIRE kontrollerer signatur, mål, størrelse og SHA256, og skriver bare inaktiv
OS-slot. Bootloader, partisjonstabell og factory beholdes ved normal OTA.
Redning kan velges med A før vanlig OS og hente signert firmware uten SD
eller Windows. Fysisk knapphold og tidligere normal OTA-slot skal
fortsatt prøves; USB-testen av tidlig reset viste tilbakeføring til factory.
Direkte GitHub-OTA er nå prøvd med RC7 som beskrevet øverst.
Backendens firmwarevisning viser bare versjoner og informasjon.

Historisk RC2 beholdes uendret med
[original katalog](fire-os-1.2.0-rc2-catalog.json). Bruk RC5: RC2 hadde målte
UI-pauser ved appinventering. Historisk RC1 beholdes også med
[original katalog](fire-os-1.2.0-rc1-catalog.json); den kunne bryte frisk Home
Auto-forbindelse hvert minutt. RC3/RC4 var private USB-mellomtester.

`fire-os-1.1.bin` og [legacy-index-v1.json](legacy-index-v1.json) beholdes for
Studio-historikk. Den usignerte gamle utgaven er ikke en oppdatering for den
nye recovery-layouten. Private signeringsnøkler følger aldri med.

## Versjonene beholdes

Alle publiserte firmwareversjoner blir liggende på GitHub. Nye utgaver får
egne filnavn; gamle binærfiler, USB-arkiver, kontrollsummer og originale
signerte kataloger slettes eller overskrives ikke. Før hovedkatalogen endres,
bevares den tidligere signerte katalogen med versjonsnavn. Nye testresultater
supplerer leveransebeviset med historikken beholdt.

Hovedkatalogen har foreløpig en grense på åtte signerte oppføringer. Før den
grensen nås, må arkivvisningen utvides; eldre filer skal ikke slettes for å
omgå grensen. Legacy 1.1 beholdes som historikk. RC3/RC4 var private
mellomtester og har ikke vært publiserte GitHub-utgivelser.

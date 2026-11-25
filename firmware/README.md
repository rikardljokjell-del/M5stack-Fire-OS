# FIRE OS firmware

## Aktuell testkandidat: fire-os-1.4.0-rc2

Polert OS og Home med kantutjevnet tekst, proporsjonale små etiketter,
ikoner tegnet i riktig størrelse og jevnere avrundede kort-/knappekanter.
Fire appkort per side og samme A/C/B beholdes. Ingen ekstra skjermbuffer.
SDK, Runtime AI, Home-tilgang, innstillinger og eksisterende apper er uendret.

Eksakt CI-bilde er installert og MD5/SHA256-tilbakekontrollert i B48 VALID/CRC;
forrige UI RC1 A47 er beholdt som reserve. Helsekontroll 45,168s og vanlig
omstart 35,15s hadde ingen panic/abort/watchdog. COM er lukket. Brukerens
visuelle prøve pågår; fysisk HA-styring eller ny OTA/SD-overføring inngår ikke.

[Normal firmware](fire-os-1.4.0-rc2.bin) ·
[signert USB-pakke](fire-os-1.4.0-rc2-usb.zip) ·
[kontrollsummer](fire-os-1.4.0-rc2-SHA256SUMS.txt) ·
[utgivelsesbevis](fire-os-1.4.0-rc2-evidence.json) ·
[lisensinformasjon](fire-os-1.4.0-rc2-NOTICES.txt).

Kilde `007a35d`, CI45685543151: 24 native tester og tre bygg; strenge
C++-kontroller består separat. Seks skjermer er kontrollert med de faktiske
tegnehjelperne. Normalbildet er 2 525 072 byte; statisk RAM er fortsatt
63 796 byte og IRAM-margin 1 128 byte. Den signerte USB-pakken beholder
fysisk testet RC2-bootloader/tabell/recovery og alle lisens-/varselfiler.

Alle eldre publiserte versjonsfiler er bytebevart. Aktiv katalog har åtte
valg; eldre utgaver, inkludert [1.2-RC2-katalogen](fire-os-1.2.0-rc2-catalog.json),
[firmware](fire-os-1.2.0-rc2.bin) og [USB-pakke](fire-os-1.2.0-rc2-usb.zip),
ligger fortsatt i arkivet. Se [UI-veiledningen](../M5Stack-backend/docs/FIRE_OS_UI.md).

## Historisk første UI-kandidat: fire-os-1.4.0-rc1

Ny visuell utforming for FIRE OS og Home:

- Hovedmeny med fire apper per side, tydelig valg og sidetall.
- A/C flytter valget, B åpner. Globale langtaster og egne appknapper beholdes.
- Nye app-/menyikoner, felles font-/fargestil, lesbare lister og dialoger.
- Home med tydelige måle-/kontrollkort, bedre innstillinger og datastatus.
- Lagret apprekkefølge, Home/Camper, rettigheter og eksisterende apper beholdes.

Ren CI-firmware er faktisk installert i A47 VALID/CRC; fungerende RC7 er
beholdt urørt i B46. Flash-MD5 og SHA256-tilbakeavlesing av hele normalbildet
består. Helsekontroll45,2s og vanlig omstart35,11s ga ingen panic/abort/watchdog.
COM er lukket. Brukerens prøve av utseende og A/B/C pågår; dette er fortsatt
en testkandidat, ikke en påstand om fysisk HA-styring.

[Normal firmware](fire-os-1.4.0-rc1.bin) ·
[signert USB-pakke](fire-os-1.4.0-rc1-usb.zip) ·
[kontrollsummer](fire-os-1.4.0-rc1-SHA256SUMS.txt) ·
[utgivelsesbevis](fire-os-1.4.0-rc1-evidence.json) ·
[lisensinformasjon](fire-os-1.4.0-rc1-NOTICES.txt).

Se [kort UI-veiledning og kontrollstatus](../M5Stack-backend/docs/FIRE_OS_UI.md).
CI45680009752 på kilde `708affb` bestod 22 native tester og tre bygg, med
separate strenge C++-kontroller. Normalbildet er 314 144 byte mindre enn RC7;
statisk RAM og IRAM-margin er uendret. Dette beviser ikke runtime-heap eller
opplevd respons. USB-pakken beholder fysisk verifisert RC2-grunnlag og alle
ni SDK-lisens-/varselfiler i tillegg til åtte signerte kjernefiler.

Aktiv signert katalog holder fortsatt grensen på åtte valg. Eldste 1.2-RC1
ligger nå i [arkivet med original katalog](fire-os-1.2.0-rc1-catalog.json),
[binær](fire-os-1.2.0-rc1.bin), [USB-pakke](fire-os-1.2.0-rc1-usb.zip),
[kontrollsummer](fire-os-1.2.0-rc1-SHA256SUMS.txt) og
[bevis](fire-os-1.2.0-rc1-evidence.json). Ingen publiserte versjonsfiler er
slettet eller omskrevet; RC7 beholdes også som et aktivt installasjonsvalg.

Live Home Assistant-styring er ikke godkjent av en skjerm-/oppstartsprøve.
Eldre appspesifikke Lua-tidsfeil og brukerutløst Runtime AI-test har uendret
avgrensning. GitHub → SD er fysisk bekreftet på RC7; denne testen er ikke
automatisk gjentatt på 1.4-kandidaten.

## Historisk fire-os-1.3.0-rc7

RC7 inneholder FIRE App SDK og asynkron Runtime AI over den eksisterende
backenden. Appstart sender nå faktisk verifisert kildehash; installasjonen
kontrollerer pakkeidentiteten på SD før den melder suksess. SDK bruker
Generational GC med uendrede tids-, minne-, instruksjons- og I/O-grenser.
Jobbpris og appens samlede utviklingspris er skilt i backend, og ukjent
forbruk vises som ukjent eller med tydelig empirisk anslag.

Eksakt CI-fil er installert i B46 VALID/CRC, med RC9 i A45 beholdt.
Flash-MD5 og SHA256-tilbakeavlesning av hele normalbildet består; full OTA-slot
med FF-utfylling er ikke kontrollert på nytt. Helse 45,055 s og vanlig
omstart 20,206 s ga ingen panic/abort/watchdog. Dette er en testkandidat.

Vanlig, kildebundet oppstart av den samme manuelle oppdragsappen består.
Den var fortsatt running/healthy på samme boot/run/pakke etter 112,97 s uten
registrert appfeil. Brukeren bekrefter at spillet vises og A/C virker.
Første update var 12,139 ms; dette er ikke en måling av alle senere frames.
Ekte knappestyrte AI-resultater og full opplevd brukerflyt gjenstår i sluttprøven.

- [Normal firmware](fire-os-1.3.0-rc7.bin)
- [Signert USB-arkiv](fire-os-1.3.0-rc7-usb.zip): åtte signerte kjernefiler
  og ni SDK-lisens-/varselfiler
- [Kontrollsummer](fire-os-1.3.0-rc7-SHA256SUMS.txt),
  [utgivelsesbevis](fire-os-1.3.0-rc7-evidence.json),
  [font- og bildekreditering](fire-os-1.3.0-rc7-NOTICES.txt)
- [Runtime AI og korte teststeg](../M5Stack-backend/docs/RUNTIME_AI.md)

Kilde `47df9da`, CI45671660337: 22 native tester og tre bygg. Strenge
C++-kontroller består separat. USB-pakken beholder de uendrede, fysisk
testede RC2-grunnlagsbildene. Runtime AI bruker samme backend og API-nøkkel.

**Fersk fysisk GitHub → SD-prøve:** Brukeren lastet ned hele RC7-filen via
vanlig meny. Hashkontroll, SD-skriving, tilbakeavlesing og begge signerte
katalogkopier bestod; brukeren bekrefter at alt fungerte. Ingen installasjon
eller omstart ble utløst. Den gamle skrivefeilen ble ikke gjenskapt, og ingen
ny kode eller firmware ble nødvendig. Se [SD-rapporten](../M5Stack-device/PHYSICAL_SD_2026-11-25.md).

Eldre appspesifikke 24 ms-feil er ikke generelt friskmeldt. Direkte OTA/recovery
er ikke fysisk gjentestet med denne RC7-utgaven. PC-resultater beviser ikke
fysisk ytelse.

Katalogen har åtte signerte installasjonsvalg. Tidligere RC3 er tatt ut av
den aktive listen på grunn av en dokumentert fysisk callback-feil, men alle
dens originale versjonsfiler og signerte katalog beholdes nedenfor. Ingen
publiserte firmwarefiler er slettet eller overskrevet. Flere fremtidige
utgaver vil kreve avgrenset arkivoppdagelse før kataloggrensen utvides.

## Historisk 1.3.0-RC3

RC3 er bevart byteidentisk: [binær](fire-os-1.3.0-rc3.bin),
[USB-pakke](fire-os-1.3.0-rc3-usb.zip),
[original signert katalog](fire-os-1.3.0-rc3-catalog.json),
[kontrollsummer](fire-os-1.3.0-rc3-SHA256SUMS.txt),
[opprinnelig bevis](fire-os-1.3.0-rc3-evidence.json) og
[lisensinformasjon](fire-os-1.3.0-rc3-NOTICES.txt).
Den manuelle oppdragsappen traff24ms-grensen etter152frames. Senere funn og
rettinger står i [den løpende fysiske rapporten](../M5Stack-backend/docs/FIRE_APP_SDK_EVALUATION.md);
det opprinnelige utgivelsesbeviset er ikke omskrevet.

## Historisk RC9

Historisk **testkandidat: fire-os-1.2.0-rc9**. Etter versjonsvalg under
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
og alle oppstartsmetadata.
Den eksakte publiserte RC9-filen er deretter lagret og tilbakekontrollert på SD;
tidligere RC8-fil/katalog er intakt. Separat SD-installasjon startet ren RC9
i **A/app0, sekvens 19 VALID/CRC**. Begge OS-plassene er nå CI-RC9 og privat
testkode er fjernet. Minst 125 s vanlig drift og én 45,044 s normal omstart
ga ingen panic/watchdog; maks gap 92,998/85,996 ms. Den rene B-kopien er ikke
separat startet. Backend bekreftet fersk boot og komplett 7/7-appinventar mot
varig siste komplette referanse før produksjons-RC9, ikke RC2-original.
Direkte RC9-OTA ble ikke gjentatt; RC7-beviset nedenfor beholdes.
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

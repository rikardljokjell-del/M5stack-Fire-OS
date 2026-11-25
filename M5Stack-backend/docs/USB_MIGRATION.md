# Engangs USB-migrering til FIRE med recovery

Dette er et separat Windows-verktøy. Backend, AI, webUI og Lua-apper kan ikke
starte det. Fysisk USB-migrering og etterfølgende RC5-oppstart er gjennomført
av device-agenten; se den kanoniske
[fysiske rapporten](../../M5Stack-device/PHYSICAL_USB_2026-11-24.md).
Pakkekontrollen nedenfor er separat og åpner ingen serieport. Kildekode og
grønne PC-tester alene er ikke fysisk verifikasjon.

**Rikards FIRE er allerede USB-migrert og kjører ren, helsegodkjent RC9.**
Device-agenten har bekreftet signert nedlasting til SD uten installering eller
omstart, etterfulgt av separat SD-installering og vanlig ren RC9-omstart.
Se den kanoniske rapporten for det avgrensede fysiske prøveomfanget. Eldre
RC6/RC8-testfeil beholdes som historikk og tilskrives ikke SD-maskinvaren. Stegene
nedenfor er en generell veiledning for en annen FIRE som trenger førstegangs-
migrering; de er ikke en ny migreringsoppgave for den ferdig oppdaterte enheten.

## Historisk RC7-flyt: direkte oppdatering fra GitHub

Følgende menyflyt er implementert i bygget og publisert RC7. Produksjonsfilen er
hentet og installert fysisk av enheten; prøveomfanget fremgår av device-rapporten.
Flyten erstatter ikke førstegangsmigreringen nedenfor. Historisk
RC5- og RC7-verifikasjon er bevart nederst. Aktuelle USB-eksempler bruker den
kontrollerte, signerte RC9-pakken; menyen fra RC8 har i tillegg valgfri SD-nedlasting.

1. Åpne **Settings → Firmware → Oppdater fra GitHub**.
2. Velg **RC7**, deretter **Installer**. Det andre valget er **Tilbake**.
3. Bekreft installeringen med **B** i bekreftelsesvinduet.
4. Enheten kontrollerer oppdateringen og starter automatisk på nytt etter
   vellykket kontroll og installering.

Direkte installering går til den inaktive OTA-plassen og krever **ikke SD-kort**.
GitHub-menyen har ingen funksjon for å lagre firmware på SD. RC7 avviser også
slike lagringsforespørsler i koden. Installering fra en ferdig eksisterende,
frakoblet SD-fil beholdes som en separat funksjon; det er ikke et nødvendig
mellomsteg for GitHub-installering. Fysisk SD-installering er ikke godkjent
av denne backendkontrollen. At den nye flyten unngår SD-skriving, beviser ikke
at SD-skrivefeilen er rettet.

## Menyflyt fra RC8, beholdt i RC9: valgfri nedlasting til SD

Instruksjonene i dette avsnittet gjelder den nye RC8-flyten. Kilden er fryst
som `02b3905beb48841df9915fe93b6c2037636faa7b`; RC8 er bygget og publisert,
og den signerte USB-pakken har bestått uavhengig kontroll uten serieport.
RC8s første private fysiske prøve stoppet før SD på en TLS-allokeringsfeil.
Den nye RC9-kandidatens separate prøve og aktuelle pakkebevis beskrives nedenfor.
RC7s tidligere fysiske resultater beholdes som historiske bevis.

1. Åpne **Settings → Firmware → Oppdater fra GitHub** og velg ønsket versjon.
2. Velg **Last ned til SD**.
3. Les bekreftelsen: filen lagres uten installering eller omstart, og gammel
   kopi beholdes som backup. Trykk **B – Last ned** for å bekrefte.

Dette er et valgfritt alternativ. Direkte installering fra GitHub er fortsatt
standard og krever ikke SD-kort. En lagret fil aktiverer ingen OTA-plass og
starter ikke enheten på nytt. Den får en egen tilhørende signert
`.catalog-v2.json`; den eksisterende `/firmware/catalog-v2.json` beholdes også
for recovery. Faktisk lagring og verifikasjon er ikke godkjent bare ved at
menyvalget og instruksjonene finnes.

Når valgt utgave er den som allerede kjører, heter installasjonsvalget
**Reinstaller direkte fra GitHub**, med **B – Reinstaller** i bekreftelsen.
Dette er en egen installasjonshandling, forskjellig fra å laste ned til SD.

## RC9: eksakt SD-prøve og ren sluttoppstart bekreftet

RC9-kilden er fryst som `b77c579bec4b4986680f9f3be82a4afbe76f59e8`.
Den beholder RC8-menyflyten, men frigjør overflødige tekstbuffere og beholder
nødvendig katalog i worker-eid PSRAM. Endelig RC9-bygg og signert pakke er
publisert, og den nyutpakkede pakken har bestått uavhengig kontroll uten
serieport. Eksemplene nedenfor bruker RC9. Device-agenten har nå bekreftet
lagring og tilbakeavlesning av eksakt publisert RC9 på SD. Tidligere RC8-binær
og tilhørende katalog var intakte; begge komplette OS-plasser og alle metadata
var uendret ved lagring, uten installering eller omstart. En separat
SD-installasjon startet deretter produksjons-RC9 i app0. Device-agenten har
bekreftet app0 som eksakt CI-RC9, sekvens 19 VALID med gyldig CRC. Bare inaktiv
app1 ble deretter erstattet med ren CI-RC9; app0 og metadata ble beholdt.
Begge OS-plasser er produksjonsutgaver, testharnessen er fjernet, og vanlig
sluttomstart i app0 viste maksimalt gap 85,996 ms uten panic eller watchdog.

Device-agentens private fysiske RC9-kandidat har lastet ned den signerte
RC8-filen til SD to ganger. Hash, begge katalogene og bevarte gamle backupkopier
er kontrollert. Begge komplette OS-plasser og alle OTA-metadata var uendret
etter hver lagring; det skjedde ingen installering eller omstart. Dette er
bevis for den private kandidaten med RC8 som nedlastingsmål, ikke for ferdig
produksjons-RC9 eller for at den tidligere RC8-testutgaven bestod. Se den
kanoniske device-rapporten for testomfanget.

Backendens første avlesning etter RC9-installasjonen bekreftet RC9-identitet;
lagrede startkvitteringer viste ny boot sammenlignet med RC7. Health og webUI
svarte 200. Firmwarekatalogen viste RC9 → RC8 → RC7 → RC6 → RC5 → RC2 → RC1
→ 1.1 som lesbar metadata uten feil, og fire Reverse TCP-kanaler var
autentisert uten rapportert transportfeil. Første inventar stod som `requested`;
eldre rapporter ble ikke tilskrevet den nye booten. Den siste kontrollen etter
ren RC9-omstart bekreftet derimot ny boot siden første RC9-observasjon, nyere
komplett inventar og tilgjengelig SD. Alle sju current-boot/current-epoch-apper
matcher på ID, versjon, checksum og normalisert package-ID mot den private,
varige referansen fra siste komplette oversikt før produksjons-RC9/SD-installasjon.
Referansen kan være fra en privat kontrollboot; den er ikke opprinnelig RC2.
Rapporten var 176 sekunder gammel ved avlesning. PC-simulering er holdt utenfor,
og inaktiv AI-sesjon i Auto/mainmenu er ikke tolket som transportfeil.

## Før du begynner

Bruk en ekte M5Stack FIRE med klassisk ESP32 og 16 MiB flash. Verktøyet kan
kontrollere ESP32/flash/eFuses/MAC, men USB-ROM kan ikke bevise produktnavnet på
etiketten. Velg riktig fysisk enhet og serieport. Ha stabil strøm og god USB-kabel.
Lukk serieovervåkere/PlatformIO-programmer som holder porten åpen.

Vanlige Lua-apper på SD-kortet berøres ikke. Den fullstendige backupen under
gjelder **intern flash, ikke SD-kortet**. Det gamle interne SPIFFS-området erstattes
delvis av recovery og nye konfigurasjonspartisjoner. Den gamle flashens innhold
beholdes i backupen. NVS, app1, dedikerte konfigurasjonsområder og coredump blir
ikke slettet av migreringskommandoen. En bevart app1 er ikke automatisk en
fungerende eller godkjent tilbakeføringsversjon.

Migrering under strøm-/USB-brudd kan kreve USB-gjenoppretting. Uavhengig recovery
fungerer først etter at den nye layouten og bootloaderen er skrevet korrekt.
Verktøyet endrer aldri eFuses, omgår aldri Secure Boot og bruker aldri `--force`.
Enheter med aktiv/tidligere flashkryptering, Secure Boot, beskyttede sikkerhetsfelt
eller ukjent layout avvises. Dette er en kompatibilitetsgrense, ikke en innstilling
du skal slå av for å tvinge fram migrering.

## 1. Kontroller pakken uten enhet

Åpne PowerShell i `M5Stack-backend`. Den ferdige pakken ligger for eksempel i
`workspace\migration\fire-os-1.2.0-rc9` og inneholder:

- `migration.json` og `migration.sig` (signert plan for alle fire bildene).
- `bootloader.bin`, `partitions.bin`, `normal.bin`, `recovery.bin`.
- `catalog-v2.json` og `release-public.pem`.

USB-pakkens utgivelsessti er `firmware/fire-os-1.2.0-rc9-usb.zip` i repoet.
Pakk ut alle åtte filene til mappen over før kontroll. En separat publisert
`fire-os-1.2.0-rc9.bin` erstatter ikke hele USB-pakken. Den kan også ligge som
en valgfri ekstrakopi i den lokale arbeidsmappen; den finnes ikke i USB-ZIP-en
og kreves ikke av migreringsverktøyet. Lokal `component-provenance.json` er også
en ekstra revisjonsfil, ikke en av de åtte nødvendige filene i USB-ZIP-en.

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fire.py check --bundle workspace\migration\fire-os-1.2.0-rc9
```

Standardkommandoen åpner **ingen serieport** og skriver ingenting til FIRE.
Den kontrollerer den fastlagte utgivernøkkelen, begge signaturene, størrelser,
filhashes, ESP32-bildenes kontrollsum/SHA256 og den eksakte partisjonstabellen.
Pakkens medfølgende nøkkel kan ikke erstatte den som er fastlagt i verktøyet.
Manglende eller usignerte bilder stopper kontrollen. RC-versjoner skal fortsatt
merkes som ikke fysisk verifisert fram til egen enhetstest.

## 2. Installer bare USB-verktøyets avhengigheter

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-migration.txt
.\.venv\Scripts\python.exe scripts\migrate_fire.py ports
```

Dette bruker esptool **4.5.1**, samme serie som device-prosjektet. Den vanlige
backendprosessen trenger ikke esptool eller serieport. Velg porten som faktisk
tilhører FIRE, for eksempel COM3; verktøyet gjetter aldri en port.

## 3. Kun forhåndskontroll av tilkoblet FIRE

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fire.py preflight --bundle workspace\migration\fire-os-1.2.0-rc9 --port COM3
```

Enheten går midlertidig til ROM-nedlastingsmodus for kontroll, og startes tilbake
etter vellykket kontroll. Dette skriver ikke intern flash. Brikke, 16 MiB,
sikkerhetsstatus, relevante eFuses og bildenes støttede brikkerevisjoner må stemme.
Hvis forbindelsen feiler, kontroller kabel/port og lukk serieovervåkeren. Ved behov
brukes enhetens dokumenterte USB-bootprosedyre; ingen sikkerhetsdialog omgås.

## 4. Bevisst migrering

Kjør først når riktig signert pakke og riktig serieport er kontrollert:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fire.py migrate --bundle workspace\migration\fire-os-1.2.0-rc9 --port COM3 --confirm MIGRATE-FIRE
```

Før skriving gjør verktøyet dette i rekkefølge:

1. Kontrollerer brikke og sikkerhetsstatus.
2. Leser hele 16 MiB, lagrer `flash.bin` lokalt og bekrefter filen på disk.
3. Leser hele flashen på nytt og sammenligner SHA256. Lagrer `backup.json`
   med størrelse, hash, maskinvareidentitet og opprinnelig layout. Filene er
   synkronisert til disk før første skriveoperasjon.
4. Kontrollerer identitet/sikkerhet på nytt etter backupen.
5. Skriver og leser tilbake normalbildet og recoverybildet, deretter
   partisjonstabell og bootloader. Alle overførte bildebyte er uendret fra
   den signerte pakken; ingen esptool-headeromskriving brukes.
6. Sletter **bare** OTA-valget ved `0xe000..0xffff`, bekrefter slettingen og
   starter enheten. Tomt OTA-valg skal føre til factory recovery. Recovery
   ber deretter om fysisk bekreftelse før oppstart av normalbildet.

Standardbackup ligger i ignorert `workspace\migration_backups\<tid-id>\`.
Ta vare på hele mappen. Den kan inneholde Wi-Fi-/enhetslegitimasjon fra NVS;
den skal ikke inn i Git, loggvedlegg eller offentlig deling. `--backup-dir`
kan velge en annen lokal mappe utenfor kildekontroll. Verktøyet avviser andre
mapper inne i Git-repoer. SHA256 oppdager endringer mot det lokale manifestet;
backupen er en privat lokal gjenopprettingskopi, ikke en offentlig signert utgivelse.

ROM-kontakt bruker 115200 baud. Etter oppstart av RAM-stubben brukes 921600 før
første fulle avlesning. To avlesninger på 16 MiB tar fortsatt flere minutter.
Hvis kabel/USB-adapter ikke tåler hastigheten, start en ny kommando med
`--baud 460800` eller `--baud 115200`. Det finnes ingen automatisk repetisjon av
en delvis skriveoperasjon. Hastigheten byttes ikke midt under backup/skriving.

Ved en feil stopper videre skriving. Ikke velg tilfeldige alternative bilder.
Ta vare på full backup, og bruk den separate gjenopprettingskommandoen ved behov.

## 5. Gjenopprett nøyaktig samme fysiske enhet

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fire.py restore --backup workspace\migration_backups\20261124-160000-eksempel --port COM3 --confirm RESTORE-FIRE
```

Bruk det faktiske mappenavnet, ikke eksemplet. Verktøyet kontrollerer full
størrelse/hash, den opprinnelige kjente partisjonstabellen og at MAC/flash-ID
tilhører samme ESP32. Det nekter annen enhet og inkompatibel sikkerhetsstatus.
Før gjenoppretting tas en ny dobbeltlest backup av nåværende innhold, også om
partisjonstabellen ble ødelagt under avbrutt migrering. Deretter skrives hele
den opprinnelige 16 MiB-kopien og leses tilbake før omstart. Dette erstatter
også senere endringer i intern flash. SD-kortet gjenopprettes ikke av kommandoen.

## Utgiverkontrakt

Kilden er `M5Stack-device/recovery/MIGRATION-v1.md` og
`M5Stack-device/SIGNED_FIRMWARE-v2.md`. `migration.json` bruker kanonisk UTF-8
JSON: sorterte nøkler, kompakte separatorer, NFC, ingen BOM eller linjeskift.
`migration.sig` er standard base64 av ASN.1 DER ECDSA-P256/SHA256 over nøyaktig
disse byte. Samme fastlagte `fire-release-2026`-nøkkel brukes for katalogen.
Private nøkler inngår aldri i pakken eller CI. Hashes fylles først etter bygg.

Skriveområder er fast kodet, ikke bestemt av vilkårlige manifestverdier:

| Bilde | Offset | Maks størrelse |
| --- | --- | --- |
| bootloader.bin | 0x1000 | 0x7000 |
| partitions.bin | 0x8000 | 0x1000 |
| normal.bin | 0x10000 | 0x640000 |
| recovery.bin | 0xc90000 | 0x300000 |

Bildene krever DIO, 40 MHz, 16 MiB, ESP32 chip-ID 0 og innebygd SHA256.
Normalbildet må stemme med størrelse/hash/kildecommit i den signerte katalogen.
Partisjonstabellen kontrolleres strukturelt, med MD5 og eksakte typer/områder.
RAM-stubbens skriveblokker begrenses til 4 KiB. Dermed kan siste blokks utfylling
ikke krysse grensene til NVS eller et annet bilde, slik standard 16 KiB-blokker
ellers kunne gjort ved en liten partisjonstabell. Dette er testet i adapterlaget.

## Verifikasjonsstatus

31 målrettede tester består mot signerte testpakker og en 16 MiB minnemodell.
De omfatter ugyldige signaturer/nøkkelbytte/hash/layout, chip/eFuse-avvisning,
full backup før skriving, bevart NVS/app1/config/coredump, stopp ved ulik
avlesning eller feil etter skriving, gjenoppretting av skadet partisjonstabell,
annen enhet og fast baud før avlesning. Ingen serieport er åpnet i disse testene.
Den faktiske signerte RC9-pakken er kontrollert av rotkoordinatoren, og backend-
agenten har uavhengig kjørt samme `check` mot den nyutpakkede USB-pakken i
`workspace\release-verify\fire-os-1.2.0-rc9`: signaturer, hashes, ESP32-bilder
og eksakt layout består (exit 0), uten serieport.
Normalbildets kilde er `b77c579bec4b4986680f9f3be82a4afbe76f59e8`, med
[CI-bevis 45575157747, jobb 139071160462](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45575157747/job/139071160462):
alle 16 tester og tre bygg bestått. Normalbildet er 2427328 byte med SHA256
`17edd52caa166558118c30ddead2d49ccc1d24360f68b326e2297eceab4fd6bd`.
USB-ZIP-en er 2653766 byte med SHA256
`c6e493690669406794c7cf663080f3d0b925fa61c7f83b98c2a9742c143c7bf7`.
Den inneholder eksakt åtte nødvendige filer; lokal komponentproveniens ligger
utenfor ZIP-en. Pakke-/CI-kontrollen er ikke fysisk OTA-/SD-verifikasjon.
Bootloader, partisjonstabell og recovery er uendret fra det fysisk testede
RC2-grunnlaget, kilde `7efbae95fa0a54aeb3e1d6a615390810b69279b4`.
Dette er RC9-normal med RC2-grunnlag, ikke et nytt RC9-bygg av alle komponentene.
Tidligere RC1/RC2/RC5/RC6/RC7/RC8-pakkekontroller beholdes som historiske bevis; RC2 ble også
kontrollert etter nyutpakking av nøyaktig åtte USB-filer.

Fysisk migrering med full backup og bilde-readback, recovery og kontrollert
tilbakeføring er nå dokumentert i
[device-rapporten](../../M5Stack-device/PHYSICAL_USB_2026-11-24.md).
RC5 er observert under normal oppstart og etter vanlig omstart med lagret
helsegodkjenning. Backend mottok fersk RC5-identitet og komplett SD-inventar
etter begge oppstarter: 7/7 like app-ID-er, versjoner, checksums og normaliserte
pakke-ID-er mot faktisk RC2-referanse. SD var tilgjengelig og fire Reverse TCP-
kanaler autentisert, uten rapportert transportfeil. Auto/mainmenu kan bevisst
lukke den inaktive AI-sesjonen; dette er ikke bevis på feil eller en pågående
AI-samtale. Ingen apper ble kjørt i denne kontrollen.

Ved første produksjonsoppstart etter GitHub-installering har backend også
mottatt fersk `fire-os-1.2.0-rc7` med ny bootidentitet. Health og webUI svarte
200; privat Reverse TCP var klar med fire autentiserte kanaler uten feil.
RC7-bootens appinventar stod først som `requested`, uten ferdig rapport for
gjeldende boot/tilkobling. Dette var ikke bevis på slettede apper. Etter den
endelige rene RC7-omstarten bekreftet backend ny boot, nyere komplett inventar
og tilgjengelig SD. Alle 7/7 gjeldende boot-/tilkoblingsoppføringer matcher
RC2-referansen på app-ID, versjon, checksum og normalisert package-ID. Rapporten
var 191 sekunder gammel ved siste avlesning; dette er lagret bevis fra den nye
booten, ikke en påstand om en melding sendt akkurat ved avlesningen.
Rotkoordinatoren har separat bekreftet app1 med sekvens 10 og VALID, samt
at begge OS-plassene inneholder eksakt CI-RC7 og testharnessen er fjernet.
Produksjonsopptak og vanlig omstart viste komplett skanning av sju apper,
uten panic eller watchdog; detaljer og målinger ligger i device-rapporten.
Firmwareoversikten viste RC7, RC6, RC5, RC2, RC1 og 1.1 i den rekkefølgen,
bare lesbar metadata og ingen katalogfeil. Privat Reverse TCP var fortsatt
klar med fire autentiserte kanaler uten feil. Ingen AI- eller appkjøring er
bekreftet av denne kontrollen. Hypotesen om at Auto avbrøt den første
inventarforespørselen er ikke bevist av disse dataene; den siste rene RC7-booten
leverte komplett inventar uten backendendring.

Fysisk strømbrudd, recovery-knappevalg, offentlig TLS, Home og AI-/Lua-kjøring
er ikke bekreftet av disse målingene. De 665 grønne backendtestene er et
separat lokalt bevis;
ingen ny fullsuite er kjørt for dette dokumentasjons- og pakkebyttet.
Esptool 4.5.1 og de låste USB-avhengighetene er installert på denne Windows-PC-en.
Import/API-tilgjengelighet og den ekte esptool-bildeparserens samsvar med vår
format-/SHA-fixture er kontrollert uten å åpne serieport.

Offisielt API-/formatgrunnlag:
[esptool v4 scripting](https://docs.espressif.com/projects/esptool/en/release-v4/esp32/esptool/scripting.html),
[ESP32 image format](https://docs.espressif.com/projects/esptool/en/release-v4/esp32/advanced-topics/firmware-image-format.html).

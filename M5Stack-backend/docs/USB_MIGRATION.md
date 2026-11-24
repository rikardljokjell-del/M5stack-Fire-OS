# Engangs USB-migrering til FIRE med recovery

Dette er et separat Windows-verktøy. Backend, AI, webUI og Lua-apper kan ikke
starte det. **Ingen fysisk flashing er utført som del av denne leveransen.**
Ferdige, signerte bilder må finnes før migrering. Kildekode og grønne tester
er ikke en ferdig eller fysisk verifisert migrasjonspakke.

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
`workspace\migration\fire-os-1.2.0-rc1` og inneholder:

- `migration.json` og `migration.sig` (signert plan for alle fire bildene).
- `bootloader.bin`, `partitions.bin`, `normal.bin`, `recovery.bin`.
- `catalog-v2.json` og `release-public.pem`.

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fire.py --bundle workspace\migration\fire-os-1.2.0-rc1
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
.\.venv\Scripts\python.exe scripts\migrate_fire.py preflight --bundle workspace\migration\fire-os-1.2.0-rc1 --port COM3
```

Enheten går midlertidig til ROM-nedlastingsmodus for kontroll, og startes tilbake
etter vellykket kontroll. Dette skriver ikke intern flash. Brikke, 16 MiB,
sikkerhetsstatus, relevante eFuses og bildenes støttede brikkerevisjoner må stemme.
Hvis forbindelsen feiler, kontroller kabel/port og lukk serieovervåkeren. Ved behov
brukes enhetens dokumenterte USB-bootprosedyre; ingen sikkerhetsdialog omgås.

## 4. Bevisst migrering

Kjør først når riktig signert pakke og riktig serieport er kontrollert:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fire.py migrate --bundle workspace\migration\fire-os-1.2.0-rc1 --port COM3 --confirm MIGRATE-FIRE
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
Reell COM-/strømbrudd-/bootloader-/recovery-test og faktisk signert utgivelsespakke
gjenstår. 624 grønne backendtester er en separat kontroll før dette verktøyet.
Esptool 4.5.1 og de låste USB-avhengighetene er installert på denne Windows-PC-en.
Import/API-tilgjengelighet og den ekte esptool-bildeparserens samsvar med vår
format-/SHA-fixture er kontrollert uten å åpne serieport.

Offisielt API-/formatgrunnlag:
[esptool v4 scripting](https://docs.espressif.com/projects/esptool/en/release-v4/esp32/esptool/scripting.html),
[ESP32 image format](https://docs.espressif.com/projects/esptool/en/release-v4/esp32/advanced-topics/firmware-image-format.html).

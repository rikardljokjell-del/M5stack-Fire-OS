# FIRE 1.2.0-rc7: bygg, migrering og redning

RC7 er fysisk installert direkte fra GitHub til inaktiv OS-slot, verifisert
mot CI, bekreftet VALID og startet normalt igjen. Avbrudd og eksplisitt nytt
forsøk er testet. GitHub-menyen bruker ingen SD-mellomlagring; SD-nedlasting
er fjernet etter fysisk SD-feil. Offline SD-installasjon er et eget, ennå ikke
sluttverifisert løp. Se [kanoniske fysiske bevis](../PHYSICAL_USB_2026-11-24.md).

Dette er fortsatt en testkandidat. Knapphold, Home/AI/lyd og øvrig fysisk
sluttkontroll gjenstår. Sluttpakken bruker eksakt RC7-normal fra CI og
byteidentiske fysisk verifiserte RC2-komponenter for bootloader, tabell og
factory recovery. Deres kilde-/CI-proveniens oppgis separat. Ingen private
testharness er igjen i enhetens to produksjonsslotter.

## Første installasjon

Bruk den komplette signerte migreringspakken sammen med
`M5Stack-backend/scripts/migrate_fire.py`. Verktøyet kontrollerer fast ESP32/
16 MiB-layout, signaturer, filer og sikkerhetsinnstillinger, tar full backup
og leser tilbake skrevne områder. Standardkjøring er kontroll uten skriving.
Se [MIGRATION-v1.md](MIGRATION-v1.md) og backendens migreringsveiledning for
eksakte argumenter. Ikke bruk PlatformIO Upload eller erase-flash.

Backupen inneholder lokale innstillinger og må oppbevares privat. Bruk stabil
USB-strøm. Et avbrudd under selve engangsmigreringen kan kreve USB-gjenoppretting;
den uavhengige redningsappen finnes først etter vellykket migrering.

Det nye oppsettet har to OS-slots og en separat factory-app. Vanlig OTA skriver
bare den inaktive OS-slotten. Factory-appen, bootloaderen og tabellen oppdateres
ikke via vanlig OTA. Home og recovery har egne NVS-områder; inkompatibelt innhold
fra tidligere SPIFFS kan formateres der ved første oppstart. Vanlig NVS med
eksisterende OS-innstillinger beholdes.

## Bruke redning

Hold **A** inne mens enheten resettes/slås på, i minst tre sekunder. Den
tilpassede bootloaderen velger recovery før vanlig FIRE OS. Dette nullstiller
bare OTA-valget, ikke vanlige innstillinger. Dette må fysisk verifiseres på FIRE.

- **Hold A:** undersøk eksisterende OS-slots. **A/C** velger A eller B;
  **B** starter den valgte slotten hvis image-kontrollen består. Skjermen viser
  at faktisk driftstilstand er ukjent. En checksum beviser ikke fungerende Wi-Fi/UI.
- **Hold C:** åpne `FIRE-Recovery`. Unikt passord vises på enheten.
  Åpne `192.168.4.1`, lagre Wi-Fi og hold C for omstart/lukking. Dette er egne
  recovery-innstillinger, uavhengig av vanlig OS. Oppsettet stenges etter ti minutter.
- **B:** hent og verifiser GitHub-katalog. **A/C:** velg utgave. **B:** installer
  den viste utgaven. Nedlasting og skriving kontrollerer signatur, mål, størrelse
  og hash. Denne veien trenger ikke SD-kort eller backend-PC.
- **Hold B:** les `/firmware/catalog-v2.json` fra SD. Velg deretter utgave og
  bekreft med B. Binærnavnet må finnes i den signerte katalogen.

Det kreves fungerende nett og publisert katalog for GitHub-veien, eller en
tilgjengelig signert SD-pakke for offline-veien. Recovery kan ikke reparere
fysisk skadet flash, strømforsyning eller ødelagt bootloader.

## Home og AI

Home finnes i hovedmenyen. Innstillinger gir Home/Camper, Lokal/Internett/Auto,
to kortoppsett og favoritter. Mobiloppsettet åpnes fra enheten og støtter import
av `device-profile.json` fra HA-oppsettet. Passord vises ikke tilbake. Lokal
MQTT bruker TLS/8883 og lokal CA; internett bruker WSS/443 `/mqtt` med offentlig
sertifikat. HA eier tillatelsene. Gamle verdier markeres og styring sperres når
de ikke er ferske. Ukjent resultat gir ingen automatisk gjentakelse av handlingen.

AI bruker backendens offentlige HTTPS-adresse og port 443, eller eksplisitt
lokal IP for eldre privat oppsett. Kontroll, lyd og pakker bruker samme
verifiserte offentlige vert. OpenAI-nøkler skal aldri legges inn på FIRE.
BUILD/RUN er fortsatt eksplisitte brukerhandlinger.

## Bygge fra kilden

Python 3.11+, PlatformIO 6.2.0. Bibliotekene er låst i `platformio.ini`.
Kommandoene nedenfor kjøres fra `M5Stack-backend/`:

```powershell
python -m platformio run --project-dir ../M5Stack-device -e m5stack-fire-ble
python -m platformio run --project-dir ../M5Stack-device -e fire-recovery
python -m platformio run --project-dir ../M5Stack-device/recovery/bootloader
python -m unittest discover -s ../M5Stack-device/tests -p 'test_*.py' -v
```

ESP-IDF avviser mellomrom i prosjektstier. På Windows kan bare det lille
`recovery/bootloader/`-prosjektet og den overordnede `partitions.csv` kopieres
til en vanlig byggemappe uten mellomrom. Behold samme relative plassering.
Linux-kontrollen bygger alle tre fra eksakt commit og laster opp usignerte
artefakter. Den bruker ingen privat signeringsnøkkel.

`tools/package_migration.py --help` viser pakkekommandoen. Den krever eksakt
kildecommit, de fire bygde filene og lokal privat nøkkel som matcher den
innbakte offentlige nøkkelen. Den signerer både katalog og hele migreringspakken.
Privat nøkkel skal bli i `.secrets/`, aldri i git, CI, logger eller leveransen.

## Måling og fysisk sluttkontroll

Serial 115200 viser hvert 30. sekund maksimal OS-tid, maksimal tid mellom
oppdateringer, callback-maksimum, intern heap/minimum, største frie blokk,
stack-margin og LED-timeouts. Nettverks- og Home-arbeidere viser egne marginer.
Feilsnapshots under `/logs/ai-developer/` beholder callback-/loopmålinger.
Tall fra kompilering er ikke mål på faktisk TLS-minnebruk.

Etter vellykket oppstart registreres OS-løkken i SDK-ets eksisterende watchdog
(fem sekunder, panic/omstart). Arduino mater den mellom løkkerunder; et faktisk
heng i løkken mater den ikke. En omstart før OTA-helsegodkjenning gir SDK-rollback.
Dette er implementert, men heng/omstart/rollback må fortsatt fysisk verifiseres.

Kontroller på fysisk FIRE: knapper/skjerm og LED-farger, lyd begge veier,
nettbrudd under tale/pakker, riktig varselknapp og duplikate/tapte ACK,
Home lokalt og eksternt med Windows av, fjernede HA-rettigheter,
OTA-avbrudd og feil før helsegodkjenning, begge gamle slots og factory-valg
med ødelagt vanlig Wi-Fi/UI. Registrer eksakt binærhash og oppgitte måletall.

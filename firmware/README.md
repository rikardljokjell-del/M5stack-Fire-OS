# FIRE OS firmware

Aktuell **testkandidat: fire-os-1.2.0-rc2**. RC2 beholder en frisk Home Auto-
forbindelse og starter ikke MQTT på nytt ved endret kortvisning. Kode, bygg, signaturer og
migreringspakken er kontrollert. Fysisk FIRE, tilbakeføring og redning må
sluttkontrolleres før kandidaten kan godkjennes for produksjon.

| Fil | Bruk |
| --- | --- |
| [fire-os-1.2.0-rc2-usb.zip](fire-os-1.2.0-rc2-usb.zip) | Komplett signert engangsmigrering: normal firmware, separat recovery, bootloader, partisjoner og signert plan |
| [fire-os-1.2.0-rc2.bin](fire-os-1.2.0-rc2.bin) | Normal firmware for direkte oppdatering etter migrering; brukes sammen med signert katalog |
| [index.json](index.json) | Signert schema 2-katalog som FIRE henter direkte fra GitHub |
| [Kontrollsummer](fire-os-1.2.0-rc2-SHA256SUMS.txt) | SHA256 for binær og USB-arkiv |
| [Bygg- og pakkebevis](fire-os-1.2.0-rc2-evidence.json) | Eksakt kildecommit, Linux-kjøring, filstørrelser, hashes og åpne fysiske kontroller |

Start med [samlet oppsett](../SETUP.md), deretter
[USB-migreringen](../M5Stack-backend/docs/USB_MIGRATION.md) og
[fysisk sluttest](../docs/PHYSICAL_CHECK.md). Pakken er allerede klargjort
lokalt i `M5Stack-backend/workspace/migration/fire-os-1.2.0-rc2/` på denne PC-en.
Ved nedlasting av USB-arkivet pakkes det ut til en ny mappe før kontrollen.
Den løse `.bin`-filen installerer ikke den nødvendige redningsløsningen alene.

Etter engangsmigreringen bruker du **Settings → Firmware** på FIRE.
FIRE verifiserer katalogsignatur, mål, størrelse og SHA256. Vanlig OTA skriver
bare inaktiv OS-plass; bootloader, partisjonstabell og factory recovery blir
beholdt. Redning kan velges med A før vanlig OS starter og kan hente direkte
fra GitHub uten SD-kort eller Windows. Faktisk knappe-/feilfunksjon står på
sluttestlisten. Backendens firmwarevisning er bare en versjonsoversikt.

Kilden er [7efbae95fa0a54aeb3e1d6a615390810b69279b4](https://github.com/rikardljokjell-del/M5stack-Fire-OS/commit/7efbae95fa0a54aeb3e1d6a615390810b69279b4).
[Linux-kontrollen](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45431615060)
bestod to firmwarebygg, bootloader og 12 tester. Det publiserte USB-arkivet
er pakket ut på nytt og godkjent av det separate migreringsverktøyet uten
serieport eller skriving til enhet. Private signeringsnøkler følger aldri med.

Historisk RC1 beholdes med uendrede binær-/USB-filer, kontrollsummer og
[original signert katalog](fire-os-1.2.0-rc1-catalog.json). Bruk RC2: RC1 kunne
bryte Home Auto-forbindelsen hvert minutt. Den gjeldende signerte katalogen
lister RC2 først og RC1 som tydelig merket historikk.

Historisk `fire-os-1.1.bin` beholdes. Dens opprinnelige metadata ligger i
[legacy-index-v1.json](legacy-index-v1.json) for Studio-oversikten. Denne
usignerte utgaven er ikke en oppdatering til den nye recovery-layouten.

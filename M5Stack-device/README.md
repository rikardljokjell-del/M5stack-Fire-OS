# FIRE OS

Et modulært Arduino/PlatformIO-startprosjekt for M5Stack FIRE med M5Unified/M5GFX.

## Ny testkandidat: 1.2.0-rc2

Denne kandidaten legger til direkte Home, verifisert HTTPS/WSS, signert OTA og
uavhengig redningsapp. Den er ikke fysisk sluttverifisert. Se
[recovery/README.md](recovery/README.md) for bygg, migrering og redning, og
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for aktuelle byggbevis.
Første installasjon krever den signerte engangspakken med full USB-backup.
Vanlig PlatformIO Upload er sperret fordi den ville erstattet recovery-bootloaderen.

RC2 retter Auto-forbindelsen i Home: en frisk ekstern forbindelse beholdes.
Lokal rute vurderes på nytt ved faktisk nettbrudd eller endret profil/oppsett.
Det kjøres ingen periodisk frakobling for å prøve lokal rute. RC1 beholdes som
historisk kandidat med egne, uendrede filer og hasher.
Endret kortvisning eller favoritter starter heller ikke MQTT på nytt.

## Første OS-milepæl

- Hovedmeny med Apps og Settings
- Safe boot ved å holde A+B+C under oppstart
- A = opp, B = velg, C = ned
- Langt A = tilbake, langt B = Quick Settings, langt C = hjem
- Date/Time med tidssoner og automatisk sommertid
- Date/Time-data er tilgjengelig for fremtidige apper via `fireOs.dateTime()`

## Navigering

- **A**: forrige valg eller tilbake
- **B**: åpne / tilbake fra en test; på mikrofon-skjermen starter et kort trykk opptak
- **C**: neste valg, reskann Wi-Fi eller testhandling
- Hold **B** inne i en test for å gå tilbake. På knappeskjermen vises siste trykk som `SHORT` eller `LONG`.

## Bygg og last opp

Åpne prosjektmappen i VS Code med PlatformIO installert. Velg miljøet
`m5stack-fire-ble` og bruk **Build**. Prosjektet bruker 115200 baud for Serial Monitor.

Fra terminal kan det bygges slik:

```text
pio run -e m5stack-fire-ble
pio run -e fire-recovery
```

Engangsmigreringen krever eksplisitt COM-port i USB-verktøyet. GPIO16/17 er
reservert til FIREs PSRAM og skal ikke brukes av apper.

## Maskinvaremerknader

- M5Unified initialiserer LCD, IMU, høyttaler og mikrofon. Hvis en komponent ikke finnes eller ikke støttes, viser testen dette i stedet for å stoppe programmet.
- RGB-testen bruker de ti FIRE-LED-ene på GPIO15. BLE-bygget sender hele
  rammen med RMT-maskinvaren; ingen timingbasert avbruddsstans brukes.
- SD-testen bruker standard FIRE SPI-pinner og CS GPIO4.
- Mikrofonopptaket er tre sekunder i 16 kHz mono og legges i PSRAM når det er tilgjengelig. Opptaket spilles av med M5Unified etterpå.
- FIRE bruker IP5306 som strømstyring. Den rapporterer batterinivå i grove trinn (0/25/50/75/100 %) og har ingen spenningsmåling via dette grensesnittet. System-skjermen viser `CHG` eller `BAT`. IP5306 kan rapportere lading via direkte USB, mens M5GO-docken kan lade via base/pogo-pinner uten at samme ladesignal blir synlig for ESP32-en.
- Wi-Fi-testen skanner passivt og forsøker ikke å koble til et nettverk.

## AI Developer og Lua-apper

AI Developer bruker backend-protokoll 0.2 når backendadresse og enhetstoken er
konfigurert under Settings → AI Backend. OpenAI-nøkler lagres ikke på FIRE.
Kontrollkanalen bruker en ikke-blokkerende WebSocket-klient med eksplisitte
bygge- og kjørebekreftelser.

Lua-apper kjører lokalt fra SD-kortet under `/apps/<id>/`. Runtime-en bruker
Lua 5.4-kjernen med begrensede, OS-eide tjenester og eksplisitte maskinvareressurser.
Gjeldende tillatelser og grenser står i
[`LUA_API.md`](../M5Stack-backend/docs/LUA_API.md) og
[`HARDWARE_API_HANDOFF.md`](../M5Stack-backend/docs/HARDWARE_API_HANDOFF.md).
Apper får ikke vilkårlig tilgang til maskinvare, filer, radio, flash eller
OS-innstillinger. Rå native `.bin`-apper kan ikke omgå signert OS-oppdatering.
Pakker må være ZIP_STORED og
kontrolleres med ytre SHA256, manifest, Lua API-versjon og payload-checksum før
de aktiveres.

Fysisk WebSocket-, tale- og installasjonsflyt må fortsatt verifiseres mot en
kjørende PC-backend og enheten. PlatformIO-builden er kontrollert med miljøet
`m5stack-fire-ble`.

## Overtakelsesstatus for ny device-agent

Kildekoden i denne mappen er den komplette FIRE OS-deviceimplementasjonen.
Backendkoden ligger separat i `../M5Stack-backend/`; backendendringer skal
ikke blandes inn i device-commits.

Siste device-arbeid omfatter FIRE OS-meny og Settings, Wi-Fi/Bluetooth/
Backend-sync, sikker boot, Lua 5.4-app-runtime, hardware-API-er,
appinstallasjon, App Manager, File Explorer, firmwarehåndtering og AI
Developer med WebSocket/Reverse TCP, lyd, bakgrunnsbygg, reboot/reconnect-
Resume, failed-build retry og Lua-appreparasjon.

Viktig dokumentasjon:

- `BACKEND_HANDOFF.md`: implementasjonsstatus, firmwarehash og faktisk fysisk
  verifisering.
- `../M5Stack-backend/docs/DEVICE_BUILD_CONTINUATION_HANDOFF.md`: gjeldende
  build-, boot- og repair-kontrakt.
- `../M5Stack-backend/docs/PROTOCOL-v0.2.md`: device/backend-protokoll.
- `../M5Stack-backend/docs/HARDWARE_API_HANDOFF.md`: Lua hardware-API.

Reproduserbart bygg:

```text
pio run -e m5stack-fire-ble
pio device monitor -p COM3 -b 115200
```

Historisk firmwareartefakt ligger under `firmware/fire-os-1.1.bin`.
Den nye kandidaten bruker schema 2 og en egen signert migreringspakke;
schema 1 eller en løs eldre binær godtas ikke av den nye OTA-flyten.
Full fysisk end-to-end-
test mot aktiv backend, failed-build retry og Vardensaga callback-timing er
fortsatt eksplisitt merket som ikke verifisert i `BACKEND_HANDOFF.md`.

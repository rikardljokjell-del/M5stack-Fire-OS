# FIRE OS

Et modulært Arduino/PlatformIO-startprosjekt for M5Stack FIRE med M5Unified/M5GFX.

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

Åpne prosjektmappen i VS Code med PlatformIO installert. Velg miljøet `m5stack-fire` og bruk **Build** eller **Upload**. Prosjektet bruker 115200 baud for Serial Monitor.

Fra terminal kan det bygges slik:

```text
pio run -e m5stack-fire
pio run -e m5stack-fire -t upload
```

Hvis porten ikke oppdages automatisk, kan `upload_port = COMx` legges til i miljøet i [platformio.ini](platformio.ini). GPIO16/17 brukes ikke av prosjektet.

## Maskinvaremerknader

- M5Unified initialiserer LCD, IMU, høyttaler og mikrofon. Hvis en komponent ikke finnes eller ikke støttes, viser testen dette i stedet for å stoppe programmet.
- RGB-testen bruker de ti FIRE-LED-ene på GPIO15 via FastLED.
- SD-testen bruker standard FIRE SPI-pinner og CS GPIO4.
- Mikrofonopptaket er tre sekunder i 16 kHz mono og legges i PSRAM når det er tilgjengelig. Opptaket spilles av med M5Unified etterpå.
- FIRE bruker IP5306 som strømstyring. Den rapporterer batterinivå i grove trinn (0/25/50/75/100 %) og har ingen spenningsmåling via dette grensesnittet. System-skjermen viser `CHG` eller `BAT`. IP5306 kan rapportere lading via direkte USB, mens M5GO-docken kan lade via base/pogo-pinner uten at samme ladesignal blir synlig for ESP32-en.
- Wi-Fi-testen skanner passivt og forsøker ikke å koble til et nettverk.

# Maskinvare og fremtidige verktøy på FIRE

Gjennomgått mot produsentkilder 25. november 2026. Dette er dokumenterte
grensesnitt og forutsetninger, ikke en liste over fysisk verifiserte moduler.
Faktiske kapabiliteter og ressurslister avgjør hvilke metoder en app får.

| Familie | Generelt grensesnitt | Produsentkilde |
| --- | --- | --- |
| ENV I/II/III/IV/Pro | I²C, modellspesifikk måling/kalibrering | [ENV](https://docs.m5stack.com/en/unit/Unit_ENV-IV) |
| ADC / ADC v1.1 | I²C, ADS1100/ADS1110 | [ADC](https://docs.m5stack.com/en/unit/adc), [v1.1](https://docs.m5stack.com/en/unit/Unit_ADC_v1.1) |
| INA226-1A/10A | I²C, riktig shunt og kalibrering | [INA226](https://docs.m5stack.com/en/unit/Unit_INA226-1A) |
| ToF / ToF4M | I²C, ulike VL53-drivere | [ToF](https://docs.m5stack.com/en/unit/Unit_ToF), [ToF4M](https://docs.m5stack.com/en/unit/Unit_ToF4M) |
| Color | I²C, RGBC | [TCS3472](https://docs.m5stack.com/en/unit/Unit_Color) |
| DAC | I²C, MCP4725 | [DAC](https://docs.m5stack.com/en/unit/dac) |
| PaHub | I²C, valgt kanal/busstopologi | [PaHub](https://docs.m5stack.com/en/unit/Unit_PaHub) |
| Encoder | I²C, modulens egne registre | [Encoder](https://docs.m5stack.com/en/unit/Unit_Encoder) |
| Weight-I²C | I²C, STM32-modul | [Weight-I²C](https://docs.m5stack.com/en/unit/Unit_Weight-I2C) |
| Bar HX711 / GPIO Weight | Timingadapter nødvendig | [Weight](https://docs.m5stack.com/en/unit/Unit_Weight) |
| GPS/GNSS | UART, ramme-/fixvalidering | [GPS](https://docs.m5stack.com/en/unit/Unit_GPS) |
| RS485/Modbus | UART og riktig elektrisk transceiver | [RS485](https://docs.m5stack.com/en/unit/Unit_RS485) |
| COMMU / ekstern CAN | SPI-driver og riktig CAN-grensesnitt | [COMMU](https://docs.m5stack.com/en/module/Module_COMMU) |
| RFID | Eksakt modul/protokoll | [RFID](https://docs.m5stack.com/en/unit/Unit_RFID) |
| Innebygd IMU | Faktiske annonserte målinger og opptaksgrenser | [FIRE](https://docs.m5stack.com/en/core/Fire) |
| BLE | Råannonser/GATT, egen radiomegling | [Espressif](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-guides/coexist.html) |
| Analoge GPIO-målinger | Godkjent ADC og kalibrering | [ADC-begrensninger](https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/peripherals/adc.html) |

## Viktige forskjeller

ENV-revisjoner, ToF-varianter og vektmoduler er ikke samme produkt selv om
navn eller I²C-adresse likner. Et ACK identifiserer ikke chipen. INA226-1A
og -10A trenger ulik shunt-/kalibreringsinformasjon. Riktig modell, enheter,
busstopologi og kalibrering følger måledata og utviklingshistorikk.

Grove A bruker normalt GPIO21/22 og deler I²C med interne komponenter.
Grove B har GPIO26/36; retning og andre eiere må kontrolleres. FIREs merkede
Grove C16/17 er koblet til PSRAM: UART-moduler trenger faktisk ledige,
annonserte omkoblede pinner. Et CoreS3-eksempel er ikke et FIRE-pinnekart.
[FIRE-dokumentasjon](https://docs.m5stack.com/en/core/Fire).

Ikke frigjør LCD/SD-/flash-/knappepinner som rå GPIO. Delt SPI skal eies av
bussadapteren med en separat godkjent CS. I²C skal beskytte OS-enhetene og
bare bruke erklærte eksterne adresser. Grove-forsyning og GPIO-signalnivå er
ulike forhold; fysisk kobling følger den konkrete modulens dokumentasjon.

Wi-Fi og BLE deler radio. Klassisk SPP, BLE GATT og råannonser er forskjellige
funksjoner. Signalopptak beviser ikke fungerende kontroll; kryptering, paring
eller protokolltilstand kan være nødvendig. GPIO-Lua er ikke en mikrosekund-
presis bit-bangingmotor. Timingkritiske sensorer trenger en faktisk native
adapter eller en ekstern bro. Weight-I²C har et annet grensesnitt enn bar
HX711. ADC2 konkurrerer med Wi-Fi; et flytende inngangssignal er ikke en
gyldig referanse. Kildene i tabellen beskriver disse forholdene.

## Slik brukes kunnskapen

Den lokale katalogen velger bare relevante, eksplisitt nevnte modellfamilier.
Vanlige klokker/spill får ikke hele sensorkatalogen i prompten. Utvalget har
fast størrelsesgrense, kilde, manglende forutsetninger og separat fysisk status.
Dokumentasjon gir aldri ekstra pinne-, fil- eller nettverkstillatelse.

Nye sensorer kan bruke de samme generelle bussene uten produktspesifikk
firmware når protokollen passer de faktiske grensene. En datasheet-lenke er
ikke bevis for en ferdig driver.

Relevant erfaring gjenbrukes direkte fra eksisterende utviklingskontekst og
brukerbekreftelser. Et nytt bygg kan få inntil tre relevante observasjoner
fra andre prosjekter med samme eier. Utvalget binder den opprinnelige appen,
kildehashen og den bekreftede konteksten; avviste, endrede eller slettede
grunnlag utelates. Resume beholder det frosne utvalget. Dette krever verken
en ekstra database eller modellrunde. Referanser gir ikke tilgang til andre
appers rådata eller kode. En brukerbekreftet observasjon er fortsatt en
observasjon, ikke automatisk en fysisk verifisert protokoll eller løsning.

## Praktisk prøve med ekstern modul

1. Oppgi konkret modulmodell og kobling én gang i utviklingssamtalen.
   Informasjonen skal deretter følge prosjekt og målesesjon.
2. Koble etter dokumentasjon og faktisk ledige FIRE-ressurser.
3. Start den testede appen. Begynn med observasjon før ønsket sending.
4. Bruk opptak/markør/referanse og bekreft hva som faktisk skjedde.
5. Velg Analyze eller Improve app. Data og tidligere kontekst følger med;
   korriger kort med tale dersom en antakelse er feil.
6. Godkjenn en konkret kandidat. Behold rådata og fungerende versjon.

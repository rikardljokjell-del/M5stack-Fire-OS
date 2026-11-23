# Frosset vater: IMU-ferskhet, 2026-11-23

Device-agent: gjennomfør denne sammen med
[callback-handoff](DEVICE_NATIVE_CALLBACK_HANDOFF.md). Backend har ikke endret,
bygget eller flashet firmware. Brukeren bekrefter at tidligere firmwaretiltak
ennå ikke er utført.

## Observasjon og kildefunn

Brukeren rapporterer at Digitalt vater0.1.2 starter, men står statisk ved
fysisk tilting. Dette er ikke en bekreftelse på fungerende sensorintegrasjon.
Pakken er `build-f1aa7e3f05b341c89686`.

Gjennomgått device-kilde: GitHub main ved commit8edd67c.

- `FireOS::update()` kaller `M5.update()` ved linje1061.
- `FireOS::luaImuAccel()` ved linje6262 og gyro-adapteren leser kun
  `M5.Imu.getImuData(&data)`.
- Det finnes ingen `M5.Imu.update()`, `getAccel()` eller `getGyro()` i
  device/src som henter ferske råmålinger.
- PlatformIO angir M5Unified`^0.2.7`; nøyaktig installert versjon må device-agent
  kontrollere i sitt eget dependency-miljø.

I offisiell M5Unified0.2.7 henter `IMU_Class::update()` nye sensordata og
oppdaterer `_latest_micros`. `getImuData()` konverterer eksisterende
`_raw_data`; den gjør ingen ny sensoravlesning. `getAccel()` kaller derimot
`update()` ved gammel måling. `M5Unified::update()` oppdaterer knapper/touch/
strømknapp, ikke IMU. Den manglende oppdateringen er en konkret integrasjonsfeil
og stemmer med brukerens symptom. Fysisk rotårsak må bekreftes ved måling etter
rettelsen; simulatoren leser ikke sensoren på FIRE.

Primærkilder:

- [IMU_Class.cpp0.2.7: update/getImuData/getAccel](https://github.com/m5stack/M5Unified/blob/0.2.7/src/utility/IMU_Class.cpp#L366-L441)
- [M5Unified.cpp0.2.7: update](https://github.com/m5stack/M5Unified/blob/0.2.7/src/M5Unified.cpp#L1693-L1911)

## Firmware-rettelse

1. Hent nye IMU-målinger i OS-eid, begrenset oppdateringsløype før appens
   Lua-update, eksempelvis25–50Hz. Bruk sensormasken fra `Imu.update()` og lagre
   gyldige, konverterte accel/gyro-verdier med tidsstempel fra samme måling.
2. La Lua-adapterne returnere dette sammenhengende snapshotet. Unngå ny
   blokkerende I²C-polling per aksespørring inne i12ms-Lua-callbacken. Accel og
   gyro må ikke lese ulike, halvoppdaterte målinger.
3. Håndter utilgjengelig sensor, manglende ny måling, sensorbytte og apprestart.
   Ikke presenter gammel gyldig verdi som fersk eller nullvektor som en
   dokumentert reell måling. Lua-runtime ignorerer i dag returverdien fra
   `host_.imuAccel`; dette må vurderes sammen med adapterens feilsemantikk.
4. Behold nåværende Lua-signatur og enhet g. Hvis timestamp/alder eller nye
   returverdier eksponeres i Lua, avklar og oppdater registry/kontrakthash med
   backend før annonsering. Ikke innfør `fire.imu.update()` som udokumentert
   appkrav; eksisterende apper skal fungere gjennom OS-adapteren.
5. Ikke kall en uendret vektor «frosset» bare fordi verdiene er like: en enhet
   som ligger stille skal gi stabil måling. Ferskhet krever måletid/gyldighet.

## Fysisk akseptanse

- Kaldstart0.1.2 uten ny AI-generering. Vipp positivt og negativt rundt begge
  akser: tall OG boble skal endres uten knappetrykk og returnere ved utflating.
- Trykk B ved helling; nye målinger skal vise relativt avvik fra denne
  referansen. A/C skal fortsatt endre toleranse og RGB-status.
- Kontroller råakser, sample-alder og maskebiter i en begrenset diagnostikk.
  Verifiser faktisk endring ved bevegelse, ikke bare at en oppdateringsteller øker.
- Test sensorfeil/recovery, Home/Back, ny appstart, Wi-Fi/reverse TCP samtidig
  og callback-maksimum. Utfør også RGB-tiltakene i den andre handoffen.
- Publiser målinger og installert firmwarecommit i BACKEND_HANDOFF.md.

## Backend gjort

Ny obligatorisk `imu_motion`-profil tester flat → positiv helling → negativ
helling → flat i SAMME appinstans, uten knapper. Den gjør ingen automatisk
kalibrering som kan skjule frosset tilstand.0.1.2 ble testet mot profilen:
0.0/0.0 →30.0/35.3 →-30.0/-35.3 →0.0/0.0 grader; boble og begge RGB-sider
fulgte tilstanden. Dette viser at appen reagerer på nye leverte målinger på PC,
ikke at fysisk IMU er reparert. Det trengs ingen tilfeldig omskriving eller
ny versjon av vater-appen for å få OS til å oppdatere sensorbufferen.

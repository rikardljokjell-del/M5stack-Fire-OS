# FIRE OS — leveransebevis

## RC2 under kontroll

RC2 retter kun Home Auto-ruting: en frisk ekstern MQTT-forbindelse brytes
ikke etter ett minutt. Lokal rute vurderes igjen etter et faktisk nettbrudd
eller endret konfigurasjon. Nye bygg, ny kildecommit og signert RC2-pakke
registreres etter kontroll; RC1-filene overskrives ikke.
Visnings-/favorittendringer endrer ikke nettverkets konfigurasjonsgenerasjon
og starter ikke MQTT på nytt; profil- og ruteendringer gjør det fortsatt.

## Historisk RC1-leveranse

Testkandidat, fysisk sluttkontroll gjenstår. Ingen enhet er flashet i dette
arbeidet. Master håndterer publisering og den samlede overleveringen.

## Kilde og bygg

Eksakt kildecommit: `34ade23bc2872dbc3561a09d859aba865d05f470`.
Denne endrer bare byggkontroll/dokumentasjon fra firmwarekilden i `35b3751`.
Alle leverte binærfiler kommer fra den nye committens Linux-kjøring:
[FIRE firmware checks 45426276015](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45426276015).

Alle tre bygg og alle 12 tester bestod. Testene dekker publisering/signaturer,
migreringspakking, faktiske portable kø-/JSON-vern og WebSocket-håndtrykk.
De erstatter ikke testing av firmware på fysisk FIRE.

CI-arkivet er 25 466 345 byte, SHA256
`11a37d5ae1de6eaa3263505637700a0572bc3d401be224b89c4396bfc9a09a8d`.
Master lastet ned og kontrollerte arkivet før ekstraksjon. Signeringen brukte
utelukkende filene fra denne ekstraksjonen, ikke lokale Windows-byggefiler.

| Fil | Byte | SHA256 |
| --- | ---: | --- |
| `normal.bin` / `fire-os-1.2.0-rc1.bin` | 2399808 | `1241877bb01510bf5e964864edc54052ec6ce594330ac68179bfbcd26f4a8a9e` |
| `recovery.bin` | 1578112 | `040b2c66a800fb4456a3aac2b7436af19fc4c53a6565b45ec63146229f55c1d5` |
| `bootloader.bin` | 27760 | `fb0e8dbc804574cc5aa7373b85e97726588c072608cd931057b805be0bc9324e` |
| `partitions.bin` | 3072 | `66f473bf47827c01ff3fc4af089c45b070b67a056df78cba704d3390535cd120` |
| `catalog-v2.json` | 954 | `6b8830908d4dc8d94ff68c9487e7ee9d17f48c3caf40ee15ce35542d4d3cb763` |
| `migration.json` | 858 | `8ebdd1f50cad2691b09439ede595d3bd7613b3b4466bdc3d29373d4cc32889b1` |
| `migration.sig` | 97 | `00455c50916e106e4f2c491a3df7a6746a191700f2c0b2546c84a8e15bea7cf5` |
| `release-public.pem` | 178 | `5e0fc99bf3a221f53129595ea31371cdb8eca502a4e9a7fd956855b98d450ccc` |

Normalbygget har 63 796 byte statisk RAM og 2 393 377 byte rapportert flashbruk.
IRAM-slutt `0x4009fb98` gir 1 128 byte margin uten utvidet linkerområde.
Recovery har 50 684 byte statisk RAM og 1 571 809 byte rapportert flashbruk.
Dette er byggetall, ikke fysisk målt intern heap, TLS-forbruk eller svartid.

Det genererte CI-sdkconfiget er kontrollert: factory reset aktiv, GPIO39 lav,
tre sekunder, bare OTA-valg slettes, tom DATA_FACTORY_RESET-liste, rollback
aktiv, DIO og 16 MiB flash. Bootloaderen passer før tabellen ved `0x8000`.

## Signert pakke og uavhengig kontroll

Lokal pakkemappe:
`M5Stack-backend/workspace/migration/fire-os-1.2.0-rc1/`.

Mappen inneholder nøyaktig de ni filene i tabellen (normalfilen finnes også
med utgavenavnet). Ingen privat nøkkel eller installerte avhengigheter følger
med. Katalogens signerte oppføring matcher normalfilens størrelse, hash og
kildecommit. Migreringssignaturen binder de fire skrivefilene og faste offsets.

Følgende bestod etter signeringen, kjørt fra `M5Stack-backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\migrate_fire.py check --bundle workspace\migration\fire-os-1.2.0-rc1
..\M5Stack-device\.venv\Scripts\python.exe ..\M5Stack-device\tools\sign_release.py verify workspace\migration\fire-os-1.2.0-rc1\catalog-v2.json ..\M5Stack-device\certs\release-public.pem
```

USB-verktøyet bekreftet signaturer, alle filhasher, faktiske ESP32-images og
eksakt partisjonslayout. Ingen serieport ble åpnet, og ingenting ble skrevet
til enheten. Dette er PC-verifisering; FIREs egen installasjonsflyt gjenstår.

## Fysisk akseptanse gjenstår

Registrer faktisk installert hash og mål loop-/callback-tid, intern heap,
største frie blokk og stack-margin under samtidig Home/AI/lyd. Test knapper,
skjerm, LED-farger, mikrofon/høyttaler, nettbrudd og duplikate/tapte ACK.

Test Home lokalt og eksternt på brukerens HA med Windows av, inkludert
rettigheter som fjernes. Kontroller signatur-/hashavslag, inaktiv OTA-slot,
avbrudd før helsegodkjenning, watchdog/rollback og factory recovery med ødelagt
vanlig Wi-Fi/UI. Prøv begge gamle OS-slots og recovery med/uten SD/backend.
Se [recovery/README.md](recovery/README.md) og rotens fysiske sjekkliste.

Signaturen viser utgiverintegritet. Kandidaten er ikke produksjonsgodkjent
eller fysisk verifisert som følge av disse byggene og testene.

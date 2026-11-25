# FIRE OS — leveransebevis

## RC9: fysisk SD-nedlasting, bevaring og separat installasjon

Kilde `b77c579bec4b4986680f9f3be82a4afbe76f59e8`, CI 45575157747: 16 tester og tre bygg bestod.
Eksakt normal: 2 427 328 B, SHA256 `17edd52caa166558118c30ddead2d49ccc1d24360f68b326e2297eceab4fd6bd`.
To kandidatlagringer med erstatning/backup og én eksakt CI-RC9-nedlasting fra
GitHub til PSRAM/SD er fysisk kontrollert. Binær og begge kataloger er lest
tilbake, begge hele OTA-slotter/metadata er uendret fra lagring, og tidligere
RC8-binær/katalog er intakte. Separat SD-installasjon ga faktisk A19 VALID/CRC,
CI-byteidentitet og normal omstart. Begge slotter er ren RC9, COM3 lukket.
Backend bekreftet en komplett oversikt fra sluttoppstarten: 7/7 app-ID-er,
versjoner, checksums og normaliserte pakke-ID-er var identiske med den varige
komplette referansen fra før RC9/SD-installasjonen. Dette var ikke RC2-baseline.
Lagring var klar, health/UI svarte 200, og fire transportkanaler var feilfrie.
Se [kanonisk fysisk rapport, minnefunn og avgrensninger](PHYSICAL_SD_2026-11-25.md).

Offentlig USB-ZIP: 2 653 766 B, SHA256
`c6e493690669406794c7cf663080f3d0b925fa61c7f83b98c2a9742c143c7bf7`.
Root har faktisk kontrollert signaturer, image, layout og ny utpakking med
migrerings-CLI; gamle versjonsfiler er bevart. Distribuert oppstartsgrunnlag er
de byteidentiske fysisk verifiserte RC2-komponentene med separat proveniens.
Normal er eksakt RC9 CI. Ingen påstand om homogent RC9-komponentbygg.

Ren produksjon målte løkkegap 92 998 µs; vanlig omstart
85 996 µs. Private fixture-tall er dokumentert separat og
holdes utenfor generelle produksjonspåstander. Home/AI/lyd, visuelle knapper og
fysisk recoveryhold gjenstår. Den historiske SD-rotårsaken er ikke erklært løst.

## Historisk RC7: fysisk direkte GitHub-oppdatering

Kilde `7eb40b7e0effca647d101031c777832aa672a010`, CI 45496282327:
15 tester og tre bygg bestod. Faktisk GitHub-nedlasting/OTA, UI-avbrudd ved 1 %,
uendret bootvalg, eksplisitt nytt forsøk, normal RC7-boot, CI-byteidentitet,
sekvens 10 VALID/CRC og vanlig omstart er fysisk kontrollert. Begge slotter har
ren CI-produksjon, app1 er valgt, ingen testharness er igjen og COM3 er lukket.
Backend bekreftet nyere komplett oversikt fra sluttoppstarten: 7/7 app-ID-er,
versjoner, checksums og normaliserte pakke-ID-er matchet RC2. Lagring var klar;
health-UI svarte 200, og fire Reverse TCP-kanaler var klare uten feil.
Se [fullt fysisk bevis, teststyringsrace og avgrensninger](PHYSICAL_USB_2026-11-24.md).

Normal: 2 422 464 B, SHA256
`55228972417300566da9c96a7c888b685cb7ec6d17a3b176b33cbc2d1df0c372`.
Offentlig USB-ZIP: 2 646 099 B, SHA256
`eec3e649611e972e40afe9d34a900e4edebd05f0e4200989896983cb52541c77`.
Eksakt utpakking `workspace/release-verify/fire-os-1.2.0-rc7` ble kontrollert av
masters faktiske migrerings-CLI. RC2-bootloader/tabell/recovery beholdes
byteidentisk med separat kilde-/CI-proveniens; normal kommer fra RC7 CI.

Produksjon målt passivt 125,015 s: løkkegap 85 014 µs;
vanlig resetopptak 45,043 s: løkkegap 86 013 µs.
Oppdateringstesten nådde 176 143 µs gap; ingen generell 100 ms-garanti påstås.
SD-nedlasting er fjernet fra GitHub-menyen etter påvist EIO/FatFS-krasj;
den underliggende SD-feilen er ikke erklært rettet. Offline SD-installasjon,
Home/AI/lyd, visuelle knapper og fysisk recoveryhold gjenstår.

## Historisk RC5: fysisk målt normal og signert sluttpakke

Kildecommit `958415d20029939a0e105f4ee23aa6008a7ab567`.
[CI 45477480676](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45477480676)
bestod 13 tester og normal-, recovery- og bootloaderbygg. Bare eksakt
CI-normal ble installert og målt. Artefaktarkivet var 25 492 851 byte,
SHA256 `152bcc7adb254c62e55681cbd79aa67daf12105a9de0a82a65b86e081bbe9e39`.

RC5 kjørte 125,221 sekunder med maks løkke/gap 83 048/87 988 µs, og vanlig
omstart 45,009 sekunder med 80 684/86 013 µs. Faktisk sekvens 4 VALID=2 med
korrekt CRC ble lest i flash. RC4 app0 er bevart som tilbakevei; factory er
urørt. Ingen ekstra reset, kjent panic/watchdog eller RGB-timeout ble sett.
Begge opptak hadde komplette inventarskanninger med sju apper; backend
bekreftet uendrede app-/versjons-/hash-/pakkeidentiteter. Ingen backend-
callback på minst 10 ms ble logget. Ingen Lua-app, AI, BUILD/RUN ble kjørt.

Dette består **under 100 ms løkkegap for oppstart/inventar i denne faktiske
testen**. Det er ikke fysisk produksjonsgodkjenning av alle brukerflyter.
RC2s 1,39-sekunderspause, RC3/RC4s mellomresultater og alle avgrensninger
står i [kanonisk USB-rapport](PHYSICAL_USB_2026-11-24.md). COM3 er frigitt.

Sluttpakke: `M5Stack-backend/workspace/migration/fire-os-1.2.0-rc5/`.
Pakkeren og PC-konsumenten har kontrollert signaturer, hasher, faktisk ESP32-
image og layout. Normal kommer fra RC5 CI. Bootloader, tabell og recovery
er de byteidentiske, fysisk testede RC2-komponentene fra kilde
`7efbae95fa0a54aeb3e1d6a615390810b69279b4`, CI 45431615060.
Komponentene er bevisst valgt og dokumentert separat, ikke fremstilt som
et homogent RC5-bygg. Signert manifest binder alle komponenthasher;
`component-provenance.json` er supplerende revisjonsbevis.

| Fil | Byte | SHA256 |
| --- | ---: | --- |
| `normal.bin` / `fire-os-1.2.0-rc5.bin` | 2408576 | `6499092470f40287776fcac49fa73abc225c1f420b41ebb8c4ea76bce1d004e7` |
| `recovery.bin` (RC2) | 1578112 | `040b2c66a800fb4456a3aac2b7436af19fc4c53a6565b45ec63146229f55c1d5` |
| `bootloader.bin` (RC2) | 27760 | `8ba4fc406ecb04ee55a11ee2b59c485c4dd9e2bd94a802f4f919466332567f64` |
| `partitions.bin` (RC2) | 3072 | `66f473bf47827c01ff3fc4af089c45b070b67a056df78cba704d3390535cd120` |
| `catalog-v2.json` | 1030 | `4e7d5339e645f94d616636f97b40c2e969b8b011e32e147196e43f2c2c9c14ff` |
| `migration.json` | 858 | `120dc8a5d8dea62a572ec4e3f3ea6aa9502e59c447c919e0b6a187dbb6da0bf8` |
| `migration.sig` | 97 | `a511745509de971cc9814077f7e393ea4ab8c648915532c2606c9c37daea4c1d` |
| `component-provenance.json` | 1287 | `09a9c38d80ba0be67fcde85ed145479376ce0b8b54022cf6c1a54773bc9f5314` |
| `release-public.pem` | 178 | `5e0fc99bf3a221f53129595ea31371cdb8eca502a4e9a7fd956855b98d450ccc` |

Ingen privat nøkkel, fullbackup eller rålogg følger med. Rotbinær, USB-arkiv
og samlet katalog er ferdig lokalt med RC5 først, historisk RC2 og RC1.
Private RC3/RC4-testbinærer skal ikke publiseres. Master håndterer publisering;
RC1/RC2-utgivelsesfiler er urørt.

Master har laget og kontrollert rotens `fire-os-1.2.0-rc5-usb.zip`:
2 637 224 byte, SHA256
`31a22078f5441cf2428bac651aa18f1f89f3c73ba214996ad61392d68effb533`.
Uavhengig kontroll med faktisk PC-konsument bestod både originalpakke og
separat ny utpakking av rotarkivet. Rotbinæren har samme normale SHA256 over.

Samlet signert `firmware/index.json`: 2 054 byte, SHA256
`b5574b42aeb3645e540fa879ac7b4f64c6f5ebe6fb6a71ae28992747e716ad1d`.
Rekkefølge: RC5, historisk RC2 med råd om RC5 på grunn av UI-pauser,
historisk RC1 med tidligere notat. Alle tre binærer ble hashkontrollert og
uendret før/etter; arkivert RC2-katalog er byteidentisk og signaturgyldig.
Katalogen ble signert og kontrollert lokalt; master håndterer git/publisering.

Før publisering ble bare utgivelsesnotatene rettet: RC5 beskriver blokkvis
WebSocket-lesing og de målte 88/86 ms; RC1 anbefaler nå RC5. Begge kataloger
ble signert på nytt. Normal/image-, migreringsmanifest-, migreringssignatur-
og alle RC1/RC2-arkivfiler er uendret. Tidligere kataloger er bevart privat.

Etter RC5-testen stod Rikards enhet i **B/app1** med RC5 sekvens 4 VALID, og RC4 A/app0 var
bevart. Den signerte engangspakken skriver normal til **A/app0** ved en ny
migrering. Disse er ulike dokumenterte installasjonsforløp.

## RC2: signert og kontrollert

RC2 retter Home Auto-ruting: en frisk ekstern MQTT-forbindelse brytes ikke
etter ett minutt. Lokal rute vurderes igjen etter faktisk nettbrudd eller
endret konfigurasjon. Visnings-/favorittendringer starter ikke MQTT på nytt;
profil- og ruteendringer gjør det fortsatt. RC1-filene er bevart urørt.

Kildecommit: `7efbae95fa0a54aeb3e1d6a615390810b69279b4`.
[FIRE firmware checks 45431615060](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45431615060)
bestod alle 12 tester og normal-, recovery- og bootloaderbygg.
Leveransen bruker bare denne kjøringens CI-artefakter. Arkivet er 25 466 940
byte, SHA256 `12de936a14e9c424067d4dc1f111e5425ef013815ce40d52fc3d4608dcc5b5d4`.

Lokal pakke: `M5Stack-backend/workspace/migration/fire-os-1.2.0-rc2/`.

| Fil | Byte | SHA256 |
| --- | ---: | --- |
| `normal.bin` / `fire-os-1.2.0-rc2.bin` | 2399824 | `c25aca3f58f3caa947f86bede567d6b987d0a654406caa98ef441ca00819b223` |
| `recovery.bin` | 1578112 | `040b2c66a800fb4456a3aac2b7436af19fc4c53a6565b45ec63146229f55c1d5` |
| `bootloader.bin` | 27760 | `8ba4fc406ecb04ee55a11ee2b59c485c4dd9e2bd94a802f4f919466332567f64` |
| `partitions.bin` | 3072 | `66f473bf47827c01ff3fc4af089c45b070b67a056df78cba704d3390535cd120` |
| `catalog-v2.json` | 1002 | `313344c52168e3e87b4faf05b9a35c0b036f2bf9a2289d74a28f5db599e9f2dc` |
| `migration.json` | 858 | `ed18d01d5702679387c56c9f18bb8261d8aa5f3e7e5c1ffdda27501754974b07` |
| `migration.sig` | 97 | `de8b049247ff2b581495ca9d7cf630f1e03bcb16e13af507651e242052407856` |
| `release-public.pem` | 178 | `5e0fc99bf3a221f53129595ea31371cdb8eca502a4e9a7fd956855b98d450ccc` |

USB-verktøyets uavhengige `check --bundle workspace/migration/fire-os-1.2.0-rc2`
bestod signatur-, hash-, faktisk ESP32-image- og layoutkontroll. Signerings-
verktøyet verifiserte også katalogsignaturen og den ene RC2-oppføringen.
Ved denne pakkekontrollen ble ingen serieport åpnet eller enhet skrevet.
Den senere fysiske USB-migreringen er dokumentert nedenfor. Ingen privat
nøkkel følger med. USB-pakkens katalog inneholder bare RC2. Samlet signert rotkatalog er laget med
RC2 først og historisk RC1 som andre oppføring. RC1-notatet anbefaler RC2 på
grunn av minuttfrakoblingen i RC1 Auto. Original RC1-arkivkatalog, RC1-filer og
hele RC2-USB-pakken er kontrollert uendret før/etter kataloggenereringen.

`firmware/index.json`: 1 538 byte, SHA256
`b8de65b28e2138f150f7e4bfb64734d4133fa16acfeccc041924b6de2547d0b4`.
Begge katalogsignaturer og tilhørende binærhasher består verifikasjon.

Master pakket rotens `fire-os-1.2.0-rc2-usb.zip`: 2 632 282 byte, SHA256
`81bd55a47f62b79af1cfd72729517623643d8e4c167b033f4a1946e9d024627b`.
Master har kontrollert en separat utpakking med det faktiske USB-verktøyet.

CI-normalbygget rapporterer 63 796 byte statisk RAM og 2 393 397 byte flashbruk.
Recovery rapporterer 50 684 byte RAM og 1 571 809 byte flashbruk. IRAM-slutt er
fortsatt `0x4009fb98` (1 128 byte margin). Generert CI-sdkconfig er kontrollert:
GPIO39 lav/tre sekunder velger factory recovery ved å slette bare OTA-valget;
rollback er aktiv og data-reset-listen tom.

## Senere fysisk RC2-test 24. november

Signert RC2 er installert med full dobbeltbackup og readbackkontroll.
Factory recovery, kontrollert SDK-rollback med ABORTED=4, 125 sekunder normal
drift, faktisk VALID=2 i flash og ytterligere 45 sekunders normal omstart er
bekreftet. Ingen krasj/resetløkke ble observert. Responskravet er ikke bestått:
en tidlig pause på omtrent 1,39 sekunder gjentas og undersøkes separat.
Se [målinger, prosedyre og avgrensninger](PHYSICAL_USB_2026-11-24.md).

Fysisk sluttkontroll gjenstår, særlig stabil ekstern Auto-forbindelse over
flere minutter, visningsendring uten frakobling, faktisk nettbrudd med nytt
rutevalg, fysisk recovery-knapphold og nett-/SD-OTA. Bygg- og signaturbevis er
ikke bevis på fysisk kjøring. Øvrig fysisk sjekkliste nedenfor gjelder fortsatt.

## Historisk RC1-leveranse

Historisk status ved RC1-leveransen: fysisk sluttkontroll gjenstod og ingen
enhet var flashet. Senere RC2 USB-test er beskrevet ovenfor.
Master håndterer publisering og den samlede overleveringen.

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

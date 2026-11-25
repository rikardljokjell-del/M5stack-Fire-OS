# Fysisk Data Engine-kontroll – 25. november 2026

## RC2: USB og vanlig oppstart bestått

Ren `fire-os-1.5.0-rc2` fra CI ble installert i inaktiv B. Bildet er
2 602 256 byte, med SHA256
`e0df55a4d2eac4116bc876fd4e4710f66564be2dbee9a51fe705027460e1a80e`.
Flashens MD5-kontroll og én tilbakeavlesning av hele normalbildets eksakte
lengde samsvarte med CI-filen. Resten av den store B-partisjonen ble ikke
tilbakeavlest på nytt.

Kilde: `8ab274f67be080a0b72494703e59b4b5f70c024d`. Firmware-CI
`45709316709`, jobb `139539334204`, artefakt `15066223828`: 25 native- og
utgivelsestester samt normal-, recovery- og bootloaderbygg bestod.

Enhet, sikkerhetsoppsett og partisjonslayout ble kontrollert før skriving.
Kun B-bildet med sektorpadding og én ordinær NEW-metadataoppføring ble
skrevet. Bootloader, partisjonstabell, recovery, NVS og SD ble ikke skrevet
av USB-prosedyren. Reservebildet `fire-os-1.4.0-rc3` i A ble bevart uten
bildeskriving; fersk A-headerkontroll samsvarte med tidligere verifisert bilde.

Firmware godkjente selv oppstarten gjennom den vanlige lokale helsekontrollen.
Tilbakeavlest metadata viste **B sekvens 50 VALID** og **A sekvens 49 VALID**,
begge med gyldig CRC. A-metadataoppføringen var byteidentisk før og etter
oppdateringen. Ingen tvungen VALID-status ble brukt.

## Observerte oppstartsmålinger

| Kontroll | Varighet | Rapportert loopmaks | Rapportert gapmaks | Lua-callback | Panic / abort / WDT |
| --- | ---: | ---: | ---: | ---: | --- |
| Lokal helsekontroll | 45,021 s | 138 297 µs | 144 002 µs | 0 µs | 0 / 0 / 0 |
| Påfølgende vanlig omstart | 35,097 s | 148 167 µs | 153 007 µs | 0 µs | 0 / 0 / 0 |

Hver oppstart ga ett diagnostikkpunkt. Minste rapporterte internheap var
henholdsvis 62 144 og 65 660 byte; stackmarginen var 4 440 og 4 424 byte.
Begge rapporterte null RGB-tidsavbrudd. Dette er korte oppstartsobservasjoner,
ikke en måling av sensoropptak eller langtidsstabilitet.

Serieporten ble lukket etter den vanlige omstarten. Ingen appinstallasjon,
RUN, AI-kall, maskinvarestyring eller simulerte knappetrykk ble utført som
del av denne USB-kontrollen.

## Gjenstående fysisk appflyt

IMU-opptak og faktisk samplerate, markører, mikrofon/BLE-opptak, overføring
av data/index/events, deterministisk analyse og Improve er **ikke bekreftet
av dette oppstartsbeviset**. Resultatet fra den vanlige måleappprøven skal
føyes til denne samme rapporten når det foreligger. Ukjente eksterne moduler
og Bluetooth-lys er ikke fysisk verifisert.

## Tillegg: vanlig måleapp installert og startet

Backend bekreftet deretter fullført normal installasjon av den håndskrevne
kontrollappen «Måledata kontroll». Vanlig RUN ga kildebundet oppstart og
healthy-status i omtrent 20 sekunder, ifølge backendens faktiske kvitteringer.
Dette er installasjons- og oppstartsbevis for appen, ikke PC-simulering.

Backend hadde på dette kontrollpunktet ikke mottatt noen `data_request`,
og intet datasett eller analyseresultat var bekreftet. Opptak, samplerate,
rådata, komponentoverføring og analyse er derfor fortsatt uavklart.
Healthy-status alene viser ikke at appens lokale opptaksjobb lyktes.
Faktisk LCD-status avventes; 1.5-kandidaten er ennå ikke offentlig publisert.

Det tidligere passive loggvinduet var avsluttet før denne faktiske appstarten
og dokumenterer ikke måleappens kjøring. Serieporten holdes lukket. Ingen
egne knappetrykk eller nye enhetskall ble gjort for dette rapporttillegget.

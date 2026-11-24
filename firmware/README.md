# FIRE OS firmware

Aktuell **testkandidat: fire-os-1.2.0-rc6**. Vanlig oppdatering går nå direkte
fra GitHub til inaktiv OS-slot, uten SD-kort eller backend. Velg
**Settings → Firmware → Oppdater fra GitHub → utgave → Installer direkte fra GitHub**
og bekreft med B. FIRE kontrollerer signatur, størrelse, nettverksdata og
tilbakeavlest flash før ny firmware velges og enheten starter om.
**Lagre pa SD** er et separat, valgfritt valg.

Alle 15 tester og tre bygg er bestått på kilde
[55a8584](https://github.com/rikardljokjell-del/M5stack-Fire-OS/commit/55a8584e8216a2760781d562b88be42679ddf387),
[CI 45492728362](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45492728362).
Den fysiske RC6-testen pågår; dette er ikke full produksjonsgodkjenning.
Normal RC6 er ny, mens USB-pakken bevarer de fysisk testede
RC2-bildene for bootloader, partisjonstabell og recovery med separat opphav.

| Gjeldende RC6-fil | Bruk |
| --- | --- |
| [Normal firmware](fire-os-1.2.0-rc6.bin) | Direkte, signert GitHub-oppdatering |
| [USB-arkiv](fire-os-1.2.0-rc6-usb.zip) | Førstegangsmigrering på en annen enhet |
| [Kontrollsummer](fire-os-1.2.0-rc6-SHA256SUMS.txt) | Eksakte filhashes |
| [Utgivelsesbevis](fire-os-1.2.0-rc6-evidence.json) | CI, komponentkilder og faktisk teststatus |

## Historisk RC5

RC5 beholdes uendret med [original katalog](fire-os-1.2.0-rc5-catalog.json).
SD-skrivefeilen er gjenskapt på fysisk FIRE, og installasjonsbekreftelsen hadde
en separat feil. Bruk RC6. Følgende er de tidligere USB-målingene:

RC5 ble fysisk installert på
Rikards FIRE og helsegodkjent. Målt maksimal løkkeavstand ved oppstart og
appinventering var 88 ms, og 86 ms etter vanlig omstart; tidligere RC2 nådde
1 391 ms. Ingen krasj eller ekstra reset ble sett i de avgrensede opptakene.
Dette er ikke full produksjonsgodkjenning av Home, tale, apper og GitHub-OTA.

| Fil | Bruk |
| --- | --- |
| [RC5 USB-arkiv](fire-os-1.2.0-rc5-usb.zip) | Signert førstegangsmigrering med fire bilder og alle åtte nødvendige filer |
| [RC5 normal firmware](fire-os-1.2.0-rc5.bin) | Direkte oppdatering etter migrering, sammen med signert katalog |
| [index.json](index.json) | Signert schema 2-katalog med nyeste kandidat først |
| [Kontrollsummer](fire-os-1.2.0-rc5-SHA256SUMS.txt) | SHA256 for normalbinær og USB-arkiv |
| [Utgivelsesbevis](fire-os-1.2.0-rc5-evidence.json) | Eksakte filhashes, komponentkilder, CI og avgrensede fysiske resultater |

Start med [samlet oppsett](../SETUP.md) og [fysisk test](../docs/PHYSICAL_CHECK.md).
**Rikards enhet er allerede migrert og kjører RC5 i B / app1.** Forrige
private testversjon i A og separat factory recovery er beholdt. En ny enhet
bruker [USB-veiledningen](../M5Stack-backend/docs/USB_MIGRATION.md); pakken
er også klargjort lokalt i
`M5Stack-backend/workspace/migration/fire-os-1.2.0-rc5/`.

RC5 retter gjentatt bytevis SD-lesing ved appoversikt, konsistent rapportering
av pakkeidentitet, ventende nettverkssvar i Auto, skjermrammebudsjett og
bytevis TCP/WebSocket-lesing. Første normalmåling var 125 sekunder, etterfulgt
av flashlesing som bekreftet VALID og en 45-sekunders vanlig omstart.
[Fysisk USB-rapport](../M5Stack-device/PHYSICAL_USB_2026-11-24.md) har scope og mellomresultater.

Normalbildet er fra kilde
[958415d](https://github.com/rikardljokjell-del/M5stack-Fire-OS/commit/958415d20029939a0e105f4ee23aa6008a7ab567),
[CI 45477480676](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45477480676),
med 13 tester og tre grønne bygg. Den distribuerte pakken **gjenbruker de
fysisk testede RC2-bildene for bootloader, partisjonstabell og recovery**;
normal RC5 er ny. De separate komponentkildene står i utgivelsesbeviset.
Alle fire eksakte bilder er bundet av den signerte migreringsplanen.
Det er ikke påstått at alle fire kommer fra samme kildecommit.

Etter engangsmigreringen bruker du **Settings → Firmware** på FIRE.
FIRE kontrollerer signatur, mål, størrelse og SHA256, og skriver bare inaktiv
OS-slot. Bootloader, partisjonstabell og factory beholdes ved normal OTA.
Redning kan velges med A før vanlig OS og hente signert firmware uten SD
eller Windows. Fysisk knapphold, GitHub-OTA og tidligere normal OTA-slot skal
fortsatt prøves; USB-testen av tidlig reset viste tilbakeføring til factory.
Backendens firmwarevisning viser bare versjoner og informasjon.

Historisk RC2 beholdes uendret med
[original katalog](fire-os-1.2.0-rc2-catalog.json). Bruk RC5: RC2 hadde målte
UI-pauser ved appinventering. Historisk RC1 beholdes også med
[original katalog](fire-os-1.2.0-rc1-catalog.json); den kunne bryte frisk Home
Auto-forbindelse hvert minutt. RC3/RC4 var private USB-mellomtester.

`fire-os-1.1.bin` og [legacy-index-v1.json](legacy-index-v1.json) beholdes for
Studio-historikk. Den usignerte gamle utgaven er ikke en oppdatering for den
nye recovery-layouten. Private signeringsnøkler følger aldri med.

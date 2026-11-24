# FIRE — fysiske USB-bevis 2026-11-24

## Sluttresultat: RC5 installert og målt

Enheten står i normal **fire-os-1.2.0-rc5**, app1 ved `0x650000`, med faktisk
OTA-sekvens 4 **VALID=2** og gyldig SDK-CRC lest fra flash. RC4 app0 med
sekvens 3 VALID er bevart som tilbakevei, og factory recovery/bootloader/
partisjonstabell er de fysisk verifiserte RC2-komponentene. COM3 er lukket.
Opprinnelig 16 MiB dobbeltbackup og alle rålogger er private og ignorerte.
En ny engangsmigrering med sluttpakken plasserer normal i A/app0; dette er
et annet installasjonsforløp enn den målte enhetens nåværende B/app1.

RC5-kilde: `958415d20029939a0e105f4ee23aa6008a7ab567`.
[CI 45477480676](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45477480676)
bestod 13 tester og alle tre bygg. Eksakt fysisk testet normal-image er
2 408 576 byte, SHA256
`6499092470f40287776fcac49fa73abc225c1f420b41ebb8c4ea76bce1d004e7`.
Statisk RAM er 63 796 byte, IRAM-slutt `0x4009fb98` (1 128 byte margin).

Før skriving ble identitet, sikkerhet, layout, fullbackupens diskhash, RC4 i
app0 og factorygrunnlaget kontrollert igjen. Eksisterende RC3 i mål-slotten
ble kontrollert og bevart separat privat. Bare inaktiv app1 ble skrevet og
fullstendig lest tilbake. Deretter ble bare andre OTA-sektor skrevet med
sekvens 4 NEW=0 og SDK-CRC; RC4s første sektor var byteidentisk.

| Måling | RC5 første oppstart 125,221 s | RC5 vanlig omstart 45,009 s |
| --- | ---: | ---: |
| Maks OS-løkke, µs | 83 048 | 80 684 |
| Maks startavstand, µs | 87 988 | 86 013 |
| Minste målt ledige interne heap, byte | 99 524 | 99 508 |
| Historisk minimum intern heap, byte | 78 456 | 79 444 |
| Minste målt største internblokk, byte | 90 100 | 86 004 |
| Laveste målt stakkreserve, byte | 5 108 | 5 108 |
| RGB-timeouts | 0 | 0 |

Alle fire utvalg i første opptak hadde samme løkke-/gapmaksimum. Begge opptak
hadde én app1-oppstart og ingen ekstra reset, Guru Meditation, abort eller
watchdog. Første oppstart gav lokal helsegodkjenningsmarkør. Etterpå bekreftet
ROM-lesing faktisk sekvens 4 VALID=2 med korrekt CRC og uendret RC4-sektor;
vanlig reset startet godkjent RC5 igjen.

**Under 100 ms løkkegap er bestått i denne faktiske oppstarts-/inventartesten.**
Den målte RC2-pausen på 1 391 000 µs er redusert til 87 988 µs her. Målingen
omfatter oppstarten; livstidsmaksima ble ikke nullstilt eller filtrert bort.
Dette er ikke en generell garanti for alle menyer, nettforhold eller apper.

Begge RC5-opptak hadde to komplette skanninger med sju apper: 3 303/3 164 ms
og 3 295/3 117 ms veggtid fordelt over mange UI-runder. Master/backend
bekreftet ferskt RC5-inventar med 7/7 like app-ID-er, versjoner, checksums og
normaliserte pakke-ID-er, tilgjengelig SD og `complete=true`. Ruten var privat
Reverse TCP med fire autentiserte kanaler. Ingen AI, BUILD/RUN eller Lua-app
ble kjørt. Lua-callbackmaksimum 0 gjelder bare dette fraværet av appkjøring.

RC5 leser WebSocket-payload i blokker på opptil 256 byte, innen eksisterende
2 048-bytebudsjett og et kooperativt 10 ms lesebudsjett. Header-, maskerings-
og fragmenttilstand fortsetter mellom rundene. En enkelt synkron native
callback kan overskride budsjettet; begge opptak hadde **ingen loggede
backend-callbacker på minst 10 ms**. Ingen enkelt målt fase på minst 100 ms
ble logget. Dette skjuler ikke de uavhengige løkke-/gapmaksimaene over.

Signert sluttpakke finnes lokalt i backendens
`workspace/migration/fire-os-1.2.0-rc5/`. Normal kommer fra RC5 CI over;
bootloader, tabell og recovery kommer byteidentisk fra RC2-kilde
`7efbae95fa0a54aeb3e1d6a615390810b69279b4`, CI 45431615060. Signert
migreringsmanifest binder alle komponenthasher; `component-provenance.json`
oppgir de separate kildene. Dette er den faktisk testede kombinasjonen,
ikke et homogent RC5-bygg av alle komponenter. RC3/RC4 nedenfor er privat
testhistorikk og skal ikke inn i offentlig firmwarekatalog.

## RC2: første migrering og rollback

Dette gjelder den signerte RC2 fra kildecommit
`7efbae95fa0a54aeb3e1d6a615390810b69279b4`, med byte og hasher i
[DELIVERY_REPORT.md](DELIVERY_REPORT.md). Ingen RC2-utgivelsesfiler ble endret.

## Migrering og backup

Fysisk preflight bekreftet klassisk ESP32, 16 MiB flash og kompatible
sikkerhetsinnstillinger. Migrering med det eksisterende PC-verktøyet fullførte
med exit 0 på 520,2 sekunder. Hele 16 MiB ble lest to ganger og sammenlignet;
backupens lagrede SHA256 ble kontrollert før første skriving og uavhengig av
master etterpå. Hvert skrevet image, partisjonstabell og bootloader ble lest
tilbake og kontrollert. Bare avtalte migreringsområder ble skrevet; OTA-valget
ble slettet og kontrollert. Ingen full erase, eFuse-endring eller vanlig
PlatformIO Upload ble brukt.

Fullbackup, rålogger, sikkerhetsidentitet og engangsverktøy oppbevares privat
under backendens ignorerte `workspace/`. De kan inneholde lokale hemmeligheter
og følger ikke med kilde eller utgivelse.

## Observerte oppstarter og rollback

1. Factory recovery ved `0xc90000` startet etter migreringen og ble observert
   i 45,155 sekunder uten ekstra reset, Guru Meditation, abort eller watchdog.
2. Installert app0 ble på nytt kontrollert mot signert RC2/hash og valgt ved
   å skrive bare 8 KiB OTA-metadata (`0xe000..0xffff`): sekvens 1, NEW=0,
   SDK-CRC `0x4743989a`, resten `0xff`. Original metadata ble bevart privat.
3. Etter mottatt `FIRE OS started` ble én vanlig reset utført 2,724 sekunder
   **fra den første resetkommandoen**, før 15-sekunders helsegodkjenning.
   UART viste app0, så factory recovery. Ny lesing av flash bekreftet
   ABORTED=4 med gyldig CRC. Observasjon varte i 80,149 sekunder; ingen
   helsegodkjenningsmarkør, Guru Meditation, abort eller watchdog ble sett.
4. App0 ble kontrollert igjen og valgt NEW på samme avgrensede måte. RC2
   kjørte i 125,144 sekunder med én oppstart og helsegodkjenningsmarkøren
   `FIRE OTA local self-test accepted; network/physical matrix not implied`.
   Ingen resetløkke, Guru Meditation, abort eller watchdog ble sett.
5. ROM-lesing av faktisk OTA-metadata bekreftet **VALID=2**, sekvens 1 og
   gyldig CRC; andre sektor var fortsatt slettet. Ingen flashskriving ble
   brukt til denne kontrollen. Deretter startet vanlig reset app0 igjen,
   observert i 45,223 sekunder uten ekstra reset eller kjente krasjmarkører.

Ved slutten av RC2-fasen ble enheten etterlatt i helsegodkjent normal RC2,
og COM3 ble lukket. Senere RC3-test er beskrevet nedenfor.
Dette er en kontrollert USB-test av SDK-rollback; den beviser ikke GitHub-OTA,
fysisk knapphold eller feil under firmwareflash.

## Målinger og åpent responsfunn

| Måling | Normal 125 s | Godkjent omstart 45 s |
| --- | ---: | ---: |
| Maks OS-løkke, µs | 1 385 952 | 1 376 756 |
| Maks startavstand, µs | 1 391 000 | 1 382 000 |
| Intern ledig heap, minste utvalg, byte | 102 568 | 102 556 |
| Historisk minimum intern heap, byte | 77 588 | 73 056 |
| Minste målt største internblokk, byte | 90 100 | 73 716 |
| Laveste målt stakkreserve, byte | 4 512 | 4 496 |
| RGB-timeouts | 0 | 0 |

Alle fire 30-sekundersutvalg i normaltesten hadde identiske løkke-/gapmaksima.
Pausen oppstod dermed før første utvalg, og ingen større pause kom senere.
Den gjentok seg ved omstart. **Responskravet er ikke godkjent.** Synkron
SD-appinventering ved backendtilkobling er et konkret undersøkelsesspor:
hvert manifest leses fire ganger bytevis fra UI-løkken. Wi-Fi-oppstart er
også et mulig spor; årsaken er ennå ikke målt per fase.

Callback-maksimum 0 betyr at ingen Lua-callback ble kjørt i disse testene.
Største ledige blokk er periodisk målt, ikke kontinuerlig minimum.

## RC3: første fysiske effektmåling

Normal-kilde `3e0d5eb6353e3a6bcdf8b6d4b50f5af090f3edc0` bestod CI
45472599229 (13 tester og alle tre bygg), samt separat native CI 45472599470.
Bare den faktiske CI-normalfilen ble brukt: 2 407 984 byte, SHA256
`4e629f652d5c955fbf39d44d20919eabe3efcf3caf605ceb4ccf37ec63694b00`.
IRAM-slutt er fortsatt `0x4009fb98`.

En privat signert testkatalog bandt kilde og image. Før skriving ble identitet,
sikkerhet, layout, fullbackupens diskhash og eksisterende RC2 app0, recovery
og bootloader kontrollert igjen. Innholdet som skulle erstattes i app1 ble
sammenlignet med originalbackupen og bevart separat privat.

Bare inaktiv app1 ved `0x650000` ble skrevet. Etter full image-readback ble
bare andre OTA-sektor ved `0xf000` skrevet med sekvens 2, NEW=0 og SDK-CRC.
Første sektor med RC2 sekvens 1 VALID ble beholdt byteidentisk. Factory,
bootloader, tabell og konfigurasjon ble ikke skrevet. Det var ingen ny full
migrering. Dette tester vanlig OS sammen med det fysisk verifiserte RC2-
redningsgrunnlaget; det er ikke et homogent RC3-bygg av alle komponenter.
RC3s felles nettverksklient har ny drain-måling som også finnes i den ubrukte
CI-recoverykilden. Den beholdte recoveryen tilskrives derfor uttrykkelig RC2.

RC3 startet én gang fra app1 og ble observert i 125,279 sekunder. Lokal
helsegodkjenningsmarkør kom, og etterfølgende ROM-lesing bekreftet faktisk
sekvens 2 VALID=2 med korrekt CRC. RC2s OTA-sektor var fortsatt uendret.
Vanlig reset startet godkjent app1 igjen, observert i 45,503 sekunder.
Begge opptak hadde null ekstra reset, Guru Meditation, abort og watchdog.
Enheten ble etterlatt i denne godkjente RC3-kandidaten; COM3 ble lukket.

| Måling | RC3 125 s | RC3 normal omstart 45 s |
| --- | ---: | ---: |
| Maks OS-løkke, µs | 127 112 | 134 627 |
| Maks startavstand, µs | 132 001 | 139 861 |
| Intern ledig heap, minste utvalg, byte | 99 408 | 99 520 |
| Historisk minimum intern heap, byte | 83 668 | 81 656 |
| Minste målt største internblokk, byte | 86 004 | 81 908 |
| Laveste målt stakkreserve, byte | 5 108 | 5 108 |
| RGB-timeouts | 0 | 0 |

Alle fire RC3-utvalg hadde samme løkke-/gapmaksimum. Den tidligere pausen på
omtrent 1,39 sekunder ble ikke observert; maksimal avstand var redusert med
omtrent 90 prosent. Appskanningen fant sju apper, komplett, fordelt over
3 809 ms veggtid. Etter omstart ble samme komplette antall lest i to
skanninger (3 618 og 3 696 ms). Dette er trinnvis arbeid mellom UI-runder,
ikke én blokkering på den samlede veggtiden.

Master/backend bekreftet ferskt RC3-hello og inventar med `complete=true`,
SD tilgjengelig, og 7/7 like app-ID-er, versjoner, checksums og normaliserte
pakke-ID-er mot RC2. Dette gir faktisk SD-manifestlesings- og rapporteringsbevis.
Den observerte backendruten var eksisterende privat Reverse TCP med fire
autentiserte kanaler; dette beviser ikke offentlig TLS eller AI-kjøring.

Faseprofileringen viser fortsatt kostbar skjermtegning: opptil 58 447 µs i
første opptak og 71 536 µs ved omstart. Backend-service hadde enkelte kall på
51 631/53 390 µs. Faseloggen alene kobler ikke alle varigheter til samme
løkke og etablerer derfor ikke den eksakte summen bak maksimumet. Kilden
tillater to tegninger i én løkke når både tidlig redraw og periodisk tegning
slår inn. En smal sperre mot dobbel tegning vurderes før endelig kandidat;
**under 100 ms er ennå ikke bevist**. Ingen Lua-callback ble kjørt.

## RC4: avgrenset skjermbudsjett, responskravet ikke bestått

Kilde `6f1ad8106c1822cde2bc57d18b43e46a47472495`, CI 45475054817,
bestod 13 tester og alle tre bygg. Eksakt normal-image var 2 408 064 byte,
SHA256 `a2afc1e6a732b3639581043961fa348c64c32e636dda5809e401a44834356828`.
Kun inaktiv app0 ble skrevet/readbackkontrollert; NEW sekvens 3 ble skrevet
bare til første OTA-sektor. RC3 app1 med sekvens 2 VALID og factorygrunnlaget
ble kontrollert og beholdt. Før erstattelsen ble eksisterende app0 bevart
separat privat, i tillegg til opprinnelig fullbackup og signert RC2-pakke.

RC4 begrenser tegning til én full ramme per runde og utsetter sen tegning
når annet arbeid har brukt 20 ms. Fysisk effektmåling godkjente **ikke**
under-100-ms-målet. Ingen RC4-pakke eller samlet katalog ble frigitt.

| Måling | RC4 125,124 s | RC4 omstart 45,201 s |
| --- | ---: | ---: |
| Maks OS-løkke, µs | 127 731 | 121 247 |
| Maks startavstand, µs | 132 996 | 127 013 |
| Minste målt ledige interne heap, byte | 97 228 | 99 444 |
| Historisk minimum intern heap, byte | 85 776 | 84 200 |
| Minste målt største internblokk, byte | 90 100 | 90 100 |
| Laveste målt stakkreserve, byte | 5 108 | 5 108 |
| RGB-timeouts | 0 | 0 |

Begge opptak hadde én oppstart av app0 og ingen ekstra reset, Guru Meditation,
abort eller watchdog. Første oppstart gav helsegodkjenningsmarkør, og faktisk
OTA-sekvens 3 VALID=2 ble lest med gyldig CRC. Andre OTA-sektor for RC3 var
byteidentisk. Vanlig omstart startet RC4 på nytt. Appinventar var komplett
med sju apper: 3 468 ms trinnvis skanning ved første oppstart og 3 307/3 332 ms
ved omstart. Master/backend bekreftet samme sju identiteter og hasher.

Ingen enkeltfase over 100 ms ble logget. Det utelukker ikke at flere kortere
faser summeres til mer enn 100 ms i samme runde. Videre undersøkelse gjelder
bytevis WebSocket-payloadlesing på den private Reverse TCP-ruten. RC4 ble
beholdt som helsegodkjent tilbakevei for neste avgrensede kandidat; COM3 lukket.

## Fortsatt ikke fysisk bekreftet

- Skjermvisning, knapper, GPIO39/A-hold i tre sekunder og recovery-valg på UI.
- Lyd, mikrofon, IMU, SD-skriving/hotplug og LED-utseende. SD-manifestlesing
  er nå bekreftet som beskrevet over. Oppstartsmarkører
  som `SD OK`/`buttons OK` bekrefter bare at init-trinnet ble passert.
- Direkte Home/Camper, MQTT/WSS, ekstern Auto over flere minutter, profilbytte,
  nettbrudd og visningsendring uten frakobling.
- GitHub-/SD-OTA, nettutfall under installasjon, AI-samtale, BUILD/RUN og apper.

Backend rapporterte RC2-hello og autentiserte reverse-kanaler under testen.
Dette er tilkoblingsbevis; det etablerer ikke stabil AI eller fysisk appkjøring.

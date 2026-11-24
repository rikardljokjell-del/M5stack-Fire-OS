# Leveransestatus – 24. november 2026

Samlet arbeid følger [godkjent plan](DELIVERY_PLAN.md). Bruk
[oppsettsveiledningen](SETUP.md) som inngang. Dette dokumentet skiller kildekode,
lokale tester og faktisk fysisk verifikasjon.

## Status nå

Kode og signert testpakke **fire-os-1.2.0-rc5** er ferdigstilt. Rikards FIRE
er fysisk USB-migrert med full backup og kjører helsegodkjent RC5 i app1.
Kontrollert tidlig omstart ga SDK-tilbakeføring til factory recovery. RC5
stod 125 sekunder og bestod vanlig omstart i 45 sekunder uten registrerte
krasj, ekstra reset eller watchdog-feil. Maksimal løkkeavstand var **87,988 ms**
og **86,013 ms**, mot **1 391 ms** før rettingene. Backend bekreftet samme
sju apper og fersk tilkobling. Se [det fysiske USB-beviset](M5Stack-device/PHYSICAL_USB_2026-11-24.md).

Dette er avgrenset fysisk oppstarts-/inventarbevis. Visuell/knapp-/lydprøve,
Home i brukerens HA, GitHub-OTA og samlet AI/appflyt står fortsatt åpne.
Produksjonsgodkjenning krever de gjenstående kontrollene under.

| Område | Implementert / lokalt kontrollert | Gjenstående bevis |
| --- | --- | --- |
| FIRE Studio | PC-/mobilvisning, innstillinger, samtale, bekreftet appbygg, jobber, bibliotek, kostnader og lesbar GitHub-firmwareoversikt | Samlet fysisk AI-/appflyt og live offentlig oppsett |
| Offentlig backend | Separate browser-/deviceverter, Access-JWT, engangspålogging lokalt, sesjon/CSRF/Origin og egne enhetstokener | Brukerens domene, konto og tunnel |
| Jobber og samtale | Samme lagring som Windows-programmet, frakoblet apputvikling, eksplisitt BUILD/RUN og sikker omstart | Nettbrudd/tale/installasjon med ny fysisk firmware |
| Direkte Home | Native kortvisning, Home/Camper, HA-styrte tillatelser, MQTT/TLS/WSS, veiviser/import; ekte HA og broker testet isolert | Brukerens entiteter/adresser og fysisk FIRE |
| Firmware/recovery | Tre bygg, 13 CI-tester, signert katalog/bundle, kontrollert USB-arkiv, fysisk oppstart/VALID/SDK-fallback og separat recovery | GitHub-OTA, redningsknapp og tidligere normal OTA-slot |

## Testbevis

- Faktisk nettleser mot isolert lokal mockserver: innlogging, forslag,
  eksplisitt bygging, ferdig jobb, bibliotek, offline installasjonsavvisning,
  innstillingslagring og GitHub-oversikt. Mobilbredde 390 px uten horisontalt
  sideoverløp; ingen nettleserfeil i kontrollen. Bildene i docs/images/ er fra
  denne testen. Produksjonsinnstillinger og OpenAI er ikke brukt i den.
- **665 backendtester bestått** på frosset kode (286,39 sekunder). Én
  Starlette TestClient-deprecation-advarsel; ingen feil. Dette inkluderer de
  nye JWT-/token-/CSRF-/Origin-kontrollene, offline utvikling, nedlastingsvern,
  omstart og eksisterende reverse TCP-transport.
  Totalen inkluderer 51 Home-tester, 31 tester av migreringsverktøyet og fem
  kontroller av den avgrensede diagnoseinnsamlingen.
- Etter fullkjøringen ble firmwareoversikten utvidet til å bevare den eldre
  GitHub-katalogen. **29 relevante katalog-/browser-/livssyklustester bestått**.
  Disse overlapper fullsuiten og skal ikke legges til som 29 unike tester.
- Home: 51 målrettede tester bestått, inkludert genererte scriptsekvenser i
  en Jinja-sandbox og faktiske strenge OpenSSL-håndtrykk. I tillegg er ekte
  Home Assistant-kjøring bestått som beskrevet nedenfor.
- Enhetens faktiske C++-headere for bytekø og JSON-kontroll er kompilert og
  begge testprogrammene kjørt grønt med g++ på Ubuntu. Inkluderer køgrenser,
  samtidige lese-/skriveoperasjoner, telleroverløp over 4 GiB, dybde-/token-
  grenser og ugyldig UTF-8. [Kontrollkjøring](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45419590919),
  kilde `76fd1127fde01019f4480a3e19b8460e72a0d740`. Dette er vertstester,
  ikke ESP32-kjøring eller fysisk nettverkslast.
- Ekte lokal backendstart og kontrollert omstart er prøvd i isolert mockprofil.
  Konfigurasjon og tokenlagring ble bevart; gammel browsersesjon avvist.
- Det eksisterende Windows-programmet ble deretter startet kontrollert på
  nytt etter kontroll av null aktive jobber/samtaler. Konfigurasjonsfil og
  OpenAI-/admin-/enhetsnøkler ble bevart. Ny `/ui/` svarer. Ingen betalt
  produksjonsforespørsel ble sendt som del av kontrollen.
- Forsøk på faktisk standard Mosquitto på denne Windows-maskinen ble blokkert
  av Windows Code Integrity for mosquitto_common.dll. Ingen sikkerhetsregel
  ble omgått. Isolert broker-røyketest er levert for egnet HA-/Linux-vert.

Ekte Mosquitto-kontroll er **bestått på Ubuntu** hos GitHub Actions: lokal TLS
med navnekontroll, WebSocket, separate listenerpassord, eksakte ACL-er og
avvisning av forfalsket state, remote→local og generell HA-lesing.
[Kontrollkjøring](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45419590750),
brokerjobb 138535122608. Windows-blokkeringen gjelder det lokale forsøket.
**Ekte Home Assistant 2026.11.3 er også bestått**, med den genererte pakken,
syntetiske enheter og ekte MQTT. Dekker faktiske handlinger/ACK, etiketter,
fjernbryter, ugyldige/utløpte/dupliserte meldinger, øktverdier, automation-reload
og en ny HA-prosess med gammel retained-forespørsel uten gjentatt handling.
[Endelig Home-kontroll](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45422781786),
kilde `17d7a7a68ed19913ba769828917e2d07d3a5abf1`.
Se [detaljert Home-bevis](M5Stack-backend/home_assistant/VERIFICATION.md).
Brukerens egne entiteter, offentlig Cloudflare/WSS og fysisk FIRE er fortsatt
åpne sluttkontroller.

## Levert firmwarepakke

RC5 erstatter synkron bytevis SD-inventering med en trinnvis, konsistent
metadataoversikt. Pakkeidentitet lagres før rapportering; mislykket skanning
publiserer ikke gamle tilstedeværelsesdata. Ventende svar og køede nettverksdata
får fullføre i Auto med frister. Skjermtegning har rammebudsjett, og WebSocket-
innhold leses i små blokker med tidsbudsjett. De fysiske tallene står over.
RC1/RC2 beholdes som uendrede historiske utgivelsesfiler. RC3/RC4 var private
USB-mellomtester og ble ikke publisert i firmwarekatalogen.

Normalfirmwarens kilde er `958415d20029939a0e105f4ee23aa6008a7ab567`.
[Linux-kjøring 45477480676](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45477480676)
bestod normal firmware med BLE/lyd, recovery, bootloader og alle **13**
C++-/signatur-/pakkekontroller. CI-arkivet er SHA256-kontrollert før utpakking.

Den distribuerte pakken gjenbruker bevisst **bootloader, partisjonstabell og
recovery fra RC2**, kilde `7efbae95fa0a54aeb3e1d6a615390810b69279b4` /
[kjøring 45431615060](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45431615060).
Dette er de uendrede, fysisk testede grunnlagsfilene. Ny normal RC5 kommer
fra den nye kjøringen. Pakken hevder ikke at alle fire bildene er bygget fra
samme kildecommit. Signert migreringsplan binder eksakte byte for alle fire;
komponentenes separate opphav står i utgivelsesbeviset.

- Normal RC5: **2 408 576 byte**, SHA256
  `6499092470f40287776fcac49fa73abc225c1f420b41ebb8c4ea76bce1d004e7`.
- [Signert USB-arkiv](firmware/fire-os-1.2.0-rc5-usb.zip): **2 637 224 byte**,
  SHA256 `31a22078f5441cf2428bac651aa18f1f89f3c73ba214996ad61392d68effb533`.
- Bare de åtte nødvendige filene er i USB-arkivet. Ny utpakking bestod faktisk
  `migrate_fire.py check` uten COM; ingen privat nøkkel følger med.
- [Maskinlesbart bevis med komponentkilder og målinger](firmware/fire-os-1.2.0-rc5-evidence.json),
  [device-rapport](M5Stack-device/DELIVERY_REPORT.md) og [firmwareoversikt](firmware/README.md).

Cloudflare CLI 2026.11.2 er også hentet og SHA256-/versjonskontrollert lokalt.
`scripts/cloudflare.ps1` bruker den lokale kopien. Ingen konto, tunnel, DNS
eller offentlig tilgang er opprettet; det krever brukerens valgte oppsett.

Historisk RC2-kontroll: Etter publisering på main `5e5853936cc10d6083dc153450e0ae2495c7b8e5`
er katalog, normalbinær, USB-arkiv, bevis og kontrollsummer hentet fra de
offentlige GitHub-adressene og sammenlignet byte for byte med leveransen.
Katalogsignaturen er verifisert på den nedlastede kopien. GitHub svarte 200
med korrekt Content-Length, uten omdirigering eller komprimering i kontrollen.
Dette er PC-bevis, ikke fysisk FIRE-nedlasting.
Den faktisk kjørende backenden svarte 200 på health og UI, og viste RC2,
historisk RC1 og 1.1 i riktig rekkefølge uten katalogfeil. Ingen omstart,
innstillingsendring eller betalte AI-kall var nødvendig i denne sluttkontrollen.

## Tidligere bevis

Ekte OpenAI-dialog, kodegenerering og validert Lua-pakke er prøvd tidligere i
prosjektet. Tidligere fysisk kontroll bekreftet pakkeinstallasjon, men avdekket
en RUN-feil; dette er ikke bevis for at den nye leveransen fungerer fysisk.
Se [E2E-status](M5Stack-backend/docs/E2E_STATUS.md) og deviceprosjektets historikk
for de eksakte avgrensningene. Den gamle påstanden om at nøkkel aldri var satt,
eller at enhetskilden aldri var endret, gjelder ikke lenger.

## Samles til slutt hos brukeren

Domene/Cloudflare-innlogging, HA-installasjonstype/MQTT-vert, valgte entiteter,
de gjenstående fysiske testene. Førstegangs USB-migrering på Rikards FIRE er
allerede utført og dokumentert. Kode, pakker, dokumentasjon og
uavhengige kontroller er klargjort før disse opplysningene etterspørres.

Produksjonsklar fysisk drift påstås først etter kontroll av oppstart,
nettbrudd, norsk tale, minne/respons, Home med Windows av og uavhengig recovery.

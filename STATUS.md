# Leveransestatus – 24. november 2026

Samlet arbeid følger [godkjent plan](DELIVERY_PLAN.md). Bruk
[oppsettsveiledningen](SETUP.md) som inngang. Dette dokumentet skiller kildekode,
lokale tester og faktisk fysisk verifikasjon.

## Status nå

Kode og signert testpakke **fire-os-1.2.0-rc1** er klargjort. FIRE Studio,
sikker offentlig backendinngang, direkte Home og OTA med uavhengig recovery
er implementert. Linux-byggfilene er signert, USB-arkivet er pakket ut på nytt
og kontrollert av det separate migreringsverktøyet. Ingen fysisk FIRE er
flashet i denne leveransen. Produksjonsgodkjenning krever sluttesten under.

| Område | Implementert / lokalt kontrollert | Gjenstående bevis |
| --- | --- | --- |
| FIRE Studio | PC-/mobilvisning, innstillinger, samtale, bekreftet appbygg, jobber, bibliotek, kostnader og lesbar GitHub-firmwareoversikt | Ny fysisk FIRE og live offentlig oppsett |
| Offentlig backend | Separate browser-/deviceverter, Access-JWT, engangspålogging lokalt, sesjon/CSRF/Origin og egne enhetstokener | Brukerens domene, konto og tunnel |
| Jobber og samtale | Samme lagring som Windows-programmet, frakoblet apputvikling, eksplisitt BUILD/RUN og sikker omstart | Nettbrudd/tale/installasjon med ny fysisk firmware |
| Direkte Home | Native kortvisning, Home/Camper, HA-styrte tillatelser, MQTT/TLS/WSS, veiviser/import; ekte HA og broker testet isolert | Brukerens entiteter/adresser og fysisk FIRE |
| Firmware/recovery | Tre bygg, 12 CI-tester, signert katalog/bundle, kontrollert USB-arkiv, inaktiv OTA-slot, watchdog og separat recovery | Fysisk oppstart, tilbakeføring og redning |

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

Kilde `34ade23bc2872dbc3561a09d859aba865d05f470`.
[Linux-kjøring 45426276015](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45426276015)
bestod normal firmware med BLE/lyd, separat recovery, custom bootloader og
alle 12 C++-/signatur-/pakkekontroller. CI-arkivet er SHA256-kontrollert før
ekstraksjon. De distribuerte filene kommer fra denne kjøringen.

- Normal firmware: 2 399 808 byte,
  SHA256 `1241877bb01510bf5e964864edc54052ec6ce594330ac68179bfbcd26f4a8a9e`.
- [Signert USB-arkiv](firmware/fire-os-1.2.0-rc1-usb.zip): 2 632 217 byte,
  SHA256 `5cb1dc081a18630325cb26223c23f215af58987e3d772e8fb5d1b99b3e2e4dbd`.
- Det publiserbare arkivet inneholder bare de åtte nødvendige filene, ingen
  privat nøkkel. Ny utpakking bestod faktisk `migrate_fire.py check` uten COM.
- [Maskinlesbart bevis](firmware/fire-os-1.2.0-rc1-evidence.json),
  [device-rapport](M5Stack-device/DELIVERY_REPORT.md) og
  [firmwareoversikt](firmware/README.md).

Cloudflare CLI 2026.11.2 er også hentet og SHA256-/versjonskontrollert lokalt.
`scripts/cloudflare.ps1` bruker den lokale kopien. Ingen konto, tunnel, DNS
eller offentlig tilgang er opprettet; det krever brukerens valgte oppsett.

## Tidligere bevis

Ekte OpenAI-dialog, kodegenerering og validert Lua-pakke er prøvd tidligere i
prosjektet. Tidligere fysisk kontroll bekreftet pakkeinstallasjon, men avdekket
en RUN-feil; dette er ikke bevis for at den nye leveransen fungerer fysisk.
Se [E2E-status](M5Stack-backend/docs/E2E_STATUS.md) og deviceprosjektets historikk
for de eksakte avgrensningene. Den gamle påstanden om at nøkkel aldri var satt,
eller at enhetskilden aldri var endret, gjelder ikke lenger.

## Samles til slutt hos brukeren

Domene/Cloudflare-innlogging, HA-installasjonstype/MQTT-vert, valgte entiteter,
førstegangs USB-migrering og fysiske tester. Kode, pakker, dokumentasjon og
uavhengige kontroller er klargjort før disse opplysningene etterspørres.

Produksjonsklar fysisk drift påstås først etter kontroll av oppstart,
nettbrudd, norsk tale, minne/respons, Home med Windows av og uavhengig recovery.

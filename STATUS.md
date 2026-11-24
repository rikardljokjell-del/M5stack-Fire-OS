# Leveransestatus – 24. november 2026

Samlet arbeid følger [godkjent plan](DELIVERY_PLAN.md). Bruk
[oppsettsveiledningen](SETUP.md) som inngang. Dette dokumentet skiller kildekode,
lokale tester og faktisk fysisk verifikasjon.

## Status nå

Leveransen er under sluttføring. FIRE Studio, sikker offentlig backendinngang
og det direkte HA-oppsettet er implementert. Enhetsagenten ferdigstiller native
Home, sikker nettverkstransport og OTA med uavhengig recovery. Ingen ny firmware
er flashet på en fysisk FIRE i denne leveransen.

| Område | Implementert / lokalt kontrollert | Gjenstående bevis |
| --- | --- | --- |
| FIRE Studio | PC-/mobilvisning, innstillinger, samtale, bekreftet appbygg, jobber, bibliotek, kostnader og lesbar GitHub-firmwareoversikt | Ny fysisk FIRE og live offentlig oppsett |
| Offentlig backend | Separate browser-/deviceverter, Access-JWT, engangspålogging lokalt, sesjon/CSRF/Origin og egne enhetstokener | Brukerens domene, konto og tunnel |
| Jobber og samtale | Samme lagring som Windows-programmet, frakoblet apputvikling, eksplisitt BUILD/RUN og sikker omstart | Nettbrudd/tale/installasjon med ny fysisk firmware |
| Direkte Home | Native HA-pakke, streng mapping/etiketter, kommando-/replaykontroll, separat MQTT-innlogging lokalt/eksternt, veiviser og importfil | Faktisk HA, ekte broker og fysisk FIRE |
| Firmware/recovery | Under ferdigstilling i deviceprosjektet | Endelig bygg/pakke/signatur og fysisk oppstart/feil/recovery |

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

## Tidligere bevis

Ekte OpenAI-dialog, kodegenerering og validert Lua-pakke er prøvd tidligere i
prosjektet. Tidligere fysisk kontroll bekreftet pakkeinstallasjon, men avdekket
en RUN-feil; dette er ikke bevis for at den nye leveransen fungerer fysisk.
Se [E2E-status](M5Stack-backend/docs/E2E_STATUS.md) og deviceprosjektets historikk
for de eksakte avgrensningene. Den gamle påstanden om at nøkkel aldri var satt,
eller at enhetskilden aldri var endret, gjelder ikke lenger.

## Samles til slutt hos brukeren

Domene/Cloudflare-innlogging, HA-installasjonstype/MQTT-vert, valgte entiteter,
førstegangs USB-migrering og fysiske tester. Dette hindrer ikke ferdigstilling
av kode, pakker, dokumentasjon og lokale kontroller.

Produksjonsklar fysisk drift påstås først etter kontroll av oppstart,
nettbrudd, norsk tale, minne/respons, Home med Windows av og uavhengig recovery.

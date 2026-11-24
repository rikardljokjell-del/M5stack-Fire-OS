# Home kontrollstatus

Kontrollert 24. november 2026. Ingen HA-konto, ekte entitet eller fysisk FIRE
er betjent av disse kontrollene. Home krever ingen kjørende Windows-backend.

## Bestått lokalt

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_home_contract.py --tb=short
```

**46 tester bestått**. De dekker:

- Strenge Home-v1-modeller og eksportert JSON Schema, UTF-8-bytegrenser,
  ukjente felt, feil typer, dupliserte JSON-felt og ikke-endelige tall.
- Utførelse av den **genererte** Jinja-/if-/choose-/condition-/action-sekvensen
  i en isolert testvert med simulerte HA-funksjoner og tjenester.
- Bare merkede, eksplisitt mappede entiteter eksporteres. Scalarstatus og
  klimasettpunkt/modus eksporteres uten generell attributtilgang.
- Feil økt/revisjon, utløp, fremtidstid, ukjent kort/handling og temperaturer
  utenfor område/steg starter ingen tjenestehandling.
- Sekvensen forbrukes før handling. Duplikater får ikke ny handling.
- Siste øyeblikks fjerning av kontroll-etikett, remote-bryter, tidsfrist eller
  økt **etter** sekvensoppdatering gir ingen handling og aldri executed-ACK.
- Malformed JSON, array, null, string og manglende felt stopper ikke neste
  gyldige kommando. Native HA JSON-parser bruker siste verdi ved dupliserte
  feltnavn; effektive verdier valideres fortsatt og sekvens kan ikke gjenbrukes.
  Den separate strenge Python-validatoren avviser dupliserte felter helt.
- Generatoren overskriver ikke eksisterende legitimasjon. Lokal og ekstern
  passordfil er adskilt, og bare eksakte Home-topics tillates i ACL.
- `device-profile.json` har enhetens eksakte felt, profile 0/1 og offentlig CA
  inline. Ingen private nøkler eller ekstra mode/port/path-felt følger med.
- Lokal sertifikatfornyelse endrer ikke CA, nøkler for innlogging eller
  enhetsprofil. Importen trenger derfor ikke gjentas ved serverfornyelse.

Dette er **modell-/schema-/malvertkontroll**, ikke faktisk HA-kjøring. Testverten
bruker Jinja2 og emulerer HA-hjelpere og tjenestehandlinger. Den modellerer at
en falsk condition stopper sin nåværende blokk, mens en eksplisitt stop avslutter
hele scriptet. Ingen fysisk handling eller faktisk Mosquitto-ACL er bevist av
disse 46 testene. Generert JSON er også gyldig YAML, men full HA-konfigurasjons-
og runtime-kontroll krever en tilgjengelig HA-installasjon.

## Ekte Mosquitto ble forsøkt, men blokkert av Windows

Offisiell portabel Mosquitto 2.1.4 ble hentet over HTTPS og pakket ut lokalt uten
installasjon eller Windows-tjeneste. Kilde:

`https://mosquitto.org/files/binary/win64/mosquitto-2.1.4-install-windows-x64.exe`

Beregnet SHA256 for nedlastingen:

`034017c8f8e3b5b86bdbd971f6c5184370311058e4de7b96a0f10204bbb9e7c8`

Dette er en lokal integritetsregistrering, ikke en uavhengig utgiversignatur.
Installasjonsfilen var ikke Authenticode-signert. Windows Application Control
blokkerte lasting av `mosquitto_common.dll` med Code Integrity-hendelser
3077/3033 og avslutningskode `0xc0e90002`. Ingen sikkerhetsinnstilling ble endret
eller omgått. En ekte broker ble derfor **ikke** kjørt eller godkjent her.

På en egnet HA-/Linux-vert med godkjent Mosquitto kan kontrollen kjøres slik:

```sh
python -m pip install -r home_assistant/requirements-setup.txt
python -m home_assistant.broker_smoke --broker-exe /usr/sbin/mosquitto
```

Denne kontrollen bruker eget midlertidig oppsett, tilfeldige localhost-porter og
testbrukere. Den kontakter aldri brukerens HA. Den skal bevise lokal TLS samt
forskjellige listener-passord, eksakt ACL, ingen forfalsket state, ingen
remote→local-omvei og ingen generell `homeassistant/#`-tilgang. Offentlig WSS
gjennom Cloudflare inngår ikke i en lokal broker-test.

## Gjenstående sluttkontroll

1. HA kontrollerer/laster den native pakken, starter og laster automations på
   nytt; ny epoch og gamle/retained forespørsler gir ingen dobbel handling.
2. Brokerens reelle ACL og listener-autentisering prøves med smoke-skriptet.
3. Ett lys, varme og valgt skript prøves med gjeldende labels; fjernet lese-
   eller kontrolltilgang håndheves hos HA.
4. Home fungerer lokalt med Windows av. Ekstern WSS og HA-bryter prøves fra
   annet nett med Windows av, inkludert allerede etablert fjernforbindelse.
5. FIRE viser fersk/utdatert/ukjent status korrekt, og er responsiv under
   gjenoppkobling og annen nettverksbelastning. Minne/tidsbruk må måles fysisk.

Disse oppsetts- og fysiske kontrollene står åpne. De stanser ikke ferdigstilling
av kilde, oppsettsfiler, verktøy eller øvrige backend-/firmwareleveranser.

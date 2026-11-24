# Home uten backend-PC

Home på FIRE snakker direkte med MQTT ved Home Assistant. Windows og OpenAI er
ikke med i denne forbindelsen. Denne mappen inneholder oppsettsverktøy, en
innebygd HA-konfigurasjon og standard Mosquitto-konfigurasjon. Ingen egen
HA-integrasjon, HACS-komponent eller egenutviklet HA-app installeres.

**Begynn lokalt.** Internett kan legges til etter at lys og status fungerer.
HA bestemmer tilgangene i begge tilfeller. FIRE har ingen HA-administratortoken.

## 1. Lag oppsettet på PC

Åpne PowerShell i `M5Stack-backend` og kjør:

```powershell
.\.venv\Scripts\python.exe -m pip install -r home_assistant\requirements-setup.txt
.\.venv\Scripts\python.exe -m home_assistant.generate --wizard --output home_assistant\generated\home
```

Veiviseren spør om profil (`home` eller `camper`), FIREs enhets-ID, lokal adresse,
valgfritt eksternt vertsnavn og kortene du ønsker. HA viser entitets-ID under
**Innstillinger → Enheter og tjenester → Entiteter**. Eksempel: `light.stue`.
For kattedo velger du en eksisterende avgrenset handling, for eksempel
`script.kattedo_trygg_handling`; Home kaller aldri et vilkårlig skript fra skjermen.

Har du allerede MQTT i HA, fyller du inn den brokerens adresse og TLS-port.
Da lages en avgrenset standard MQTT-bridge. Eksisterende HA-integrasjon og
MQTT-enheter beholdes. Har du ikke MQTT, lar du brokerfeltet stå tomt.

Du kan også bruke en fil:

```powershell
Copy-Item home_assistant\example.json home_assistant\generated\min-profil.json
# Endre kun adresser, kort og entitets-ID-er i kopien.
.\.venv\Scripts\python.exe -m home_assistant.generate --config home_assistant\generated\min-profil.json --output home_assistant\generated\home
```

Målmappen må være ny/tom. Verktøyet overskriver aldri eksisterende passord.
`home_assistant/generated/` er ignorert av Git. Ikke send denne mappen til GitHub
eller i chat: den inneholder passord og private sertifikatnøkler.

## 2. Standard MQTT-tjeneste

Det genererte oppsettet gir to forskjellige innlogginger:

- Lokal TLS-forbindelse på 8883 tar bare lokal FIRE-bruker og HA-brukeren.
- Internettforbindelsen på en separat WebSocket-listener tar bare fjernbrukeren.
  Den er kun publisert på vertens `127.0.0.1:9001` og nås gjennom lokal tunnel.

En lokal nøkkel kan derfor ikke brukes på fjerninngangen. Topic-ACL gir FIRE
kun sitt eget `request` og egne `catalog/state/ack`; aldri `homeassistant/#`.
Lokal TLS verifiserer både sertifikatet og adressen. Verktøyet lager en privat
lokal CA og et navnebundet serversertifikat (ett års gyldighet).

### Home Assistant Container eller annen Linux-/Docker-vert som alltid er på

Kopier den genererte mappen til en egen mappe på denne verten, ikke til Windows
hvis Home skal virke med Windows av. I den kopierte mappen:

```sh
docker run --rm -v "$PWD:/mosquitto/config" eclipse-mosquitto:2.1.4-alpine sh /mosquitto/config/hash-passwords.sh
sudo chown -R 1883:1883 .
docker compose up -d
```

Første kommando konverterer bare de genererte passordfilene til hash. Kjør den
én gang; ikke konverter allerede hashkonverterte filer på nytt. Servernøklene
beholdes på tjenestens vert. `certs/ca.pem` er offentlig og kan kopieres til
FIRE/HA. **Kopier aldri `ca-private.key` eller `server.key` til FIRE.**

Det er en separat Compose-mappe med bare tjenesten `fire-home-mqtt`; eksisterende
HA-/MQTT-containere endres ikke. Kontroller at port 8883 ikke allerede er i bruk.
Ved portkonflikt må den nye tjenesten bindes til en egen vert/IP; ikke slå av den
eksisterende brokeren for å få plass.

### Home Assistant OS med den offisielle Mosquitto-appen

Den eksisterende appen kan gjenbrukes for HA-integrasjonen og lokale enheter.
For den strenge skillet mellom lokal/fjernnøkler bruker den genererte bridgen
en separat **standard** Mosquitto-tjeneste på en alltid-på Linux-/containervert.
Det kan være HA-vertens containerplattform dersom tilgjengelig eller en annen
eksisterende hjemmetjener. Den skal ikke være avhengig av Windows-backend.

Stock-appen laster en global autentiseringsplugin. Ikke lim inn bare en ekstra
`password_file` og anta at det isolerer en offentlig listener. Vi har ikke
verifisert en slik overstyring i din HA OS-appversjon. Hvis du bare har HA OS og
ingen vert som kan kjøre standardtjenesten, er dette et konkret oppsettvalg som
må fullføres før ekstern Home-tilgang. Ingen usikker automatisk reservevei brukes.

### Dersom MQTT allerede finnes: koble bridgen til den

1. Opprett den **broker-lokale** brukeren `fire_home_bridge` i eksisterende
   broker. I offisiell Mosquitto-app brukes `logins` i appens konfigurasjon,
   ikke en ny generell HA-bruker.
2. Passordet ligger i genererte `secrets.yaml`, feltet
   `fire_home_fire_home_bridge`. Ikke publiser det.
3. Legg tilgangene fra `existing-broker-acl.txt` til eksisterende ACL. **Legg
   til; ikke erstatt eksisterende brukere/rettigheter.** HA-systembrukerne må
   beholde sine eksisterende nødvendige rettigheter.
4. Kopier eksisterende brokers offentlige CA til `certs/ha-broker-ca.pem` hos
   den nye standardtjenesten. Servernavnet må stemme med sertifikatet.
5. Start den nye Home-MQTT-tjenesten. Bridgen videresender bare denne FIREs
   konkrete Home-topics. Kontroller forbindelsen før resten av oppsettet.

Har du ingen MQTT-integrasjon, kobler du HAs **innebygde MQTT-integrasjon** til
den nye tjenestens lokale adresse/8883 med brukeren `fire_ha` og passordet fra
`secrets.yaml`. Last opp `certs/ca.pem` som tilpasset CA. Behold navnekontroll
og sertifikatkontroll på. Ingen «ignore certificate validation».

## 3. Legg den innebygde HA-pakken inn

1. Ta en HA-sikkerhetskopi.
2. Kopier bare `fire_home.yaml` til `/config/packages/fire_home.yaml` i HA.
3. Aktiver packages i eksisterende `homeassistant:`-seksjon i
   `configuration.yaml` dersom dette ikke allerede er aktivert:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Ikke opprett to `homeassistant:`-seksjoner. Behold eksisterende innhold.
Den genererte `.yaml`-filen bruker JSON-syntaks, som også er gyldig YAML.
4. Kontroller konfigurasjonen i HA og start HA på nytt.
5. Opprett etikettene **fire_home_read** og **fire_home_control** i HA.
6. På hver valgt **entitet** legger du til `fire_home_read` for visning og,
   hvis styring skal være lov, også `fire_home_control`. Merking av et helt
   rom/enhet arves ikke automatisk. En etikett gir bare tilgang hvis entiteten
   også står i den eksplisitte kortmappingen du valgte i veiviseren.

Pakken består bare av standard `input_text`, `input_number`, `input_boolean`,
`script`, `automation` og `mqtt.publish`. Den eksporterer aldri vilkårlige
HA-attributter. Kattedo-/scenehandlinger peker på faste skript/scener valgt i
oppsettet; ingen skriptargumenter kommer fra FIRE.

Fjerner du en etikett, avvises neste handling. Katalog og status erstattes ved
registerendring og minst hvert 30. sekund, slik at fjernede ting forsvinner.
Kommandoer blir ikke lagret som retained. Økt, sekvens og kort levetid avviser
gamle eller dupliserte meldinger. Ved ukjent resultat prøver ikke enheten
automatisk igjen. HA-hjelpere gir ingen garanti om transaksjonell nøyaktig én
fysisk utførelse over strømbrudd; ny økt opprettes ved start/automation-reload.

## 4. Koble FIRE til

Åpne enhetens lokale Setup-side fra Settings. Velg import av Home-profil og
last opp den genererte **device-profile.json**. Filen inneholder nøyaktig
enhetens konfigurasjonsfelter og den offentlige lokale CA-en inline; ingen
manuell JSON-redigering eller kopiering av PEM-strenger er nødvendig.

Oppsettet som importeres er:

- profil/enhets-ID fra veiviseren;
- lokal adresse, port 8883, lokal brokerbruker/passord;
- den offentlige lokale CA-en fra `certs/ca.pem`;
- eventuelt fjernadresse, port 443, `/mqtt`, fjernbruker/passord.

Profil 0 er Home og profil 1 er Camper. Portene er faste 8883/443 med `/mqtt`.
Verdiene finnes i den lokale `device-profile.json`. Denne filen er sensitiv.
Bruk kontrollert enhetsoppsett; ikke legg den i appbibliotek, Lua-pakker eller
GitHub. Kontroller at FIRE har riktig tid for TLS og kommandoenes tidsfrister.

Velg **Lokal** først. Du skal se bare kortene HA har gitt tilgang til. Prøv ett
lys, deretter varme. Avslå styring ved å fjerne kontroll-etiketten og kontroller
at kortet blir skrivebeskyttet. Stopp Windows-backend: Home skal fortsette.

## 5. Valgfri ekstern Home og Auto

Dette krever en egen tunnel/proxy **ved Home-MQTT-verten**, ikke ved Windows.
En vanlig Nabu Casa-URL videresender ikke automatisk MQTT.

1. Opprett en permanent HTTPS-tunnel for eksempel `home.ditt-domene.no` med
   samme konto-/domeneprinsipp som AI-backenden.
2. Kjør standard `cloudflared` på samme vert som Home-MQTT. Publiser
   `http://127.0.0.1:9001`; generert `cloudflared-ingress.yaml` viser ruten.
   WebSocket-transport må være tillatt. FIRE bruker offentlig **WSS/443**.
3. Den offentlige inngangen skal ikke ha interaktiv nettleserinnlogging;
   MQTTs separate fjernbruker og strenge ACL er enhetens autentisering.
   Ingen portvideresending til 1883/8883/9001 i ruteren.
4. Slå på HA-hjelperen **FIRE home tillat fjernaksess**. Den er av første gang.
5. På FIRE velger du **Internett**, og tester fra et annet Wi-Fi/mobilhotspot.
6. Slå av HA-bryteren mens FIRE er tilkoblet eksternt. Fjernkatalogen tømmes og
   nye eksterne handlinger avvises, mens lokal bruk beholdes.
7. Velg **Auto** etter at begge veier virker. Auto prøver lokal først og bytter
   til den avtalte fjernadressen. Den gir aldri nye HA-tillatelser.

## 6. Camper og endringer senere

Kjør veiviseren med `site=camper` i en ny mappe. Installer pakken på riktig HA
og bruk profilens egne adresser/legitimasjoner. Ikke bland Home/Camper-filer.
For flere steder med forskjellige HA-installasjoner **og forskjellige brokere**
er dette en rett frem, separat installasjon per sted.

**Home og Camper på samme HA/broker krever ett koordinert felles oppsett.**
Det er ikke tilstrekkelig å gi to HA-pakker forskjellige filnavn. Veiviseren
leverer ett site/device-par per kjøring og lager nye tilfeldige passord/CA hver
gang. Samme enhets-ID gjenbruker brukernavnene, og to standardtjenester prøver
dessuten å bruke de samme portene 8883/9001.

Et felles oppsett må bruke én broker/Compose-tjeneste, riktig felles CA og
koordinerte innlogginger, samlet ACL for begge profiler, eventuelt samlet bridge
og separate HA-pakkefilnavn. Ikke legg de to genererte brokeroppsettene over
hverandre. For Rikards eventuelle fremtidige Camper på felles broker klargjøres
denne standardkonfigurasjonen når HA-installasjon/brokertype er avklart.

Endrer du bare kortmappingen, behold eksisterende brokernøkler og kopier bare
den nye HA-pakken etter kontroll. Ikke distribuer nye tilfeldige nøkler med
mindre du faktisk vil pare enheten på nytt.

Forny LAN-serversertifikatet før ett år har gått, uten å endre CA eller passord:

```powershell
.\.venv\Scripts\python.exe -m home_assistant.renew_certificate --directory home_assistant\generated\home
```

Kopier bare nye `certs/server.pem` og `certs/server.key` til brokerverten og
start bare Home-MQTT-tjenesten på nytt. FIRE beholder CA og legitimasjon.
Ta vare på `ca-private.key` lokalt for slik fornyelse; ikke publiser den.

## Kontroll før produksjonsbruk

Isolert ekte-broker-test på en vert hvor Mosquitto er tillatt:

```sh
python -m pip install -r home_assistant/requirements-setup.txt
python -m home_assistant.broker_smoke --broker-exe /usr/sbin/mosquitto
```

Skriptet bruker tilfeldige localhost-porter, testbrukere og lokale sertifikater,
og terminerer testprosessen etterpå. Det kontrollerer faktisk listener-isolasjon,
TLS og ACL. Det kontakter aldri din HA. Offentlig WSS, HA-automatiseringer med
dine entiteter og fysisk FIRE må testes i ditt oppsett. En separat grønn Linux-
kontroll har også kjørt den genererte pakken i faktisk Home Assistant med
syntetiske standardentiteter, inkludert omstart og gammel retained forespørsel.
Se `VERIFICATION.md` for konkrete resultater og gjenværende tester.

Kilder: [HA MQTT](https://www.home-assistant.io/integrations/mqtt/),
[HA packages](https://www.home-assistant.io/docs/configuration/packages/),
[etiketter](https://www.home-assistant.io/template-functions/label_entities/),
[offisiell Mosquitto-app](https://github.com/home-assistant/app-mosquitto/blob/main/mosquitto/DOCS.md),
[Mosquitto-konfigurasjon](https://mosquitto.org/man/mosquitto-conf-5.html).

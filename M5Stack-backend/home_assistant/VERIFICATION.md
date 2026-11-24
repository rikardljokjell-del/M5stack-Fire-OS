# Home kontrollstatus

Kontrollert 24. november 2026. Home krever ingen kjørende Windows-backend.
Ingen privat HA-konto, ekte hjemmeentitet eller fysisk FIRE ble betjent.

## Ekte Linux-, broker- og Home Assistant-kontroll bestått

[GitHub Actions-kjøring 45422781786](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45422781786)
er grønn på kildeversjon `17d7a7a68ed19913ba769828917e2d07d3a5abf1`.
Kontrollen ligger i `.github/workflows/home-checks.yml`.

- **Broker**, jobb `138546507879`: ekte Mosquitto 2.1.4 bygget fra offisiell
  kilde med TLS og innebygd WebSocket-støtte. Faktisk sertifikat/navnekontroll,
  separate listener-passord og topic-ACL bestått. Lokal nøkkel avvises på
  fjernlistener og omvendt; enheten kan ikke forfalske state, bruke remote som
  lokal rute eller lese generell `homeassistant/#`.
- **Native HA**, jobb `138546508793`: offisielt Home Assistant 2026.11.3-image
  og standard `eclipse-mosquitto:2.1.4-alpine` på et isolert containernettverk.
  Ingen porter publiseres. Den uendrede genererte HA-pakken lastes gjennom
  vanlig `configuration.yaml`/packages og kjører med ekte MQTT-integrasjon,
  registreringer, etiketter, script og automations.

Brokerens kildearkiv hentes fra
`https://mosquitto.org/files/source/mosquitto-2.1.4.tar.gz` og kontrolleres mot
fast SHA256 `ca30b26ccd3041c0e11fc407fe4f2e62bc445e8d8dea94a083cc60c09bd5ea30`.
Dette er en innholdsfesting, ikke en påstand om separat utgiversignatur.

Den native HA-kontrollen bruker bare syntetisk template-bryter, temperatursensor,
standard termostat, script og teller. Den bekrefter:

1. Native oppstart/pakkelasting, merket katalog, begrenset status og eksplisitt
   klimametadata/settpunkt/modus.
2. Virkelig MQTT-kommando, faktisk native tjenestehandling og ACK etter handling;
   duplikatet gjør ingen ny handling.
3. Array/null/string/ødelagt JSON stopper ikke senere gyldig kommando. Utgått
   kommando og temperatur utenfor tillatt steg avvises.
4. Fjerning av HA-leseetikett fjerner kort/status; fjernet kontroll-etikett
   hindrer tjenestehandling.
5. HA-bryteren for fjernaksess håndheves også på allerede etablert WebSocket-
   forbindelse. Fjernkatalogen tømmes og nye fjernhandlinger avvises.
6. Virkelig automation-reload gir ny epoch uten å gjenta retained forespørsel.
7. En **ny HA-prosess** startes med samme native lagring og gammel retained
   forespørsel hos brokeren. Ingen ny handling skjer. Også en fersk forespørsel
   med gammel epoch avvises; neste gyldige forespørsel virker.
8. Native HA-malmotor kjører de faktiske genererte hashuttrykkene med bevisste
   tall-/null-testverdier. Innledende nuller og 16 tegn beholdes. Faktisk MQTT-
   katalog/kommando prøves med tall-epoch og innledende nuller; null-epoch
   avvises. Bare hashresultatet er fast testdata i denne delkontrollen.

Alle passord og CA-/servernøkler i CI opprettes midlertidig for testen. Ingen
brukernøkler eller repository-secrets brukes. Bare resultat-JSON lastes opp
som artefakter; konfigurasjon, passordfiler og sertifikatnøkler lastes ikke opp.

## 51 målrettede lokale tester bestått

Kjør fra `M5Stack-backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_home_contract.py --tb=short
```

**51 tester bestått**, sist på 6,53 sekunder før siste CI-kjøring. De dekker
strenge Home-v1-modeller/JSON Schema, UTF-8-grenser, feil typer/duplikatfelt,
ikke-endelige tall, den genererte action-sekvensen i en separat Jinja-sandbox,
siste øyeblikks tilgangs-/TTL-/epoch-avvisning etter sekvensforbruk, eksakt
enhetsprofil/CA-import og sertifikatfornyelse uten å bytte CA eller passord.

En faktisk OpenSSL TLS-håndtrykkstest med MemoryBIO, streng sertifikatkontroll
og navnekontroll består for både generert og fornyet serversertifikat. Ingen
nettverkstjeneste eller fysisk enhet trengs for denne testen.

Jinja-testverten emulerer HA-hjelpere/tjenester og er fortsatt **modellkontroll**.
Den er ikke alene bevis for HA-runtime. Den separate grønne native HA-jobben
ovenfor er runtime-beviset med syntetiske standardentiteter. Native HA-parser
bruker siste verdi ved dupliserte JSON-felt; effektive felt valideres og sekvens
kan ikke gjenbrukes. Den strenge Python-validatoren avviser dupliserte felt helt.

## Gjenta brokerkontrollen på egnet Linux-vert

```sh
python -m pip install -r home_assistant/requirements-setup.txt
python -m home_assistant.broker_smoke --broker-exe /usr/sbin/mosquitto
```

Dette bruker midlertidige testbrukere, sertifikater og localhost-porter og
kontakter aldri brukerens HA. Hver negativ ACL-test har ferske klienter og
positiv kontroll. Prosessen avsluttes etterpå. Native HA-kontrollen kan gjentas
med workflowens konkrete containerkommandoer; bruk aldri en eksisterende HA-
konfigurasjonsmappe til `ha_runtime_smoke`.

Windows Application Control blokkerte det første lokale Mosquitto-forsøket
(`mosquitto_common.dll`, hendelse 3077/3033, `0xc0e90002`). Ingen sikkerhetspolicy
ble endret. De faktiske kontrollene ble gjennomført på vanlig Ubuntu i CI.

## Gjenstående kontroll hos brukeren

1. Installer det genererte oppsettet på valgt HA-/brokervert, bruk riktige
   adresser/entiteter og prøv ett lys, varme og eventuelt valgt script.
2. Kontroller Home på fysisk FIRE med Windows av, og at egne etiketter gir
   ønsket visning/styring.
3. Ved fjernbruk: kontroller egen Cloudflare-rute, offentlig WSS-sertifikat,
   annet Wi-Fi og HA-fjernbryteren. CI prøver intern WS, ikke offentlig WSS.
4. Mål faktisk FIRE-respons/minne og prøv gjenoppkobling/belastning på maskinvaren.

Native helper-lagring lover ikke transaksjonell, nøyaktig én fysisk handling
over et vilkårlig strømbrudd. Epoch/sekvens/TTL og ingen automatisk reprise ved
ukjent resultat er den beskrevne mekanismen. De fysiske kontrollene står åpne;
syntetisk HA og Linux-broker er faktisk kjørt og bestått.

# Kom i gang med FIRE OS

Denne veiledningen samler oppsettet. Gjør én del av gangen. Kontoer, adresser,
HA-innhold og fysisk FIRE må fylles inn hos deg; eksempelfiler gir ikke tilgang
til huset før du har valgt det i Home Assistant.

## Dette går direkte

| Hva du bruker | Forbindelse | Må Windows-PC-en være på? |
| --- | --- | --- |
| Home: lys, varme og sensorer | FIRE → MQTT ved Home Assistant | Nei |
| Firmware fra Innstillinger | FIRE → GitHub | Nei |
| Installerte selvstendige apper | På FIRE | Nei |
| AI-samtale, tale og lage Lua-apper | FIRE eller nettleser → PC-backend → OpenAI | Ja |
| FIRE Studio og appbibliotek | Nettleser → PC-backend | Ja |

FIRE trenger Wi-Fi med internett for ekstern bruk. Et mobilhotspot kan gi dette.
FIRE har ikke innebygd mobilnett. Et nett med egen innloggingsside må eventuelt
godkjennes separat. Home kan også brukes bare lokalt.

## 1. Start FIRE Studio på PC-en

1. Start det eksisterende Windows-programmet for FIRE Backend. Fra prosjektmappen
   kan du også åpne `M5Stack-backend/start-ui.ps1`.
2. Klikk **Åpne FIRE Studio ↗**. Dette logger inn i nettleseren på samme PC.
3. Velg **Innstillinger**. Den eksisterende OpenAI-nøkkelen beholdes når nøkkelfeltet
   er tomt. Nøkkelen lagres lokalt på PC-en, aldri på FIRE eller i apper.
4. Velg **AI Developer**, riktig enhet og forklar appen du ønsker. Les forslaget
   og velg **Bekreft og bygg**. En frakoblet FIRE kan fortsatt få en app bygget.
5. Når FIRE er tilkoblet, installer den testede pakken fra biblioteket. Kjøring
   krever sin egen bekreftelse. Ferdig bygg betyr ikke at appen kjører på FIRE.

Du kan lukke nettleseren mens en jobb går. Åpne samme jobb igjen etterpå.
Velg **Fortsett samme jobb** for å fortsette; en ny byggejobb er en ny handling.
Innstillinger og bibliotek er felles med Windows-programmet.

## 2. Bruk AI og Studio fra andre nett

Dette oppsettet gjøres én gang. Du trenger en Cloudflare-konto, et domene under
den kontoen og egen innlogging. Ingen ruterport skal åpnes.

Du velger to adresser, for eksempel:

- `studio.dittdomene.no`: nettleseren, med din Cloudflare Access-innlogging.
- `fire.dittdomene.no`: FIRE, med enhetens eget begrensede token.

Følg [de nummererte Cloudflare-stegene](M5Stack-backend/docs/WEB_STUDIO_SETUP.md#én-gang-mobil-og-internett).
Der finner du ferdig tunnelmal, hva du skal erstatte, og hvilke felt du fyller
inn i Studio. PC-en og tunnelen må være i gang for ekstern AI og Studio.
Windows må også holdes våken mens du vil bruke AI utenfra; hvilemodus stopper
PC-tjenestene. Kontroller strøm-/hvileinnstillingen når PC-en står på strøm.

Etter oppsettet åpner du `https://studio.dittdomene.no/ui/` fra mobil eller PC.
På FIRE velger du den offentlige backendadressen på port 443. Ikke kopier
OpenAI-nøkkelen til FIRE. Ikke legg nettleserinnlogging foran enhetsadressen.

## 3. Koble Home til Home Assistant

**Start lokalt med ett lys.** Når dette virker, kan du legge til varme, sensorer
og internett. Dette krever ikke Windows-backenden i daglig bruk.

1. Finn entitets-ID for lyset i HA under **Innstillinger → Enheter og tjenester
   → Entiteter**. Eksempel: `light.stue`.
2. Kjør den lokale oppsettsveiviseren i
   [Home-veiledningen, del 1](M5Stack-backend/home_assistant/README.md#1-lag-oppsettet-på-pc).
   Velg profil `home`, enhets-ID, lokal adresse og ønskede kort.
3. Følg den relevante delen for din HA-installasjon og eksisterende MQTT.
   De genererte filene inneholder standard Mosquitto-oppsett og en innebygd
   HA-pakke. Du skal ikke installere en egenutviklet HA-app eller integrasjon.
4. Legg HA-pakken inn og opprett etikettene **fire_home_read** og
   **fire_home_control**. Merk bare entitetene FIRE skal få se og styre.
   Entiteten må også være valgt i oppsettet. Å merke hele huset gir ikke tilgang.
5. På FIRE: **Home → Innstillinger → Oppsett på mobil**. Koble mobilen/PC-en til
   **FIRE-Setup** med passordet som vises på FIRE. Åpne
   `http://192.168.4.1/home`, velg **Importer device-profile.json**, velg filen
   fra veiviseren og trykk **Lagre sikkert på enheten**. Koble tilbake til vanlig
   Wi-Fi. Velg **Lokalt** i Home og kontroller at lyset vises. Fjern kontroll-
   etiketten i HA: styring skal avvises.
6. Stopp Windows-backenden og prøv lyset igjen. Home skal fortsatt virke.

Filer med passord og private nøkler blir bare i den lokale genererte mappen.
Ikke last dem opp til GitHub eller lim dem inn i chat. Kun den offentlige CA-en
skal til FIRE; aldri private sertifikatnøkler eller et generelt HA-token.

For kattedo eller andre sammensatte handlinger: velg et fast HA-skript med
handlingen du faktisk ønsker å tillate. FIRE får ikke fri tilgang til tjenester.
For bobilen lager du en egen **Camper**-profil mot riktig HA-installasjon.

## 4. Slå ekstern Home av og på

Etter lokaltesten følger du
[Home-veiledningen, del 5](M5Stack-backend/home_assistant/README.md#5-valgfri-ekstern-home-og-auto).
Det blir en egen tunnel ved Home-MQTT-verten. Den skal være på en enhet som er
på hjemme, uavhengig av Windows-PC-en. En Nabu Casa-adresse er ikke automatisk
en MQTT-adresse.

Den daglige bryteren er HA-hjelperen **FIRE home tillat fjernaksess**:

- Av: ekstern Home-katalog tømmes og nye eksterne kommandoer avvises.
- På: valgte rettigheter kan brukes eksternt med egen fjerninnlogging.

På FIRE velger du **Lokalt**, **Internett** eller **Auto**. Auto gir ikke flere
rettigheter. HA avgjør fortsatt hva som er tillatt ved hver handling.

Med bare HA OS og den offisielle Mosquitto-appen trengs et konkret valg av
alltid-på vert for den isolerte eksterne MQTT-inngangen. Veiledningen forklarer
den ferdige standardtjenesten/bridgen. Ikke eksponer den eksisterende brokeren
offentlig eller skru av sertifikatkontroll for å hoppe over dette steget.

## 5. Firmware og førstegangsoppgradering

Ny oppstartsløsning med uavhengig redning krever en førstegangs USB-migrering.
Etter migreringen skal normale oppdateringer hentes fra **Innstillinger på FIRE**
direkte fra GitHub. Studio viser bare versjoner og informasjon.

Migreringspakken og den eksakte enhetsveiledningen klargjøres sammen med den
ferdige firmwarebyggen. Ingen firmware skal installeres bare fordi den er
signert: fysisk oppstart, tilbakeføring og redning må også kontrolleres.

## Samlet sluttkontroll hos deg

Dette er de opplysningene som trengs for å fullføre ditt oppsett:

1. Hvilket domene/Cloudflare-team og hvilken innlogging du vil bruke.
2. HA-installasjonstype, eksisterende MQTT og hvilken alltid-på vert som finnes.
3. Første valg av HA-entiteter/handlinger og eventuell Camper-installasjon.
4. En fysisk FIRE for førstegangs USB-migrering og testen under.

Test i denne rekkefølgen etter oppsett:

1. FIRE starter og knapper/skjerm reagerer under nettverksarbeid.
2. AI-samtale, appforslag, bekreftet bygg, installasjon og bekreftet kjøring.
3. Samme flyt på et annet Wi-Fi/mobilhotspot; ingen doble jobber etter nettbrudd.
4. Home lokalt og eksternt med Windows av. Avslå tilgang i HA og prøv igjen.
5. Firmwareoppdatering, avbrutt nedlasting og redningsstart med riktig knapp.

Bruk [den korte fysiske testveiledningen](docs/PHYSICAL_CHECK.md).
Se også [faktisk leveransestatus](STATUS.md) og [kontrollpunktene](ACCEPTANCE.md).
Lokale tester og vellykket kompilering erstatter ikke de fysiske testene.

# PC → FIRE: reverse TCP v1

Backend implementerer denne transporten uten endringer i `M5Stack-device/`.
Device-agenten implementerer mottakeren i firmware. Protokoll 0.2,
autentisering på HTTP/WebSocket, kapabiliteter og bekreftelser videreføres.

## Formål og innstillinger

Ved USB-nettdeling kan PC-en nå FIREs Wi-Fi-adresse selv om FIRE ikke kan nå
PC-en gjennom telefonens NAT. PC-en oppretter derfor TCP-forbindelsene.
Dette fungerer bare når PC-en faktisk har en rute til FIRE; det er ingen
skytjeneste eller universell NAT-traversering. Telefon/ruter endres ikke.

Windows: **Tilkobling → Mobilnett / omvendt TCP**. Oppgi FIREs lokale IPv4,
port `8766`, og lagre. ID og token hentes fra samme lagrede M5Stack-profil som
backend bruker. OpenAI-nøkkel og admin-token sendes aldri i transportprefikset.
Eksisterende profiler starter i direkte modus. Innstillingene følger vanlig
lagre/start-på-nytt-flyt; nøkler beholdes i Windows legitimasjonsbehandling.

CLI: sett `FIRE_REVERSE_HOST`, `FIRE_REVERSE_PORT` (8766) og
`FIRE_REVERSE_DEVICE_ID` til en ID i `FIRE_DEVICE_TOKENS`.
Tom host slår av broen. Bare lokale IPv4-adresser godtas.
Backendens HTTP-port er fortsatt normalt `8765`.

## Ledningsformat

FIRE lytter på TCP 8766 når Wi-Fi og backend-konfigurasjon er klare. PC-en
holder **fire** samtidige forbindelser, hver med følgende autentisering:

1. PC → FIRE: én UTF-8 JSON-linje, avsluttet med LF, høyst 1024 byte inkludert LF:

   `{"type":"reverse_open","version":1,"device_id":"m5stack-fire-01","token":"<device-token>"}`

2. FIRE validerer samme enhets-ID og enhetstoken som i backend-konfigurasjonen.
   Ved suksess svarer FIRE med én UTF-8 JSON-linje avsluttet med LF:

   `{"type":"reverse_ready","version":1,"device_id":"m5stack-fire-01"}`

3. Etter LF er forbindelsen en gjennomsiktig, toveis byte-strøm. FIRE er fortsatt
   HTTP-/WebSocket-klient og sender eksisterende `GET /ws/device` eller annen
   HTTP-forespørsel over den aksepterte forbindelsen. PC-en videresender til
   backend på lokal loopback og konfigurert backend-port. Eksisterende
   `Authorization: Bearer <device-token>` kreves fortsatt på HTTP/WS.

FIRE må bevare bytes etter autentiseringslinjen og PC-en bevarer bytes etter
`reverse_ready`, også når JSON og HTTP kommer i samme TCP-pakke. Ingen
meldingslengder eller ekstra innramming tilføyes etter autentisering. Binære
ZIP/WAV-data og WebSocket-rammer må gå uendret gjennom strømmen.

FIRE velger en ledig, autentisert strøm for hver ny klientforbindelse.
WebSocket bruker én, ZIP-nedlasting og WAV-opplasting bruker andre.
Transportvalget beholdes ut levetiden til den enkelte HTTP/WS-forbindelsen;
ikke bytt midt i en operasjon. Direkte forbindelse kan beholdes som fallback.
Avslutt ferdige HTTP-forbindelser slik at poolen ikke fylles med ubrukte klienter.

## Levetid, status og sikkerhet

- PC-en har tre sekunders frist for TCP-oppkobling og `reverse_ready`.
- Autentiserte, ubrukte strømmer holdes åpne uten HTTP-forespørsel. Lokal
  backendforbindelse åpnes først når FIRE sender første byte, slik at backendens
  HTTP-idletimeout ikke stenger poolen. TCP keepalive er aktivert.
- Avbrutte strømmer erstattes automatisk. Mislykkede forsøk bruker økende
  ventetid fra ett til maksimalt ti sekunder. Normal avslutning erstattes raskt.
- Videresending bruker avgrensede 8192-byte biter og mottrykk, og støtter
  half-close med inntil fem sekunder for å fullføre motsatt retning etter EOF.
- ID/versjon/JSON valideres før noen lokal backendforbindelse åpnes.
  Feil og status inneholder faste feilkoder; prefiks, tokens og payload logges ikke.
- Dette er ukryptert lokal TCP, med samme tillitskrav til nettet som eksisterende
  HTTP/WS. Ikke eksponer port 8766 mot internett. Token gjelder bare valgt enhet.
- Brostatus vises under Tilkobling og i lokal adminbeskyttet `/desktop/status`:
  venting/autentiseringsfeil, autentiserte/aktive kanaler og byte-tellere.
  **Bro klar er ikke en godkjent enhetssesjon eller fysisk integrasjonstest.**

## Verifisering

`python -m pytest tests/test_reverse_tcp.py -q` tester ekte lokale TCP-strømmer:
fragmentert/sammenslått prefiks, avvist ID/versjon/JSON, fire kanaler,
gjenoppkobling, binærdata, half-close og bevart legitimasjon.
En simulert FIRE kobler gjennom poolen til den faktiske backendserveren,
oppgraderer til WebSocket, henter og hashkontrollerer en app-pakke, sender
installasjons-/kjørekvitteringer og laster opp WAV større enn én buffer.
Mock-modus brukes; ingen OpenAI-kall. Baseline har audio_input=true og
audio_output=false. Ingen lydutgang kreves.

Fysisk FIRE-integrasjon er **ikke verifisert** før ekte firmware har koblet til
og gjennomført relevante operasjoner gjennom denne broen.

På utviklings-PC-en 21. november 2026 svarte FIRE `10.5.1.163:8766` med gyldig
`reverse_ready` på alle fire kanaler. Dette bekrefter nettverksvei og
transportautentisering gjennom gjeldende mobiltilkobling. Ingen `session_start`,
appnedlasting eller lydopplasting fra fysisk FIRE var observert ved denne kontrollen.
Mottakerkontrakten er lest fra device-commit `90028a9` og samsvarer med prefikset over.

# Datadrevet apputvikling fra FIRE

Bestilling 25. november 2026. Dette er implementerings- og akseptansegrunnlaget
for oppgraderingen etter FIRE OS 1.4.0-rc3. Ingen gjennomført fysisk test eller
ferdig funksjon påstås bare fordi den står i denne planen.

## Viktigste leveranse

En installert app skal samle målinger, presentere en analyse og velge
«Improve app». Da følger riktig kilde, versjon, bestilling, historikk,
målegrunnlag, resultater og observasjoner automatisk til eksisterende
AI Developer. Brukeren kan legge til en kort instruks og få en målrettet,
testet kandidat uten eksport/import eller å forklare appen på nytt.

Den samme flyten støtter en ny app basert på en eksisterende, korrigering av
AI-antakelser, fysisk testfeedback, gjenopptakelse og vanlig app-rollback.
Build og fysisk kjøring beholder de eksisterende eksplisitte bekreftelsene.

## Gjenbruk og eierskap

| Område | Eksisterende mekanisme som utvides |
| --- | --- |
| Målinger og filer | App-privat SD, eksisterende I/O-worker, sti-/ressurskontroll |
| Asynkront arbeid | Fire jobs, poll/result/cancel/close, eksisterende callbackgrenser |
| Nettverk | Én backend, samme autentiserte HTTP/WebSocket og enhetsidentitet |
| Analyse med AI | Eksisterende Runtime AI, modellvalg, konto og forbruksregistrering |
| Iterasjon | Eksisterende prosjekt/pakker, current proposal, Builder/Resume/RepairBaseline |
| Sikker levering | Validering, kilde-/arkivhash, installasjonskvittering og rollback |
| Lagring på PC | Eksisterende filbaserte Store og kvoter, ingen database |
| Skjerm og kontroll | Eksisterende FIRE OS og App SDK, knapper fremfor vanlig fritekstdialog |

Device-agenten eier firmware og er eneste eier av COM-porten. Backend-agenten
eier server, modell-/byggeintegrasjon, simulator, API og backendgrensesnitt.
Rotkoordinatoren eier den felles nye kontrakten, relevant maskinvareresearch,
avgrensning, uavhengig kontroll og samlet integrasjon/publisering. Agentene
arbeider i samme mappe; ingen nye serverkopier, arbeidskopier eller agentlag.

## Felles Data Engine

Den separate valgfrie [kontrakten](M5Stack-backend/contracts/DATA_ENGINE-v1.json)
er eneste kilde til navn, argumenter, grenser, identitet og dataflyt.
Generatoren skriver samme register til backendpakken og native konstanter.
De eksisterende hardware-, SDK- og Runtime AI-kontraktene beholdes.

- `create`, `append`, `mark`, `seal`, `info`, `read`, `record`, `process`
  bruker eksisterende jobber. `develop` er den avgrensede broen til OS/Developer.
- CSV, tekst, binærdata og eksisterende WAV-opptak har råfil, metadata,
  faktisk tidsgrunnlag og hendelses-/chunkindeks.
- Data ligger under `/apps/<app-id>/appdata/datasets/<dataset-id>/`.
  Et ferdig forseglet datasett overskrives ikke. Oppdatering/rollback sletter
  ikke appens data. Kvotefeil vises; rådata slettes ikke automatisk.
- Filer strømmes gjennom små blokker, uten store Lua-tabeller eller en ny
  framebuffer. SD-operasjoner, hashing og overføring skjer utenfor callbacks.
- Faktisk rate, tidsstempel, gyldige/manglende prøver og tapte prøver bevares.
  En ønsket rate eller syntetisk prøve er ikke en fysisk måling.
- Filstatistikk, filtrering, sammenligning og et begrenset FFT-vindu er
  deterministisk forbehandling. Resultater refererer til rådata og algoritme.
- Relevant rågrunnlag overføres ved behov, med offset, chunk-SHA og fil-SHA,
  autentisert eierskap, avbrudd og gjenopptakelse. Ingen Lua-valgt URL/nøkkel.

Runtime AI kan motta autoriserte datasett-referanser i sin eksisterende
forespørsel. Backend lager et deterministisk relevant sammendrag innen de
uendrede grensene: 768 byte data og 1536 byte samlet forespørsel. Råfiler
sendes ikke automatisk til modellen, og det legges ikke til et ekstra
modellkall bare for å oppsummere. AI-resultat er en vurdering med opphav,
modell-/forbruksreferanse og inputreferanser, aldri automatisk et bekreftet faktum.

## Utviklingsgrunnlag og gjenbrukbar kunnskap

Et utviklingssnapshot binder grunnlaget til prosjekt, app/pakke, kildehash,
datasett-revisjoner og relevante analyse-/feedbackreferanser. Resume bruker
samme frosne grunnlag. Nye målinger krever et bevisst nytt grunnlag fremfor
at et pågående bygg endrer premisser i bakgrunnen.

Eldre forseglede datasett kan leses av senere versjoner av samme app.
Append er bundet til den opprettende instansen. En ny app basert på en annen
får bare eksplisitt autoriserte, skrivebeskyttede historikkreferanser; ingen
generell adgang til andre appers SD-filer. Eksterne logger, radioinnhold og
appskrevne tekster behandles som ubetrodde data, ikke systeminstrukser.

Kunnskap skiller produsentdokumentasjon, antakelser, simulering, måledata,
brukerobservasjoner og fysisk verifiserte løsninger. Tidligere feil og
fungerende kode finnes allerede i bygge-/kvalitetshistorikken og skal brukes
selektivt. Nye fakta/profiler må ha opphav og nødvendig bekreftelse.

## Maskinvare

Generell I²C/UART/SPI/GPIO/ADC/PWM-tilgang prioriteres foran produktspesifikke
firmwaredrivere. Eksisterende BLE/GATT/Wi-Fi/mikrofonbindinger implementeres
der de mangler. Rå BLE-annonser bruker én eksplisitt begrenset metode i den
valgfrie nye utvidelsen, uten å endre gammel `advertise(name,uuid)`.

AI Developer får et lite relevant utvalg fra den kildebelagte
[maskinvareoversikten](M5Stack-backend/docs/HARDWARE_COMPATIBILITY.md), ikke
hele katalogen. Dokumenterte grensesnitt er muligheter, ikke bevis på
tilkobling, tillatelser eller ferdig testede drivere. GPIO16/17 forblir
beskyttet som PSRAM, interne I²C-adresser beskyttes, og delt SPI håndteres
av busseieren fremfor å frigjøre OS-pinner som rå GPIO.

Ukjent eller kryptert Bluetooth-protokoll kan kreve paring/nøkler. Timingkritisk
bit-banging kan kreve native adapter eller ekstern bro. Slike forhold beholdes
som konkrete avklaringer; de skal ikke gi oppdiktet støtte eller blokkere
arbeidet med den generelle infrastrukturen.

## Utføring og avslutningsporter

1. Kartlegg og frys felles kontrakt, fil-eierskap og bevisnivåer.
2. Implementer SD/jobs/capture og backendlagring/prosessering parallelt.
3. Integrer Runtime AI-referanser, kontekst, Improve/fork/feedback/Resume,
   eksisterende UI og faktisk maskinvareforhandling.
4. Kjør meningsfulle negative tester: eierskap, gamle callbacks, ugyldige
   data, filgrenser, avbrudd, delvis overføring, feil hash, ressurskonflikt,
   offline og uendret legacy-levering. Behold rådata/feilhistorikk.
5. Frys kode; kjør relevant backendregresjon og native-/firmware-CI.
   Uendrede tester gjentas ikke uten en konkret grunn.
6. Aktiver eksisterende backend ved dokumentert idle, med uendrede nøkler og
   innstillinger. Signer eksakt CI-firmware og skriv bare inaktiv OS-plass;
   behold en fungerende tilbakevei. Alle tidligere GitHub-utgaver bevares.
7. Prøv normal appbygging og iterasjon med konkrete data. Fysiske handlinger
   på ukjent ekstern maskinvare styres av brukeren. Brukertester samles i korte
   sluttsteg og stopper ikke annet arbeid som kan fullføres.
8. Lever faktisk status, kostnader, begrensninger og korte nødvendige
   brukerhandlinger. PC-simulering gjør aldri et resultat fysisk verifisert.

## Representative akseptanser

| Scenario | Automatisk bevis | Fysisk bevis |
| --- | --- | --- |
| Bluetooth-lys | Rålogg/markering, deterministisk sammenligning, autorisert AI-analyse, Improve med samme data/kilde, testet kandidat, GATT/AD-bounds | Eget lys/fjernkontroll, brukers signalopptak og bekreftelse på faktisk lysrespons; protokoll kan kreve paring |
| Elektronikk | Busser/ressurser, binærlogger, analyse, testfeedback og målrettet versjon uten tap av data | Identifisert modul og kobling; riktige måleverdier og ønsket respons, også frakoblet modul |
| Vibrasjon | CSV/timing, markør/referanse, kjent syntetisk frekvens, filtrering/FFT/sammenligning, analyse→kontekst→ny appversjon | FIRE IMU-opptak, faktisk rate/tap, forskjell mellom hvile/bevegelse, fortsatt knapp-/OS-respons |

Dette er tester av en generell infrastruktur. Ingen hardkodet lys-, modul-
eller vibrasjonsløsning erstatter den samlede funksjonen.

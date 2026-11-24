# Sluttkontroll for FIRE OS leveransen

Dette er kontrollpunktene for leveransen i `DELIVERY_PLAN.md`. Et punkt blir
først bestått når resultat, versjon og testmiljø er registrert. PC-test og
fysisk test er ulike bevis. Dokumentet er ikke en liste over allerede beståtte
tester.

| Område | Kontroll | Bevis som kreves |
| --- | --- | --- |
| Offentlig tilgang | Feil enhet, token, JWT-signatur, utsteder, audience og utløp avvises. Falske proxyheadere og loopback gir ikke admin. | Faktiske auth-ruter i offentlig modus |
| Nettleser | Endringer krever riktig sesjon, CSRF og Origin. Enhetstoken gir ikke webadmin. Cookies er sikret; secrets er write-only. | Negative HTTP-/WS-tester og faktisk nettleser |
| Appbygger | Frakoblet FIRE kan få en app bygget mot kjent målprofil. Feil proposal/package avvises. Installasjon kontrollerer ny profil. | Backendtester og komplett mockflyt |
| Samtale og jobber | Reconnect/reboot/minimering bevarer korrekt jobb og historikk, uten ekstra betalt kall eller implisitt kjøring. | Tapte/dupliserte meldinger og gjenoppretting |
| Firmwareoversikt | Bare GitHub-katalog, kort info og rapportert enhetsversjon. Ingen import/send/flash i normal backendflyt. | UI-/API-kontroll |
| Direkte Home | Katalog, status og handlinger virker uten backend-PC. Ingen tilgang til andre topics eller publisering av state/ACK. | Faktisk broker/ACL, senere fysisk FIRE+HA |
| HA-tillatelser | HA validerer valgt funksjon, les/styr, verdiområde og fjernaksess ved utførelse. Fjerning av tillatelse blokkerer neste handling. | Faktisk automation/template, ikke bare regelmodell |
| Home-reconnect | Kommandoer beholdes ikke som retained. Utløpte/dupliserte kommandoer og ukjent ACK gir ikke ny fysisk handling. Home/Camper blandes ikke. | Broker/HA-restart og negative meldinger |
| Sikker OTA | Feil signatur, target, hash, størrelse og trunkert fil aktiveres ikke. Kun inaktiv slot oppdateres. | Pakke-/signaturtester og devicebevis |
| Recovery | Krasj før godkjenning og ødelagt normal Wi-Fi/UI kan reddes før vanlig OS starter, uten Windows og uten krav om SD. | Fysisk enhet; eksakt bootloader/partisjon/firmware |
| Respons | Ingen connect/TLS-/SD-venting i UI. Callbackmaksimum, lengste OS-pause, intern minimumsheap, største blokk og stackmargin registreres under last. | Kildekontroll og fysisk timing/minne |
| Oppsett | Norske trinn dekker ren backendprofil, domene/Cloudflare, MQTT, HA, paring og første USB-migrering. Eksempelfiler bruker ingen ekte hemmeligheter. | Kontroll av faktiske distribuerte filer |

## Kan kontrolleres uten brukerens konto eller fysisk enhet

Auth/CSRF/Origin, parser-/kontraktgrenser, redirect-/sertifikatfeil mot testserver,
lokal broker, konfigurasjonsvalidering, replay/utløp, nettleserflyter, bygging og
firmwaresignaturer. HA-runtimekontroll krever et faktisk egnet HA-testmiljø;
syntaktisk YAML eller en Python-regelmodell erstatter ikke det.

## Samles til brukerens sluttoppsett

Domene/Cloudflare-innlogging, installering i faktisk HA, valg av entiteter,
ekstern Home-adresse, første USB-migrering og fysiske nett/lyd/knapp/strømtester.
Disse punktene stanser ikke uavhengig implementering og lokal kontroll.

## Registrerte resultater 24. november 2026

| Kontrollmiljø | Resultat | Avgrensning |
| --- | --- | --- |
| Samlet backendpytest på frosset kode | 665 bestått; én deprecation-advarsel | Inkluderer Home-, migrerings- og diagnoseverktøytester; ingen fysisk FIRE eller live Cloudflare |
| Generert HA-policy i Jinja-/scriptvert og streng OpenSSL | 51 bestått, inkludert siste-øyeblikks tilgangsfjerning | Separat lokal kontroll; ekte runtime har eget bevis under |
| Faktiske C++-headere, g++ på Ubuntu | Begge kø-/JSON-programmene bestått; kilde 76fd112 | Vertstest, ikke ESP32 eller fysisk TLS-last |
| Faktisk nettleser, isolert mockprofil | Dialog → bekreftet bygg → bibliotek; innstillinger; firmwareoversikt; 390 px mobil uten sideoverløp | Ingen betalte AI-kall eller produksjonsendringer |
| Faktisk lokal prosess/HTTP-restart, isolert profil | Innstillinger/token beholdt; gammel browsersesjon avvist | Mock, ikke fysisk tale |
| Eksisterende Windows-program etter idle-kontroll | Kontrollert omstart, innstillinger/nøkler bevart; ny UI svarer | Ingen produksjons-AI-kall sendt |
| Ekte Mosquitto på Windows | Ikke kjørt: Code Integrity blokkerte biblioteket | Ingen sikkerhetspolicy omgått; Linux-kontroll pågår |
| Ekte Mosquitto 2.1.4, Ubuntu | Bestått TLS/navn, WS, passordskille og negative ACL-kontroller; jobb 138535122608 | Isolert testbroker, ikke brukerens HA/MQTT eller offentlig Cloudflare |
| Ekte HA 2026.11.3 og broker, Linux | Run 45422781786 grønn; pakke, handling/ACK, labels, fjernbryter, feilinput, reload og ny prosess med retained replay | Syntetiske entiteter; fysisk FIRE og brukeroppsett står åpne |
| Firmware, Linux på 34ade23 | Run 45426276015 grønn: normal, recovery, bootloader og 12 tester | Ingen fysisk FIRE; BLE/lyd kompilert, ikke fysisk testet |
| Distribuert USB-arkiv etter ny utpakking | Faktisk signatur-/hash-/image-/layoutkontroll bestått | Ingen COM åpnet; selve flashingen og tilbakeføring står åpne |

Fysisk oppstart/recovery og responstid forblir åpne til de er prøvd. Følg
[den konkrete sluttesten](docs/PHYSICAL_CHECK.md) og registrer resultatet samlet.

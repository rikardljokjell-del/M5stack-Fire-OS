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
ekstern Home-adresse og gjenstående fysiske nett/lyd/knapp/strømtester.
Rikards førstegangs USB-migrering er allerede gjennomført og dokumentert under.
Disse punktene stanser ikke uavhengig implementering og lokal kontroll.

## Registrerte resultater 25. november 2026

| Kontrollmiljø | Resultat | Avgrensning |
| --- | --- | --- |
| RC9 på frosset kilde b77c579 | CI 45575157747: 16 tester og alle tre bygg bestått | Normal RC9; USB beholder fysisk kontrollert RC2-bootloader/tabell/recovery med separat proveniens |
| Offentlig RC9 og signert pakke | Åtte filer HTTP 200 og byteidentiske; to katalogsignaturer samt opprinnelig og nyutpakket USB-pakke kontrollert | Offentlig fil-/pakkekontroll; fysisk installering er egen kontroll |
| Privat RC8-basert første forsøk | TLS RSA/MPI-allokering feilet trygt før filbyte/SD; ingen panic eller watchdog | Privat ekstra katalogkopi; uendret RC8-produksjon alene ble ikke isolert |
| Frosset RC9-kode i privat kontroll, signert RC8-mål | To faktiske GitHub→PSRAM→SD-lagringer; binær/begge kataloger og tidligere backups kontrollert; begge fulle OS-slotter og alle 8192 metadata-byte uendret etter hver | 342,596 s uten panic/WDT; maks gap 273,995 ms og min intern heap 5064 B gjelder privat kontroll/last, ikke ren normaldrift. Ingen installering eller omstart fra lagring |
| Tidligere publiserte firmwareversjoner | Opprinnelige 26 filer uendret; RC8-binær/USB/hash bevart; RC7-/RC8-kataloger arkivert med opprinnelig signatur | RC8-bevis får bare faktiske historikktillegg; gamle binærer og katalogbytes erstattes ikke |
| Eksakt publisert RC9, faktisk Firmware-UI | GitHub→PSRAM→SD med korrekt binær/begge kataloger; gamle RC8-fil/katalog intakte; begge fulle OS-slotter og alle metadata uendret ved save | Én RC9-lagring; erstatnings-/backupflyt prøvd to ganger med samme frosne kode og RC8-mål |
| Separat RC9-installasjon fra SD | Ren A/app0, sekvens 19 VALID og gyldig CRC; faktisk image matcher CI. Root parsede lagrede 8192 metadata-byte uavhengig | Direkte RC9-GitHub-OTA ikke gjentatt; RC7-direkteløpet står som historisk bevis |
| Ren RC9-sluttstatus | Begge OS-plasser CI-RC9; harness fjernet, A/metadata urørt ved B-opprydding; minst 125 s normaldrift  + 45,044 s vanlig omstart uten panic/WDT; gap 92,998/85,996 ms | B-kopien er bytekontrollert, ikke separat startet; ingen Lua-/AI-/Home-last påstått |
| Faktisk siste RC9-inventar | Ny boot og nyere complete/SDready; 7/7 current-scope ID/version/checksum/normalisert pakke-ID matcher varig alternativ referanse; health/UI200, korrekt 8-versjonskatalog uten feil | Referanse er siste komplette før produksjons-RC9/SD-installasjon, mulig privat kontrollboot, ikke RC2-original. Lagret rapportalder176 s |

Eksakt RC9 SD-lagring, separat SD-installasjon og ren produksjonsboot står i
[SD-rapporten](M5Stack-device/PHYSICAL_SD_2026-11-25.md).

## Registrerte resultater 24. november 2026

| Kontrollmiljø | Resultat | Avgrensning |
| --- | --- | --- |
| Samlet backendpytest på frosset kode | 665 bestått; én deprecation-advarsel | Inkluderer Home-, migrerings- og diagnoseverktøytester; ingen fysisk FIRE eller live Cloudflare |
| Generert HA-policy i Jinja-/scriptvert og streng OpenSSL | 51 bestått, inkludert siste-øyeblikks tilgangsfjerning | Separat lokal kontroll; ekte runtime har eget bevis under |
| Faktiske C++-headere, g++ på Ubuntu | Begge kø-/JSON-programmene bestått; kilde 76fd112 | Vertstest, ikke ESP32 eller fysisk TLS-last |
| Faktisk nettleser, isolert mockprofil | Dialog → bekreftet bygg → bibliotek; innstillinger; firmwareoversikt; 390 px mobil uten sideoverløp | Ingen betalte AI-kall eller produksjonsendringer |
| Faktisk lokal prosess/HTTP-restart, isolert profil | Innstillinger/token beholdt; gammel browsersesjon avvist | Mock, ikke fysisk tale |
| Eksisterende Windows-program etter idle-kontroll | Kontrollert omstart, innstillinger/nøkler bevart; ny UI svarer | Ingen produksjons-AI-kall sendt |
| Ekte Mosquitto på Windows | Ikke kjørt: Code Integrity blokkerte biblioteket | Ingen sikkerhetspolicy omgått; Linux-kontroll bestått under |
| Ekte Mosquitto 2.1.4, Ubuntu | Bestått TLS/navn, WS, passordskille og negative ACL-kontroller; jobb 138535122608 | Isolert testbroker, ikke brukerens HA/MQTT eller offentlig Cloudflare |
| Ekte HA 2026.11.3 og broker, Linux | Run 45422781786 grønn; pakke, handling/ACK, labels, fjernbryter, feilinput, reload og ny prosess med retained replay | Syntetiske entiteter; fysisk FIRE og brukeroppsett står åpne |
| RC7-firmware, Linux på 7eb40b7 | Run 45496282327 grønn: normal, recovery, bootloader og 15 tester | Eksakt normal RC7; USB-pakken beholder fysisk testet RC2-bootloader/tabell/recovery med eksplisitt komponentproveniens |
| Faktisk C++ for HTTP og SD-filbytte, Linux | Nye tester av streng HTTP-framing/lengde og kort skriving, korrupt readback og feil ved filaktivering bestått i samme CI | Vertstester; fysisk SD-kort og ESP32 OTA er egne kontroller |
| Offentlig RC7-utgivelse | Sju filer HTTP 200, korrekt lengde, byteidentiske; katalogsignaturer verifisert | PC-nedlasting, ikke fysisk FIRE OTA |
| Brukerens SD-feil på fysisk FIRE | EIO gjenskapt: 9 av 2048 byte skrevet etter omtrent 1,64 MB; god plass | Lav heap observert samtidig, men årsakssammenheng er ikke bevist |
| Privat RC6-basert SD-test | Ikke bestått: LoadProhibited i FatFS validate/f_write før OTA | Ingen kjent årsak eller grunnlag for å tilskrive maskinvare; RC7 fjerner SD-nedlasting fra firmwareflyten |
| Fysisk RC7 direkte GitHub→OTA | Avbrudd ved 1 % med alle 8192 metadata-byte uendret; nytt UI-forsøk installerte eksakt CI-bilde og startet app1 | Minst 24225 byte bekreftet skrevet før avbrudd; ikke egen partial-image-readback |
| RC7 sluttstatus og vanlig omstart | App1 sekvens10 VALID/CRC bekreftet; begge slotter ren CI-RC7; 125 s + 45 s uten panic/watchdog; gap85,014/86,013ms | Privat teststyring hadde en for tidlig feilmelding; faktisk firmware/boot kontrollert uavhengig uten produksjonskodeendring |
| Faktisk siste RC7-inventar til backend | Ny boot/nyere komplett inventar, 7/7 ID/versjon/checksum/normalisert pakke-ID bevart, SD klar | Native appfil-identiteter; ingen AI-/app-RUN eller brukerens HA påstått |
| Distribuert USB-arkiv etter ny utpakking | Faktisk signatur-/hash-/image-/layoutkontroll bestått | Denne separate pakkekontrollen åpner ingen COM-port |
| Faktisk USB-migrering på FIRE | Dobbel 16 MiB-backup, skriving og eksakt tilbakeavlesning bestått | Backup og rålogger er private; normal OTA er egen kontroll |
| Kontrollert tidlig reset | SDK markerte oppstart ABORTED og lastet factory | Ikke fysisk GPIO39-knapphold eller tilbakeføring til tidligere normal OTA-slot |
| Fysisk RC5-oppstart og vanlig reset | VALID lagret, 125 s + 45 s uten ekstra reset/panic/watchdog; gap 87,988 / 86,013 ms | Oppstart/inventar, ingen Lua-callback eller tale/Home-belastning |
| Faktisk RC5 til eksisterende backend | Fersk HELLO og komplett SD-inventory, 7/7 ID/versjon/checksum/pakke-ID bevart | Ingen AI-/appkjøringspåstand; Auto kan være idle/offline når transporten er klar |

Det avgrensede USB-beviset står i [fysisk rapport](M5Stack-device/PHYSICAL_USB_2026-11-24.md).
Visuell UI/knapper/lyd, Home, fysisk nett-/strømbrudd og samlet AI/appflyt er fortsatt åpne.
Følg [den konkrete sluttesten](docs/PHYSICAL_CHECK.md) og registrer resten samlet.

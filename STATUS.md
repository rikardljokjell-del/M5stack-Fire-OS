# Leveransestatus – 26. november 2026

Samlet arbeid følger [godkjent plan](DELIVERY_PLAN.md). Bruk
[oppsettsveiledningen](SETUP.md) som inngang. Dette dokumentet skiller kildekode,
lokale tester og faktisk fysisk verifikasjon.

## Åpne gjøremål

- [x] **Aktuell GitHub → SD-flyt på fire-os-1.3.0-rc7 er fysisk verifisert.**
  Etter brukerens nye ønske om retting ble normal Settings-flyt prøvd med
  passiv logging. Hele filen på 2 683 760 byte ble lastet ned, hashkontrollert,
  skrevet til SD og lest tilbake, inkludert begge signerte katalogkopier.
  Brukeren bekreftet «SD kontrollert / nedlasting fullført» og at alt fungerte.
  Ingen installasjon, omstart, formatering eller firmwareendring ble gjort.
  Den tidligere skrivefeilen ble ikke gjenskapt; dens isolerte rotårsak er
  derfor fortsatt ukjent. Én vellykket prøve er ikke en garanti mot alle
  fremtidige kort-/nettfeil. Se [den fysiske SD-rapporten](M5Stack-device/PHYSICAL_SD_2026-11-25.md).

## Status nå

### Backend-sync og sikker nettilgang – 26. november

**Målrettet retting etter adressebyttet:** Brukeren fikk ikke koblet FIRE til den
offentlige backenden, heller ikke etter Backend-sync Off/On, og opplevde tregere
statusendring. Passiv diagnostikk viste gjentatt
`start_ssl_client=-1` før WebSocket-oppstart, uten nok informasjon til å fastslå
underårsaken. Ett separat vindu målte 2,739 sekunder i tegning/knappbehandling.
RC6 er deretter fysisk installert i A55, med RC5 i B54 bevart. Oppkoblingsfasen
beholdes nå uten gjentatte Connecting-varsler, og Sync skriver bare sin egen
NVS-innstilling. Etter RC7 bekrefter brukeren at Sync-betjeningen fungerer.

Den nye diagnosen i to normale oppstartsvinduer viser åtte feil med åpen socket,
TLS-tilstand 17 (`SERVER_NEW_SESSION_TICKET`), retur −1 og varighet 5,778–5,847 s.
Dette avgrenser feilen til TLS-håndtrykkets femsekundersfrist, før WebSocket.
RC7 med avgrenset 12-sekunders TLS-håndtrykksfrist er nå fysisk installert i B56,
med RC6 i A55 bevart. Fem sekunders TCP-frist og sertifikatkontroll er uendret.
Begge ordinære oppstarter fullførte DNS/TCP/TLS på henholdsvis 5,598 og 5,654 s,
etterfulgt av HTTP101 og godkjent backendøkt. Ingen TLS-feil, panic, watchdog,
JSON-avvisning eller mistede inputhendelser ble registrert i disse to vinduene.
Full bildelesing/SHA-256, VALID/CRC, native-CI og komplett firmware-CI er grønne.
Dette er positiv fysisk oppkoblingsverifikasjon. Brukeren svarte «funker» på
prøven med gjentatt Off/On, rask Sync-betjening og AI Developer åpen. Svaret er
brukerbekreftelse, uten målt trykklatens eller presis stoppeklokke. Langtidsprøve
og annet Wi-Fi avventes fortsatt; brukeren har uttrykkelig utsatt hotspot-prøven.
Brukeren bekrefter faktisk Studio-innlogging og appvisning fra mobilen med mobildata.
Én etterkontroll viser tre aksepterte gjenoppkoblinger på samme økt/oppstarts-ID,
uten avslag. En påfølgende ny oppstarts-ID er registrert; årsaken er foreløpig
ukjent og avklares med brukeren. Dette alene fastslår ikke fysisk omstart,
ettersom klientkonfigurasjon også oppretter en ny oppstarts-ID.
Brukeren er usikker på om FIRE ble startet på nytt eller konfigurert; årsaken
beholdes derfor som uavklart, uten påstand om selvstendig omstart eller panic.
Offentlig HTTPS-helse fra PC virker også med TLS 1.2 og sertifikatkontroll.
Ingen sertifikat-/autentiseringsgrense er svekket som feilsøkingstiltak.

Brukerens RC4-avslag er gjenskapt. Kvitteringer viser at en utløpt samtale ble erstattet av
en ny, mens senere FIRE-forsøk fortsatt sendte forgjengerens ID. Den nye
samtalen blokkerte da gjenopptakelsen. Disse fem requestene er rekonstruert
med samme normaliserte SHA som loggen; enhet, oppstart og kapabiliteter var
identiske. Hvorfor den første nye startkvitteringen ikke ble adoptert på FIRE,
er fortsatt ikke fysisk fastslått. Alle aktuelle bootstrap-meldinger passer
de uendrede byte-/token-/dybdegrensene.

Varig, strengt avgrenset forgjenger/etterfølger-gjenopptakelse og kvitterte
app-/modusvalg er implementert. Backendrettingen er aktivert i samme prosessmodell,
og den dokumenterte gamle CE/FC-tilstanden er koblet med en kontrollert,
atomisk metadataretting. Opprinnelige hendelser er bevart byteidentisk.
Ingen generell overtakelse eller omgåelse av bygge-/kjøre-/kostnadsporter er innført.
En reell Python 3.11-kanselleringsfeil i eksisterende Reverse TCP er også rettet.

Samlet backendregresjon: **1251 PASS**, 4 varsler, 673,29 sekunder. Slutt-CI:
292 PASS og to Windows-spesifikke tester som kjøres lokalt (12/12 PASS).
Reell lokal WebSocket/Reverse TCP-prøve dekker tapt startrespons og gjenforsøk
uten dupliserte samtaler eller arbeid. Alle sikkerhets- og meldingsgrenser er beholdt.

Brukeren bekrefter nå på fysisk RC4 at den kobler til, beholder forbindelsen og
at Backend-sync Off/On fungerer. FIRE ble ved et uhell startet på nytt før
prøven; dette er derfor **ikke** verifikasjon av den gamle CE-bootens gjenopptakelse.
Signert og CI-kontrollert **1.6.0-rc5** er nå fysisk installert i B54 og markert
VALID med gyldig CRC etter 45 sekunders helsekontroll og én normal omstart.
Hele det tilbakeleste bildet på 2 739 776 byte matcher testet SHA-256.
RC4 i A53 og dens metadatasektor er bevart. RC5 inkluderer kvitterte app-/modusvalg
og korrekt visning av det midlertidige oppsettspassordet. Dette installasjonsbeviset
er separat fra den kommende fysiske prøven av offentlig WSS.
Faktisk RC5-HELLO og fersk, komplett inventory fra sluttbooten bekrefter alle
13 app-ID-er og uendrede SDK-/Runtime AI-/Data Engine-/Evolution-kontrakter.

Cloudflare er aktivert i **samme backend**. Eksisterende `fire-pc`-tjeneste
gjenbrukes, med kontrollert offisiell binærfil og automatisk tjenesteoppstart.
Studio-adressen er `https://firestudio.ljoekjell.no/ui/`; FIRE-adressen er
`wss://fire-device.ljoekjell.no/ws/device`. Faktiske offentlige prøver bekrefter
Access-videresending, signaturkontroll, avvisning av feil enhetsnøkkel og en
autentisert offentlig WSS-oppkobling uten noen enhetshendelser eller AI-kall.
Enhetsdomenet gir ikke tilgang til Studio eller desktopkontroller.

Én eid automatisk oppstart for eksisterende backend er installert for denne
Windows-brukeren. Gjentatt installasjon og kjøring beholdt samme ene prosess.
PC-en må være våken, på nett og brukeren innlogget; oppstart før Windows-innlogging
er ikke etablert. Nøkler, modeller og kostnadsgrenser er bevart.

FIREs adresse er nå lagret som `fire-device.ljoekjell.no:443` via eksisterende
Backend config etter brukerens fysiske åpning av oppsettsvinduet. Enheten svarte
med bekreftet lagring; blanke nøkkel-/ID-felt beholdt eksisterende verdier.
Backenden er byttet kontrollert fra lokal Reverse TCP til direkte offentlig WSS.
Kun transportfeltet ble endret; public-felt, modeller, grenser, nøkler og automatisk
oppstart er bevart. Én prosess og vellykkede helse-/autentiseringskontroller er
bekreftet. Etter RC7 bekrefter faktisk backendstatus offentlig admisjon med online
socket/økt, korrekt RC7 og ferskt, komplett inventory med alle 13 app-ID-er på
samme siste boot/epoch. Begge RC7-oppstartene er akseptert uten nye avslag.
Ingen Reverse TCP-kanal er aktiv. Dette er en faktisk offentlig fysisk forbindelse;
langtidsstabilitet og gjentatte av/på-runder er fortsatt egne brukerprøver.

**Gjenstår før fysisk fjernbruk av FIRE fra annet nett er godkjent:** fysisk
oppkobling/Off-On via den offentlige adressen fra et annet Wi-Fi. Brukeren prøver
dette senere. Studio-innlogging og appvisning fra mobil med mobildata er bekreftet.
Ingen ekstra tunnel eller tokeninnsamling er gjort.

### Tidligere meny- og tilkoblingsrettinger

Brukeren har meldt trege/mistede knappetrykk, flere konkrete menyavvik og
gjentatt til-/frakobling i AI Developer på installert 1.6.0-rc2. Den videre
Evolution-akseptanseprøven er derfor satt på vent.

Tilkoblingsfeilen er gjenskapt fra faktisk lagret trafikkgrunnlag:
`session_started` passer enhetens grenser, mens følgende `session_snapshot`
har 6 978 byte, men 1 227 JSON-tokens mot tillatte 1 024. Dupliserte
kapabiliteter i enhetsdelen er fjernet; grensene økes ikke. Backendrettingen
er aktivert med én grasiøs omstart og uendrede rå innstillinger/Vault-fingeravtrykk.
Brukeren opplevde cirka to minutter stabil tilkobling på RC2. En etterfølgende
status viste offline og flere tilkoblinger; dette alene dokumenterer ikke en
kontinuerlig socket. Auto-hvile og faktisk tilkoblingsbrudd må skilles i RC3-prøven.

Statiske menyer tegnes nå ved endring og lavfrekvent statusoppdatering.
En avgrenset GPIO-edgekø fanger korte trykk også under rendering, med samme
sprett-/hold-/vekkeregler og vakt mot usett godkjenning. Globale dobbeltklikk
og tilhørende innstillinger er fjernet etter brukerens godkjenning. Resume er
samlet i én liste; arbeidsmenyen bruker eksisterende jobbkontroller. De meldte
DateTime-/Bluetooth-/bunntekst-/Back-/MenuLayout-funnene er rettet i kandidaten.

Appikoner bruker et delt utvalg fra eksisterende SDK-ikoner, uten ekstra
AI-kall. Tidlig ikoncheckpoint har grønn backend-, native- og firmware-CI.
Ny signert **1.6.0-rc3**, kilde `d37a99ad90d5bee781d0cd1278ab1110d35bccef`,
har grønn firmware-, native- og backend-CI. Faktisk IRAM er 130 400 av 131 072
byte (672 byte fri); statisk DRAM er 64 212 byte, 408 byte mer enn RC2.
Ingen SDK-/appgrenser er økt, og ingen ekstra framebuffer er innført.

Samlet backendkjøring ga 1203 PASS og én reell kostnadsregresjon ved appvalg
under tale. Minsterettingen beholder eksplisitt jobbmål, men bruker endelig
valgt app i vanlig samtale. Opprinnelig test er beholdt; etterporter ga 76/76
PASS og slutt-CI 210/210 PASS. Python-pakken er prøvd isolert med nett blokkert;
Windows-bygg og 71 modulers kildebytekode/ressurser er kontrollert uten å kjøre
usignert EXE (Windows App Control). Fullsuiten er ikke gjentatt.

RC3 ble først fysisk installert i B52 og markert VALID med gyldig CRC etter normal
helsekontroll og omstart. Eksakt fullbildelesing matcher den testede CI-filen.
RC2 i A51 og SD-/NVS-data ble bevart i dette steget. RC3-sluttbootens HELLO og
ferske inventory bekrefter RC3, riktige kontrakter og alle 13 apper; de sju
opprinnelige app-ID-ene er beholdt. Dette er ikke en versjonssammenligning.

Ett passivt vindu på 150 sekunder fant ingen omstart, panic, watchdog eller
avvist JSON, men registrerte ingen enkelttrykk. Én sluttavlesning viste samme
boot og epoch, offline og ingen nye tilkoblinger i akkurat dette vinduet.
Dette var ikke et målevindu for brukerens senere prøve.

Brukeren bekrefter deretter at knappene er raske og fungerer bra, og at
forbindelsen holder seg når den først er etablert. Brukeren melder samtidig
oppkobling over 30 sekunder eller uten resultat, særlig Backend av → vent → på.
Tre faktiske startavslag er funnet. Deres detaljerte konfliktgrunn var ikke
lagret. En åpen WebSocket kunne fortsatt svare på ping mens FIRE ventet uten
egen frist på en godkjent samtale. Dette forklarer en konkret fastlåst tilstand,
men fastslår ikke hvilket identitetsfelt som ga de historiske avslagene.

Ny, avgrenset RC4-retting har fem sekunders samtalestartfrist og tydelig
terminalt avslag med eksplisitt ny prøve via eksisterende av/på/config.
Backend gjenoppretter bare identisk, inaktiv utløpt/stoppet samtale som en ny
samtale med samme prosjekt og plan, uten gamle forslag eller fullmakter.
En identisk aktiv jobb kan kobles til samme samtale også etter lang venting,
slik at Pause/Avbryt fortsatt virker. Nye avslag journalfører kort årsakskode.
Feil eier, oppstart, kapabiliteter eller prosjekt omgås ikke.

Sluttkontrollen for backend har 223/223 PASS i CI; den berørte lokale porten
har 43/43 PASS etter 91/91 for første checkpoint. Firmware-/native-CI for
RC4 er grønne, med uendret IRAM og statisk DRAM fra RC3. Signert privat pakke
består uavhengig kontroll. Backend er aktivert én gang med uendrede rå
innstillinger/nøkkelfingeravtrykk og én lytter. RC4 er fysisk installert i
A53 VALID/CRC, med RC3 B52 som bevart reserve. Flash-MD5 og full tilbakelesing
av de 2 737 216 bildebytene matcher CI/SHA256. Helseprøve 45,170 sekunder og
vanlig omstart 35,021 sekunder bestod uten panic/watchdog/avvist JSON; COM er
lukket. SD, NVS og grunnlagsfirmware ble ikke skrevet. Den etterfølgende
brukerprøven feilet som dokumentert ovenfor; oppstartskontrollen alene beviser
ikke fungerende gjenoppkobling.
Ingen tallfestet trykklatens eller garanti om hver oppkobling utledes av
brukerbekreftelsen.

Siste kontroll fant også at Avbryt på et Evolution-underbygg måtte stoppe
hele eksisterende Evolution-jobben. Nå tilbakekalles mandatet før oppgaven
kanselleres. Vanlig kanselleringskvittering, kandidater, kostnad og eventuelt
ukjent forbruk beholdes. Feilen er gjenskapt og rettet med målrettede tester;
ingen nye jobbtyper eller kontrollmekanismer er opprettet.
Ingen betalte backend-AI-kall eller nye brukerappkommandoer er gjort.

### Evolution og felles AI Developer Settings – installert, funksjonsprøve gjenstår

Evolution er implementert som styring rundt eksisterende Builder, Repairs, Jobs,
Data Engine, Runtime AI, apphistorikk og kostnadsregistrering. Det opprettes
ingen ny backend, database eller konkurrerende applivssyklus. Alle fem
egenskaper er av som standard. Mandater, uavhengig sammenligning, strategiarkiv
og eksplisitt brukerhukommelse bruker eksisterende filbasert lagring.

FIRE-kandidaten har én appvelger, Resume-valg med appnavn og en samlet Settings
over Back. Settings henter og endrer backendens faktiske Runtime AI-valg,
modellroller og bruksgrenser. Disable all limits slår av alle backendens
kostnadsgrenser, inkludert Evolution; tekniske grenser og installasjons-/
kjøregodkjenninger beholdes. Innstillinger og nøkler på produksjon er ikke endret.

Én samlet backendregresjon ga **1167 PASS / én feil i en testfixture**, 618,97 s.
Testen byttet sesjonens eier uten å bytte prosjektets eier; eierkontrollen ble
beholdt, og fixturen bruker nå vanlig PC-samtale. Etterkontroller ga 13 PASS
for ruting/fixtur og tre appers vanlige BUILD-bekreftelser, 3 PASS for jobb-/
appkost uten dobbelttelling, og 32 PASS for omstart, mandatbinding, Pause/Resume
og overgang tilbake til vanlig manuelt arbeid. Fullsuiten ble ikke gjentatt.
GEPA-kjernen, låst holdout, replay fra faktisk lagringsformat og tre normale
Builder-baser/kandidater er prøvd offline; dette er ikke en live AI-rangering.

Den avsluttende Python 3.11/Linux-kontrollen er **181/181 PASS**, 32,47 s
([CI](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45788517423)).
Første Linux-kjøring avdekket en reell kappløpsfeil der et allerede publisert
BUILD-forslag kunne bli avvist før tekstoppgaven hadde avsluttet sin siste
statusmelding. Bekreftelsen venter nå kort på akkurat denne oppgaven og
revaliderer forslag/sesjon; hele protokollbolken bestod 20/20 tester.
Manglende GUI-skjerm i CI og en test med eksakt flyttallsammenligning er også
rettet uten å endre kostnadsberegning eller tilgangskontroll.

Sluttpakken for Python er kontrollert mot alle backendkildene og prøvd isolert
med ekte GEPA, Evolution av og nettverk blokkert. Windows-pakken er bygget;
70 innebygde moduler er sammenlignet med kildekodens bytekode, og ressurser,
GEPA-metadata og lisenser er kontrollert. Den usignerte EXE-filen er ikke kjørt
fordi Windows App Control blokkerer den. Dette er ikke Windows-runtimebevis.

Firmware **1.6.0-rc2**, kilde `d0fff47c5218cbc30ace0edd53d6edd02b43daee`, har
[grønn firmware-CI](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45784404031)
med faktiske native tester og normal/recovery/bootloader-link. Manuelle bygg
åpnes gjennom kilde-/prosjektbundet eksisterende Developer-forslag, også for
godkjente prøver på flere apper. BUILD, installasjon og RUN omgås ikke.
Den private signerte RC2-pakken har bestått en uavhengig kontroll av signatur,
hasher, bilder og partisjonsoppsett. Ingen serieport ble åpnet. Alle 68
tidligere publiserte firmwarefiler er kontrollert byteuendret.

Den integrerte backenden er aktivert etter tre ferske tomme aktivitetskontroller,
grasiøs lukking og én kjøring av eksisterende launcher. Én ny lytter, HTTP/UI/
ressurser, Evolution-status og tilgangskontroller er verifisert. Rå innstillinger
og Vault-fingeravtrykk er uendret; Evolution er fortsatt deaktivert med alle fem
brytere av. Ingen brukerappkommando ble sendt.

Ved den opprinnelige Evolution-leveransen, før RC3-rettingene ovenfor, ble eksakt signert
**1.6.0-rc2 fysisk installert i A51 VALID/CRC**. Flash-MD5 og full tilbakelesing
av de 2 665 296 bildebytene matcher CI/SHA256. Forrige fungerende 1.5.0-rc2
i B50 VALID er beholdt. Lokal helseprøve 45,208 s og vanlig omstart 35,009 s
bestod uten panic/abort/watchdog; serieporten er lukket. Det ble ikke skrevet
over SD, NVS, partisjonsoppsett, recovery eller bootloader.
Sluttoppstartens faktiske HELLO annonserer 1.6.0-rc2 og riktig Evolution-
kontrakt; SDK, Runtime AI, Data Engine og Hardware API er uendret. Samme
oppstart har komplett, fersk SD-oversikt med 13 apper. De opprinnelige sju
app-ID-ene og «Måledata kontroll» var fortsatt present. Dette historiske
snapshotet var offline; årsaken til frakoblingen ble ikke fysisk fastslått.

Brukerbetjening, live AI-prøve og fysisk Evolution-sløyfe er fortsatt
utestående. Ingen betalte AI-kall eller brukerappkommandoer ble utført.
Den utsatte «Måledata kontroll»-avlesningen ble ikke gjort før den godkjente
omstarten; appen må åpnes igjen for å avklare manglende dataflyt. Oppstartsbevis
er ikke godkjent måleflyt. Eldre signerte pakker og publiserte firmwarefiler
er bevart.

Se [Evolution-veiledningen](M5Stack-backend/docs/EVOLUTION.md) og
[research/gjenbruksvalg](M5Stack-backend/docs/EVOLUTION_RESEARCH.md).

### FIRE Data Engine – inkludert i 1.6.0-rc2, måleflyt fortsatt uverifisert

Data Engine er integrert med eksisterende Lua-jobber, SD, transport, Runtime AI
og AI Developer. Appene kan lagre tidsindekserte opptak og hendelser, behandle
data med statistikk, filtrering, spektrum og sammenligning, og sende relevant
grunnlag til videreutvikling. Improve, ny app fra eksisterende app, tilbakemelding
og Resume bruker kilde-/eierbundet, frosset kontekst. Vanlige bygge-, installasjons-
og kjørebekreftelser beholdes. Data og innstillinger følger samme app ved oppdatering.

Generelle bussgrensesnitt og et selektivt produsentregister utvider relevante
maskinvareopplysninger uten å annonsere funksjoner som enheten ikke tilbyr.
Tre representative BLE-, elektronikk- og IMU-forløp er testet med simulert
nettklient; dette er ikke fysisk kontroll av eksternt utstyr.

Backendens fullkjøring ga 1097 PASS og tre utdaterte testforutsetninger.
Rettede forventninger og de siste avgrensede adapterendringene har 120/120
berørte tester PASS. Separat utpakket wheel kjører fra pakkede ressurser.
CI45709316709 på kilde `8ab274f` har 25 native tester og tre bygg PASS;
strenge C++-kontroller består separat. Statisk RAM er økt med åtte byte,
og IRAM-marginen er uendret. Eksisterende tids-/minne-/I/O-grenser beholdes.

Ved den forrige Data Engine-leveransen ble eksakt signert 1.5.0-rc2 fysisk
tilbakeavlest med MD5/SHA256 og installert i B50 VALID/CRC, med 1.4.0-rc3
A49 som daværende tilbakevei. Helseprøve 45,021 s og vanlig omstart
35,097 s ga ingen panic/abort/watchdog. Dette bekrefter firmware/oppstart;
måling → SD → analyse → Improve prøves nå separat med en vanlig Lua-app.
Ingen betalte AI-kall er utført i denne oppgraderingen så langt.

«Måledata kontroll» er ordinært installert og har gitt ekte, kildebundet
started/healthy på RC2. Den var fortsatt healthy etter 20 sekunder. Det er
foreløpig ikke mottatt noen dataforespørsel eller noe datasett fra opptaket.
Skjermstatusen må avklare den lokale fasen før videre prøve; dette resultatet
føres ikke som bestått opptak, synkronisering, analyse eller Improve.
RC2-utgivelsesfilene holdes foreløpig private; offentlig katalog er ikke flyttet.

Fersk faktisk HELLO annonserer Data Engine `15a9ff7e…` med IMU 50/100 Hz,
mikrofon 8/16 kHz og BLE-opptak. SDK- og Runtime AI-hashene er uendret.
SD er klar; alle 12 apper er rapportert etter forespørselen på gjeldende
boot/forbindelse. Alle sju opprinnelige app-ID-er er bevart. Dette er ikke
en påstand om uendrede versjoner eller fysisk testing av hver opptakskilde.

Se [praktisk veiledning](M5Stack-backend/docs/DATA_ENGINE.md),
[maskinvareoversikt](M5Stack-backend/docs/HARDWARE_COMPATIBILITY.md) og
[fysisk rapport](M5Stack-device/PHYSICAL_DATA_ENGINE_2026-11-25.md).

### Polert FIRE OS og Home – tidligere installert 1.4.0-rc3

Fire appkort per side og felles utforming i OS/Home er på plass. Tekst og
ikoner er kantutjevnet, og kort/knapper har jevnere avrundede kanter. Brukeren
bekreftet at RC2 så bra ut; deretter ble ikon og navn sentrert i hvert
hovedmenykort. Knapperaden viser nå bare handlingene, uten A/B/C-merker.
Fysiske knappetrykk, lagrede valg og appdata fungerer etter samme logikk.

Ingen ekstra skjermbuffer eller endring av SDK/Runtime AI, Home-rettigheter
eller protokoll. 24 native tester, seks faktiske C++-tegnede skjermer, tre
bygg og strenge C++-kontroller består. Statisk RAM/IRAM-margin er uendret.
Eksakt RC3 er fysisk MD5/SHA256-kontrollert og helsegodkjent i A49 VALID/CRC;
akseptert RC2 B48 er urørt reserve. Vanlig omstart bestod uten panic/watchdog,
COM er lukket. Oppstartsmaksima er ikke en måling av knapperespons.
Alle eldre publiserte firmwareversjoner beholdes. HA-styring er ikke
bekreftet av denne UI-prøven. Se [UI-veiledningen](M5Stack-backend/docs/FIRE_OS_UI.md).

### Runtime AI, kostnader og appflyt – tidligere RC7-prøve

Runtime AI er implementert som en valgfri, asynkron SDK-tjeneste over samme
backend og transport, med global/per-app-aktivering, eget modellvalg og
forbruk. Ingen nye API-nøkler på enheten. Jobbpris, appens samlede
utviklingspris og Runtime AI-forbruk er skilt. Ukjent bruk vises som ukjent,
eventuelt med empirisk anslag; maksimumsreserve vises ikke som forbruk.

Byggeflyten beholder den beste validerte rettingskandidaten. Ferdigdialog,
installasjonskvittering, nedlastingsprogresjon og korte statuslinjer er rettet
i firmwarekilden. Backend: 1013 PASS / fire gamle kostasserts; rettede
forventninger og berørte kost-/jobbtester består. Windows-backenden er
aktivert med bevarte innstillinger/nøkler. Kostnadsvisningen er også kontrollert
i det faktiske Windows-programmet.

RC5 rettet en fysisk bekreftet full innstillingslagring som kunne gi falsk
«installert»-kvittering. Samme app startet deretter faktisk, men traff fortsatt
24 ms-grensen ved frame 152. RC6 bruker en avgrenset SDK-GC-endring med samme
minne-, instruksjons- og tidsgrenser; 21 native tester og tre bygg består.
Eksakt RC7 er fysisk helsegodkjent i B46, med RC9 A45 beholdt. RC7 sender
faktisk verifisert kildehash i alle startkvitteringer, etter et konkret
backendavslag i RC6. Ingen sikkerhetskontroll er svekket.

Samme manuelle oppdragsapp startet med ekte, kildebundet started/healthy og
kjørte 112,97 s på samme boot/run/pakke uten registrert appfeil. Brukeren
bekrefter synlig spill og fungerende A/C. Første update var 12,139 ms; alle
senere frametider er ikke målt. Faktiske B-utløste Runtime AI-resultater og
kostnader gjenstår i sluttprøven. Tidligere kilde-/firmwarefeil er bevart i
historikken og er ikke generelt friskmeldt.

Se [Runtime AI og teststeg](M5Stack-backend/docs/RUNTIME_AI.md). Tidligere
appspesifikke 24 ms-feil er ikke friskmeldt. Den aktuelle GitHub → SD-prøven er nå bestått, se øverst.


### FIRE App SDK – tidligere utviklings- og testhistorikk

SDK-arbeidet er godkjent og pågår i eksisterende firmware/backend. Felles
grafikk-/fontdata, UI-kit, temaer og kontrakt ligger i
`M5Stack-backend/fire_backend/data/app_sdk/` og
`M5Stack-backend/contracts/APP_SDK-v1.json`. Se
[SDK-veiledningen](M5Stack-backend/docs/FIRE_APP_SDK.md).
Eksisterende Lua-apper og hardwarehash skal bevares; SDK krever eksplisitt
ny kapabilitet. Simulator, Studio-preview og eksisterende AI-review utvides
samordnet. Innhold og tidlige PC-tester er ikke fysisk SDK-verifikasjon.
Den tidligere firmware-SD-feilen ble senere prøvd på nytt, med bestått RC7-flyt, se øverst.

Siste backendkjøring ga 957 beståtte tester og én feil i to avledede
grensesnittfiler med gammel SDK-hash. Filene er regenerert og den berørte
kontrakttesten består. Bakgrunnsforberedelse og simulator har i tillegg
bestått 182 berørte og 68 avsluttende målrettede tester, med identiske
piksler for alle seks gallerisider og fire representative appkilder.
Den samordnede native endringen avventer nytt CI-bygg og fysisk måling.
Koordinatoren har prøvd faktisk Studio-forhåndsvisning med virtuelle A/B/C,
nullstilling og tidsfremdrift. Dette er PC-verifikasjon. De private
De første SDK-prøvene stoppet ved 12 ms. Etter kontrollert kalibrering bestod
første faktiske galleriskjerm; tung buegrafikk traff fortsatt grensen.
Ren CI-testfirmware **1.3.0-rc1 kjører nå i B34 VALID/CRC**, med RC9 beholdt
i A33 som tilbakefall og COM lukket. Dette er en lokal testkandidat, ikke
en godkjent offentlig SDK-leveranse.
Arbeidet er avgrenset til ferdigstilling av SDK-fundament, ytelse og fysisk
kontroll; nye funksjoner og betalte appforsøk er stanset.
Tegnerammen kalibreres nå uttrykkelig til 24 ms for SDK-update etter målte
15–17 ms galleriframes. Eldre update/knappetrykk beholder 12 ms; oppstart
beholder faktisk eksisterende 250 ms. De øvrige ressursgrensene endres ikke.
Ny fysisk prøve av tegning, OS-respons og feilavbrudd kreves før publisering.
Brukerens faktiske redigering fra API0.2 til SDK1.0 er ferdigbygd med samme
app-ID/prosjekt og ny versjon. Normal SDK-pakkeinstallasjon avdekket deretter
en manglende SDK-gren i firmwareinstalleren. En avgrenset retting og gjenbruk
av trigonometriske buepunkter klargjøres som RC2; brukerens pakke beholdes.
Den første AI-kohorten ga ingen godkjente leveranser; dette skjules ikke av grønne
adaptertester. Se [den løpende SDK-evalueringen](M5Stack-backend/docs/FIRE_APP_SDK_EVALUATION.md).

### Sist fysisk overlevert firmware

**RC9** viderefører et separat **Last ned til SD** uten installering eller
omstart. Filen hentes til avgrenset PSRAM, lengde/hash kontrolleres og alle
socket-/TLS-objekter avsluttes før SD åpnes. SD-filen leses tilbake, og både
versjonens egen signerte katalog og global recovery-katalog kontrolleres før
publisering. Tidligere kopier beholdes ved feil. Direkte installasjon er
fortsatt standard; samme versjon merkes **Reinstaller**. Overflødige
HTTP-/katalogbuffere frigjøres før TLS, og nødvendige katalogbytes beholdes
i workerens PSRAM-allokering.

Den private RC9-kandidaten har fysisk lagret signert RC8 fra GitHub til SD
to ganger. Binærhash, begge signerte katalogkopier og tidligere backupfiler
stemte. Begge fulle OS-plassene og alle 8 KiB oppstartsmetadata var uendret
etter hver lagring; ingen installering eller omstart ble startet. Dette er
et avgrenset kandidatbevis. Deretter hentet FIRE den eksakte publiserte RC9-
filen fra GitHub til SD. Tilbakelesing av binær og begge kataloger bestod,
tidligere RC8-fil/katalog var intakt, og lagringen endret ingen OS-områder
eller oppstartsmetadata. Separat **Installer fra SD** startet ren RC9 i
**A/app0, sekvens 19 VALID**, med gyldig CRC og eksakt CI-byteidentitet.

Testbildet er fjernet; begge OS-plassene inneholder CI-RC9. Bare inaktiv B
ble skrevet under opprydding, med A/oppstartsmetadata urørt. Den rene B-kopien
er ikke separat startet. Ren A-produksjon ble observert minst 125 s og ved
én vanlig sluttomstart på 45,044 s, uten panic/watchdog. Maks løkkegap var
**92,998 / 85,996 ms**. COM3 er lukket. Private kontrollbilder hadde egne
høyere gap-/minnetall; se [SD-rapporten](M5Stack-device/PHYSICAL_SD_2026-11-25.md).

Siste backendkontroll bekreftet ny sluttboot, nyere komplett inventar og SD
klar. **7/7** app-ID-er, versjoner, checksums og normaliserte pakke-ID-er
matcher den varige siste komplette referansen før produksjons-RC9/SD-
installasjonen. Dette er en alternativ referanse, ikke den tapte flyktige
RC2-mappen. Rapporten var 176 s gammel ved lesing. Health og nettsiden svarte
HTTP 200; transport var klar uten feil. Firmwarelisten viste
**RC9 → RC8 → RC7 → RC6 → RC5 → RC2 → RC1 → 1.1**, kun lesing og uten katalogfeil.

Kilden er fryst på `b77c579bec4b4986680f9f3be82a4afbe76f59e8`.
[CI 45575157747](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45575157747)
bestod **16 tester og tre bygg**. Signert utgave er publisert på main
`21c0b81e3da71ca39108c5a06de74811c0cb91f8`; åtte offentlige filer er
bytekontrollert og begge katalogsignaturer verifisert. USB-pakken og ny
utpakking bestod faktisk signatur-/hash-/image-/layoutkontroll.

Alle **26 opprinnelige versjonsfiler** er beholdt uendret. Også RC8-filene
beholdes. RC7s og RC8s opprinnelige signerte kataloger er arkivert før
hovedlisten flyttes videre. Ingen gammel firmwareversjon slettes; se
bevaringsreglene i [firmwareoversikten](firmware/README.md#versjonene-beholdes).

## Historisk RC8-kandidat

Alle **16 tester og tre bygg** er bestått på kilde
`02b3905beb48841df9915fe93b6c2037636faa7b`,
[CI 45569401808](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45569401808).
Signert kandidat er publisert på main `aa13421a69187b1a54b71b3c24a7b661d1edf451`;
seks offentlige filer er hentet og sammenlignet byte for byte, og begge
katalogsignaturer er kontrollert. Ny USB-utpakking bestod faktisk pakkekontroll.
Første private RC8-baserte SD-forsøk stoppet trygt ved en TLS-allokeringsfeil,
før noen filbyte eller SD-skriving. Privat kontroll brukte ekstra intern
katalogkapasitet; testen isolerer ikke uendret produksjonskode alene.
Korrigert privat kontroll og produksjonens minnetiltak ble prøvd samlet i RC9.
Den eldre EIO-/FatFS-feilens rotårsak er fortsatt ikke fastslått.

## Historisk RC7-kontroll

Signert testkandidat **fire-os-1.2.0-rc7** er publisert på main
`093d7751a507b92b5d1d332f76a7961f20032050`. Alle **15 tester og tre bygg**
bestod på kilde `7eb40b7e0effca647d101031c777832aa672a010`,
[CI 45496282327](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45496282327).
Sju offentlige filer er hentet og sammenlignet byte for byte; katalogsignaturer
og USB-pakken er kontrollert. FIRE har deretter selv hentet og installert
den eksakte RC7-filen fra GitHub, uten SD-mellomlagring.

Avbrudd ved én prosent ble akseptert etter minst 24 225 vellykket skrevne
byte; alle 8 192 byte oppstartsmetadata var uendret. Ett eksplisitt nytt
forsøk fullførte nedlasting, flashkontroll og vanlig RC7-oppstart. Faktisk
app1/B ble lest tilbake med riktig CI-hash og sekvens **10 VALID** / gyldig
CRC. Inaktiv testutgave er erstattet; begge OS-plasser er nå ren RC7.
125 sekunders vanlig drift og en 45-sekunders vanlig omstart viste ingen
panic, ekstra reset eller watchdog. Maks løkkegap var **85,014 / 86,013 ms**.
Siste omstart ga to komplette skanninger med sju apper. COM3 er lukket.

Eksisterende backend bekreftet deretter ny RC7-boot med nyere komplett
inventar: **7/7** app-ID-er, versjoner, checksums og normaliserte pakke-ID-er
matcher den tidligere fysiske referansen. Både health og nettsiden svarte
HTTP 200. Firmwareoversikten viste **RC7 → RC6 → RC5 → RC2 → RC1 → 1.1**,
kun lesing og ingen katalogfeil. Transporten var klar uten registrert feil.

RC7 installerer direkte fra GitHub til inaktiv OS-slot uten SD-kort eller
backend. Nettverksdata og tilbakeavlest flash må matche signert hash før
oppstartsvalget endres. Menyens installasjonsbekreftelse er rettet.
Unødvendige forbindelser pauses under firmwarearbeid; aktive AI-/appjobber
avbrytes ikke automatisk. SD-nedlasting er fjernet fra firmwaremenyen og
avvises også ved kølegging. Status, fremdrift og avbryt vises under arbeidet.

Brukerens SD-feil er gjenskapt fysisk: ett kall skrev bare 9 av 2048 byte
med EIO etter omtrent 1,64 MB. Kortet hadde god plass. Internminnet var også
presset, men drivergjennomgangen beviser ikke at minnepress forårsaket EIO.
En privat RC6-basert SD-test krasjet senere med LoadProhibited i FatFS
validate/f_write; direkte OTA ble ikke nådd. Årsaken er ikke fastslått og
tilskrives ikke maskinvare. Den kjente SD-skrivebanen brukes ikke ved RC7
GitHub-oppdatering. Se [samlet fysisk bevis](M5Stack-device/PHYSICAL_USB_2026-11-24.md).

Normal RC7 er **2 422 464 byte**, SHA256
`55228972417300566da9c96a7c888b685cb7ec6d17a3b176b33cbc2d1df0c372`.
[USB-arkivet](firmware/fire-os-1.2.0-rc7-usb.zip) er **2 646 099 byte**, SHA256
`eec3e649611e972e40afe9d34a900e4edebd05f0e4200989896983cb52541c77`.
Bare de åtte nødvendige filene er med; ny utpakking bestod faktisk
signatur-/hash-/image-/layoutkontroll. Bootloader, tabell og recovery er
uendrede fysisk testede RC2-komponenter med separat kildeopphav i
[utgivelsesbeviset](firmware/fire-os-1.2.0-rc7-evidence.json).

### Tidligere fysisk RC5-bevis

Kode og signert testpakke **fire-os-1.2.0-rc5** ble ferdigstilt. Rikards FIRE
ble fysisk USB-migrert med full backup og kjørte helsegodkjent RC5 i app1.
Kontrollert tidlig omstart ga SDK-tilbakeføring til factory recovery. RC5
stod 125 sekunder og bestod vanlig omstart i 45 sekunder uten registrerte
krasj, ekstra reset eller watchdog-feil. Maksimal løkkeavstand var **87,988 ms**
og **86,013 ms**, mot **1 391 ms** før rettingene. Backend bekreftet samme
sju apper og fersk tilkobling. Se [det fysiske USB-beviset](M5Stack-device/PHYSICAL_USB_2026-11-24.md).

RC5-tallene er historiske oppstarts-/inventarbevis. RC7 GitHub-OTA er nå
prøvd som beskrevet over. Visuell/knapp-/lydprøve, Home i brukerens HA og
samlet AI/appflyt står fortsatt åpne.
Produksjonsgodkjenning krever de gjenstående kontrollene under.

| Område | Implementert / lokalt kontrollert | Gjenstående bevis |
| --- | --- | --- |
| FIRE Studio | PC-/mobilvisning, innstillinger, samtale, bekreftet appbygg, jobber, bibliotek, kostnader og lesbar GitHub-firmwareoversikt | Samlet fysisk AI-/appflyt og live offentlig oppsett |
| Offentlig backend | Separate browser-/deviceverter, Access-JWT, engangspålogging lokalt, sesjon/CSRF/Origin og egne enhetstokener | Brukerens domene, konto og tunnel |
| Jobber og samtale | Samme lagring som Windows-programmet, frakoblet apputvikling, eksplisitt BUILD/RUN og sikker omstart | Nettbrudd/tale/installasjon med ny fysisk firmware |
| Direkte Home | Native kortvisning, Home/Camper, HA-styrte tillatelser, MQTT/TLS/WSS, veiviser/import; ekte HA og broker testet isolert | Brukerens entiteter/adresser og fysisk FIRE |
| Firmware/recovery | RC7: 15 tester/tre bygg, fysisk GitHub→OTA, avbrudd/nytt forsøk, flash-readback, VALID og vanlig omstart; ren RC7 i begge slotter | Fysisk strømbrudd, redningsknapp og tidligere normal OTA-slot gjenstår |

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

## Historisk RC5-pakke og testbevis

RC5 erstatter synkron bytevis SD-inventering med en trinnvis, konsistent
metadataoversikt. Pakkeidentitet lagres før rapportering; mislykket skanning
publiserer ikke gamle tilstedeværelsesdata. Ventende svar og køede nettverksdata
får fullføre i Auto med frister. Skjermtegning har rammebudsjett, og WebSocket-
innhold leses i små blokker med tidsbudsjett. De fysiske tallene står over.
RC1/RC2 beholdes som uendrede historiske utgivelsesfiler. RC3/RC4 var private
USB-mellomtester og ble ikke publisert i firmwarekatalogen.

Normalfirmwarens kilde er `958415d20029939a0e105f4ee23aa6008a7ab567`.
[Linux-kjøring 45477480676](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45477480676)
bestod normal firmware med BLE/lyd, recovery, bootloader og alle **13**
C++-/signatur-/pakkekontroller. CI-arkivet er SHA256-kontrollert før utpakking.

Den distribuerte pakken gjenbruker bevisst **bootloader, partisjonstabell og
recovery fra RC2**, kilde `7efbae95fa0a54aeb3e1d6a615390810b69279b4` /
[kjøring 45431615060](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45431615060).
Dette er de uendrede, fysisk testede grunnlagsfilene. Ny normal RC5 kommer
fra den nye kjøringen. Pakken hevder ikke at alle fire bildene er bygget fra
samme kildecommit. Signert migreringsplan binder eksakte byte for alle fire;
komponentenes separate opphav står i utgivelsesbeviset.

- Normal RC5: **2 408 576 byte**, SHA256
  `6499092470f40287776fcac49fa73abc225c1f420b41ebb8c4ea76bce1d004e7`.
- [Signert USB-arkiv](firmware/fire-os-1.2.0-rc5-usb.zip): **2 637 224 byte**,
  SHA256 `31a22078f5441cf2428bac651aa18f1f89f3c73ba214996ad61392d68effb533`.
- Bare de åtte nødvendige filene er i USB-arkivet. Ny utpakking bestod faktisk
  `migrate_fire.py check` uten COM; ingen privat nøkkel følger med.
- [Maskinlesbart bevis med komponentkilder og målinger](firmware/fire-os-1.2.0-rc5-evidence.json),
  [device-rapport](M5Stack-device/DELIVERY_REPORT.md) og [firmwareoversikt](firmware/README.md).

RC5 ble publisert på main `2e9f0f35634638655d143533bfc7227a8c8f2af2`.
Alle seks offentlige filer — katalog, normalbinær, USB-arkiv, bevis,
kontrollsummer og arkivert RC2-katalog — ble deretter hentet fra GitHub og
sammenlignet byte for byte med leveransen. Alle svarte HTTP 200 med korrekt
Content-Length, uten omdirigering eller komprimering. Begge nedlastede
katalogsignaturer bestod kontroll. Dette er PC-bevis; fysisk nedlasting og
oppdatering direkte fra FIRE gjenstår.

Den eksisterende produksjonsbackenden svarte deretter HTTP 200 på både
health og nettsiden. Etter naturlig utløp av femminutters mellomlagring viste
firmwareoversikten **RC5 → RC2 → RC1 → 1.1**, `read_only=true` og tom
katalogfeil. Ingen omstart, innstillingsendring, betalt AI-kall eller
COM-tilgang ble brukt i denne sluttkontrollen.

Cloudflare CLI 2026.11.2 er også hentet og SHA256-/versjonskontrollert lokalt.
`scripts/cloudflare.ps1` bruker den lokale kopien. Ingen konto, tunnel, DNS
eller offentlig tilgang er opprettet; det krever brukerens valgte oppsett.

Historisk RC2-kontroll: Etter publisering på main `5e5853936cc10d6083dc153450e0ae2495c7b8e5`
er katalog, normalbinær, USB-arkiv, bevis og kontrollsummer hentet fra de
offentlige GitHub-adressene og sammenlignet byte for byte med leveransen.
Katalogsignaturen er verifisert på den nedlastede kopien. GitHub svarte 200
med korrekt Content-Length, uten omdirigering eller komprimering i kontrollen.
Dette er PC-bevis, ikke fysisk FIRE-nedlasting.
Den faktisk kjørende backenden svarte 200 på health og UI, og viste RC2,
historisk RC1 og 1.1 i riktig rekkefølge uten katalogfeil. Ingen omstart,
innstillingsendring eller betalte AI-kall var nødvendig i denne sluttkontrollen.

## Tidligere bevis

Ekte OpenAI-dialog, kodegenerering og validert Lua-pakke er prøvd tidligere i
prosjektet. Tidligere fysisk kontroll bekreftet pakkeinstallasjon, men avdekket
en RUN-feil; dette er ikke bevis for at den nye leveransen fungerer fysisk.
Se [E2E-status](M5Stack-backend/docs/E2E_STATUS.md) og deviceprosjektets historikk
for de eksakte avgrensningene. Den gamle påstanden om at nøkkel aldri var satt,
eller at enhetskilden aldri var endret, gjelder ikke lenger.

## Samles til slutt hos brukeren

Domene/Cloudflare-innlogging, HA-installasjonstype/MQTT-vert, valgte entiteter,
de gjenstående fysiske testene. Førstegangs USB-migrering på Rikards FIRE er
allerede utført og dokumentert. Kode, pakker, dokumentasjon og
uavhengige kontroller er klargjort før disse opplysningene etterspørres.

Produksjonsklar fysisk drift påstås først etter kontroll av oppstart,
nettbrudd, norsk tale, minne/respons, Home med Windows av og uavhengig recovery.

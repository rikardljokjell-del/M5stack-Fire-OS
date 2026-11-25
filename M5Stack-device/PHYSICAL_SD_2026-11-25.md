# FIRE — fysisk GitHub/SD-kontroll 2026-11-25

## Sluttresultat: RC9 lagret på SD, installert separat og startet normalt

FIRE kjører ren **fire-os-1.2.0-rc9 i A/app0**, faktisk sekvens **19 VALID=2**
med gyldig SDK-CRC lest fra flash. B/app1 har samme eksakte CI-produksjonsfil
som kontrollert fallback-kopi. Ingen privat automatisk testkode er igjen.
COM3 er lukket. Full RC7-slotbackup, opprinnelig dobbeltbackup og sensitive
rålogger er bevart privat; ingen formatering, brukerdata-/NVS-reset, betalt
AI/RUN eller ny appinstallasjon ble utført.

Kilde `b77c579bec4b4986680f9f3be82a4afbe76f59e8`;
[CI 45575157747](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45575157747)
bestod 16 tester og normal-, recovery- og bootloaderbygg. Eksakt fysisk
nett-/SD-installert normal er 2 427 328 byte, SHA256
`17edd52caa166558118c30ddead2d49ccc1d24360f68b326e2297eceab4fd6bd`. Bootloader, tabell og factory er de byteidentiske fysisk verifiserte
RC2-komponentene med presis kilde-/CI-proveniens nedenfor.

Den frosne minnekandidaten hentet faktisk signert RC8 to ganger og lagret
til SD med vanlig UI aktivt. Før begge SD-faser var nettarbeideren stoppet,
inkludert destruksjon av socket/TLS-objekter. Begge binærer og begge nye
katalogkopier overlevde close/reopen med riktig hash/signatur. Ved andre
lagring ble også den tidligere binæren og begge tidligere katalogkopiene
kontrollert i backup. Etter hver lagring var **begge fulle 6 553 600-byte
OTA-slotter og alle 8 192 byte oppstartsmetadata uendret**. Ingen installasjon
eller omstart ble startet av «Last ned til SD». Dette rensede kandidatopptaket
varte 342.596 s uten panic/watchdog eller ekstra reset.

Deretter hentet slutt-testen den eksakte publiserte CI-RC9-filen fra GitHub,
lagret til SD og kontrollerte binær, katalog ved filen og global recovery-
katalog. Begge fulle OS-slotter og oppstartsmetadata var fortsatt uendret.
Den allerede lagrede RC8-binæren beholdt SHA
`c4d9cd362517ba7cf35a0350629b46edb46f385a4d698944c0d18fccbf8a1e05`, og dens
katalogkopi var byteidentisk med den tidligere verifiserte signerte RC8-
katalogen. En ny global katalog gjorde dermed ikke den gamle filen foreldreløs.
Tidligere versjonsfiler på GitHub er også kontrollert uendret av master.

Først etter lagringskontrollen ble **separat «Installer fra SD»** bekreftet
gjennom faktisk Firmware-UI. FireOta leste filens signerte katalogkopi og
kontrollerte SD-fil, ESP32-image og tilbakeavlest inaktiv flash før bootvalg.
SDK startet deretter den vanlige RC9-produksjonsfilen i A og godkjente den.
Faktisk A-image ble lest tilbake mot CI, og sekvens 19 VALID/CRC ble lest
uavhengig. Dette er GitHub → PSRAM → SD og separat SD-installasjon; direkte
GitHub-OTA er beholdt som standard, med historisk fysisk RC7-bevis i
[gårsdagens rapport](PHYSICAL_USB_2026-11-24.md). Direkte RC9-OTA ble ikke
gjentatt som et ekstra løp.

| Måling | Ren RC9 etter SD-installasjon | Vanlig sluttomstart, 45.044 s |
| --- | ---: | ---: |
| Antall periodiske prøver | 4 | 1 |
| Maks løkke, µs | 87625 | 80460 |
| Maks løkkeavstand, µs | 92998 | 85996 |
| Minste målt intern heap, byte | 103412 | 99060 |
| Historisk minimum intern heap, byte | 92332 | 78200 |
| Minste målt største internblokk, byte | 90100 | 94196 |
| Stakkreserve, byte | 5108 | 5108 |
| RGB-timeouts | 0 | 0 |

Ren produksjon ble observert minst 125 s etter første oppstart og deretter
fra reset i sluttopptaket. Ingen ekstra reset, kjent panic/watchdog eller
RGB-timeout ble observert. Privat minnefixture målte maks gap
273995 µs og historisk minste interne heap
5064 byte. Den endelige private installasjonsfixture
målte gap 271992 µs og historisk minimum
8468 byte. Private fixtures inkluderer hel-slot-hashing,
kontrollkopier og SD-/flasharbeid. Disse maksimumstallene er beholdt og kan
ikke uten årsaksbevis tilskrives vanlig UI eller ren produksjonsoppstart.

Backend-agenten bekreftet via master en nyere, komplett oversikt med klar
lagring fra den endelige RC9-oppstarten. Alle 7/7 app-ID-er, versjoner,
checksums og normaliserte pakke-ID-er matchet den varige siste komplette
referansen fra før produksjons-RC9/SD-installasjonen. Dette var ikke en ny
sammenligning mot den opprinnelige RC2-referansen, som ikke lenger var
tilgjengelig. Oversikten var 176 sekunder gammel ved lesing; health/UI svarte
HTTP 200, versjonskatalogen hadde åtte utgaver, og fire transportkanaler var
klare uten feil. Dette etablerer ikke betalt AI/RUN eller andre brukerflyter.

Etter faktisk A19 VALID/CI-kontroll ble det private B-bildets fulle overskrevne
område bevart lokalt og erstattet med eksakt CI-RC9 pluss FF-padding over
resten av testbildets område. Full readback og uendret bootmetadata ble
kontrollert. Bare inaktiv B ble skrevet; aktiv A var urørt og startet normalt
igjen. B/sekvens 18 VALID-metadata stammer fra testbildets tidligere lokale
helsekontroll og ble ikke endret ved kopieringen. Den rene B-kopien er ikke
separat startet i sluttløpet. Ingen helsetilstand ble skrevet manuelt som VALID.

Oppstartsgrunnlaget er uendrede RC2-komponenter fra kilde
`7efbae95fa0a54aeb3e1d6a615390810b69279b4`, CI45431615060, med separat
komponentproveniens. Det er ikke et homogent RC9-bygg av alle distribuerte
komponenter. Home/HA, lyd/AI, fysisk visuell knappkontroll og recovery-knapphold
er ikke etablert av dette SD-løpet. Den gamle EIO/FatFS-rotårsaken er ikke
erklært løst; den nye arbeidsflyten er fysisk kontrollert i dette avgrensede oppsettet.

## Historisk klargjøring: RC8-kilde og første forsøk

RC8-kilde `02b3905beb48841df9915fe93b6c2037636faa7b` er fryst.
[CI 45569401808](https://github.com/rikardljokjell-del/M5stack-Fire-OS/actions/runs/45569401808)
bestod tester og alle tre bygg. Dette var status før de fysiske resultatene dokumentert over.
Dette var CI-filen planlagt for det opprinnelige RC8-forsøket. Gjeldende
RC9-produksjonsfil kommer fra CI 45575157747, som dokumentert over;
private testbilder er ikke utgitt som produksjonsfiler.

RC8 laster hele den signerte filen til begrenset PSRAM, kontrollerer størrelse
og SHA, og venter til nettarbeiderens lokale socket-/TLS-objekter er destruert.
Deretter skrives SD. Binær, filens signerte katalogkopi og global katalog for
eksisterende recovery kontrolleres ved close/reopen før publisering.
Tidligere filer beholdes som unike backups; feil håndteres med tilbakeføring.
«Last ned til SD» installerer ikke og velger ingen OS-slot. Direkte GitHub-OTA
er fortsatt standardvalget. Samme versjon får «Reinstaller»-bekreftelse.

Den tidligere EIO-/FatFS-feilens rotårsak er ikke fastslått. Dette er en ny
arbeidsflyt med adskilte nett- og SD-faser, ikke en påstand om reparert SD-kort.
Se [historisk RC7-/migreringsbevis](PHYSICAL_USB_2026-11-24.md).

## Faktisk USB-preflight før ny test

Før ny skriving ble begge faktiske RC7-image kontrollert mot CI-SHA256
`55228972417300566da9c96a7c888b685cb7ec6d17a3b176b33cbc2d1df0c372`.
OTA-metadata viste A/app0 **sekvens 11 VALID=2**, B/app1 **sekvens 10 VALID=2**,
begge med gyldig SDK-CRC. A var dermed valgt etter metadata. Dette støtter
at brukerens sammeversjonstest reinstallerte RC7 etter forrige overlevering
i B/sekvens 10; sekvensen alene dokumenterer ikke hele brukerforløpet.
Faktisk byteidentitet til RC7 er kontrollert uavhengig av denne tolkningen.

Hele valgte A-slot, 6 553 600 byte, er bevart privat med SHA256
`e3ee85817316b0be5a95726009a00068c21ed2d5e7e5a1ee23d00d10b158726b`.
Opprinnelig dobbeltbackup ble kontrollert på disk; identitet, sikkerhet,
partisjonstabell, bootloader og recovery ble kontrollert igjen mot det
fysisk verifiserte RC2-grunnlaget. Ingen NVS-reset, formatering eller sletting
av brukerdata ble gjort. Bare inaktiv B ble klargjort for den private testen;
oppstartsvalget ble beholdt frem til publisert RC8 var bekreftet.

Alle nye rålogger, backupfiler, private testbilder og målinger oppbevares
under ignorert `M5Stack-backend/workspace/device-physical/2026-11-25/`.
Det private bildet er basert på samme frosne RC8-kilde med separat kildeproveniens;
det skal fjernes før overlevering. Sensitive rålogger publiseres ikke.

## Opprinnelig fysisk testplan (installasjonsdelen senere erstattet)

Den private engangstesten bruker faktisk Firmware-UI og produksjonsmanager.
Begge fulle OTA-slotter hashes, og alle 8 KiB oppstartsmetadata sammenlignes
før og etter hver av to SD-lagringer. Begge katalogkopier og den ferdige
binæren leses tilbake; ved andre lagring kontrolleres også tidligere kopier.
Deretter brukes den lagrede signerte RC8-filen til vanlig SD-installasjon,
fulgt av SDK-helsekontroll, faktisk VALID/CRC og vanlig omstart. Testbildet
erstattes til slutt med eksakt CI-produksjon, med aktiv produksjon urørt.
Ingen ekstra gjentakelse av de historiske RC7-OTA-testene planlegges.

Den planlagte RC8-installasjonen fra SD ble ikke utført. Etter TLS-minnefunnene
ble bare RC8-lagring og erstatning gjennomført med den private minnekandidaten.
Installasjonsdelen ble erstattet av det endelige eksakte RC9-løpet over.
RC9 var den eneste produksjonsfilen som ble installert fra SD i dette arbeidet.

## Første private forsøk: trygg TLS-feil før SD

Den første private RC8-utgaven hentet og verifiserte katalogen, men første
filforbindelse feilet før noen filbyte var mottatt og før SD-fasen ble åpnet.
Ingen panic/watchdog eller ekstra reset ble sett. Faktisk PSRAM-heap var
4 194 303 byte totalt, 3 909 267 byte ledig og største frie blokk 3 866 612 byte
før staging av filen på 2 427 040 byte. PSRAM-plass var altså tilstrekkelig.

TLS-koden rapporterte X509 `-12288` etter `PK verify ... FFFFBD70`.
Installert SDK definerer dette som `RSA_PUBLIC_FAILED (-0x4280)` pluss
`MPI_ALLOC_FAILED (-0x10)`: intern minneallokering feilet under RSA-kontrollen.
Før operasjonen var intern heap 84 348 byte, største blokk 59 380 byte.
Sertifikatverifisering ble ikke slått av, og ingen SDK/task-størrelser endres.

Testutgaven beholdt en ekstra katalogkontrollkopi i en vanlig Arduino-String,
omtrent 3,7 kB intern RAM utover produksjonsbehovet. Denne flyttes til eksplisitt
PSRAM. Samtidig prøves en privat RC9-minnekandidat som frigjør overflødig
katalogkropp/HTTP-buffer og UI-kopi etter at den nødvendige worker-kopien er
overtatt. Arduino `String = ""` beholder kapasiteten i denne SDK-en; kandidatens
frigjøring er eksplisitt. URL/request og nødvendige signerte katalogbytes beholdes.

De to minnetiltakene testes samlet mot eksisterende signert RC8 før eventuell
RC9-publisering. Forsøket isolerer ikke hvert tiltaks nødvendighet og beviser
ikke at uendret RC8-produksjon alene er defekt. Den gamle EIO/FatFS-rotårsaken
er fortsatt ikke fastslått. Kandidaten stopper etter to SD-lagringer uten
installasjon; endelig eksakt produksjonsversjon skal testes etter CI/publisering.

Den første minnekandidaten, med frigjorte midlertidige buffere og privat
katalogkopi i PSRAM, fikk også samme RSA/MPI-feil før SD. Dens sammenlignbare
«quiet»-måling var 93 940 byte intern heap; 76 564 byte ble målt senere, inne
i workeren rett før TLS. Dette er ulike målepunkter, ikke en minnenedgang.
Den passerte kandidaten la i tillegg workerens nødvendige signerte katalog
etter binærregionen i samme PSRAM-allokering. Den målte 80 256/80 432 byte
intern heap før de to fil-TLS-forsøkene og 79 020/79 612 byte ved de to
SD-fasene etter TLS-opprydding. Resultatene er dokumentert samlet over.

## Samlet minnetiltak og avgrensning

Kandidaten som passerte frigjorde overflødig String-kapasitet og flyttet også
workerens nødvendige signerte katalogbytes til samme PSRAM-allokering som
filen, utenfor den avgrensede binærregionen. Privat katalogkontroll ble flyttet
til PSRAM. Tiltakene ble prøvd samlet; nødvendigheten av hvert enkelt tiltak
er ikke isolert, og uendret RC8-produksjon alene ble ikke bevist defekt.
SDK, task-størrelser, sertifikatverifisering og rollback ble ikke svekket.
Faktisk kartlagt PSRAM var 4 194 303 byte, selv om nyere FIRE-spesifikasjon
oppgir mer fysisk PSRAM. Hele filen/katalogen må få plass med 512 KiB reserve;
for liten eller fragmentert PSRAM gir trygg avvisning før SD åpnes.

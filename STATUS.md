# Leveransestatus – 25. november 2026

Samlet arbeid følger [godkjent plan](DELIVERY_PLAN.md). Bruk
[oppsettsveiledningen](SETUP.md) som inngang. Dette dokumentet skiller kildekode,
lokale tester og faktisk fysisk verifikasjon.

## Åpne gjøremål

- [ ] **GitHub-firmware til SD: skrivefeil etter nedlasting.** Brukeren meldte
  25. november 2026, etter RC9-leveransen, at nedlastingen ble etterfulgt av
  feilmeldingen «SD-skriving feilet». Feilen er åpen; årsak og gjeldende
  enhetsstatus er ikke undersøkt på nytt. Tidligere beståtte tester nedenfor
  er avgrensede resultater og betyr ikke at brukerflyten er feilfri.
  **Kun notert etter brukerens ønske. Ingen feilsøking eller retting nå.**

## Status nå

### FIRE App SDK – under implementering

SDK-arbeidet er godkjent og pågår i eksisterende firmware/backend. Felles
grafikk-/fontdata, UI-kit, temaer og kontrakt ligger i
`M5Stack-backend/fire_backend/data/app_sdk/` og
`M5Stack-backend/contracts/APP_SDK-v1.json`. Se
[SDK-veiledningen](M5Stack-backend/docs/FIRE_APP_SDK.md).
Eksisterende Lua-apper og hardwarehash skal bevares; SDK krever eksplisitt
ny kapabilitet. Simulator, Studio-preview og eksisterende AI-review utvides
samordnet. Innhold og tidlige PC-tester er ikke fysisk SDK-verifikasjon.
Den registrerte firmware-SD-skrivefeilen over undersøkes ikke i dette arbeidet.

Siste backendkjøring ga 957 beståtte tester og én feil i to avledede
grensesnittfiler med gammel SDK-hash. Filene er regenerert og den berørte
kontrakttesten består. Bakgrunnsforberedelse og simulator har i tillegg
bestått 182 berørte og 68 avsluttende målrettede tester, med identiske
piksler for alle seks gallerisider og fire representative appkilder.
Den samordnede native endringen avventer nytt CI-bygg og fysisk måling.
Koordinatoren har prøvd faktisk Studio-forhåndsvisning med virtuelle A/B/C,
nullstilling og tidsfremdrift. Dette er PC-verifikasjon. De private
SDK-prøvene på FIRE stoppet ved den uendrede 12 ms callbackgrensen; ren SDK-
firmware er derfor ikke godkjent eller offentlig publisert. Enheten er
ført tilbake til RC9 i A/app0, sekvens 27 VALID/CRC, med COM3 lukket.
Arbeidet er avgrenset til ferdigstilling av SDK-fundament, ytelse og fysisk
kontroll; nye funksjoner og betalte appforsøk er stanset. Den første
AI-kohorten ga ingen godkjente leveranser; dette skjules ikke av grønne
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

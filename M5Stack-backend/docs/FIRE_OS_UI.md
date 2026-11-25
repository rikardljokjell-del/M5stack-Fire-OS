# Ny utforming i FIRE OS 1.4

Oppgraderingen gir FIRE OS og Home samme mørke stil, tydelige valg,
lesbare verdier og et samstemt ikonsett. Tekst og ikoner ligger lokalt. Poleringen bruker kantutjevnet dekning fra
originale font-/ikonfiler, uten nye nedlastinger eller en ekstra skjermbuffer.

## Hovedmenyen

- Fire apper vises per side i et 2 × 2-rutenett.
- Kort **A/C** flytter valget bakover/fremover. Siden skifter automatisk.
- Kort **B** åpner valgt app. Sidetallet viser hvor du er.
- Lagret rekkefølge, synlighet og snarveier beholdes.

Hold **A** for hjem, **B** for hurtiginnstillinger og **C** for tilbake.
Appenes egne korte A/B/C-handlinger og Lua-grensesnitt er uendret.

## Home

Home viser enten fire kontrollkort eller ett stort kort. Velg dette i
Home-innstillingene, sammen med Home/Camper, lokal/ekstern/automatisk
forbindelse og favoritter. Navigasjon og bekreftelser fungerer som før.

Målt verdi og måltemperatur skilles. En ukjent eller utilgjengelig enhet
vises tydelig, og gamle verdier fremstår ikke som ferske. Bare handlinger
som Home Assistant har gitt tilgang til kan velges. En ventende kommando
er ikke en bekreftet tilstandsendring.

Et tomt Home-oppsett viser veien til innstillinger og mobiloppsett. Denne
oppgraderingen oppretter ingen HA-forbindelse eller tillatelser på egen hånd.

## Kontrollstatus

Visningen er kontrollert med de faktiske font-, ikon- og tegnehjelperne på PC.
Dette er ikke en fysisk HA-prøve eller en måling av ytelse på ESP32.
Endelig bygg, fysisk oppstart og brukerens visuelle prøve dokumenteres i
[statusrapporten](../../STATUS.md).

## Første UI-kandidat RC1: bygg og kildekontroll

Kilde `708affb05809ce70e4a9c07a92beb9ca65d5ef7b` bestod 22 native tester og
alle tre firmware-/recoverybygg i CI45680009752. Strenge C++-kontroller
bestod separat i CI45680009653. PC-kontroll brukte faktiske felles
bitmapfonter, ikoner og tegnehjelpere for seks representative skjermer.
Skriving utenfor skjermens 320 × 240 piksler ble kontrollert.

Normalbildet er 2 369 616 byte, 314 144 byte mindre enn RC7. Statisk
RAM-bruk er fortsatt 63 796 byte og IRAM-marginen 1 128 byte. Dette er
byggmålinger; de beviser ikke faktisk fri heap eller knapperespons.
SDK-data, kontrakter og aktive Lua-apper er uendret av denne UI-rettingen.

Den signerte USB-pakken beholder fysisk testet RC2-bootloader,
partisjonstabell og recovery, med åtte signerte kjernefiler og ni
SDK-lisens-/varselfiler. En ny utpakking har bestått signatur-, hash-,
bilde- og layoutkontroll.

## Første UI-kandidat RC1: fysisk installasjon

Eksakt CI-fil er tilbakekontrollert med flash-MD5 og SHA256. Ny UI ligger i
A47 VALID/CRC; den fungerende RC7-kopien er beholdt urørt i B46 VALID/CRC.
Helsekontroll på 45,2 sekunder og én vanlig omstart på 35,11 sekunder hadde
ingen panic, abort eller watchdog. Ingen innstillinger eller appdata ble
nullstilt, og COM ble lukket etter kontrollen.

Normalbildets SHA256 er
`25d67435be610a7047a1a7afb2fabf48a9da1e7414a5e97b4924d16a08ca05ce`.
Dette er kontroll av bildet og oppstarten. Det er ikke en full frametidsmåling,
prøve av HA-styring eller en gjentatt OTA/SD-installasjon. Brukerens praktiske
utseende-/navigasjonsprøve står fortsatt åpen.

Backend mottok deretter en fersk 1.4-oppstart med uendrede SDK-/Runtime
AI-kontrakter og komplett SD-inventar for gjeldende oppstart. Alle sju
opprinnelige app-ID-er er bevart; totalt tolv apper inkludert tillegg.
Dette er identitetskontroll, ikke påstand om uendrede brukerredigerte versjoner.
Ingen appkommandoer, betalte AI-kall eller HA-styring ble utløst av kontrollen.

## Polering RC2: skarpere tekst og jevnere kanter

Små OS-etiketter bruker nå en proporsjonal font. Tekst tegnes fra original
Atkinson-dekning, og ikoner gjengis direkte fra Lucide-originalene i størrelsen
som faktisk vises. Kort og knapper har jevnere avrundede kanter. Fyll og ramme
blandes samlet mot den faktiske bakgrunnen for å unngå mørke/lyse kantstriper.
Skjermens fysiske oppløsning er fortsatt 320 × 240.

Dette gjelder OS og Home. Appenes SDK-fonter, kontrakter og grenser er uendret,
sammen med A/C/B, Home-forbindelse, rettigheter, lagrede valg og kommandoer.
Ingen ekstra skjermbuffer, bildecache eller backendprosess er lagt til.

Kilde `007a35d6318d37466949ba45ff2c1dbeee233194` bestod 24 native tester
og tre bygg i CI45685543151; strenge C++-kontroller bestod i CI45685543156.
Seks representative skjermer ble tegnet av de faktiske C++-hjelperne og
visuelt kontrollert. Testene dekker fargeblanding, gjennomsiktighet, klipping,
avrundede kanter og font-/ikondata.

Normalbildet er 2 525 072 byte, SHA256
`225ba6d95d9744b1d6cb28b78d3de6e8716bd3fc6db4684c30e7a42fba6de1e8`.
Det er 155 456 byte større enn RC1; statisk RAM er fortsatt 63 796 byte og
IRAM-marginen 1 128 byte. Dette er byggmålinger, ikke målt knapperespons.
Signatur-, hash-, bilde- og layoutkontroll av en ny utpakking består også
uavhengig. USB-pakken beholder det fysisk testede RC2-grunnlaget og alle
ni lisens-/varselfiler i tillegg til åtte signerte kjernefiler.

### RC2 på den fysiske FIRE-enheten

Eksakt CI-bilde er kontrollert med MD5 og SHA256-tilbakeavlesing. RC2 kjører
i B48 VALID/CRC; UI RC1 i A47 er bevart urørt som reserve. Helsekontroll
45,168 sekunder og vanlig omstart 35,15 sekunder hadde ingen panic, abort
eller watchdog. COM er lukket, og innstillinger/appdata er beholdt.

Eksisterende oppstartslogger viste maks loop/gap på 113,653/118,998 ms og
120,350/126,016 ms etter omstart. Ingen ny stor løkkestopp ble observert i
disse korte opptakene; dette er ikke en isolert ramme- eller knappmåling.
Brukerens praktiske prøve av utseende og navigasjon er siste vurdering.
Ingen HA-handling eller betalt Runtime AI-kall ble utløst av denne kontrollen.

Backend mottok deretter en ny RC2-oppstart med uendrede SDK-/Runtime
AI-kontrakter og komplett, ferskt SD-inventar for den oppstarten: tolv apper,
inkludert alle de opprinnelige sju app-ID-ene. Brukerredigerte versjoner
hevdes ikke å være uendret. Ingen appkommando eller AI-kall ble sendt.

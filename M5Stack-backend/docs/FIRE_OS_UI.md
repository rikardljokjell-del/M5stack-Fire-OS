# Ny utforming i FIRE OS 1.4

Oppgraderingen gir FIRE OS og Home samme mørke stil, tydelige valg,
lesbare verdier og et samstemt ikonsett. Den bruker de eksisterende lokale
fontene og ikonene, uten nye nedlastinger eller en ekstra skjermbuffer.

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

## Bygg og kildekontroll

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

## Fysisk installasjon

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

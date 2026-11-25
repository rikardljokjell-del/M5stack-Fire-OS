# Måle, analysere og forbedre appen fra FIRE

FIRE Data Engine samler appens målinger og logger med appversjon, analyser og
utviklingshistorikk. Når du velger **Improve app**, følger grunnlaget med til
AI Developer. Ingen eksport til ChatGPT, mobil eller PC er nødvendig.

Bruk oppdatert backend og FIRE OS 1.5-kandidaten. Faktisk installert versjon og
gjennomførte fysiske prøver står i [leveransestatus](../../STATUS.md).
Funksjonene aktiveres ut fra det enheten faktisk rapporterer.

## Vanlig arbeidsflyt

1. Åpne **AI Developer → New app**, eller velg en eksisterende app.
2. Beskriv problemet, ønskede målinger og eventuell tilkoblet modul.
   Oppgi modulmodellen og koblingen én gang; dette følger prosjektet videre.
3. Godkjenn det konkrete byggeforslaget. Installer og kjør den testede pakken.
4. Bruk appens knapper for opptak, markører, referansemåling og analyse.
   Vanlige menyer bruker A/C for å flytte og B for å velge.
5. Velg appens **Forbedre / Improve app**, eller finn handlingen i appens
   Apps-meny. En stoppet app har et tydelig startvalg før grunnlaget hentes.
6. Legg eventuelt til en kort muntlig instruks, for eksempel:
   «Bruk siste måling til å skille jevn bevegelse fra raske vibrasjoner.»
7. Godkjenn et nytt konkret forslag. Oppdateringen beholder appens identitet
   og appdata. Den nye versjonen får egne tester og vanlig installasjonskontroll.

**New app from this** oppretter en separat app med skrivebeskyttede referanser
til det valgte grunnlaget. Den endrer ikke den opprinnelige appens data.
En app kan sende en konkret observasjon med **Test feedback**. OS lar deg
bekrefte eller avvise den. Du kan også gi egne tilbakemeldinger med kort tale
i AI Developer. Appens egen tekst kan ikke bekrefte seg selv på dine vegne.

## Kontrollappen

**Måledata kontroll** er en liten, manuelt skrevet infrastruktursjekk.
Den er ikke et bevis på AI-generering eller AI-review.

- Ved start tar den ett IMU-opptak på to sekunder med nominell 100 Hz.
- Opptaket lagres på SD, synkroniseres og behandles med vanlig statistikk.
- **A:** bytt visning. **B:** ta ett nytt opptak. **C:** åpne forbedring med
  appkoden, opptakene og resultatene som grunnlag.
- Vent på **Synket og analysert** før C. Skjermen viser også prøvetall.

Kontrollappen bruker ingen betalt AI under opptak eller statistikk. C gjør
grunnlaget klart; en ny kodejobb krever fortsatt vanlig byggebekreftelse.
Beveg enheten under et nytt B-opptak hvis du vil sammenligne med hvile.

## Hva som følger med

Utviklingsgrunnlaget binder riktig appkode, versjon og kildehash til relevante
opptak, hendelsesmarkører, beregninger, AI-vurderinger og feilhistorikk.
Opprinnelig bestilling og tidligere fungerende versjoner følger også med.
For eldre prosjekter som mangler originalbestillingen, merkes den tidligste
bevarte bestillingen som nettopp det.

Et pågående bygg bruker et frosset grunnlag. **Resume** gjenopptar samme
grunnlag; nye målinger erstatter det ikke i det stille. Velg en ny forbedring
når du vil bruke et nytt målegrunnlag. En eldre testet appversjon kan velges
i appens versjonsliste uten å slette appdata.

Relevant tidligere brukerbekreftet erfaring kan gjenbrukes fra andre prosjekter
med samme eier. En observasjon, en beregning og en AI-vurdering holdes adskilt.
En bekreftet observasjon er ikke automatisk en verifisert protokoll eller årsak.

## Målinger og AI

Statistikk, filtrering, frekvensanalyse og sammenligning bruker deterministisk
behandling. Runtime AI bruker de samme datareferansene og et lite relevant
sammendrag, ikke hele råloggen. Synkronisering krever ikke et ekstra modellkall.
Visningen skal skille målte verdier fra **AI-vurdering**.

Runtime AI beholder eksisterende global/per-app-bryter, modellvalg og
forbruksoversikt. Utviklingskostnad og Runtime AI-forbruk føres separat.
Opptak, overføring og vanlig statistikk er ikke OpenAI-kall.

Enheten oppgir hvilke opptakskilder den faktisk støtter. MPU6886-opptak bruker
FIFO, med sampleindeks og separat mottakstid. En nominell sensorrate er ikke
en kalibrert klokke. Manglende eller uegnet tidsgrunnlag skal ikke presenteres
som en fysisk verifisert frekvens i Hz.

## SD, forbindelse og avbrudd

Data legges automatisk under
`/apps/<app-id>/appdata/datasets/<dataset-id>/`. Hvert datasett har råfil,
manifest, tidsindeks og hendelser. Ferdige datasett er skrivebeskyttet for
appen. Oppdatering og tilbakeføring bevarer appdata.

Store filer leses og overføres i små blokker. En avbrutt overføring kan fortsette
fra verifisert posisjon. Avbrutte opptak beholdes som delvise; de fremstilles
ikke som komplette opptak. Et frakoblet nett skal gi en tydelig status og
bevare målegrunnlaget, ikke en oppdiktet analyse.

Grensene er 16 MiB per datasett inkludert indeks/hendelser, 128 MiB og 128
datasett per app. Rådata slettes ikke automatisk ved en kvotegrense. Eksplisitt
sletting av hele apphistorikken er en annen handling enn versjonsbytte.

Backendens **Data**-side viser synkroniserte datasett, analyser og frosne
utviklingsgrunnlag. Nedlasting der er valgfri; den vanlige FIRE-flyten bruker
referansene automatisk.

## Eksternt utstyr

Generelle bussgrensesnitt og relevante produsentprofiler brukes fremfor en
parallell driverplattform. Se [maskinvareoversikten](HARDWARE_COMPATIBILITY.md).
Et signalopptak bekrefter ikke at et Bluetooth-lys kan styres. Riktig modul,
protokoll, elektrisk kobling og faktisk respons må inngå i den praktiske testen.
Klassisk Bluetooth/SPP og vilkårlig HTTP annonseres ikke som implementert.

Teknisk kontrakt: [Data Engine v1](../contracts/DATA_ENGINE-v1.json),
[Lua API](LUA_API.md) og [transport](PROTOCOL-v0.2.md).

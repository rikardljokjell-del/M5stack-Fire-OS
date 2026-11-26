# Evolution i AI Developer

Evolution bruker den samme appbyggeren, reparasjonsmotoren, simulatoren,
Data Engine og apphistorikken som resten av FIRE. Vanlig bruk styres fra
enheten. Studio og Windows viser flere detaljer, men er ikke nødvendig for
å godkjenne en vanlig utviklingsrunde.

Funksjonaliteten er implementert i kildekoden. Se [leveransestatus](../../STATUS.md)
for faktisk testet og installert støtte. Menyer eller PC-simulering betyr
ikke at den fysiske måle-/utviklingssløyfen er godkjent.

## Velg app og egenskaper

Åpne appens **Evolution**. Alle valg er av som standard, også for nye apper.

- **Generate:** løse behov med gjenbruk eller ny kode uten unødige duplikater.
- **Repair:** behandle konkrete feil og tilby en testet retting.
- **Optimize:** sammenligne avtalte, målbare forbedringer med en baseline.
- **Expand:** legge til funksjoner basert på et faktisk behov.
- **Evolve:** evaluere bedre utviklingsstrategier for denne appen.

Valgene er uavhengige. Repair trenger ikke at Generate er slått på.
Bryterne styrer Evolution; de sperrer ikke vanlig manuell apputvikling.

## Velg hvor mye som kan skje automatisk

**Manual** starter når du ber om det. **Suggest** analyserer vesentlige nye
funn og foreslår tiltak. **Auto Build** kan bygge innenfor ett konkret mandat.
**Assisted** kan gjennomføre flere avgrensede runder og sammenligne resultatene.

Et mandat viser app, basisversjon, mål, datagrunnlag, modeller og grenser før
du bekrefter. Standard er 0,50 USD, to kandidatbygg med maksimalt to
genereringsforsøk per bygg, og 2 USD per app per døgn. Mandatet utløper etter
syv dager og fornyes ikke automatisk. Analyse, refleksjon og retries teller med.

Evolution har tekniske svartak: analyse 1 500, refleksjon 2 000, kodegenerering
8 000 og review 4 000 outputtokens. De er synlige i mandatet og økes ikke
automatisk. Andre modell-/kostnadsinnstillinger endres ikke av disse standardene.
En konservativ reservasjon kan stanse et kall før budsjettet faktisk er brukt;
reservasjonen skal fortsatt ikke vises som betalt kostnad.

## Felles AI Developer Settings

**Settings** ligger rett over **Back**. **Runtime AI** viser backendens faktiske
AUTO/OFF. **Model** viser modellrollene og gjeldende valg; velg en rolle for
å åpne de samme tillatte modellene som backend tilbyr. **Usage** viser nylige
operasjoner, kostnad for siste jobb og relevante grenser. **Voice test** ligger
også i Settings.

Endringer bekreftes av backend og lagres i den eksisterende konfigurasjonen.
Ved nettbrudd vises innstillingen som ikke oppdatert til kvitteringen kommer.
Et pågående modellkall beholder sitt opprinnelige modellvalg.

**Disable all limits** er brukerens eksplisitte valg om å slå av alle
kostnadsgrenser i backend, også Runtime AI og Evolution. Det opphever ikke
OpenAI-kontoens kvoter, tekniske svartak, iterasjonsgrenser eller
godkjenninger av maskinvaretillatelser, installasjon og kjøring.

## Tiltak og godkjenninger

**Improve now**, **Findings**, **Feedback**, **Measurements**, **History** og
**Compare** bruker eksisterende utviklings-, data- og versjonsflyt. En vanlig
byggbekreftelse eller en gyldig mandatfullmakt kreves før kode bygges.

Ved Manual og Assisted åpner **Åpne byggforslag** den vanlige AI Developer-
samtalen med riktig appnavn og gjeldende forslag. Du bekrefter fortsatt BUILD
der. En godkjent prøve på flere apper viser det faktiske målappnavnet for hvert
bygg. Nye tillatelser vurderes separat; en beholdt kandidat kan deretter testes
og kontrolleres uten å kjøpe samme kodegenerering på nytt.

Nye maskinvaretillatelser, installasjon og kjøring på FIRE krever egne
godkjenninger. En app kan ikke godkjenne dem selv. En testkjøring sender ikke
automatiske styresignaler til eksternt utstyr.

**Pause** hindrer neste handling. **Stop** tilbakekaller mandatet og avbryter
der det er mulig. **Resume** bruker det lagrede grunnlaget. Allerede påløpt
kostnad og ferdige kandidater slettes ikke. Ved frakobling vises et lokalt
stoppønske som ventende til backend har kvittert.

Et ukjent utfall fra et betalt kall eller en installasjon sendes ikke blindt
på nytt. Faktisk kvittering eller kontroll må avklare tilstanden først.
Etter omstart beholdes mandatbindingen; et gammelt BUILD kan ikke bli et
ubegrenset manuelt bygg. En eksplisitt ny bestilling eller et appbytte frigjør
den gamle samtalekoblingen og pauser uferdig Evolution-arbeid.

## Målinger, sammenligning og hukommelse

Telemetri krever eget samtykke per app. OS sender små summer av blant annet
callbacktid, minne, jobbfeil og knapper. Ved nettbrudd brukes et avgrenset
lokalt mellomlager. Full kø gir et synlig droppantall; råmålingene dine slettes
ikke for å gi plass. Appspesifikke opptak og logger bruker Data Engine.

En sammenligning låser krav, tester, kildegrunnlag, SDK og måledata.
Standard terskel for et numerisk mål er fem prosent. Manglende batteri-,
referanse- eller tidsmåling vises som ikke målt. Avspilling av målte data i
simulatoren er fortsatt PC-testing og beviser ikke fysisk hastighet.

Brukerpreferanser, apphistorikk og gjennomgått systemkunnskap holdes adskilt.
En AI-hypotese blir ikke automatisk et faktum. Preferanser kan gjennomgås og
fjernes. Strategier for én app blir ikke standard for fremtidige apper uten
separat godkjenning og bredere evaluering.

En foreslått felles strategi prøves på minst tre navngitte, eksisterende apper
med hver sin låste basisversjon og samme avtalte forbedringsmål. Dette er en
egen bekreftet evaluering; to bygg i standardmandatet er ikke tilstrekkelig.
Systemet reduserer ikke testsettet eller øker budsjettet automatisk. Kandidater,
kostnad og måleresultater beholdes, men evalueringen installerer eller starter
ingen apper. Først når alle sammenligningene består, kan strategien tilbys som
ny standard gjennom en separat godkjenning.

Endringer i SDK-data eller relevante validatorversjoner ugyldiggjør eldre
sammenligningsgrunnlag. En ny fysisk feil sperrer også bruk av et tidligere
lokalt godkjent kandidatbevis; en cache kan ikke friskmelde pakken.

## Beholdt fysisk testpunkt

«Måledata kontroll» er installert og har startet, men dataflyten er ikke
verifisert. Brukeren skal lese skjermstatusen senere. Ingen ny opptaks- eller
AI-handling skal fremstilles som utført på brukerens vegne.

Se også [Data Engine](DATA_ENGINE.md), [Runtime AI](RUNTIME_AI.md) og
[research og gjenbruk](EVOLUTION_RESEARCH.md).

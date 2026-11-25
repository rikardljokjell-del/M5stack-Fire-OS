# Runtime AI på FIRE

Runtime AI lar en Lua-app be om en AI-vurdering mens appen kjører. Appen bruker
den samme backenden og OpenAI-nøkkelen som AI Developer. Ingen ny konto, server
eller Home Assistant-konfigurasjon er nødvendig.

**Status 25. november 2026:** Backend og firmware er implementert. Native CI
består 21 tester og alle tre bygg. Backendens fullkjøring ga 1013 beståtte
tester og fire utdaterte kostforventninger; forventningene er rettet og de
berørte kontrollene består. Windows-backenden er aktivert med bevarte innstillinger og nøkler. Eksakt RC3
er installert i B og helsegodkjent; RC9 i A er beholdt. Faktiske
knappestyrte AI-resultater og opplevd respons gjenstår i sluttprøven.
PC-resultater alene bekrefter ikke Runtime AI under fysisk appkjøring.

## Bruk

1. Hold den eksisterende FIRE-backenden tilgjengelig for enheten.
2. Velg Runtime AI-modell i backendens innstillinger. Utgangspunktet er
   `gpt-6-luna` for korte, avgrensede analyser og spillinnhold.
3. Bruk **AUTO** i AI Developer når appbyggeren skal vurdere AI-funksjoner.
   **OFF** utelater nye AI-funksjoner. En enkel klokke trenger ikke AI.
4. Be om oppgaven du ønsker, for eksempel «analyser måleavvik med AI» eller
   «lag nye spilloppdrag med AI». Appen skal ha tydelige knapper for dette.
5. Under **Innstillinger → Runtime AI i apper** velger du global aktivering,
   generering AUTO/OFF og eventuelle grenser. Modell velges sammen med de øvrige
   AI-modellene. Under **Apper** kan Runtime AI slås av for valgt app.
   Forbruksgrenser er valgfrie og er deaktivert som standard.

En app viser når en forespørsel arbeider, og skiller faktiske målinger fra
AI-vurderingen. Nettilgang og et tillatt AI-kall er nødvendig for nytt
AI-innhold. Lokale funksjoner skal fortsatt virke når det er hensiktsmessig.
Avslag, tidsavbrudd og nettfeil skal gi en kort melding og mulighet til å prøve
igjen, uten å låse appen eller FIRE OS.

## Kostnader

- **Jobber:** Bare den aktuelle bygge-, oppdaterings- eller reparasjonsjobben.
- **Apper:** Akkumulert kostnad for apputviklingen, inkludert tidligere
  oppdateringer og reparasjoner.
- **Runtime AI:** Egne summer per app og totalt, med kall, tokens, kostnad og
  svartid. Dette skal kunne skilles fra apputvikling og vanlig AI-dialog.

USD-beløp beregnes fra leverandørens rapporterte forbruk og registrerte priser;
de er ikke en avstemming av OpenAI-fakturaen. Manglende forbruk vises som
**ukjent**, eventuelt med et tydelig merket realistisk anslag. En intern
maksimumsreserve for budsjettkontroll er ikke faktisk forbruk.

## Felles utviklingskontrakt

Den kanoniske [Runtime AI-kontrakten](../contracts/RUNTIME_AI-v1.json) styrer
både backend og enhet. Den valgfrie utvidelsen beholder eksisterende
maskinvare- og App SDK-kontrakter.

`fire.ai.request(instructions, data_json, schema_json, timeout_ms)` oppretter en
asynkron jobb. Appen bruker eksisterende `fire.jobs.poll`, `result`, `cancel`
og `close`. Et vellykket resultat er `{ok=true, data=<strukturert objekt>}`.
Vanlige feil returneres som jobbfailure, slik at appen kan vise feil og
fortsette å svare på knapper.

`init()` gjør lokal oppsett. Et AI-kall utløses fra `update()` eller et
knappetrykk etter at kjøringen er bekreftet; kall under lasting eller `init()`
gir `nil, "stale_run"` uten jobb eller API-forbruk. En engangsforespørsel ved
oppstart kan forberedes med et lokalt flagg i `init()` og startes fra `update()`.

Appen samler, oppsummerer og velger relevante data lokalt før sending. En
forespørsel er begrenset til 1536 UTF-8-byte med instruks, data og skjema.
Resultatet er et validert JSON-objekt på høyst 512 byte. Det er én ventende
AI-jobb per app, innenfor den eksisterende grensen på fire jobber. Standard
tidsavbrudd er 30 sekunder, med tillatt område 1–60 sekunder.

Tillatelsen er bundet til den faktiske appen og pakken som kjører. Appen får
ikke velge nøkler, modell, URL, verktøy eller en annen apps identitet. Stopp,
avbrytelse, omstart og frakobling hindrer at et gammelt svar brukes i en ny
kjøring. Et avbrutt kall kan allerede ha påført API-forbruk.

Kjør `scripts/build_runtime_ai_contract.py --check` for å kontrollere at
kontrakt, pakkedata og enhetens genererte konstanter er identiske.

## To korte praktiske sluttprøver

De manuelle testappene **AI Analyse test** og **AI Oppdrag test** er
eksempler for integrasjonstesting, ikke bevis på AI-genereringens kvalitet.
De skal installeres og åpnes gjennom den vanlige, bekreftede appflyten.

1. Åpne analyseappen og la den samle minst 16 gyldige måleprøver. Trykk **B**
   for vurdering. Se at målinger og AI-vurdering er atskilt, og at knapper
   fortsatt svarer mens forespørselen arbeider.
2. Åpne oppdragsappen. Trykk **B** for et nytt AI-generert oppdrag. Kontroller
   at et strukturert resultat vises og at lokal spilling fortsatt fungerer.
3. Kontroller Runtime AI-forbruket under appen og i forbruksoversikten.
   Ingen idle- eller per-frame-kall skal belastes.

En reell forespørsel bruker den eksisterende OpenAI-nøkkelen og koster penger.
Før faktiske knappetrykk er resultatene bare offline-/simulatorbevis.

**Avgrensninger:** Den rapporterte firmware-SD-skrivefeilen er fortsatt et
eget, utsatt gjøremål. Denne leveransen løser heller ikke automatisk eldre
appspesifikke tidsoverskridelser; disse må vurderes på faktisk app og enhet.

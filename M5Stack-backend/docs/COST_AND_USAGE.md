# Kostnad og bruk i Windows-programmet

Oppdatert 2026-11-23. Gjelder `M5Stack-backend/`; device-koden er uendret.

## Rimelig standardoppsett

| Oppgave | Standardmodell | Begrunnelse |
| --- | --- | --- |
| Lage og rette Lua-kode | `gpt-6-luna` | Brukerens valgte rimelige standard for fokuserte Lua-oppgaver. |
| Kontroll av kildekode før levering | `gpt-6-luna` | Egen kontroll beholdes; ingen dyr automatisk modelloppgradering. |
| Samtale og avklaring av appønsker | `gpt-realtime-2.1-mini` | Kort, strukturert dialog i eksisterende taleflyt. |
| Gjøre taleopptak om til tekst | `gpt-transcribe` | Beholder nyere transkripsjon og norsk forståelse. |
| Lese opp AI-svaret | `gpt-realtime-2.1-mini` | Viderefører den eksisterende lydtransporten og stemmen. |

`OpenAI → Anbefalt rimelig oppsett` fyller inn disse modellene og
standardgrensene. Trykk `Lagre og bruk` for å ta dem i bruk. Kontroll av
API-nøkkelen henter modellisten; den tester ikke betalt kode- eller talegenerering.

Kodekontroll og lokale Lua-tester beholdes. En billigere modell er ikke et bevis
på identisk kvalitet, og en bestått PC-test er ikke fysisk verifikasjon på FIRE.
Utviklingstester bruker lokal simulering og API-mocker, ikke brukerens betalte
API-nøkkel. Live bruk kan likevel koste penger, også når en respons avbrytes eller
appen ikke blir ferdig.

Eldre Windows-profiler kan migreres med `DesktopStore.migrate_cost_profile()`.
Profilversjon 2 bytter tidligere standardvalg Sol/Astra for kode og kontroll til
Luna én gang. Den første profiloppgraderingen bytter også full Realtime til mini;
et bevisst Realtime-valg i en nyere profil bevares. Egendefinerte modellnavn, API-nøkkel, device-token, nettverk og
prosjektmappe beholdes. Ingen modell oppgraderes automatisk til en dyr modell
fordi et bygg feiler. Ukjent prisgrunnlag må avklares før nye kall tillates.

## Modellvalg med priser

`OpenAI → Modeller` har separate nedtrekkslister for dialog, kodegenerering,
kodekontroll, transkripsjon og talesvar. Valget viser modell-ID og inn-/utpris.
Forklaringen under hvert valg viser enhet, cachepriser og eventuelle lydpriser.
Prisene og kostnadstelleren bruker samme katalog, `fire_backend/model_catalog.py`.

- Kode/kontroll: GPT-6 Luna, GPT-5.6 Luna, GPT-6.1 Terra, GPT-6.2 Sol,
  GPT-6.1 Sol og GPT-6.2 Astra. Luna koster USD 0,10 inn / 0,50 ut per million
  tokens (Standard). Cacheskriving med 30 minutters levetid koster USD 0,125.
- Dialog: Realtime 2.1 mini og Realtime 2.1. Denne transporten bruker tekst;
  lydsvaret er et separat kall. Luna har ingen lydutdata og tilbys ikke her.
- Talesvar: de samme to Realtime-modellene, med separate tekst- og lydpriser.
- Transkripsjon: GPT-Transcribe, USD 0,0045 per minutt opptak. Tekstutdata er
  inkludert. Den er den aktuelle modellen for fullførte WAV-opptak. Live-Transcribe
  trenger en annen strømmetransport; utgående 4o-/Whisper-modeller tilbys ikke.

Innstillinger lagrer bare modell-ID, aldri visningstekst med pris. Tidligere
lagrede egendefinerte modellnavn beholdes og merkes tydelig. Kontotilgang er
ikke garantert av katalogen. Prislisten er datert og oppdateres i kode, ikke
automatisk fra nettet. Lange forespørsler over 272 000 inputtokens prises med
2× input/cache og 1,5× output i regnskapet. Ingen betalte testkall brukes for å
verifisere modellvelgeren eller migrasjonen.

## Verifikasjon av modellvelgeren 2026-11-23

487 tester bestått, inkludert modellvalg/lagring, engangsmigrasjon med bevarte
legitimasjoner, SDK-forespørsler og forbruksprising for alle seks kodemodeller.
Windows-vinduet er kontrollert visuelt med nedtrekksliste, cachepris,
lydpriser og rulling til hele oppsettet. PC-profilen er migrert til Luna for
kode og kontroll, programmet er startet på nytt og `/health` svarer `ok`.
Ingen betalte API-kall ble brukt. Dette bekrefter integrasjon og lokale tester;
kvaliteten på nye Luna-genererte apper er ikke fysisk verifisert på FIRE.

## Bruk og kostnad

Den nye siden viser:

- anslått USD og antall kall siden nullstilling, i dag og siden målingen startet;
- kostnadsdrivere fordelt på kodebygging, kontroll, samtale, taletolkning og talesvar;
- fordeling per modell og appjobb;
- siste kall med tokens inn/ut/cache, status og lokal kostnadsberegning;
- lydlengde, lydtokens og appjobb ved valg av et kall.

Oversikten hentes lokalt og utløser ingen nye betalte API-kall. Den lagrer ikke
API-nøkler, prompts, Lua-kilde, lyd eller komplette modelsvar i bruksregnskapet.
Opplysninger om app-/bygg-ID og modell brukes til å forklare kostnadsdriverne.

USD-beløpene er **anslag, ikke OpenAI-faktura**. Grunnlaget er en datert lokal
prisliste og rapportert bruk der endepunktet leverer det. Cachetokens inngår i
inputtotalen; reasoning inngår i outputtotalen. De belastes ikke en ekstra gang
som egne totale tokenmengder.

Cachelesing og cacheskriving vises separat og prises etter rapportert bruk.
Kodeforespørsler bruker eksplisitt cachepunkt før prosjektdata og 30 minutters
levetid; innhold som bare gjelder den enkelte appen blir ikke skrevet til cache
som om det var en felles instruks. Ingen cachetreff eller spareprosent loves.

Ved manglende tokenmåling beholdes en konservativ kostnadsreserve, og kallet
merkes som anslag. Dette gjelder også avbrutte eller usikre kall etter omstart:
backend kan ikke anta at OpenAI ikke fakturerte dem. Tokenoversikter kan derfor
inneholde reserverte maksimumsverdier sammen med rapporterte målinger. Velg et
kall for å se grunnlaget. Varighetsprisede transkripsjoner beregnes fra lydlengde.

Forbruk før denne målingen ble aktivert kan ikke rekonstrueres nøyaktig fra gamle
byggefiler. Tidligere betalte beløp, for eksempel de første to utviklingsdagene,
blir derfor ikke lagt inn som oppdiktede målte tall. OpenAIs egen forbruksoversikt
og faktura er fasit for det faktiske historiske beløpet.

## Kostnadsgrenser

Standard under `Innstillinger`:

| Grense | Standard |
| --- | ---: |
| Maks per dag | USD 2,00 |
| Maks per appjobb | USD 0,60 |
| Maks per API-kall | USD 0,25 |
| Automatiske rettinger etter første kandidat | 1 |

Før et betalt kall reserverer backend et konservativt beløp for innholdet og
det tillatte svaret. Hvis denne reserven ville passere en grense, startes ikke
kallet. En jobb kan derfor stoppes selv om det endelige modelsvar hypotetisk
kunne ha blitt billigere. Dette er ønsket vern mot uventet forbruk; det er ingen
garanti for at alle appønsker fullføres innenfor beløpet.

Grensene gjelder kall som går gjennom denne backenden og dette lokale
bruksregnskapet. De er ikke en grense satt hos OpenAI, påvirker ikke andre
programmer som bruker samme konto, og er ikke et mål på gjenværende API-kreditt.
Daggrensen og hvilken tidssone som brukes vises i oversikten. Ved manglende
tidssonedatabase kan backend rapportere UTC i stedet for Europe/Oslo.

## Nullstill visningstellerne

Knappen `Nullstill visningstellerne` starter en ny visningsperiode. Den sletter
ikke historikken, nullstiller ikke dagens kostnadsgrense og tilbakefører ikke
API-kreditt. «I dag» og «Siden målingen startet» bevarer tidligere bruk. Et kall
som fortsatt pågår ved nullstilling, vises når det fullføres i den nye perioden.

## Offisielle kilder

Modellvalg og prisliste er kontrollert mot OpenAI Docs 2026-11-23:

- [GPT-6.2 Sol](https://developers.openai.com/api/docs/models/gpt-6.2-sol)
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [GPT-6.1 Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra)
- [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [GPT-6.2 Astra](https://developers.openai.com/api/docs/models/gpt-6.2-astra)
- [GPT-Realtime-2.1](https://developers.openai.com/api/docs/models/gpt-realtime-2.1)
- [GPT-Realtime-2.1 mini](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini)
- [GPT-Transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe)
- [Priser](https://developers.openai.com/api/docs/pricing)
- [Kostnadsoptimalisering](https://developers.openai.com/api/docs/guides/cost-optimization)

Modellpriser og tilgjengelighet kan endres. Ukjente modeller trenger et eksplisitt
prisgrunnlag; backend skal ikke gjette at de er gratis.

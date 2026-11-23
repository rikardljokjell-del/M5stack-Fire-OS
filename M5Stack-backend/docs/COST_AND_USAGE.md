# Kostnad og bruk i Windows-programmet

Oppdatert 2026-11-23. Gjelder `M5Stack-backend/`; device-koden er uendret.

## Rimelig standardoppsett

| Oppgave | Standardmodell | Begrunnelse |
| --- | --- | --- |
| Lage og rette Lua-kode | `gpt-6.2-sol` | Enklere FIRE-apper trenger ikke Astra som fast standard. |
| Kontroll av kildekode før levering | `gpt-6.2-sol` | Egen kontroll beholdes; ingen dyr automatisk modelloppgradering. |
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
Migrasjonen bytter tidligere standardvalg Astra og full Realtime til de rimelige
valgene én gang. Egendefinerte modellnavn, API-nøkkel, device-token, nettverk og
prosjektmappe beholdes. Ingen modell oppgraderes automatisk til en dyr modell
fordi et bygg feiler. Ukjent prisgrunnlag må avklares før nye kall tillates.

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
- [GPT-Realtime-2.1 mini](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini)
- [GPT-Transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe)
- [Priser](https://developers.openai.com/api/docs/pricing)
- [Kostnadsoptimalisering](https://developers.openai.com/api/docs/guides/cost-optimization)

Modellpriser og tilgjengelighet kan endres. Ukjente modeller trenger et eksplisitt
prisgrunnlag; backend skal ikke gjette at de er gratis.

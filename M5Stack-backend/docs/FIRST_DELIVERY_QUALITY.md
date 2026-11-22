# Fast standard: fungerende og gjennomførte apper ved første levering

Brukeren skal ikke måtte be om at en ny app repareres eller gjøres penere.
Dette er nå en permanent instruks og en ekstra leveringsport for alle nye
OpenAI-genererte apper og oppdateringer, også uten tidligere feilhistorikk.

## Før appen sendes

1. Generering får `APP_QUALITY_POLICY` fra `fire_backend/app_quality.py` sammen
   med forhandlet maskinvare-/tegnekontrakt og kjente feilregler allerede på første
   forsøk. Reglene omfatter krav, initialisering, knapper, reset, tomme/fulle data,
   pause/game-over, feil/timeout, ressursopprydding og native ytelsesrisiko.
2. Kandidaten må passere eksisterende release-v4: sju input-/tidsprofiler og tre
   ekstra I/O-feilprofiler for utvidede hardwareapper. Ingen kjent feilkilde eller
   blank/tung rendering godkjennes ved å slå av kontrollene.
3. En separat OpenAI-forespørsel gjennomgår den faktiske kandidaten mot avtalt
   funksjon, kjøresikkerhet og grafisk kvalitet. Den får koden, konkret appønske,
   maskinvarekontrakten og testresultatene, uten generatorens begrunnelse som bevis.
   Den vurderer skjermoppsettet fra tegnekoden; den påstår ikke å ha sett et fysisk
   skjermbilde. Ingen kilde kjøres av denne gjennomgangen.
4. Konkrete funn returneres til den eksisterende automatiske korreksjonsløkken.
   Endret kilde må testes og gjennomgås på nytt. Maks opprinnelig forsøk pluss
   tre rettinger; uavklart/avvist/ufullstendig kontroll gir ingen ny leverbar pakke.
   Dette er interne forsøk, ikke nye brukersynlige appversjoner.
5. Godkjenningen bindes til SHA256 av den faktiske kildekoden og lagres i
   `validation.pre_delivery_review`. Nye pakker har
   `pre_delivery_review_required=true`. Manglende/avvist/feil kildehash eller
   mock-godkjenning for en live pakke blokkerer levering. Retesting av uendrede
   pakker må bevare porten, aldri fjerne den. Eldre pakker omskrives ikke.

## Design er et krav for hver app

- En helhetlig visuell stil tilpasset appen: rolig bakgrunn, begrenset palett,
  tydelig aksent og lesbar kontrast.
- Konsekvente marger, avstander og justering; tydelig hierarki mellom tittel,
  spill/verktøy, resultat og kort knapphjelp.
- Spill skal ha et gjennomført brett/spillområde, poeng/status og tydelige
  pause-/sluttilstander. Verktøy skal ha ordnede seksjoner, markert valg,
  lesbare målinger og forståelig arbeids-/feilstatus.
- Bruk grafiske figurer, kompakte rutenett, målere og enkle ikoner når egnet,
  fremfor lange ASCII-rader eller en skjerm full av debugtekst.
- Umiddelbar feedback, stabil bevegelse og responsive kontroller. Ingen pynt som
  sprenger minne-/callbackbudsjettet, blanke mellomrammer eller autoavslutning.
- Bruk kun faktisk annonsert API og støttede tegn. God design krever ikke
  oppdiktede fonts, sprites eller uimplementerte tegnekall.

Reglene gjelder nybygg og reparasjoner uansett om brukeren ber om pent design.
Feilminnet fremmer bare faste, gjennomgåtte regler; rå enhetslogger eller
modelltekst blir ikke nye systeminstrukser. Tidligere feilversjoner forblir sperret.

## Verifikasjon og grenser

Automatiske tester kontrollerer at en kandidat som passerer runtime men avvises
for design blir rettet før første pakke, at vedvarende funn gir null pakker,
at review er kildebundet og at retesting bevarer det. Mockgjennomgang merkes
`mock_fixture`; dette er ingen live AI-/grafikkverifikasjon.

En AI-gjennomgang og endelige PC-profiler beviser ikke alle fremtidige tilstander,
faktisk ESP32-ytelse eller fysisk maskinvare. Funksjonsmangler i firmware må fortsatt
løses av device-agenten. Backend skal ikke sende en kandidat med påviste feil eller
påstå fysisk feilfri drift på grunnlag av disse kontrollene.

22. november: hele suiten besto med 323 tester. Isolert ekte OpenAI-bygging av
«Reaksjonsfelt» viste at PC-godkjente kandidater ble avvist av kildegjennomgangen
for konkrete knapp-/tilstandsfeil. Først fjerde interne forsøk ble godkjent etter
ny testing og gjennomgang. Bare én pakke ble publisert i det isolerte testområdet;
ingen devicekommandoer ble sendt. Den godkjente kildehashen er
`a7f8b0b553d67136234fb00e8fdf4ccb3b4ed905bc5330690cba82481458a389`.
Testen omfatter ikke fysisk drift eller faktisk skjermvurdering på FIRE.

Implementasjonen bruker eksisterende Responses/Pydantic-støtte fra
[OpenAIs dokumentasjon for strukturerte svar](https://developers.openai.com/api/docs/guides/structured-outputs).

# SDK-standardkrav: deterministisk kontroll før levering

Implementert som `fire-sdk-standards-v1`. Den frosne V3-målingen og tidligere
READY-resultater endres ikke. Denne endringen gjelder nye SDK-bygg; 0.1/0.2-wire,
kontrakthasher og eksisterende legacyporter bevares.

1. **Frys sannhetsgrunnlaget ved byggestart.** Lag en backendforfattet
   standardkontrakt fra faktiske annonserte kapabiliteter, gjeldende FIRE
   experience-regler og bekreftet appbestilling. Lagre dette med input-/kildehash.
   Kandidatens `required_services` kan aldri redusere hva enheten faktisk tilbyr.
   Bruk samme sentrale kategorisering for et entydig spillønske; modellens egen
   `kind` er ikke eneste grunnlag. Tvetydige nye produktkrav innføres ikke.

2. **Respekter brukerens avtalte unntak.** Et eksplisitt ønske om ingen RGB eller
   ingen spilllyd kan slå av den aktuelle standardforventningen. «Lyd av/på» som
   menyvalg og «starter med lyd av» er ikke det samme som et permanent opt-out.
   Følg faktisk tilgjengelighet og dagens serviceclosure; annonser ingen ny
   maskinvare og tving aldri en uannonsert tjeneste inn i pakken.

3. **Mål faktisk bruk.** Utvid eksisterende workertelemetri med små avgrensede
   RGB-aggregater per profil: antall kall, skrevne indekser og ikke-null aktivitet
   på hver fem-LED-side. Dette skal være uavhengig av den avkortede tracen og
   skjermbildefangsten. Bruk eksisterende `jobs_started` for faktisk startet
   speaker-jobb i relevante normale/brukerdefinerte testsekvenser. Nullstilling
   alene eller en serviceerklæring er ikke bevis på meningsfull RGB/lydbruk.
   Ingen lydsamples eller nye ubegrensede logger innføres.

4. **Kontroller etter lokale kjernetester, før review/pakking.** Når standarden
   krever RGB, må både erklæring og målt aktivitet på begge sider finnes. Når
   avtalt spilllyd kreves og støttes, må speaker/jobs/dependencies og faktisk
   startet avspilling finnes, også når lyd starter av og må aktiveres i menyen.
   Manglende testdekning gir målrettet tilbakemelding om sekvens/feature, aldri
   tillatelse til å fjerne funksjonen. AI-review vurderer fargemønstre, relevant
   musikalsk bruk, gain/mute, knapper og øvrig semantikk; jobbkvitteringer er ikke
   fysisk hørbarhetsbevis.

5. **Bevar den fungerende kjernen.** Et apputkast som består kjørerprofilene men
   mangler standardfeedback skal beholdes som kjernetestet reparasjonsgrunnlag.
   Be om en målrettet endring og nye tester/review; ikke start et nytt prosjekt
   eller kast kildekoden. Ingen pakke blir leverbar eller fysisk godkjent bare
   fordi kjernen passerer. Resume må beholde samme grunnlag og standardkontrakt.

6. **Meningsfulle regresjoner.** Test utelatt RGB/speaker i `required_services`,
   kun én LED-side, bare svart/nullstilling, lyd aldri slått på, faktisk fungerende
   RGB/audio, permanente opt-outs mot av/på-meny, manglende firmwaretjenester,
   gjenbruk av kjernekandidat og uendrede legacy-/build_confirm/run_confirm-porter.

Tidligere V3-Luna-stoppeklokke er lokalt/review-godkjent, men har bare display og
ingen app-RGB til tross for annonsert RGB. Den beholdes som dokumentert negativt
eksempel på standardkravsgapet, uten å omskrive historisk måleresultat.

## Implementasjon og avgrensning

`sdk_standards.py` lager kontrakten fra faktisk capabilities og bekreftet bestilling.
`Builder` måler standarden etter kjernetestene og før eksisterende AI-review.
Bare normale profiler og brukerdefinerte normale scenarioer teller som positiv
RGB-/lyddekning; feilprofilens aktivitet alene er ikke tilstrekkelig. Aggregatene
bevares også når den korte tegnetracen er full. AI-review vurderer om bruken er
relevant, ikke bare om det finnes en API-aktivitet. Ingen av disse PC-målingene
bekrefter fysisk lydkvalitet, RGB, ESP32-tid eller installasjon.

Standardkontrollens resultat bindes til kildehash og standardkontraktens hash.
Leveringskontrollen avviser SDK-livepakker uten gyldig standardbevis. Resume
bevarer det sterkeste kjernetestede grunnlaget når en senere rettelse regresserer.
Offline revalidering henter faktisk opprinnelig profil/bestilling og den nøyaktige
kandidatens testsekvenser; den kopierer ikke et gammelt standardbevis blindt.

SDK-simulatoren godtar native-gyldig randklipping, inkludert UI-partikler ved
skjermkanten, uten å utvide native argumentgrenser. Gamle 0.2-designporter beholdes.
Leveringskontrollen bruker 384 gridceller for SDK og fortsatt 128 for gammel
genereringspolicy. `display_semantics` kommer direkte fra kanonisk SDK-registry,
én gang i API-konteksten, uten parallelle signaturer.

`scripts/audit_sdk_standards.py` tester bevarte benchmarkpakker i en ny lokal
evidensmappe. Den endrer ikke de opprinnelige målingene, bruker ingen AI-kall og
sender ingen devicekommandoer. Historisk pipeline-READY og ny standardgodkjenning
rapporteres hver for seg. Dette er ingen garanti for feilfri generering.

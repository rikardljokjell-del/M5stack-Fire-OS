# Automatisk feilsøking, kvalitetsport og applevetid

Backendendring, 22. november 2026. Device-kilde er lest til 7787ed0; ingen firmware er endret eller flashet av backend-agenten. Bruk dette som tillegg til samtale- og applivssykluskontrakten.

## Hvorfor gamle apper kunne slippe gjennom

Den gamle porten kjørte 180 frames à 16ms (2,88s), én syntetisk sekvens av A/B/C og ett rent oppstartsscenario. Feil etter tre sekunder, holdte knapper, tilstandsoverganger, reset og varierende dt kunne derfor unngå test. PC Lua 5.4 bruker dessuten andre tall-/allokeringsdetaljer enn ESP32s LUA_32BITS. Et grønt PC-resultat er ikke bevis for korrekt hardware eller at alle mulige interaksjoner er testet.

Dialogen fikk manifest og krav, men ikke en automatisk sammenstilling av kilde/feil/diagnostikk. Den kunne derfor be brukeren om logger eller foreslå en ny generisk app. Runtimefeil sperret heller ikke den immutable pakken for senere ny levering. Disse hullene er rettet generelt, uten å endre brukerens Snake-kilde eller installasjon.

## Implementert backendflyt

### Navngitt reparasjon uten appvelger

«Fiks slangespillet. Jeg får app error når jeg starter det.» finner nå automatisk
den entydige Slangespill-appen innenfor den autentiserte enhetens egne prosjekter.
Navn/SD-ID søkes med store/små bokstaver og norske endelser som slangespill/slangespillet.
Navnet er et søkekriterium; kildeidentiteten verifiseres fortsatt med eier, prosjekt,
pakke og arkivhash. Andre enheters apper kommer aldri med i kandidatsøket.

Et navngitt mål overstyrer en annen valgt app uten å blande historikk. Generisk
«fiks appen» bruker valgt app, en entydig faktisk installert/kjørende app eller
den eneste lagrede appen. Ukjent navn gir aldri reparasjon av en tilfeldig app.
Bare ekte flertydighet gir et kort spørsmål med appalternativer. Ingen krav om
PC-appvelger, linjenummer eller manuell feillogg når appen allerede er identifiserbar.

Aktiv session/turn beholdes gjennom automatisk prosjektvalg. BUILD/RUN-bekreftelser
beholdes. Backend husker begrensede, verifiserte tidligere prosjekt-ID-er for denne
sesjonen, slik at resume fra gammel firmware ikke mister reparasjonen hvis dens
prosjektcache ennå er gammel. Eksplisitt nytt appvalg nuller disse resume-aliasene.
Device bør håndtere app_selected og oppdatere lokal prosjekt/basecache fra serveren,
uten å avbryte det aktive opptaket eller slette gjeldende turn_id.

1. Brukeren navngir appen eller bruker allerede valgt app, for eksempel «Fiks slangespillet» eller «den fungerer ikke, fiks den».
2. Backend identifiserer bare valgt prosjekt/baseversjon, verifiserer arkivet, leser hele kilden og tester den automatisk mot releaseporten. Ingen navnebasert gjetting eller spørsmål om linjenummer/loggutdrag.
3. Tidligere korrelerte device-feil og resultatet fra gjenskaping på PC samles i en reparasjonskontekst. Feil som ikke gjenskapes rapporteres som ikke gjenskapt; de påstås ikke løst.
4. Backend lager et målrettet reparasjonsforslag som bevarer opprinnelige funksjoner/kontroller. BUILD bekreftes med den eksisterende knappen; det stilles ikke en ny runde tekniske spørsmål. Ved reparasjon av en kjørende app stopper backend først den korrelerte kjøringen og venter på kvittering uten å blokkere kontrollkanalen.
5. Byggeren får eksakt tidligere kilde, bekreftede krav, runtimefeil, kjente forholdsregler og valideringsfeil. Én generering og opptil tre automatiske korreksjoner er tillatt innen samme begrensede byggejobb.
6. Alle sju releaseprofiler må bestå før en ny pakke publiseres: idle, normal knappesekvens, A holdt, B holdt, C holdt, raske knapper og varierende dt. Hver profil starter i ny VM. Positiv levetidsgrense testes helt ut; unlimited-profil testes 60 sekunder per profil. Dette er en testhorisont, ikke en lukketimer.
7. Den eksakte kildehashen til en tidligere rapportert feilversjon av samme prosjekt avvises som en uendret reparasjon. Ved mislykket korrekturløkke finnes ingen leverbar ny pakke. App-ID/mappe beholdes og versjonsnummer øker først ved vellykket publisering.
8. RUN bekreftes separat. PC-test, installert, startet og device-healthy holdes atskilt. Gammel immutable ZIP beholdes som dokumentasjon og blir ikke overskrevet.

## Varig erfaring og leveringssperrer

Lokalt workspace/quality inneholder dedupliserte hendelser med prosjekt/device/pakke, kildehash, opprinnelse, feilklasse og avgrenset redigert feiltekst. Kildene er user_report, device_receipt, device_diagnostic, release_validator og repair_reproduction. Tidligere feil beholdes gjennom backendrestart.

Bare faste, gjennomgåtte regler for bounds/indekser/nil/minne/API/tekst/livssyklus brukes som genereringsinstruksjoner. Vilkårlig device-logg eller modelltekst blir ikke ny systempolicy og det kjøres aldri generert Python/shellkode. Erfaringen er lokal, ikke trening av OpenAI-modellen. Nye feil gir ny dokumentasjon og relevante faste forholdsregler; nye feilklasser krever fortsatt nye ordentlige regresjonstester i backend.

En rapportert feilversjon sperres for download, ny installering og ny RUN. Eldre pakker som bare har den gamle 180-frame-testen er også sperret for ny levering; velg appen og be om en ny testet bygging. Å lese sperret kilde til diagnose/oppdatering er tillatt. Gjenoppretting bruker eksisterende korrelerte rollbackregler og starter aldri appen automatisk.

En testet rettelse gir candidate_validated_on_pc, ikke fysisk løst. app_healthy for den nye pakken gir device_reported_healthy, ikke et løfte om feilfrihet under utestet bruk. Samme feil senere registreres igjen. Ved sletting av PC-prosjekthistorikk slettes prosjektets feiltekst også; bare de faste, innholdsfrie forholdsreglene beholdes.

## Device-agent: runtimefeil må sendes automatisk

Ved en backendstartet kjøring brukes eksisterende app_failed med korrekte run_id, package_id, session_id, boot_id, error_code og message. Behold linjenummer, callback og den faktiske Lua-feilen i den avgrensede meldingen. Backend validerer korrelasjonen før erfaring lagres.

Ved lokal start fra Apps finnes ofte ingen backend-run_id. Bruk da det nye eventet app_diagnostic, aldri en oppdiktet app_failed-run_id:

    {"type":"device_event","protocol_version":"0.2","event":"app_diagnostic",
     "device_id":"m5stack-fire-01","session_id":"session-example","boot_id":"boot-example",
     "event_id":"diagnostic-example","app_id":"snake","package_id":"build-example",
     "error_code":"runtime_error","message":"lua update: main.lua:79: ..."}

Package-ID og app-ID må være de faktiske som tilhører den installerte versjonen. Backend kontrollerer eier/app/pakke. Dette eventet registrerer feil og sperrer pakken; det oppfinner ingen runtime-state og autoriserer ingen bygging. Backend kvitterer med case_id og sender repair_available. Rapporter også on_button/init/load-feil, ikke bare update-feil. Bevar et begrenset antall rapporter i outbox ved offlinefeil og send med riktig identitet etter reconnect. Ikke logg API-nøkler eller rå tale. Når brukeren åpner AI Developer for en app som kjører, stopp appen og send korrekt app_stopped før opptak, slik at brukerens repair-ønske kan behandles uten «busy».

## Device-agent: fjern automatisk lukking etter ti sekunder

Ny avtalt sentinel: capabilities.max_runtime_ms=0 og manifest.max_runtime_ms=0 betyr **kjør til brukeren avslutter**. Det betyr ikke en null millisekunder lang app, og ikke deaktivert callbackvern. Backend aksepterer/genererer denne profilen nå. Firmware må:

- Annonsere max_runtime_ms=0 først når ubegrenset applevetid faktisk støttes.
- Godta 0 i manifestvalidering og behold verdien ved installasjon/runtime-start.
- Fjerne global 10000ms-grense for denne profilen i FireLuaRuntime::update; ingen skjult alternativ timeout.
- Beholde 12ms callback-/instruksjonsbudsjett, minnegrense, korte callbacks og OS-kontroll. Fastlåste apper skal fortsatt stoppes som feil.
- Beholde OS-langtrykk på Home/Back, stopp ved eksplisitt exit og sende app_stopped reason=user_exit med riktig korrelasjon. En app skal kunne startes igjen umiddelbart.
- Migrere eldre lokalt genererte apper til ønsket levetid med en tydelig manifest-/policystrategi; ikke bare endre backendens tall mens firmware fortsatt stopper etter 10s.
- Beholde støtte for positive, eksplisitte legacygrenser der de faktisk ønskes. Backend setter ikke unlimited på en enhet som fortsatt annonserer 10000 og later ikke som firmware er oppdatert.

60s PC-testhorisont endrer ikke applevetiden på enheten. Test på FIRE i minst fem minutter, avslutt med både Home og Back, start igjen, og test watchdog/minnevern med en kontrollert fastlåst callback.

## Backendverifisering

215 samlede pytest-tester bestått, inkludert navngitt automatisk reparasjon, enhetsscope og resume etter prosjektbytte. Isolert ekte OpenAI-dialog/kodegenerering har passert sju-profil-porten og ga en validert Sprettsirkel-pakke. Dette var en separat testmappe, ikke brukerens Snake-app og ikke en fysisk installasjon. Ingen API-nøkler eller brukerpakker publiseres i GitHub. Windows-appen har Reparer valgt app, viser leveringssperrer og skjuler installasjon for pakker uten ny releaseport.

## Akseptansekriterier

- Appfeil etter 3s, holdte knapper og dt-jitter som gammel port overså må avvises før pakking.
- En korreksjon som feiler fire ganger publiserer ingen ZIP og lar forrige versjon/historikk være intakt.
- Feilrapport → automatisk valgt-kilde/feillogg/PC-gjenskaping → samme app/ny versjon, uten tekniske spørsmål. Bare eksisterende BUILD/RUN-bekreftelser.
- Feilregister overlever restart; ukjente/andre enheters pakker og falske run-ID-er kan ikke forurense det.
- En tidligere feilpakke kan ikke lastes ned/installere/kjøres på nytt via retry.
- Unlimited-profil testes på PC til 60s, på enheten til minst fem minutter, avsluttes bare ved brukerens exit eller faktisk runtimefeil.
- Alle resultater merkes med testhorisont, profiler og fysisk verifiseringsnivå. Ingen endelig testmatrise kan bevise at enhver mulig app aldri har en feil.

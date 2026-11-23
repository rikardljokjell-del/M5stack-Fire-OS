# Kostnad, modellvalg og effektiv apputvikling

Oppdatert 2026-11-23. Gjelder Windows-programmet og M5Stack-backend/.

## Standard: ingen beløps- eller svartak fra backend

Under Innstillinger er alle fire tallfelt **0 som standard**:

| Felt | 0 betyr |
| --- | --- |
| Maks per dag (USD) | Ingen dagsgrense |
| Maks per appjobb (USD) | Ingen beløpsgrense per jobb |
| Maks per API-kall (USD) | Ingen beløpsgrense per kall |
| Automatiske rettinger | Automatisk retting etter framgang, uten fast antallsgrense |

Bruk kostnadsgrenser er av som standard. Når bryteren slås på, håndheves bare
positive beløp; et enkelt felt med 0 er fortsatt uten grense. Lagrede beløp kan
endres ved behov. En positiv grense for rettinger er et eksplisitt valg om et
fast antall etter første kandidat. Standard 0 deaktiverer ikke feilretting.

Bruk ekstra svartak for AI er også av som standard. Kodegenerering og
kodekontroll sender da ingen max_output_tokens fra backend. Realtime dialog
og talesvar bruker inf, som betyr modellens egen tilgjengelige kapasitet.
Dette opphever ikke modellens tekniske kapasitet, konto-/kredittbegrensninger,
nettfeil eller enhetens minne- og driftsgrenser.

Hvis ekstra svartak velges, brukes 24000 for Luna-generering (12000 for
andre kodemodeller) og 6000 for kontroll. Et avkuttet svar kan gjenopprettes
med større svarrom én gang. Dette er valgfri virkemåte, ikke standardtaket.

Forbruksregnskapet er aktivt uansett om grensene er av. Nullstilling av
visningstellerne endrer aldri de historiske registreringene eller appens Cost.
Når måling mangler, brukes et konservativt anslag fra modellens maksimale
svarrom. Et slikt beløp merkes som reserve, ikke som målt fakturert bruk.

## Rimelige modeller og arbeidsmåte

| Oppgave | Standard |
| --- | --- |
| Lage og rette Lua-kode | gpt-6-luna |
| Kontroll før levering | gpt-6-luna |
| Samtale | gpt-realtime-2.1-mini |
| Opptak til tekst | gpt-transcribe |
| Hørbart AI-svar | gpt-realtime-2.1-mini, når talesvar er slått på |

OpenAI-siden har nedtrekkslister med inn-/utpris og riktig enhet. Kodevelgeren
inkluderer Luna 6/5.6, Terra 6.1, Sol 6.2/6.1 og Astra 6.2. Lydvalg filtreres
etter transporten som faktisk er implementert. Modeller oppgraderes ikke
automatisk til dyrere alternativer. Modellkatalogen og kostnadstelleren har
samme prisgrunnlag i fire_backend/model_catalog.py, datert 2026-11-23.

Kostnadseffektivitet oppnås ved å redusere unødvendig arbeid:

- Lav resonnering og presise, komplette kildekodesvar.
- Et stabilt instruksjonsprefiks med eksplisitt 30-minutters caching.
- Kompakte test-/sensordata uten å fjerne nødvendig funksjonalitet eller bevis.
- Registryens tjenestenavn som enum i AI-skjemaet. Entydig navnefeil som
  fire.display til display rettes lokalt uten et nytt modellkall.
- Lokale Lua-/kontrakttester før egen AI-kontroll. Ingen utestet pakke leveres.
- Automatisk retting fortsetter når det kommer nye kontrollfunn. Gjentatt
  identisk kode eller samme uløste kontrollfunn stopper en løkke uten framgang,
  med forklaring og bevart plan. Det finnes fortsatt en teknisk jobbtidsgrense.
- Ved avbrutt/feilet AI-kontroll kan Resume gjenbruke kildekoden som allerede
  bestod lokale tester. Prosjekt, krav, kildehash, kontekst, capabilities,
  modus og basisversjon må samsvare. Lokale tester og AI-kontroll kjøres igjen.
  Endrede krav eller manipulert kode gjør at den ikke gjenbrukes.
- Konto-/betalingsfeil og avslag gjentas ikke som om de var Lua-feil.
- Å åpne Resume eller hente kostnadsoversikten gjør ingen nye modellkall.

En billig modell er ikke et bevis for at alle apper fungerer. Fysisk kjøring
må bekreftes av enheten; lokale tester og AI-kontroll beholdes uansett prisvalg.

## Slå AI-talesvar av eller på

OpenAI har valget **Les AI-svar høyt på FIRE**. Standard er på for å bevare
valg og den eksisterende taleflyten. Slå av og trykk Lagre og bruk for å spare
lydgenereringen. Da blir det ingen speech/TTS-kall eller audio_ready fra nye
svar. Mikrofon, transkripsjon, tekstsvar, avklaringer og appbygging virker
fortsatt. Replay/Test lyd er ikke tilgjengelig mens talesvar er av.

Dette er uavhengig av Aktiver backendens lydtransport: den transporten må
være på for mikrofonopptak. Det endrer heller ikke Lua-appers spilllyd eller
OS-hovedvolum. Conversation audio gir aldri ekstra Lua-hardwaretjenester.

USD20 for Realtime mini betyr per én million genererte lydtokens, ikke per
svar. Mini er allerede det rimeligste aktuelle alternativet i den eksisterende
Realtime-transporten. Eldre Speech API-modeller tilbys ikke som ny løsning:
de er utgående og planlagt stengt 2027-01-06. Bryteren kan spare hele den
framtidige TTS-delen; transkripsjon, dialog og kode har fortsatt egne kostnader.

## Cost i Apper

Apper viser **Cost (USD)** på appens samlede rad. Hver versjon får samme
prosjekttotal fra backend; UI summerer ikke disse versjonstotalene en gang til.
Den valgte versjonen påvirker aldri beløpet. Beregningen bruker hele den
registrerte levetidshistorikken, med blant annet:

- generering og kontroll for alle versjoner;
- mislykkede bygg, nye forsøk og feilrettinger;
- dialog, transkripsjon og AI-talesvar som kan knyttes til appen;
- registrert usikkert/avbrutt forbruk, tydelig behandlet som anslag.

Regnskapet grupperes etter prosjekt-ID, ikke navn, slik at forskjellige apper
med samme navn ikke blandes. Bygg-ID gir sikker reservekobling når en eldre
registrering mangler prosjekt-ID. Nye byggregistreringer får denne koblingen
før historiske versjoner kan slettes. Når et taleønske automatisk velger en
annen reparasjonsapp, knyttes den aktuelle taleomgangens kostnad til den
løste appidentiteten; beløp og eksplisitte byggekoblinger endres ikke.

Sletting av en versjon og Nullstill visningstellerne sletter ikke API-bruken.
Cost kombinerer registrert bruk med tydelig merkede historiske byggeanslag.
Det er ikke en OpenAI-faktura. Apper med historiske anslag vises med ≈.
Detaljene viser registrert beløp, historisk anslag, scenariointervall og modell.

Historiske bygg før målingens start rekonstrueres én gang fra request.json,
attempt-N.lua og review-N.json, også mislykkede forsøk knyttet til appen.
Lagret modell brukes; i den undersøkte historikken var dette GPT-6.2 Astra.
Review-modell antas lik lagret kodemodell når eget modellnavn mangler.
Ved oppdateringer tas forrige pakkes kildekode med i inputanslaget.
Lokale metadata-/lydforsterkningsrettelser uten AI-kall gis ingen ekstra kostnad.

Metode retained-artifacts-v2: tegn/4 anslår tokens; scenariointervallet bruker
tegn/5..3. Sentralt anslag legger til 1500 resonneringstokens for generering og
1000 for review, begrenset av daværende 8000/4000 svartak. Øvre scenario bruker
hele daværende svartak og 2,5 ganger inputpris for mulig cache-skriving; ingen
cache-leserabatt antas. Full lagret kontekst, kilde, simuleringsdata og 4096
tegn instruksjons-/skjemapåslag inngår. Dette er grove scenarioanslag, ikke
statistiske konfidensintervaller eller garanterte øvre/nedre fakturabeløp.
Ukjent faktisk resonnering, cache-treff og tapte svar kan gi vesentlige avvik.
Eldre dialog/tale uten måling er utelatt; slike kostnader fordeles ikke vilkårlig.

Historiske anslag lagres separat uten prompts, kildekode eller nøkler.
De inngår i appens Cost, men aldri i dagens forbruk, budsjetter eller
nullstillbare API-tellere. Sletting av versjoner/bygg og nullstilling bevarer
anslagene. Senere registrert/importert bruk for samme bygg og operasjon erstatter
hele denne operasjonens historiske anslag, slik at den ikke telles dobbelt.

## Resume og konkrete feilårsaker

RPG-jobben build-a5ab57cfbc8444cca5f5 brukte tidligere 8000 outputtokens til
intern resonnering uten kode. Grensen inkluderte både resonnering og selve
svaret; beløpet var USD0,00571425. Denne backend-svargrensen er ikke lenger
aktiv som standard.

Status og faktisk bruk leses før JSON parses. Avslag, avkutt og ugyldig
svarstruktur skilles fra hverandre. Plan, dialog og manuelle tillegg beholdes.
Velg Jobber -> Resume valgt jobb, endre planen eller bekreft et nytt bygg.
Tidligere jobb og kostnad bevares; det nye bygget peker tilbake med retry_of.
FIRE bruker samme flyt gjennom build_resume, med kort norsk årsak og separat
begrenset diagnosefelt. Se DEVICE_FAILED_BUILD_RESUME.md.

## Profiloppgradering og sikker lagring

Profilversjon3 setter de fire grensene til0 og slår ekstra kostnads-/svartak
av én gang, etter brukerens uttrykkelige bestilling. Senere egne innstillinger
bevares. Eksisterende modellvalg fra profilversjon2, nettverk, workspace,
API-nøkkel og device-token bevares. For enda eldre profiler gjelder den tidligere
Luna-/mini-migrasjonen. Nøkler lagres fortsatt i Windows Credential Manager.

Bruksregnskapet lagrer ikke API-nøkler, enhetstoken, prompts, lyd, kildekode
eller rå modellfeil/resonneringstekst. Metadata om prosjekt/bygg/sesjon/taleomgang,
modell, tokens, status og beregnet USD brukes for måling og appfordeling.

## Offisielle kilder

Verifikasjon denne leveransen: hele testsuiten, 533 tester bestått. Deretter bestod
9 målrettede historikktester, inkludert pakkekilde ved oppdatering. Windows-UI er visuelt kontrollert: alle fire felt har 0, svartak/beløpstak
er av, Talesvar har egen bryter og Apper har Cost (USD). PC-profilen er migrert
og /health svarer ok. Ingen betalte API-testkall er utført. Fysisk visning og
lyd på FIRE etter denne oppdateringen er ikke bekreftet i disse testene.

- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [Realtime mini](https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini)
- [GPT-Transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe)
- [Kostnadsoptimalisering](https://developers.openai.com/api/docs/guides/cost-optimization)
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Realtime svargrenser](https://developers.openai.com/api/reference/resources/realtime/client-events)
- [Speech API og utgående modeller](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)

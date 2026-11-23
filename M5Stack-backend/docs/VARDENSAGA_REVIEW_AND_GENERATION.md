# Vardensaga: årsak og ny arbeidsflyt for alle apper

Undersøkt 2026-11-23. Endringene gjelder M5Stack-backend/ og alle nye apper,
oppdateringer og reparasjoner. Ingen device-kode er endret i denne leveransen.

## Det som faktisk skjedde

Vardensaga 0.1.1, pakke build-821cd176a43445d7b657, fikk en fysisk rapport:
app callback budget exceeded i update, main.lua:117. Målt callback var
136083 us, etter 649 bilder. Den rapporterte kilden har SHA256
5dea161e6054e8f34cc5a984b14dcffaa85e09926e719e83a7cebfd6cc19c8a9.
Pakken er fortsatt sperret; ingen av endringene nedenfor friskmelder den.

Reparasjonsjobb build-eb73ef9dd86b423babbe brukte 15 genereringer og 12
kodekontroller før den tekniske 900-sekundersfristen. Registrert modellkostnad
var omtrent USD 0,054947. Fasehistorikken viser omtrent 291 s generering og
596 s testing/kodekontroll. Ingen av reparasjonskandidatene ble publisert.

Det var flere separate feil i arbeidsmåten:

1. Alle 15 nye kandidater hadde ANNEN SHA256 enn den fysisk feilende pakken.
   Flere kodekontroller hevdet likevel at det var samme kildehash/kandidat som
   var målt til 136083 us. Kontrollmodellen blandet tidligere enhetsbevis med
   ny kilde og krevde fysisk bevis den selv ikke kunne hente. Dette skapte
   omskriving uten mulighet til å tilfredsstille den feilaktige begrunnelsen.
2. Knapperegelen var for absolutt. Kontrollene avviste stadig fulle, endelige
   køer og fikk generatoren til å prøve 15, 128 og 256 plasser. En begrenset
   enhet kan ikke ta imot en uendelig strøm av trykk tapsfritt. Riktig krav er
   ordnet behandling av AKSEPTERTE handlinger, og synlig avvisning før en NY
   handling aksepteres når kapasiteten er brukt opp.
3. Noen svar inneholdt norsk bekreftelsestekst i main_lua. Tidligere tok neste
   forsøk alltid utgangspunkt i siste svar, også når det var ugyldig tekst.
   Det kastet bort bedre kildekode som allerede hadde bestått lokale tester.
4. Enkelte nye kodekontroller krevde nye detaljer/polering eller fant en annen
   feil uten at tidligere fungerende løsninger ble beholdt. Hele appen kunne
   bli skrevet om istedenfor at en konkret feil ble rettet målrettet.
5. De lokale budsjettmodellene er ikke faktiske ESP32-tidsmålinger. Den første
   PC-godkjenningen kunne derfor ikke utelukke den senere fysiske tidsfeilen.

## Endringene som håndheves av backend

- Backend beregner kandidatens SHA256 selv. source_identity skiller eksakt
  kandidat fra historiske native feilkilder og sier eksplisitt at ny kode
  ikke er fysisk verifisert. Rå historisk reparasjons-JSON flyttes ut av
  kontrollmodellens instruksjonsfelt. Etterfølgende kontrakter beholdes.
- Ved live-avvisning må hver konkret feil ha kandidatens kildehash og
  evidence_scope. Feil hash, manglende hash, påstått ny enhetsobservasjon
  uten faktisk observasjon, eller avvisning uten konkret feil gir én
  korrigert kodekontroll av SAMME kode. Ingen ny generering eller full lokal
  testsuite kjøres bare for å rette slik bevisforveksling.
- Hvis kontrollen fortsatt blander bevis, stoppes kodekontrollfasen med
  ai_review_evidence og en forklaring. Lokalt testet kode og samme jobb er
  bevart for Resume. Dette er ikke en penge-/token- eller rettingsgrense,
  og modellen får ikke bruke opp resten av tiden på vilkårlige omskrivinger.
- verification_notes rommer faktisk begrensning i bevis, for eksempel at
  kandidatens fysiske timing må testes. Manglende fysisk bekreftelse alene
  skal ikke oppdiktes som en kildefeil. Konkrete kodefeil blokkerer fortsatt.
- Kjent fysisk feilende eksakt kildehash blokkeres fortsatt programmatisk.
  Ny hash alene er heller ikke et funksjonsbevis: alle lokale profiler og
  en uavhengig kodekontroll må fremdeles bestås før en pakke leveres.
- RepairBaseline beholder den sterkeste testede kandidaten og dens konkrete
  kontrollfunn. Syntaksfeil/prosa kan ikke erstatte dette grunnlaget.
  Generering får primærfeil, grunnlagets hash, åpne funn og påminnelser om
  tidligere godkjente sjekkpunkter. Små målrettede rettelser er standard.
- Resume undersøker checksum-bundne review-/kildeartefakter og finner tilbake
  til en tidligere lokalt testet kandidat selv om siste svar var prosa.
  Historisk kodekontroll er bare utvalgsgrunnlag; ingen gammel godkjenning
  erstatter nye tester/kontroll. Manipulert kilde velges ikke.
- Ren retting av testplan kan beholde identisk Lua-kode. Stillstandsvakten
  sammenligner både kilde og testsekvenser, slik at nødvendig I/O-testretting
  ikke krever unødvendig kildeendring.
- Små validation-N.json/strategy-N.json gir sporbarhet uten rå tegningsspor
  eller ny konfigurasjonskilde. Kandidatens kilde, forsøk og kostnader bevares.

## Permanente instrukser fra første forsøk

Den bekreftede funksjonslisten er fast. Ikke legg til nye funksjoner eller
omdesign under feilretting uten et nytt brukerønske. Behold tidligere rettede
feil og godkjente egenskaper. Kun kjørbar Lua i kodefeltet; byggeautorisasjon
er allerede sjekket av backend. Installering og Run har fortsatt egne porter.

Render hele den synlige scenen hver oppdatering, men bygg tekst/menu-/story-
rader når tilstanden endrer seg. Sikt mot høyst 12 display-kall og 160 tekstbyte
per bilde for margin under de eksisterende harde vertsgrensene. Dette er
veiledende ytelsesmål, ikke målt native tid. Bruk liten, begrenset knappkø eller
umiddelbar behandling; håndter full kø synlig. Poll aktive lydjobber med en
passende timer og gjør ingen tjenestekall når de er inaktive. Send bare endrede
RGB-farger. Ikke innfør blanke bilder eller fjern avtalte funksjoner for å
bestå en test. Modellvalg og brukerens deaktiverte kostnadstak er uendret.

## Firmware og fysisk verifikasjon

Device-agentens BACKEND_HANDOFF.md ved cc46c69 opplyser at RGB er bufret og
flushes utenfor Lua, og at callbackfase/tid rapporteres i eksisterende
DeviceDiagnostics. Instruksjonene skiller nå eldre synkrone adaptere fra nyere
bufring, mens det konservative kompatibilitetsbudsjettet beholdes.

Vardensaga var ikke fysisk tilgjengelig i device-agentens siste verifikasjon.
Det gjenstår å prøve korrigert kode på faktisk firmware og måle samme profil.
Backend kan ikke bevise native timing med en PC-modell eller love at enhver
AI-generert app er feilfri. Den skal redusere feil, avvise konkrete feil,
bevare brukbar kode og bruke reelle tilbakemeldinger uten å blande versjoner.

Offisielt grunnlag for adskilte roller/kontekst og målbare regresjoner:
[Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering),
[Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
Ingen betalte AI-evalueringer er kjørt for denne backend-endringen.


## Verifikasjon av backend-endringen

Hele offline-suiten bestod med 552 tester. Deretter bestod 51 målrettede
kontroller av kildebevis, testplanretting, beholdt kode, modellmåling, kontroll-
skjema og status/UX. Siste små baseline-endringer er kontrollert separat.
Testene bruker lokale mocks; ingen betalte modellkall eller fysisk appstart
ble utført. Testene dekker blant annet at kjent krasjende hash fortsatt sperres,
at en historisk feil ikke tilskrives ny kilde, at samme kode kontrolleres igjen
ved beviskonflikt, at en vedvarende konflikt ikke gir pakke, at Resume kan
kontrollere beholdt kode uten ny generering, og at prosa ikke erstatter et
bedre grunnlag. Uendret kilde med korrigert testsekvens får passere ny test.

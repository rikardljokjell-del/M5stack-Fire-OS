# Device-agent: «Fix error» fra APP ERROR, 2026-11-23

Backend-støtte er implementert. Endre bare `M5Stack-device/`. Les også
[IMU-ferskhet](DEVICE_IMU_FRESHNESS_HANDOFF.md) og
[native callback/RGB](DEVICE_NATIVE_CALLBACK_HANDOFF.md); firmwaretiltakene
der er ennå ikke utført ifølge brukeren. Ikke anta at en ny Lua-pakke alene
retter disse firmwarefeilene.

## Brukerflyt

1. APP ERROR viser appnavn/versjon, kort feil og **Fix error**. Behold hele
   feilidentiteten når runtime stoppes og UI/state ryddes.
2. Ett kort knappetrykk på Fix starter forberedelse og automatisk bekreftelse
   av reparasjonsforslaget. Brukeren skal ikke gå til AI Developer, forklare
   feilen, velge app på nytt eller trykke BUILD enda en gang.
3. Samme side viser kø/arbeid/testing/fremdrift. Ingen blokkering av OS-løkken,
   venteløkke, lang tekststrøm eller ekstra framebuffer.
4. Når klar, vis **Kjør rettet app** og versjon. Dette bruker normal nedlasting/
   installasjon, korrekt installasjonskvittering og eksplisitt run_confirm for
   DEN NYE package-ID-en. UI kan la dette ene brukertrykket autorisere både
   installasjon og etterfølgende kjøring. Ikke send run_confirm før riktig
   install_result=ok; ikke kjør automatisk fordi reparasjonen ble ferdig.
5. Home/Back kan lukke feilsiden når som helst. Reparasjonen fortsetter på PC.
   Lukk UI/subscription, ikke kanseller backendjobben. Pakken kan hentes i
   eksisterende App Manager når klar. Status kan gjenhentes etter reconnect.
6. Ved backend offline: behold et lite feil-snapshot og marker venter på
   tilkobling. Ikke send nye bekreftelser i loop. Resend samme event-ID ved
   mistet ACK; hent status før nytt arbeid opprettes.

## Identitet skal normalt være automatisk

Ta et snapshot ved faktisk appstart: app-ID/SD-mappe, manifestversjon,
package-ID, SHA256 av Lua-kilden, eventuell run-ID. Feilrapporten bruker dette
snapshotet, ikke gjeldende AI-samtale, global «sist valgte app», prosjektets
current-pointer eller en gammel installasjonsmapping.

Viktig funn: en senere vater-feil på linje105 rapporterte gammel package-ID
`build-0c153938345f40e4b9d3`, men source_bytes5062, mens den pakken har4904
kildebyte. Dette kan koble feilen til feil versjon. Backend lagrer nå slike
rapporter som identitetskonflikt, ber om inventar og sperrer ikke feil kildehash.

- Appen velges automatisk fra runtime-feilens snapshot.
- Hvis app-ID faktisk mangler, vis et appvalg som reserve. Bruk lokal
  installasjonsoversikt/manifest eller backendens paginerte app_list. Vis
  navn+versjon. Ikke gjett mellom ulike apper eller send tom appidentitet.
- Versjon og logg er valgfrie når appen er kjent. Backend bruker lagret kilde,
  versjonshistorikk, inventar og feilhistorikk; den ber ikke brukeren debugge.
- Kildehash har prioritet over en foreldet package-ID. Ukjent kildehash eller
  manglende kildekode må vises ærlig; ikke hevde at en annen app ble reparert.
- Vis gjerne «kjørte0.1.1 / nyeste0.1.2». Backend baserer ny reparasjon på
  nyeste lagrede versjon, så eldre feilrapport ikke ruller tilbake nyere arbeid.

## Protokoll0.2, additive hendelser

### Bruk eksisterende SD-mappe `/logs` til små feil-snapshots

Brukeren bekrefter at `/logs` finnes og kan benyttes. Anbefalt implementasjon
for device-agenten er en avgrenset feilbuffer under `/logs/ai-developer/`:

- Inntil åtte roterende `error-0.json`…`error-7.json`, maks4KiB hver. Ikke
  overskriv eller rydd andre filer i `/logs`. Ingen voksende fritekstlogg.
- Ta snapshot i RAM ved feil, før appidentitet og runtime ryddes. Skriv én gang
  etter at Lua-callbacken har returnert og appen er stoppet, i OS-eid arbeid.
  Aldri SD-skriving per frame eller inne i den tidsbegrensede Lua-callbacken.
- Lagre schema_version, en stabil lokal error_id, opprinnelig boot-ID,
  app-ID, faktisk manifestversjon, package-ID, Lua-SHA256, eventuell run-ID,
  kort feiltekst og tilgjengelige typede diagnostics. Uptime er relativ til
  boot; ikke dikt opp klokkeslett. Legg til repair_id når backend returnerer den.
- Skriv via en begrenset midlertidig fil og rename; håndter avbrutt skriving,
  fullt/utkoblet SD og ugyldig JSON uten å kræsje feilsiden. RAM-snapshot og
  vanlig reparasjonsforespørsel fungerer fortsatt hvis lagring mislykkes.
- Etter omstart kan APP ERROR/historikk bruke siste gyldige snapshot for å
  identifisere appen automatisk. Hvis repair_id finnes, hent status først.
  En lagret logg skal ikke starte en betalt reparasjon uten brukerens Fix-trykk.
- Send eksisterende strukturerte app_repair_prepare-felt og diagnostics til
  backend. Det er ikke implementert et generelt filopplastingsendepunkt for
  `/logs`; ikke send hele JSON-filen som et nytt/ukjent felt. Privat metadata
  fra filen som ikke finnes i protokollskjemaet beholdes lokalt.
- Bruk gjeldende session_id/boot_id i nye transportmeldinger etter omstart.
  Ikke gjenbruk en gammel event-ID med endret envelope/payload. Samme event-ID
  brukes bare ved nøyaktig replay av samme melding; jobbstatus og backendens
  app-/jobb-deduplisering håndterer resten.
- Ingen API-nøkler, device-/admin-token, lydopptak, Wi-Fi-passord, appkilde
  eller full samtalehistorikk i loggen. Ikke eksponer `/logs` som åpen filserver.

Dette er firmwarearbeid som gjenstår. Backend har fortsatt ikke skrevet til
SD-kortet eller endret device-koden. Lagring av rapporten er støtte for
feilgjenoppretting, ikke dokumentasjon på at appen er reparert.

Vanlig envelope beholdes: `type=device_event`, protocol_version, device_id,
session_id, boot_id, unik event_id. Bruk samme autentiserte reverse/WebSocket-
transport som eksisterende meldinger. Ingen ny tjeneste, token eller API-nøkkel.

Ved brukertrykket **Fix error**, send eksempel:

```json
{
  "type":"device_event", "protocol_version":"0.2",
  "device_id":"m5stack-fire-01", "session_id":"session-example",
  "boot_id":"boot-example", "event_id":"evt-fix-prepare-1",
  "event":"app_repair_prepare", "app_id":"digitalt-vater",
  "package_id":"build-f1aa7e3f05b341c89686", "app_version":"0.1.2",
  "sha256":"<64 lowercase hex of main.lua>",
  "error_code":"runtime_error", "message":"Lua update: main.lua:105: app callback budget exceeded",
  "diagnostics":{"phase":"update","callback_us":135053,"source_bytes":5062,"frames":1335}
}
```

`sha256` er en plassholder i eksemplet, ikke en gyldig hash. Kun app_id er
obligatorisk for prepare, utover envelope. Utelat ukjente felt fremfor å dikte
opp verdier. run_id og button/action kan oppgis som faktisk kjørekontekst/siste
knappetrykk. message≤240 tegn; eksisterende strengt typede diagnostics-felt
beholdes. Ikke last opp rå loggfil, lyd eller skjermbilder; backend har kilden.

Backend sender `type=app_repair_status` med repair_id, app_id, project_id,
navn, status, phase, progress0..100 og kort message. Første status er normalt
`awaiting_confirmation`, med proposal_id og expires_at. Den samme brukerens
Fix-handling bekreftes deretter automatisk i protokollen:

```json
{
  "type":"device_event", "protocol_version":"0.2",
  "device_id":"m5stack-fire-01", "session_id":"session-example",
  "boot_id":"boot-example", "event_id":"evt-fix-confirm-1",
  "event":"build_confirm", "repair_id":"repair-returned-id",
  "proposal_id":"proposal-returned-id"
}
```

Ingen ekstra brukerbekreftelse i UI. Dette bevarer eksplisitt build_confirm
med riktig proposal-ID. Prepare alene starter ikke en betalt modelljobb.
Hvis prepare i stedet returnerer queued/building/ready, følg eksisterende jobb;
ikke lag en ny. Gjentatte klikk skal ikke starte parallelle reparasjoner.

Statusverdier: awaiting_confirmation, queued, building, ready, failed,
interrupted, unavailable (pakken er slettet/sperret eller ikke kompatibel).
Fremdriftsfasene følger byggeren: preparing/generating/validating/
compiling/testing/packaging/ready. `compiling` betyr Lua-kontroll, aldri firmware.
Ved ready følger package_id og version. Vis ikke «fysisk verifisert» fra ready.
Ved failed vis kort feil og Prøv igjen; ingen utestet pakke er levert. Ved
interrupted har backend startet på nytt; ny eksplisitt Fix-handling kreves.

Gjenhent uten ny modelljobb:

```json
{"event":"app_repair_status","repair_id":"repair-returned-id"}
```

Legg på normal envelope. Alternativt app_id når repair_id ikke er kjent.
Backend sender også siste opptil fire reparasjonsstatuser etter session_snapshot
ved reconnect. Korreler på repair_id/app_id; ikke la en annen apps status ta
over feilsiden. Forslaget utløper etter300s; bekreftet arbeid utløper ikke da.

## Klar pakke og normal App Manager

Når brukeren velger Kjør, send eksisterende app_download med ready.package_id.
Hent ZIP, verifiser SHA256, installer atomisk og send korrekt
device_install_result. Først da send eksisterende run_confirm med ny package-ID.
run_request/run-ID/app_started/app_healthy gjelder fortsatt. Ikke gjenbruk en
gammel run-ID. Hvis en tidligere styrt kjøring finnes, send korrekt app_failed/
app_stopped før ny installasjon/start; ikke la backend stå med en aktiv kjøring.

## Test som device-agent skal utføre

- Feil fra både Apps og AI Developer velger faktisk app/versjon automatisk.
- Fix uten logg reparerer kjent app, ingen forespørsel om å finne logger.
- Foreldet package-ID + korrekt kildehash identifiserer riktig versjon.
- Dobbelttrykk, mistet ACK og reconnect oppretter kun én jobb.
- Lukk feilsiden under generering; ny versjon blir tilgjengelig i App Manager.
- Status/progress etter reconnect; ingen «session is busy» fra privat bygger.
- Kjør fra samme side bruker ny pakke, korrekt installkvittering og run_confirm.
- Gjentatt appfeil viser en ny reparerbar feilsituasjon uten evig autoloop.
- Home/Back og treknappsnavigasjon fungerer mens PC bygger.
- IMU-ferskhet, RGB-queue og callback-tid må fysisk verifiseres separat.

Backendtester dekker jobber, målvalg, kildehashkonflikt, deduplisering,
sessionlukking, gjenhenting, eierskap, utløpte forslag, restart og ingen
automatisk installasjon/kjøring. Fysisk feilsiden må fortsatt implementeres og
verifiseres av device-agenten. Backend har ikke endret firmware.

Verifisering i denne backendoppdateringen: full testkjøring403 bestått;
etterfølgende målrettet kjøring38 bestått, inkludert to nye tester for
WebSocket→reparasjon→nedlasting→installkvittering→run_confirm og feilende
reparasjon som frigjør byggeren. Disse er mock-/enhetsemulatortester, ikke
fysisk firmwaretest eller et nytt live AI-byggeforsøk på brukerens FIRE.

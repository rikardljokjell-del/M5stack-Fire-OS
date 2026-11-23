# Device-oppdrag: forklar byggfeil og gjenoppta mislykkede jobber

Backend-oppdrag 23. november 2026. Endre firmware hos device-agenten;
backend-agenten endrer bare `M5Stack-backend/`. Ingen flashing er utført her.
Dette beskriver backend-kontrakten som leveres sammen med oppdraget.

Nyeste samlede instruks: [DEVICE_BUILD_CONTINUATION_HANDOFF.md](DEVICE_BUILD_CONTINUATION_HANDOFF.md).
Den inkluderer samme jobb-ID ved gjenopptak, boot-status, ferdigpopup og avbryt/minimer feilretting.

## Hendelsen som avdekket problemet

`build-a5ab57cfbc8444cca5f5` gjaldt et RPG-spill. GPT-6 Luna brukte 8000
av 8000 outputtokens på intern resonnering og leverte ingen appkode. Ingen
Lua-pakke ble validert eller sendt. Rapportert forbruk var USD 0,00571425.
Dette var en uheldig backend-svargrense, ikke et FIRE-/SD-problem. Den gamle
teksten «OpenAI code response incomplete or refused» skilte ikke disse årsakene.

Backend endrer generering til lav resonnering og større, modelltilpasset
svarrom. Et avkuttet svar får maksimalt ett ekstra forsøk med mer plass,
Kostnads- og ekstra svartak er nå av som standard; 0 betyr ingen fast grense. Hver respons måles separat.
Avslag eller konto-/betalingsfeil utløser ikke slike gjentakelser.

## Påkrevd brukerflyt på FIRE

1. En byggfeil skal vise **årsaken**, ikke bare «Arbeidet mislyktes».
2. Behold jobben i **Resume**, også med status `failed`, etter at AI Developer
   lukkes, etter reconnect og etter reboot. Vis navn, feilårsak og jobb-ID.
3. Åpning av en mislykket jobb sender eksisterende `build_resume` med `build_id`.
   Dette gjenoppretter prosjekt, plan og dialog uten et nytt AI-kall.
4. Backend svarer med `build_resumed`, `state=awaiting_build_confirmation`,
   `can_retry=true`, en NY `proposal_id`, tidligere feil og `history_restored=true`.
   Et ordinært `build_proposal` følger for kompatibilitet med eksisterende UI.
5. Vis skjermen som en bevart utviklingsjobb, ikke som et nytt tomt prosjekt.
   Vis stoppårsak. Korte klikk: **A Prøv igjen**, **B Endre**, **C Tilbake**.
   A sender vanlig `build_confirm` med den nye gjeldende `proposal_id`.
   B lar brukeren beskrive endringen gjennom eksisterende dialogflyt.
   C lukker bare visningen. Ingen jobb eller plan slettes.
6. Etter bekreftelse fortsetter SAMME build_id. Følg samme jobb i fremdrift,
   bakgrunn, Resume og varsling. resume_count øker; forsøk og kostnader samles.
   Den gamle feilen bevares i run_history og ryddes fra aktiv feilvisning.
7. En ferdig jobb følger vanlig installasjonskvittering og eksplisitt RUN.
   Resume eller feilretting skal ikke omgå install-/run-kontrakten.

## Felt som backend leverer

`build_jobs.jobs[]` / `build_job_status` for feil:

```json
{
  "build_id": "build-example",
  "project_id": "app-example",
  "status": "failed",
  "phase": "failed",
  "progress": 0,
  "message": "AI-svaret ble avkuttet",
  "error_code": "ai_output_limit",
  "error_status": "AI-svaret ble avkuttet",
  "diagnostic_message": "AI brukte alle 8000 svartokens på intern resonnering og returnerte ingen appkode. Planen er bevart; velg Resume.",
  "retryable": true,
  "can_open": true,
  "can_resume": true,
  "status_text_version": "fire-status-text-v1"
}
```

`build_resumed` ved feil har i tillegg `state`, `proposal_id`, `can_retry`,
`history_restored` og den opprinnelige jobbidentiteten. `package_id=null`:
det finnes ingen kjørbar pakke ennå. Feilinformasjon kan også komme på
`build_progress` og `error`. Meldingen er allerede en komplett norsk statuslinje.

Backend annonserer `failed_build_resume_v1` i `backend_features`. Eksisterende
events brukes; ikke finn på et firmware-spesifikt retry-endepunkt.

## Visning av feil og detaljer

- Statuslinjen bruker `message`/`error_status`, maks 28 UTF-8-byte. Behold æøå,
  og bruk eksisterende måling av pikselbredde. Ikke vis rå engelske API-feil.
- Eksempler: `AI-svaret ble avkuttet`, `AI avslo forespørselen`,
  `Kostnadsgrensen er nådd`, `Kontroller API-kontoen`, `Appen bestod ikke testen`.
- Vis `diagnostic_message` som eget lesbart detaljfelt ved åpning av feilen,
  med linjebryting/rulling ved behov. Dette er ikke den øverste statuslinjen.
  Backend begrenser device-detaljer til 240 tegn; PC-en viser mer informasjon.
- Ikke erstatt en feilårsak med en generell IDLE-tekst når en påfølgende
  `state`/`event_ack` ankommer. Ikke kall AI-talesvar for å lese tekniske feil.
- «Retryable» betyr at konteksten kan hentes og forsøket bekreftes på nytt.
  Det lover ikke at manglende kreditt, hardware eller nett er blitt reparert.
- Ikke skjul Resume bare fordi `status=failed` eller `package_id` mangler.
  `can_resume=true` / `can_open=true` er nok for å vise åpnehandlingen.

## Konkrete firmwarefunn ved kodegjennomgang

I `fire_os.cpp` behandler `handleBackgroundBuildMessage` (omtrent linje 6180)
`build_progress`, `build_job_status` og `build_resumed` i samme gren. `failed`
setter workflow til 0 og resten tolkes som aktiv bygging. Utvid dette:

- `build_resumed` med `state=awaiting_build_confirmation` må vise bekreftelse,
  aldri settes til aktiv bakgrunnsbygging. Bruk den NYE proposal-ID-en.
- Les og bevar `error_code`, `error_status`, `diagnostic_message`, `can_resume`
  og `can_retry`. Rene status- og ACK-meldinger skal ikke nullstille dem.
- `build_jobs` leser i dag bare ID/navn/status. Ta også med kort feiltekst og
  gjenopptakbarhet i den begrensede jobbmodellen.
- Eksisterende JSON-uttrekk med første `{`/`}` er sårbart for objekter og
  klammeparenteser inne i strenger. Parse strukturen riktig eller bruk en
  avgrenset strengbevisst parser; test nested `progress` og escaped quotes.
- Håndter dupliserte og forsinkede events etter reconnect med session/boot,
  jobb-ID og proposal-ID. Gammelt `failed` må ikke overstyre et nytt retry-bygg.
- Begrens tekstbuffere og antall jobber som før; ikke lagre kildekode eller
  modellens resonnering på FIRE. Ingen API-nøkler eller andre enheters data.

## Akseptansetester hos device-agenten

- Simulert tokenavkutt viser riktig norsk årsak, ikke generisk «mislyktes».
- Mislykket ny app uten pakke kan åpnes fra Resume etter reboot/reconnect.
- Åpning av Resume utløser ingen betalt generering. A med gjeldende proposal-ID
  fortsetter samme jobb én gang. Dobbelklikk/replay starter ikke to.
- Dialog, samme prosjekt, appvalg og manuelle tillegg beholdes ved Resume.
- B Endre fungerer før nytt forsøk. C Tilbake beholder jobben.
- Kostnads-/konto-/nettfeil vises med årsak og kan åpnes for justering.
- Ny jobb-ID følges, gammel feilmelding vinner ikke over ny fremdrift.
- Reconnect og bakgrunnsbygg fungerer som før. Godkjent pakke installeres via
  normal kvittering; appen starter bare med eksplisitt RUN.
- Test norsk æøå, maks tekstbredde, lange forklaringer, anførselstegn og `{}`.

Rapporter separat hva som bare er bygget/simulert og hva som er fysisk prøvd.

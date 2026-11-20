# FIRE Developer protocol

**Firmware integration contract: [PROTOCOL-v0.2.md](PROTOCOL-v0.2.md).**
Version 0.2 separates simulation from device installation/running, uses scoped
device tokens, durable event IDs and correlated receipts. Implement that version
for physical devices. The old 0.1 PC-client reference follows below; its `current`
semantics are superseded by 0.2. Backend implementation and verification are in progress.

## Legacy PC protocol v0.1

Endpoint: `ws://PC-IP:8765/ws/device`. Samme forbindelse brukes gjennom dialog,
bekreftelser og byggestatus. Ved aktivt backend-token brukes Authorization-header.
JSON-meldinger er maksimalt 8192 UTF-8-bytes; tekstfelt maks 4000 tegn.
Ukjente felter og hendelsestyper avvises. Ingen binær lydtransport i v0.1.

## Klient → backend

Start sesjon først:

```json
{"type":"device_event","device_id":"m5stack-fire-01","event":"session_start"}
```

`project_id` kan settes ved start for videre arbeid i et eksisterende prosjekt.
En annen aktiv sesjon med samme `device_id` avvises. Alle senere meldinger må
bruke samme enhets-ID som sesjonen. ID-er er små bokstaver/tall, `_` eller `-`,
1–64 tegn, med bokstav/tall først.

```json
{"type":"device_event","device_id":"m5stack-fire-01","event":"text","text":"Lag en animasjon med en sirkel som beveger seg."}
```

```json
{"type":"device_event","device_id":"m5stack-fire-01","event":"button","button":"B","action":"pressed"}
```

Knapper A/B/C og pressed/released/long_pressed anerkjennes, men starter aldri
bygg eller kjøring. Eksplisitte bekreftelser er egne hendelser med serverens ID:

```json
{"type":"device_event","device_id":"m5stack-fire-01","event":"build_confirm","proposal_id":"proposal-..."}
```

```json
{"type":"device_event","device_id":"m5stack-fire-01","event":"run_confirm","package_id":"build-..."}
```

`proposal_id` konsumeres ved byggestart. Ny brukertekst gjør tidligere forslag
ugyldige. Feil ID, duplikatbekreftelse og feil state gir error, ikke et nytt bygg.
`run_confirm` krever pakke fra den samme sesjonen og prosjektet, en vellykket
build og nye integritetskontroller. Modellen får ingen metode for bekreftelse.

Andre hendelser:

- `ping` → `pong` med gjeldende sesjonsstatus.
- `session_stop` → avbryter dialog/bygg/test, lukker Realtime og forkaster forslag.
- `app_failed` med `package_id` → fremtidig device-feilrapport; validerer at ID
  samsvarer med prosjektets current og ruller tilbake metadata. Starter ingenting.
- `app_stopped` er reservert; avvises i PC-prototypen fordi ingen device-runtime
  er tilkoblet. Bruk session_stop.

## Backend → klient

`session_started`: session_id, device_id, project_id, state, mode og eventuelle
proposal_id/package_id/build_id. `mode` er alltid eksplisitt `mock` eller `openai`.
Sesjonsmeldinger har stigende `seq` og `session_id`. Dette gir rekkefølge i én
forbindelse; det er ikke en vedvarende meldingskø eller replay-garanti.

```json
{"type":"ui_event","event":"assistant_state","state":"listening","session_id":"session-...","seq":2}
```

```json
{"type":"assistant_message","text":"Jeg lager en grønn sirkel som beveger seg. Bekreft bygging.","session_id":"session-...","seq":4}
```

```json
{"type":"build_proposal","proposal_id":"proposal-...","project_id":"app-...","summary":"Grønn sirkel på svart bakgrunn","session_id":"session-...","seq":6}
```

```json
{"type":"build_progress","build_id":"build-...","phase":"compiling","progress":50,"message":"Kontrollerer Lua 5.4; ingen firmwarekompilering","eta_seconds":null,"session_id":"session-...","seq":10}
```

`eta_seconds` er null når varigheten er ukjent. Progress er fasebasert, ikke et
målt compiler-estimat. Heartbeat gjentar siste status hvert tiende sekund under
lange operasjoner. Faser: preparing, generating, validating, compiling, testing,
packaging, ready, failed. uploading er reservert og sendes først når faktisk
enhetstransport er implementert; backend påstår ikke at en pakke er lastet til FIRE.

`package_ready`: package_id, fullstendig manifest, archive_sha256 og relativ
download_url. HTTP-nedlasting krever samme backend-token.

`run_result`: package_id, target=`pc_simulation`, status=`completed`, antall frames
og API-operasjoner. Ingen melding om faktisk FIRE-kjøring sendes.

`rollback`: stopped_package_id, current og forklaring.

`error`: code og kort message. Ingen nøkler, rå OpenAI-feilobjekter eller
forespørselsheadere inkluderes. Full lokal logg er begrenset og hemmeligheter
redigeres. `session_stopped` avslutter sesjonen.

## State-maskin og gjenoppkobling

```text
idle -> listening -> processing
processing -> clarification_needed -> processing
processing -> awaiting_build_confirmation
awaiting_build_confirmation --build_confirm--> building
building <-> testing
building/testing -> ready_to_run
ready_to_run --run_confirm--> running -> ready_to_run
operasjonsfeil -> failed
failed -> processing (ny bestilling)
alle aktive tilstander --session_stop/disconnect--> idle
```

Alle nettverks-/konto-/kodefeil stopper aktuell operasjon. Ingen installasjon eller
automatisk kjøring følger. Én byggesluse gjelder hele backend, så to prosjekter
bygger ikke samtidig. Backend fortsetter å ta imot ping og stopp mens OpenAI
arbeider. Et frakoblet WS stopper sin sesjon, inkludert pågående bygg. Ferdige
prosjekter/pakker beholdes. Ny tilkobling starter en ny sesjon med ferske ID-er
og nye bekreftelser; gamle godkjenninger gjenopptas ikke automatisk.

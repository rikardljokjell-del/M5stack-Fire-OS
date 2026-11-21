# FIRE OS – neste steg etter reverse TCP

Dette er den felles arbeidsplanen for `M5Stack-device/` og
`M5Stack-backend/`. Planen gjelder etter at en fysisk FIRE har etablert
reverse-forbindelse til Windows-backend. Firmware og backend skal fortsatt
utvikles separat, men mot samme transport- og protokollkontrakt.

## Nåværende status

- Device reverse TCP er implementert på port `8766`.
- Autentisering bruker lagret `device_id` og device-token.
- Maksimalt fire samtidige reverse-forbindelser støttes.
- WebSocket-kontroll, WAV-opplasting og Lua-pakkenedlasting kan velge reverse
  transport med direkte TCP som fallback.
- Protokoll 0.2, Lua API, SHA256, `build_confirm` og `run_confirm` er beholdt.
- Firmware er bygget, flashet og bootet normalt.
- Brukeren har rapportert at backend nå er tilkoblet.
- Full fysisk reverse smoke-test er ikke ferdig verifisert ennå.

## Fase 1 – fysisk transport-smoketest

### Device-agent

1. Bekreft at FIRE viser `Backend connected (Reverse TCP)`.
2. Kontroller at vanlig meny, knapper og BLE fortsatt er responsive mens
   reverse-listeneren er aktiv.
3. Test reconnect etter at Windows-broen stoppes og startes på nytt.
4. Test feil token, feil device-ID, ugyldig JSON, melding over 1024 byte og
   autentiseringstimeout.
5. Kontroller at direkte backendtilkobling fortsatt fungerer når reverse-broen
   ikke er tilgjengelig.

### Backend-agent

1. Åpne en reverse-forbindelse til FIRE på port `8766`.
2. Send nøyaktig `reverse_open`-linje og vent på `reverse_ready`.
3. Koble reverse WebSocket-forbindelsen til lokal backend på port `8765`.
4. Logg transporttype og feilkode, men aldri device-token eller API-nøkkel.
5. Bruk maksimalt fire forbindelser: én kontrollforbindelse og opptil tre
   samtidige HTTP-operasjoner.

### Godkjenningskriterium

Enheten må holde UI og knappene responsive, vise reverse-status, og kunne
opprette kontrollforbindelsen på nytt uten dobbel `session_start`.

## Fase 2 – kontrollflyt og appkjøring

Test hele flyten med en liten kjent Lua-app:

1. `session_start` og capabilities.
2. Tekstbestilling fra FIRE.
3. AI-forslag og `build_proposal`.
4. Eksplisitt `build_confirm` med korrekt `proposal_id`.
5. `build_progress` og `package_ready`.
6. `install_request` via separat reverse HTTP-forbindelse.
7. Lokal størrelse-, manifest- og SHA256-validering på FIRE.
8. `device_install_result` etter faktisk installasjon.
9. Eksplisitt `run_confirm` med korrekt `package_id`.
10. `run_request`, `app_started` og `app_healthy` etter faktisk appstart.

PC-simulering skal fortsatt merkes `physical_verified=false`. Backend skal ikke
sette installert/kjørende/current-status før tilsvarende device-kvittering er
mottatt.

## Fase 3 – lyd over reverse transport

### Device-agent

- Test push-to-talk med PCM16 mono 16 kHz.
- Send `listen_start` og `listen_stop` over WebSocket.
- Last opp WAV på en separat reverse HTTP-forbindelse.
- Hold opptak innenfor eksisterende buffer- og tidsgrenser.
- Vis LISTEN/THINK/TALK basert på faktiske backend-hendelser.

### Backend-agent

- Kontroller WAV-format, maksimumsstørrelse og timeout.
- Returner transkripsjon med korrekt `turn_id`.
- Send talesvar kun når device annonserer og fysisk støtter audio output.
- Hold `audio_output=false` til playback er fysisk verifisert.
- Test brudd under opplasting og sikre at forbindelsen frigjøres til poolen.

## Fase 4 – feil, reconnect og rollback

Test minst følgende:

- Reverse-forbindelse brytes under WebSocket-handshake.
- Reverse-forbindelse brytes under HTTP-nedlasting.
- Reverse-forbindelse brytes under WAV-opplasting.
- Wi-Fi forsvinner og kommer tilbake.
- Backend restartes midt i bygging, installasjon og kjøring.
- Gammel `proposal_id`, `package_id`, `run_id` eller duplikatmelding.
- Korruptert ZIP, feil størrelse, feil SHA256 og ugyldig manifest.
- Mislykket Lua-app og trygg retur til FIRE OS.
- Direkte transport som fallback uten at samme operasjon bytter transport
  halvveis.

For hver feil skal systemet rydde sockets, stoppe midlertidige filer, beholde
forrige fungerende appversjon og vise en kort brukerforståelig status.

## Fase 5 – regresjon og levering

### Device-regresjon

- Normal boot og safe boot med A+B+C.
- Hovedmeny, Settings, Quick Settings og alle Back/Home-regler.
- Wi-Fi Auto/On/Off og vanlig direkte backendforbindelse.
- BLE, SD/File Explorer, tidssynk, lyd, RGB og IMU.
- Responsivitet mens reverse-listeneren er aktiv.
- Flash- og RAM-forbruk sammenlignet med stabil baseline.

### Backend-regresjon

- Eksisterende pytest-, mock- og emulatorflyt.
- Reverse auth med riktige og feil credentials.
- Delvise auth-linjer og byte etter newline.
- Poolgrense på fire forbindelser.
- Idempotens og reconnect.
- Fysisk status separert fra simulatorstatus.
- Ingen hemmeligheter i logger, pakker eller Git.

## Leveringsrekkefølge

1. Backend-agenten ferdigstiller reverse-broen og logger transportstatus.
2. Device og backend gjennomfører Fase 1 sammen på fysisk FIRE.
3. Fase 2 gjennomføres med en liten kjent Lua-testapp.
4. Deretter testes lyd, feil/reconnect og rollback.
5. Først etter fysisk verifikasjon oppdateres leveransestatus til
   `physical_verified=true` for de konkrete funksjonene.

## Handoff-regler

- Device-agenten endrer kun `M5Stack-device/`.
- Backend-agenten endrer kun `M5Stack-backend/`.
- Endringer i transportformat må dokumenteres i device-handoff og backendens
  protokolldokument før de implementeres på nytt.
- Ingen agent skal rapportere fullført fysisk integrasjon basert på build,
  mock eller emulator alene.

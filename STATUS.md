# Status – FIRE OS AI Developer backend 0.2

Backend videreutvikles kun i `M5Stack-backend/`. Firmware i `M5Stack-device/`
eies av den separate firmwareagenten. Backendarbeidet har ikke endret, bygget
eller flashet enhetskoden. Firmwarekilden er gjennomgått i skrivebeskyttet modus.

## Implementert

- Windows-program med skrivebordsikon, start/stopp, sikker nøkkellagring,
  API-test, modeller, nettverksoppsett, enhetsstatus og tekst til tilkoblet FIRE.
  Se [Windows-veiledning](M5Stack-backend/docs/WINDOWS_APP.md).

- Protokoll 0.2 og JSON-skjemaer publisert tidlig for firmwareintegrasjon.
- Direkte OpenAI Realtime/Responses, varig samtalehistorikk og prosjektkode ved endringer.
- Avgrenset WAV-opplasting, transkripsjon, PCM-talesvar, avbrudd og opprydding.
- Egne enhetstokener, eierskapskontroll og varige operasjons-/hendelses-ID-er.
- Testet pakke, installert pakke og faktisk rapportert appstart skilles.
- Korrelert installasjon/start/healthy/stopp/rollback og historikk per enhet/prosjekt.
- Lua-kapabiliteter, minnegrenser, ZIP-kontroller og tidligere fungerende versjoner beholdes.
- Mock-/PC-klient og enhetsemulator; én lokal backendprosess uten database/Docker.
- Tilpasset BACKEND_HANDOFF.md og enhetskilde 069ea09e: faktisk sesjonsprofil,
  gyldig oppstart uten lyd, tydelig tekststatus og uavhengige lydflagg.
- Samme-boot-gjenoppkobling uten resume-hint bevarer samtale og forslag.
- Oppdatert maskinvarekontekst og Lua-kontroll: heltall, konturer, uniform RGB,
  OS-uptime og bare pressed-callback. PC-støtte gir ingen ekstra enhetstjenester.

## Verifisert

- **108 tester bestått**, inkludert handoff, Windows-konfigurasjon, sikker
  nøkkellagring, lokal tilgangskontroll, oppstart/stopp/restart og portkonflikt.
  `pip check` uten feil.
- **4/4 PC-smoke-flyter** mot faktisk lokal server.
- **5/5 enhetsemulerte flyter**, inkludert syntetisk lydtransport og kvitteringer.
- **4/4 flyter mot den pakkede Windows-exe-en**, med native lydflagg false,
  tekst fra desktop, pakket Lua-worker og korrelerte kvitteringer. Ingen ekte FIRE.
- Windows-program og skrivebordsikon er opprettet lokalt. OpenAI-nøkkel kan
  legges inn i programmet. Windows kan be om nettverkstilgang/administrator-
  godkjenning; denne dialogen håndteres av brukeren.
- Windows Application Control blokkerte siste usignerte exe-pakke. Aktivt
  skrivebordsikon bruker installert pythonw.exe og samme GUI uten terminal.
  Ingen sikkerhetsinnstillinger er endret for å kjøre usignert program.
- Firmwaremappen skal være identisk med GitHub-basen ved backendpublisering.

## Gjenstår før ferdig fysisk løsning

1. Sette OpenAI-nøkkel på PC og verifisere faktisk modell-/kontotilgang, norsk tale og kodegenerering. Nøkkelen er fortsatt ikke satt; live-kontroll rapporterer not_run.
2. Enhetskilden har nå protokollklient, Lua-runtime, OS-adaptere og SD-pakkehåndtering. Kildegjennomgangen fant gjenstående feil i Lua-kallrekkefølge, ZIP-parser, HTTP-headerlesing, ressursgrenser og versjonsaktivering; se handoff-oppfølgingen.
3. Teste hele flyten på en fysisk M5Stack FIRE, inkludert lyd, minne, avbrudd, appstart og rollback.

Mock-transkripsjon/testtone og enhetsemulering er ikke ekte OpenAI eller fysisk
integrasjon. Nyeste gjennomgåtte kilde df06c65 har I2S/WAV-opplasting og annonserer
audio_input=true/audio_output=false. Mikrofonflyten må testes fysisk; avspilling
og full stopp-/rollbackflyt må ferdigstilles og testes på fysisk FIRE.
AI-genererte Lua-apper bruker en separat kontrakt og aldri OTA/flashing.

Start fra repo-roten: `.\M5Stack-backend\start.ps1 -Mock`.
Ingen automatisk Windows-oppstart er installert. Nettverkstilgang styres av
Windows-dialogen og programmets brannmurknapp med administratorgodkjenning.

Se [protokoll](M5Stack-backend/docs/PROTOCOL-v0.2.md),
[Lua-API](M5Stack-backend/docs/LUA_API.md),
[leveranserapport](M5Stack-backend/docs/DELIVERY.md) og
[drift](M5Stack-backend/docs/OPERATIONS.md). Konkrete kildefunn og backendtilpasninger:
[handoff-oppfølging](M5Stack-backend/docs/DEVICE_HANDOFF_RESPONSE.md).

# Device handover: fortsett bygg, boot-status og ferdigvarsel

Oppdatert 2026-11-23. Backend endres i M5Stack-backend/. Device-agenten eier
alle firmware-endringer; ingen device-filer er endret av backend-agenten.

## Bestillingen fra brukeren

- Prøv igjen skal fortsette SAMME jobb med samme build_id, plan, app, tidligere
  kode, kontrollfunn, dialog, manuelle tillegg, forsøk og samlede kostnader.
- Å legge AI Developer i bakgrunnen, lukke siden, miste Wi-Fi eller reboote
  FIRE skal ikke avbryte PC-byggingen. C Avbryt er eksplisitt stopp.
- Boot skal finne og stabilt vise pågående jobb når Backend/Backup sync er
  På eller Auto. Av skal fortsatt ikke opprette automatisk forbindelse.
- Resume øverst i AI Developer åpner eksisterende status eller ferdig pakke.
- Når appen er ferdig mens AI Developer er minimert: synlig popup med Åpne og
  Avbryt. Åpne fører til riktig app/installasjon og eksplisitt Run. Avbryt
  lukker bare varselet; appen forblir tilgjengelig i Resume/App Manager.
- Statuslinjen er én fullstendig norsk tekstlinje, maks 28 UTF-8-byte.
  Langtrykksnarveier skal ikke stå i korttrykksknappenes tekst.

## Konkrete funn i inspisert firmware

Undersøkt fire_os.cpp i GitHub-historikken ved backend-commit 7bcc3b7.
Linjer nedenfor er orientering, bruk funksjonsnavn hvis device-agentens HEAD
allerede har flyttet dem. Kontroller nyere kode før dere endrer noe.

1. updateBackend(), rundt 6450–6482: Auto setter backendBootAttempted_=true
   og backendBootPending_=false straks backendClient_->service() er kalt
   første gang. Dette beviser ikke at TCP/WebSocket, session_started og
   build_jobs er ferdige. Neste løkke i hovedmenyen kan få backendDemand=false
   og koble fra før jobblisten kommer. Lag en ikke-blokkerende boot-sync-
   tilstandsmaskin: Wi-Fi -> backend -> sessionReady -> request jobs -> mottatt
   jobbliste/ferdigvarsler. Hold etterspørselen til svar eller et kontrollert
   tidsavbrudd. Ved aktiv jobb fortsetter Auto å holde forbindelsen og
   reconnecte. Ikke gjør busy-wait eller blokker UI. På holder forbindelsen;
   Av (backendMode_==2) beholder nåværende av-policy.
2. requestBackgroundBuildJobs(): buildJobsRequested_ må bety faktisk pending
   forespørsel, med timeout/retry og nullstilling ved ny boot/WS-session.
   En sendt forespørsel uten svar må ikke låse senere oppdatering permanent.
3. handleBackgroundBuildMessage(), rundt 6296–6307: den generelle buildEvent-
   vakten forkaster ALLE jobbhendelser med annen ID enn aiBuildId_, også
   build_ready_notice. Dermed kan en ferdig jobb bli skjult hvis en annen
   jobb/eldre feil er valgt. Skill valgt detaljvisning fra global jobbcache og
   ferdigvarselkø. Valgt jobb skal beskytte sin egen detaljvisning, men ikke
   blokkere andre legitime jobber/varsler. Cache etter build_id, ikke appnavn.
4. Rundt 6308/6325: gamle feil ryddes hovedsakelig når build-ID endres eller
   nye ikke-tomme feilfelt kommer. Samme jobb gjenopptas nå med SAMME ID.
   På queued/building/ready må aiBuildErrorCode_, aiBuildErrorStatus_,
   aiBuildDiagnosticMessage_, aiAssistantText_ med gammel feil og relevante
   retry/resume-flagg ryddes også når build_id er lik. Behold forrige feil i
   historikk/diagnoser, men aldri som aktiv stoppmelding.
5. build_resumed.progress er et OBJEKT, mens build_progress.progress er et
   TALL. Nåværende jsonIntField(message,"progress") i den felles håndteringen
   kan nullstille fremdriften ved Resume. Backend gir derfor phase, status,
   progress_percent og resume_count øverst i build_resumed. Bruk disse, eller
   les det nestede progress-objektet. Ikke flatte ut objektet ved å anta 0.
6. drawMain(), rundt 9063–9086: identisk buildNoticeActive_-popup tegnes TO
   ganger og vanlig footer overstyrer modalens knappehint. Fjern duplikatet.
   Bruk en felles modal/overlay til sist i tegningen og konsistente knapphint.
   Nåværende onButton() avskjærer globalt når buildNoticeActive_; sørg for
   at en modal som tar knapper faktisk også er synlig på gjeldende skjerm.
7. Flere jobber kan finnes. Backend lister running/building før queued og
   sender samlet status deterministisk. Ikke la en køjobb eller historisk
   feil overskrive statusen til den faktisk kjørende jobben. Vis venting bare
   hvis den valgte jobben faktisk venter på en ANNEN aktiv jobb.

## Backend-kontrakt i denne leveransen

Ingen ny påkrevd eventtype eller autentisering. PROTOCOL-v0.2.md gjelder.
Backend-oppdateringen publiseres separat etter denne handoveren.

- build_resume på en failed jobb gjenoppretter planen og sender nytt proposal_id
  uten betalt AI-kall. Prøv igjen sender ett build_confirm med gjeldende ID.
- Bekreftelsen fortsetter samme build_id; ny prosjekt-/jobb-ID skal ikke kreves
  eller forventes av firmware. Historiske retry_of-barn fra eldre backend kan
  fortsatt finnes, men nye gjenopptak lager ikke slike barn.
- Forsøk nummereres videre. total/max_attempts kan være null: automatisk retting
  uten fast antall, så vis supplied message og eventuelt forsøksnummer.
- Samme forbrukte proposal_id kan ikke opprette ny køjobb ved dobbelttrykk eller
  et nytt event_id. Firmware bør også deaktivere retry-knappen mens ACK ventes.
- build_progress/build_job_status gir resume_count (0 første gjennomføring).
  Samme build_id kan gå failed -> queued -> building -> ready. Det er gyldig.
  Ignorer eldre resume_count for denne jobben; bruk ordinær sekvens/boot/session-
  kontroll innen samme gjennomføring. Gammelt failed skal ikke gjenåpne feilen.
- build_resumed gir progress-objekt pluss phase, status, progress_percent og
  resume_count. build_proposal beholder proposal_id/summary slik som før.
- Oppstart/reconnect/snapshots oppdager også aktive foreground-jobber; det er
  ikke nødvendig at Background-eventen rakk frem før en reboot.
- Ferdigvarsel holdes pending også hvis foregående Background-event manglet.
  build_ready_notice gjentas ved reconnect til build_notice_ack(open/dismiss).
  Dedup lokalt etter build_id og gjeldende gjennomføring. Send IKKE ACK bare
  fordi hendelsen ble mottatt, skjermen tegnet eller AI Developer åpnet.
- build_notice_ack(open) bruker eksisterende package_ready/install_request og
  receipts. Ikke auto-run uten run_confirm, og ikke gjenbruk kommandoer fra
  forrige boot. popupen kan vise Åpne; videre side viser Run når installert.
- PC Jobber får egen Cost-kolonne, inklusive historiske Astra-anslag. Firmware
  trenger ikke beregne eller vise kostnader for å implementere denne flyten.

## Testmatrise device-agenten må gjennomføre

1. På og Auto: start bygg -> bakgrunn -> reboot -> Wi-Fi -> backend -> samme
   jobb synlig stabilt midt mellom tid/dato, Resume peker på samme build_id.
2. Gjenta med reboot rett etter Build, før Background ble bekreftet.
3. Auto fra kald boot på hovedmenyen: ikke koble fra før jobbsvar. Mist ett
   jobbsvar/forbindelsen; pending timeout gir kontrollert retry uten skjermlås.
4. Av: ingen automatisk boot-sync. Slå senere til På/Auto: status hentes da.
5. Feilet jobb -> Prøv igjen -> queued/building med SAMME ID. Gamle feiltekster
   forsvinner; siste kode/kontrollfunn brukes av backend. Raske dobbelttrykk
   oppretter ikke to jobber. Gå ut/inn og reboot også i denne fasen.
6. To jobber: running vises først, queued som kø. Ferdigvarsel for A kan komme
   mens B er valgt og må fortsatt dukke opp uten å overskrive Bs detaljstatus.
7. Ferdig mens minimert: popupen er synlig, tegnes én gang og bruker korte
   Åpne/Avbryt-knapphint. Åpne installerer rett pakke, Run krever bekreftelse.
   Avbryt lukker kun varselet. Ingen installasjon/run skjer bare ved mottak.
8. Ferdig mens offline: varsel etter reconnect/reboot; gjentatte meldinger
   gir ikke flere popup-er eller installasjoner. Etter ACK er popupen borte,
   men pakken finnes i Resume/App Manager.
9. Nullable total, norske æøå, lange diagnoser og progress-objekt håndteres
   uten avklipping til ufullstendige setninger eller feil nullprogresjon.

Rapporter firmware-commit, build/flash-resultat og hvilke fysiske prøver som
faktisk er gjennomført i M5Stack-device/BACKEND_HANDOFF.md. Ikke kall hele
flyten fysisk verifisert før reboot, popup, Åpne/Run og Avbryt er prøvd på FIRE.


## Tillegg: feilretting fra App error (nyeste brukerkrav)

A korttrykk = Minimer, C korttrykk = Avbryt, også i feilrettingsvinduet.
Dette gjelder både kø før bygg-ID er tildelt og aktiv generering/testing.
Minimer må ikke sende cancel_turn/session-stop som kansellerer reparasjonsjobben.
Det er trygt å lukke bare UI/tilhørende samtaleside: Repairs-worker eies av PC.

- Behold repair_id, app_id, rapportert package_id/versjon og eventuell build_id
  i en global jobbcache. Ingen manuell omvalg av appen ved gjenåpning.
- Før build_id finnes, bruk app_repair_status og repair_id for status.
  Etterpå kan normal build_job_status brukes for topplinjen. Ikke mist
  repair_id når build_id kommer; to identiteter beskriver samme feilretting.
- Backend annonserer repair_cancel_v1 og støtter NY additiv device-event:
  {event:"app_repair_cancel", repair_id:"repair-...", ...vanlig v0.2-envelope}.
  Krever autentisert riktig device/session/boot/event_id. C sender denne,
  slik at den også fungerer mens reparasjonen står i kø UTEN build_id.
  Svaret er vanlig app_repair_status med status=cancelled, phase=cancelled,
  message="Byggingen ble avbrutt". Gjentakelse er idempotent. Et bygg som
  allerede rakk å publiseres svarer ready og beholder pakken; Cancel sletter
  aldri en testet app. Ikke send til eldre backend uten repair_cancel_v1.
- A lukker reparasjonsvinduet, viser hovedmenyen og beholder oppgaven.
  Vis kort status/fremdrift midt i topplinjen slik som vanlig appbygging.
- AI Developer får øverste inngang Resume feilretting hvis en reparasjon er
  aktiv/ferdig. Åpne samme reparasjonsvindu og hent app_repair_status med
  lagret repair_id. Ved mistet lokal ID etter reboot: session_snapshot sender
  eide reparasjoner, aktive først; byggkatalogen gir build_id/project_id.
  Ikke opprett ny prepare/confirm bare for å vise pågående feilretting.
- build_jobs har operation=repair og backend-utvidelsen repair_id for bygg som
  tilhører en feilretting. Bruk koblingen for å åpne riktig vindu fra Resume.
- Hvis Run ikke er mulig før installasjon, vis Åpne/Installer først og Run
  etter korrekt receipt. Ingen gammel boot-kommando kan gjenbrukes.

Tillegg til fysisk testmatrise: feil i kjent app -> Fix error -> A Minimer ->
progresjon i topplinjen -> Resume feilretting -> samme repair_id/status.
Gjenta med reboot i På/Auto og med C både før build_id, midt i generering,
under test og akkurat ved ferdigstilling. C stopper bare valgt reparasjon,
og ingen annen appjobb. Ferdigvarsel vises også for minimert feilretting.

## Tillegg: appliste

Backendens Windows-appliste er nå kronologisk, sist opprettet/oppdatert øverst.
Hvis firmware presenterer backendlisten: bevar samme forståelige nyest-først-
rekkefølge og én rad per app med versjonsvalg. Ikke sorter tilfeldige app-ID-er
eller appnavn som erstatning for tid. Backend leverer updated_at på PC-bibliotekets
versjonsrader; avtale ekstra devicekatalogfelt før dere krever dem i firmware.


## Supplerende backendfunn fra siste levende RPG-jobb

Et genereringsforsøk returnerte norsk bekreftelsestekst i main_lua i stedet
for Lua-kode: modellen ba om build_confirm etter at backend allerede hadde
validert denne. Lua-testen stoppet korrekt denne kandidaten. Backend skiller
nå uttrykkelig autorisert kodegenereringsfase fra brukerens dialogfase, og
kodefeltets skjema krever bare komplett Lua. Dette gir ingen ekstra rettighet
til installasjon eller kjøring: run_confirm er fortsatt separat og obligatorisk.
Firmware skal ikke be om ny bekreftelse for hvert automatisk rettingsforsøk.

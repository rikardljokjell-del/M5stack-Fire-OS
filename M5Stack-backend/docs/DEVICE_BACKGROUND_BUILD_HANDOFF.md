# Device handoff: bakgrunnsbygg, Resume og enkle statuser

Dato: 2026-11-23. Oppdrag fra bruker, samlet før backend-utrulling.
Arbeidsdeling: device-agent endrer bare M5Stack-device/. Backend-agent endrer bare M5Stack-backend/.
Backend-kontrakten nedenfor implementeres/testes parallelt; ikke anta støtte før backend annonserer `background_builds_v1` i `backend_features` ved session_started/session_snapshot.
Les også PROTOCOL-v0.2.md, DEVICE_FIX_ERROR_HANDOFF.md og DEVICE_FIX_ERROR_REVIEW.md. De konkrete reparasjons-/reconnect-funnene i review-dokumentet gjelder fortsatt.

## 1. Brukerflyt og eierskap

- Et eksplisitt bekreftet bygg (ny app, oppdatering eller feilretting) eies av backend-jobben, ikke av skjermen eller TCP-forbindelsen.
- FIRE-reboot, nettbrudd, Home/Back eller bruk av andre menyer skal ikke avbryte jobben. PC/backend må fortsette å kjøre. Backend-prosess som selv avsluttes kan ikke love videre generering; ferdige pakker og varsler beholdes på disk.
- Jobben bevarer riktig project_id, build_id, kilde/basisversjon, bekreftet plan og samtalekontekst. Ny oppstart får nye boot/session-ID-er; gamle install-/run-ID-er skal aldri brukes om igjen.
- Ikke send cancel når en skjerm lukkes. session_stop/forbindelsesbrudd frigjør enhetssessionen, men stopper ikke et bekreftet device-bygg.
- Fysisk kjørende app og backend-generering er forskjellige ting. Lokale apper kan brukes mens PC bygger. Ikke la en ferdig PC-jobb overta eller stoppe en annen app.

## 2. Tre knapper i AI Developer

Teksten under knappene gjelder KUN korte enkelttrykk. Fjern HOLD HOME/HOLD BACK og alle beskrivelser av langt trykk/dobbeltklikk fra disse tre tekstfeltene. OS-snarveier skal fremdeles fungere som vanlig.

Under bygging:
- A: `Bakgrunn`. Send build_background for riktig build_id og gå til hovedmenyen når ACK/status er mottatt. Ved nettbrudd kan navigasjonen gjennomføres lokalt; hent jobbstatus ved reconnect. Backend jobber videre.
- B: `Innst.` hvis korttrykket faktisk åpner hurtiginnstillinger. Dagens QUICK betyr hurtiginnstillinger, ikke raskere modell/bygg. Hvis kort B ikke gjør dette, fjern etiketten eller implementer overlayen. Ikke vis en funksjon som ikke finnes.
- C: `Avbryt`. Send build_cancel med riktig build_id; vent på korrelert ACK/build_cancelled. Dette avbryter selve jobben. Ikke bruk session_stop eller cancel_turn som byggavbrudd.

Forslag: A `Bygg`, B `Mer tale`, C `Avbryt`.
Ferdig: A `Run` (eller kort norsk Kjør), B `Mer tale`/reell tilgjengelig handling, C `Lukk`. Lukk etter ferdigstillelse sletter ikke pakke/prosjekt.
Opptak: B `Ferdig`. Taleavspilling: B kan avbryte AI-lyden og starte neste taleomgang gjennom eksisterende turn-kansellering. Ikke endre appjobb når bare lyd avbrytes.

## 3. Resume ØVERST i AI Developer

- Vis `Resume` som første valg når en pågående eller ferdig jobb finnes. Resten: Ny app, Endre app, Kun samtale.
- Hent build_jobs ved åpning, boot og reconnect. Ved flere jobber gir Resume en liten liste med appnavn og status; behold identiteten, ikke gjett fra navn.
- build_resume med build_id gjenopptar riktig prosjekt. Vis gjeldende fase/prosent som om siden aldri var lukket. Ikke nullstill fremdriften eller generer på nytt.
- Hvis klar: vis den eksisterende pakken og Run etter faktisk installasjon. Resume åpner utvikling og kan tilby/installere den allerede testede pakken, men starter aldri Lua automatisk. Run er en egen eksplisitt run_confirm etter install receipt.
- Backend gjenoppretter dialog og plan. Ikke send app_select etter build_resume, da det ville nullstille konteksten.
- Oppdater skjermen fra build_resumed.state/progress/package_id og etterfølgende build_progress/package_ready/install_request. UI må ikke henge igjen i opptaks-/ventetilstand etter reconnect.
- Også avvist/lukket ferdigvarsel skal kunne gjenopptas fra Resume eller appbiblioteket.

## 4. Ny app / Endre app mens noe annet er aktivt

Vis konkret valg FØR noen destruktiv handling:
- `Avbryt og fortsett`: avbryt aktuell backend-jobb med build_cancel og/eller stopp fysisk kjøring med app_stop og gyldig app_stopped-receipt. Åpne deretter valgt Ny app/Endre app.
- `Cancel`: lukk bare dette valget; den gamle jobben/kjøringen fortsetter urørt. Ikke send cancel_turn, build_cancel, session_stop eller app_select her.

Vis appnavn for jobben/kjøringen som faktisk avbrytes. Hvis flere er aktive må identiteten være entydig. Backend kan holde andre bekreftede jobber i kø, men UI må følge brukerens valg. Skjermnavigasjon alene er aldri tillatelse til å avbryte.
En installasjon i gang må avsluttes eller ryddes opp via eksisterende staging/kvittering; ikke la sen kvittering installere eller kjøre feil prosjekt.

## 5. Status i hovedmenyen

- Liten fremdriftsindikator ØVERST, MIDT MELLOM TID OG DATO, uten å flytte eller overlappe disse.
- Bruk faktisk backend-prosent/fase, f.eks. ikon + `Bygg 75%`. Ikke simuler prosent med tid eller la animasjon gi inntrykk av målt fremdrift.
- Mål tilgjengelig pikselbredde fra faktisk klokke-/datotekst. Den lille indikatoren trenger ikke gjenta hele statuslinjen fra AI Developer.
- build_job_status oppdaterer bakgrunnsjobben uten å bytte skjerm. Heartbeat/reconnect gjenoppretter status også etter tapt event.
- Ved nettbrudd behold sist kjente fremdrift og vis diskret frakoblet, ikke erklær byggfeil. Backend kan fortsatt arbeide.
- Minimer RAM: en liten bounded jobboversikt; ingen kildekode/komplette logger i UI. Poll build_jobs sjeldent, ikke per frame.

## 6. Ferdigvarsel

- build_ready_notice viser popup med appnavn og fullstendig kort melding `Appen er klar`, valg `Åpne` og `Avbryt`.
- Åpne: build_notice_ack(notification_action=open), åpne AI Developer/Resume for akkurat build_id. Ikke auto-run.
- Avbryt: build_notice_ack(notification_action=dismiss), lukk bare varslet. Pakken/prosjektet beholdes og kan hentes senere.
- Dedupliser popup på build_id. Backend gjentar uavklarte varsler ved reconnect/heartbeat; ikke vis en ny popup hver gang. Kvitter bare etter et faktisk valg, med stabil event_id ved replay.
- Lagre liten pending build/notice-identitet i NVS eller atomisk liten SD-fil ved tilstandsendringer, ikke per prosent/frame. Hent serverlisten ved boot; NVS er kun cache, ikke egen sannhet.
- OS må holde/polle den vanlige backend-forbindelsen også utenfor AI Developer. Opprett ikke ekstra forbindelser per frame. Reverse TCP-poolens begrensninger gjelder fortsatt.
- En popup må ikke ødelegge aktivt opptak, lokal app eller filinstallasjon; utsett overlay til trygg UI-grense, behold pending varsel. Underliggende app stopper ikke ved Cancel.

## 7. Alle statuser på én linje, tale adskilt

Backend sender `status_text_version=fire-status-text-v1`. Statuskatalogen har maks 28 tegn OG 28 UTF-8-byte, NFC-normalisert. Dette er kompatibelt med tidligere 28-bytefelt, men device må likevel måle tekstens pikselbredde med valgt font.

- Bruk build_progress.message, app_repair_status.message, error.status_message/message, build_job_status.message og last_error_status fra snapshot. diagnostic_message er PC-detaljer, aldri en skjermstatus eller TTS.
- Ingen vilkårlig substring, bytekutt, to linjer, ellipse eller ufullstendig setning. Eksempler: `Klargjør appen`, `Lager appen (1/4)`, `Tester knapper og sensorer`, `Venter på AI-kapasitet`, `Ny versjon klar`.
- Behold æøå pent: UTF-8-dekoding og font med riktige norske glyfer; ingen translitterering/mojibake. Test Åpne/Kjør/ø/æ/å fysisk på LCD.
- Fjern `DOWNLOADING AI VOICE` fra brukerstatus. Lydnedlasting er intern transport og trenger ingen egen fremtredende melding. Behold relevant samtale-/byggstatus.
- assistant_message/transcript/audio_ready-tekst er samtalen, ikke status. AI kan gi et lengre men konsist naturlig talesvar. Ikke erstatt dette med statusetikett eller les opp prosent/faser.
- Avslutt aktivt opptak, bygg / App-handling pågår skal ikke være normal navigasjonsblokk. Nytt bevisst tale-/appvalg avbryter gammel tale/opptak og kan frigjøre skjermen uten å drepe et PC-bygg. Fysisk run/install må fortsatt få riktige stopp-/installasjonskvitteringer.

## 8. AI Developer viser hele appbiblioteket

Bruk SAMME paginerte app_list/app_catalog- og app_versions-kontrakt og flettelogikk som App Manager:
- Vis alle backendapper OG lokale apper, med riktige Cloud/Both/Local/Locked-indikatorer og versjoner, deduplisert på stabil app_id.
- En app som er slettet lokalt, men finnes i backend, skal kunne velges under Endre app uten å installeres først. Bruk backend project_id/app_id og base_package_id fra app_versions; backend har kilden.
- Lokal sletting er ikke prosjektsletting. Ikke filtrer bort Cloud-apper eller anta at manglende SD-map betyr manglende kilde.
- Lokale apper uten backendkilde kan vises, men ikke påstå at kildekode finnes. Vis ærlig utilgjengelig/redigeringsstatus og eventuell eksisterende importflyt; ikke rediger en annen app med likt navn.
- app_select(app_mode=update,project_id,base_package_id) velger riktig backendapp. Nye versjoner kan senere lastes ned via normal installasjonsflyt.
- Gjenbruk App Manager-sletting/versjonsregler; ikke lag en ny uavhengig katalog eller slett backend automatisk ved lokal sletting.

## 9. Additive v0.2 meldinger

Alle device-eventer har vanlig type=device_event, protocol_version=0.2, unik event_id, device_id, gjeldende session_id og boot_id. Eksemplene viser bare ekstra felt.

```json
{"event":"build_background","build_id":"build-example"}
{"event":"build_jobs","offset":0}
{"event":"build_resume","build_id":"build-example"}
{"event":"build_cancel","build_id":"build-example"}
{"event":"build_notice_ack","build_id":"build-example","notification_action":"open"}
{"event":"build_notice_ack","build_id":"build-example","notification_action":"dismiss"}
```

Svar:
- build_backgrounded: build_id, message; event_ack bekrefter handlingen.
- build_jobs: jobs (maks4), offset, next_offset, active_run. Hver jobb: build_id/project_id/app_id/name/status/phase/progress/message/package_id/version/can_open/background/created_at/status_text_version. List flere sider etter behov.
- build_job_status: samme jobbmetadata som push ved fremdrift og reconnect. Kan være queued/building/ready/failed; failed er ikke en klar pakke. Ingen automatisk kjøring.
- build_ready_notice: samme metadata for ferdig jobb, message=Appen er klar.
- build_resumed: build_id/project_id/base_package_id/package_id/state/progress/history_restored/message. Normal install-/run-kontrakt gjelder.
- build_cancelled: build_id/status/message. Hvis jobben akkurat ble ferdig, beholdes ferdig pakke; avbryt er aldri sletting.
- build_notice_closed: build_id/action/message. Dette er kvittering på popup-valg, ikke run-kvittering.

Ukjente/manglende build_id eller annen enhets jobb avvises. Skift aldri jobb ved bare appnavn. Nye eventer håndteres før opptaks-/dialog-busy-guard. Firmware må tåle ukjente additive felt/eventer og eldre backend uten å låse UI.

For Fix error: eksisterende app_repair_status beholder repair_id og vil inneholde build_id når bygg er startet. Byggstatus/Resume-varsler bruker det build_id. Ventende repair uten build_id bruker fortsatt app_repair_status. Ikke send dobbelt build_confirm ved reconnect; følg DEVICE_FIX_ERROR_REVIEW.md.

## 10. Verifikasjonsmatrise for device-agent

1. Bekreft ny app, A Bakgrunn, bruk hovedmeny og annen lokal app; indikatoren er mellom tid og dato.
2. Åpne AI Developer: Resume ligger øverst, viser samme prosent/fase og rett prosjekt/dialog.
3. Reboot og Wi-Fi-avbrudd under generation/testing; én bekreftet jobb fullføres, ingen dobbel fakturert generering.
4. Ferdig mens offline: popup etter reconnect. Åpne gjenopptar riktig pakke, install receipt før eksplisitt Run. Avbryt beholder pakken, ingen automatisk Lua-start.
5. C Avbryt stopper riktig aktiv eller kølagt jobb; ingen utestet pakke leveres, neste jobb kan starte.
6. Ny/Endre mens arbeid pågår: Cancel lar jobben fortsette; Avbryt og fortsett stopper rett jobb/run og åpner først så valgt prosjekt. Test sen install/run/stop-kvittering og dobbelttrykk.
7. Alle statusfaser, feil og norske tegn vises på én linje. Ingen DOWNLOADING AI VOICE, ingen HOLD-etiketter under korttrykksknappene. B-etikett svarer til faktisk handling.
8. AI Developer viser Cloud/Both/Local-apper som App Manager. Slett app lokalt, velg backendversjonen i Endre app og bygg videre uten forhåndsinstallasjon.
9. Ferdigvarsel gjentas ikke hver heartbeat; etter dismissal kan Resume fortsatt åpne pakken. Test flere jobber og eiegrense mot annen device-ID.
10. Tidligere Fix error-reconnect/JSON/SD-gjenoppretting og ekte native callback-feil testes etter review-dokumentet. Bygg/flash/boot alene er ikke fysisk ende-til-ende-verifikasjon.

Rapporter commit, faktisk build/flash og hvilke fysiske testpunkter som er kjørt. Ikke rapporter utestet popup-, nettbrudd-, tale- eller reparasjonsflyt som verifisert.

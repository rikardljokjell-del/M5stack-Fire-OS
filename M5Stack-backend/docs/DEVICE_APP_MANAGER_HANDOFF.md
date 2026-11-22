# Device-agent: App Manager med backendapper, nedlasting og sletting

Backend støtter nå brukerens ønskede Settings → App Manager-flyt. Kun filer i
M5Stack-backend er endret. Device-agenten må koble menyen til kontrakten under;
backendendring alene gjør ikke nye knapper synlige på FIRE.

## Ønsket meny og tilkobling

- Én app per rad, med Lokal / Backend / Begge som tydelig tilstedeværelse.
- Versjonsvalg for backendappen. Ikke anta at nyeste alltid kan leveres.
- «Last ned valgt versjon» lagrer pakken gjennom eksisterende installasjonsflyt.
- «Slett lokalt» beholder PC-historikken og sender app_deleted etter faktisk
  sletting. «Slett fra backend» er en egen bekreftet handling; velg én versjon
  eller alle. Backend-sletting forutsetter bekreftet lokalt fravær.
- Ved offline: lokale apper og lokal sletting virker fortsatt. Backendlisten
  merkes frakoblet; en gammel cache er aldri bevis for at en sletting er tillatt.

Hold eksisterende autentiserte backendforbindelse aktiv når App Manager er åpen,
også uten AI Developer. Send/fortsett vanlig session_start/session-resume og
vent på session_started før katalogkall. Ikke opprett to samtidige sesjoner for
samme device-ID. UI må ikke flytte til AI Developer når den mottar katalog,
installasjonsfremdrift eller app_selected mens App Manager er aktiv.

Konkret kildefunn i device-merge f1d884a/f0ecdee: FireOS::updateBackend sin
backendDemand inkluderer Settings/Firmware, men IKKE Screen::AppsSettings.
Den grenen kaller disconnect når ingen filoverføring pågår. Legg til
AppsSettings (og relevant backend-appmeny) der; ellers mister App Manager
forbindelsen idet brukeren åpner den. drawAppsSettings og knapphandleren viser
fortsatt bare lokale apper. FireBackendClient må få nye forespørsler og
korrekt, begrenset parsing av app_catalog/app_versions-arrayene og svarene
under; håndter escaping/UTF-8 og boolske verdier som JSON, ikke løse teksttreff.

Direkte nett og reverse TCP/HTTP bruker samme meldinger. Bruk kun enhetens
eget token i Authorization-headeren. Ingen admin-/OpenAI-nøkkel på enheten.

## Konvolutt og lesing

Alle forespørsler er vanlige device_event med protocol_version=0.2, event_id,
device_id, boot_id og session_id. Nye event-ID-er for nye handlinger, samme ID
og identisk payload ved forsøk på å få igjen en tapt kvittering.

1. event=app_list, offset=0. Backend sender app_catalog med fire apper per side,
   offset, next_offset og request_event_id. Hent neste side først ved behov;
   null avslutter listen. Behandle bare aktuell forespørsel/side i UI.
2. Hver app har app_id (stabil SD-mappe), project_id, name, latest_package_id,
   latest_version, base_package_id, version_count og device_presence.
3. Nye felt: downloadable og download_block_reason gjelder NYESTE versjon;
   can_delete_from_device og device_delete_block_reason gjelder sletting fra
   FIRE. Det gamle can_delete_backend er PC-kontrollen og kan være false mens
   can_delete_from_device er true for en ledig sesjon som har valgt samme app.
4. event=app_versions med project_id eller app_id og offset=0. Backend sender
   app_versions, project_id, åtte versions per side, offset, next_offset og
   request_event_id. Hver versjon har package_id, version, checksum (Lua),
   archive_sha256 (ZIP), size_bytes, downloadable og download_block_reason.

Katalog/versjonslesing bytter ikke app, tømmer ikke dialog, starter ikke AI,
bygger ikke og installerer ikke. Vis også sperrede versjoner med kort årsak;
ikke omgå releaseporten. Eldre pakker kan kreve ny bygging/reparasjon fra AI
Developer eller PC før de er tilgjengelige for ny levering.

Ikke slå sammen navn alene: project_id er backendidentitet, app_id er lokal
mappe. Bruk version/checksum/package_id til å vise hvilken versjon som er lokal.
HTTP-leserutene /devices/{id}/apps og /projects/{id}/versions finnes fortsatt,
men WS-sidene anbefales for begrenset minne og handlingsflaggene over.

## Last ned valgt versjon, uten automatisk RUN

Et eksplisitt menyvalg sender:

    {"event":"app_download", "project_id":"app-...", "package_id":"build-..."}

project_id er valgfri når package_id er gitt; app_id kan også sendes for ekstra
identitetskontroll. Alle oppgitte ID-er må samsvare og eies av denne enheten.
Backend kontrollerer v3-releaseport, feilsperre, annonserte ressurser og hele
arkivets integritet før den endrer installasjonskontekst.

Backend sender eksisterende install_request med install_id, package_id,
project_id, app_id, size_bytes, archive_sha256 og download_url. Event-ack gir
status=awaiting_device_install og samme install_id/package_id. Gjenbruk vanlig
ZIP-overføring, begrensede buffere, hash/CRC/manifestkontroll og staging til
/apps/<app_id>/. Send device_install_result med de ekte ID-ene og riktig hash.
Bare denne kvitteringen markerer installasjonen. En duplikat app_download med
samme event_id lager ingen ny installasjon.

Appen starter IKKE etter nedlasting. Åpne fra den lokale appmenyen eller bruk
separat eksplisitt run_confirm. En nedlasting er ingen BUILD/RUN-godkjenning.
Aktivt opptak, modellbehandling, bygging eller kjøring må avsluttes først.

## Sletting fra backend: klargjør og bekreft

Ny eksplisitt brukerautorisasjon tillater nå at FIRE sletter sin EGEN
backendhistorikk gjennom denne bestemte protokollen. Vanlig DELETE /projects
krever fortsatt PC/admin. Ingen generell adminrettighet er gitt til device.

1. Slett den lokale appen først hvis den finnes. Etter faktisk sletting send
   app_deleted med app_id og vent på kvittering, eller send en komplett,
   vellykket app_inventory som viser fravær. SD må være klar. Tom, avbrutt,
   begrenset eller delvis skanning må ALDRI merkes complete=true. Inventaret
   har maks 32 appoppføringer; ved flere/ukjent antall må complete=false brukes
   inntil en senere avtalt utvidelse finnes. En ufullstendig rapport gir aldri
   slettingstillatelse.
2. Hent/oppdater katalogen. Vis device_delete_block_reason hvis sletting er
   sperret, for eksempel pågående PC-dialog, bygg, nedlasting eller ukjent SD.
3. For én versjon:

       {"event":"app_backend_delete_prepare", "project_id":"app-...",
        "delete_scope":"version", "package_id":"build-..."}

   For alle versjoner:

       {"event":"app_backend_delete_prepare", "project_id":"app-...",
        "delete_scope":"all"}

   app_id kan erstatte project_id. scope=all skal ikke ha package_id.
4. Backend sender app_backend_delete_ready med delete_id, project_id, app_id,
   name, delete_scope, package_id, version_count og expires_at. event_ack har
   samme data og status=confirmation_required. Ingenting er slettet ennå.
5. Vis konkret bekreftelse: appnavn, valgt versjon eller ALLE N versjoner, og
   at PC-historikken slettes. Etter brukerens bekreftelse send:

       {"event":"app_backend_delete_confirm", "delete_id":"delete-..."}

   Valget gjelder i 90 sekunder og er bundet til enhet, session, boot og eksakt
   apphistorikk. Ved ny versjon, endret SD-status, aktiv operasjon eller utløp
   avvises det; oppdater listen og be om nytt konkret valg. Ikke bekreft gamle
   valg automatisk ved reconnect eller en ny boot.
6. Backend sender app_backend_deleted med status=deleted, project_id, app_id,
   delete_scope, package_id, remaining_versions og replacement_project_id.
   event_ack har samme resultat. Oppdater begge lister etter kvitteringen.

Hvis appen var valgt i den samme ledige AI-sesjonen, flytter backend sesjonen
til et nytt tomt prosjekt, ugyldiggjør gammelt forslag og sender app_selected
med app_mode=new. Oppdater lokal cache fra dette, men behold App Manager som
aktiv skjerm. Andre aktive samtaler på prosjektet sperrer fortsatt sletting.
Sletting av ett gammelt bygg endrer ikke andre arkivbytes eller versjonstelleren.
Sletting av siste versjon fjerner prosjektet. En annen versjon fremstilles aldri
automatisk som installert, og backend sender ingen lokal slettekommando.

Ved tapt ack: send identisk event med samme event_id. Duplikat returnerer samme
resultat uten ny sletting. unknown etter avbrudd betyr at klienten må avstemme
med katalog/snapshot, ikke gjette eller sende en ny destruktiv bekreftelse.

## Akseptanse for device-agenten

Backendverifisering: 272 samlede tester bestått; 18 nye App Manager-kontroller
dekker autentisert katalog/versjoner, faktisk ZIP-nedlasting og hash i emulator,
ingen automatisk RUN, én/alle versjoner, duplikater, utløp, endret historikk,
endret/ukjent SD, pågående nedlasting/annen sesjon, feil boot/enhet, sperret eller
korrupt pakke, ugyldige slettingsvalg og avgrensede sider uten endring av dialog.

Test Settings → App Manager uten å åpne AI Developer: autentisering, katalog
med flere sider, versjonsvalg, nedlasting/hash, faktisk SD-installering og
start fra lokal meny. Test lokal sletting med bevart PC-historikk, deretter
bekreftet backend-sletting av én og alle versjoner. Test offline, reconnect,
ukjent/full/fjernet SD, dobbelttrykk/tapt ack, utløpt valg og en ny appversjon
mellom klargjøring og bekreftelse. Ingen firmware- eller appstart skal følge
en slettehandling. Ingen stor katalog/ZIP skal allokeres samlet i device-RAM.

Backendens tester bruker emulator og verifiserte ZIP-er. Fysisk App Manager-UI
og ekte SD-kvitteringer er ikke bekreftet av backend-agenten. Oppdater device-
handoff med testet SHA og de faktiske fysiske resultatene.

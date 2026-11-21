# Appvalg, versjoner og sletting – tillegg til protokoll 0.2

Device-agenten eier UI/SD. Backend-agenten eier kun M5Stack-backend.
Dette er det additive grensesnittet for tidlig valg av ny/eksisterende app.
Eksisterende session_start/build_confirm/run_confirm beholdes. Gamle klienter
uten appvalg virker fortsatt; nye klienter velger før første tale/teksttur.

Alle hendelser har vanlig device_event/0.2-konvolutt med event_id, device_id,
boot_id og session_id. Samme token/eierskapskontroll og deduplisering gjelder.

## Tidlig valg

- `app_list`: hent side i appkatalogen, valgfri `offset` (standard 0).
  Svar: `app_catalog`, `apps`, `offset`, `next_offset` (null når ferdig).
  Fire apper per side; hver har app_id, project_id, navn, siste pakke,
  foreslått base_package_id, tilstedeværelse på device og antall versjoner.
- `app_versions`: `project_id` eller `app_id`, valgfri offset.
  Svar: `app_versions`, `versions` med package_id, version, checksum og
  archive_sha256, og next_offset. Åtte versjoner per side.
- `app_select`, `app_mode="new"`: ny, separat app og tom samtalehistorikk.
  Ingen app_id/project_id/base_package_id skal sendes for new.
- `app_select`, `app_mode="update"`: oppgi `project_id` eller `app_id` og
  eventuelt `base_package_id` fra versjonslisten. Begge ID-er må peke på samme
  app hvis begge sendes. Pakke og prosjekt må tilhøre den autentiserte enheten.
  Standard base er kjent versjon på enheten, ellers sist fungerende/siste
  backendversjon. Svar `app_selected` inkluderer valgt prosjekt/app/base.

Valget bygger/installerer/kjører ingenting. Et nytt valg ugyldiggjør tidligere
forslag og ubekreftede kommandoer. Valg avvises mens bygg/opptak/behandling eller
appkjøring er aktiv. Update beholder stabil mappe og prosjektets stigende
versjonsnummer, også når en eldre versjon velges som base. Ny app får ny mappe.

HTTP-reserve: GET `/devices/<device_id>/apps`, GET `/projects/<project_id>/versions`.
Bare egne prosjekter/enheter er tilgjengelige med device-token.

## Sletting og ny SD-inventarliste

- Etter vellykket fysisk sletting: `app_deleted`, `app_id`. Ikke send før
  SD-operasjonen faktisk er ferdig. Backend kvitterer; PC-historikken beholdes.
- Etter oppkobling eller SD-endring: `app_inventory`, `storage_ready`,
  `complete` og `apps` (maks 32). Hver oppføring har `app_id`, eventuelt
  `version` og `checksum` (SHA256 av main.lua), og kjent `package_id`.
- `complete=true` brukes bare når ALLE appmapper er undersøkt og SD er klar.
  En kort UI-liste, avbrutt skanning eller en ulest SD er ikke komplett.
  `storage_ready=false`/`complete=false` gjør ikke manglende apper til slettet.
  Ved større katalog: bruk delvise lister og eksplisitte app_deleted-hendelser.
- Komplett inventar kan markere tidligere kjente, manglende mapper som
  `missing`. Eksplisitt sletting merkes `deleted`. Ingen av delene sletter
  PC-versjoner eller utløser automatisk gjeninstallasjon.
- Inventar er tilstedeværelsesrapport, ikke installasjons-/kjørekvittering.
  Bare korrelert device_install_result kan autorisere RUN. Gamle kommandoer
  ugyldiggjøres ved sletting, og et pågående bygg får ikke gjenopprette en
  app som ble slettet mens byggingen pågikk. Bruker må velge/installere på nytt.

Eksempel (legg til vanlig konvolutt):

```json
{"event":"app_select","app_mode":"update","app_id":"sprettsirkel","base_package_id":"build-..."}
{"event":"app_inventory","storage_ready":true,"complete":true,"apps":[{"app_id":"sprettsirkel","version":"0.1.2","checksum":"<64 lowercase hex>"}]}
{"event":"app_deleted","app_id":"sprettsirkel"}
```

Sletting kan også skje mens backend er frakoblet; neste komplette inventar
avklarer forskjellen. Historiske healthy-/installasjonskvitteringer beholdes,
men Windows viser ikke appen som installert/kjørende når den er rapportert borte.
Gjenoppretting fra PC er et eksplisitt valg og krever fortsatt separat RUN.

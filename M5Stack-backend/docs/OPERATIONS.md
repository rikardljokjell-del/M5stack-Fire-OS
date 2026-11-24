# Lokal Windows-drift

Vanlig Windows-bruk: start `start-ui.ps1` og velg **Åpne FIRE Studio ↗**.
Se [PC-/mobiloppsettet](WEB_STUDIO_SETUP.md). Windows-programmet og Studio bruker
samme DesktopStore/Windows Credential Manager; de leser ikke CLI-innstillingene
i `.env`. API-nøkkel er write-only i Studio. Offentlig HTTPS/WSS krever separate
browser-/device-verter og validert Access-innlogging, aldri proxy-/loopback-tillit.
USB-migrering er et separat, eksplisitt verktøy; se [USB_MIGRATION.md](USB_MIGRATION.md).

## Før ekte bruk

Punktene under gjelder kommandolinjeutgaven. Ekte OpenAI-kontroll krever et eget
admin-token også når serveren lytter på loopback. Anonym tilgang gjelder bare
eksplisitt lokal mock-modus. Windows-programmet lager og lagrer admin-tokenet selv.

1. Installer Python 3.11+ og bruk start.ps1 fra backendmappen.
2. Kopier .env.example til .env og sett OpenAI-nøkkelen KUN på PC.
3. Bruk forskjellige, tilfeldige admin-/enhetstokener. Generer for eksempel med
   `python -c "import secrets; print(secrets.token_urlsafe(32))"` i egen terminal.
   Legg verdiene lokalt i .env; ikke lim dem inn i logger eller GitHub.
4. Sett FIRE_BACKEND_HOST til PC-ens LAN-IP og konfigurer enhetens backend-adresse.
   Hold serveren på et betrodd privat nett. Bruk TLS før andre nett eller ekstern tilgang.
5. Kontroller /health og kjør check_openai.py --live med egen .env. HTTP-helse alene
   beviser ikke API-/modelltilgang. Sett FIRE_AUDIO_ENABLED=true for tale.

## Brannmur (valgfritt, utføres av administrator)

Åpne bare privat nett/lokalt subnett, og bare valgt Python/port. Eksempel i en
forhøyet PowerShell etter at du har kontrollert stien og IP-oppsettet:

```powershell
$backendDir = (Resolve-Path '.\M5Stack-backend').Path
$backendPython = Join-Path $backendDir '.venv\Scripts\python.exe'
New-NetFirewallRule -DisplayName 'FIRE backend private LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Program $backendPython -Profile Private -RemoteAddress LocalSubnet
```

Dette er en instruksjon, ikke noe backend har kjørt. Ikke åpne en generell
offentlig regel eller videresend porten fra ruteren.

## Oppstart og restart

Den støttede kommandoen er start.ps1 eller `.venv\Scripts\python.exe -m fire_backend`
med backendmappen som arbeidsmappe. Bruk én prosess, ingen Uvicorn-workers/reload
i drift. Prosesslås i workspace hindrer to vanlige starter i samme mappe.

For automatisk start kan Windows Oppgaveplanlegging settes opp manuelt:

- Program: absolutt sti til .venv\Scripts\python.exe.
- Argumenter: -m fire_backend. Start i: absolutt backendmappe.
- Bruk dedikert/egen Windows-konto med tilgang til workspace og .env.
- Velg ønsket oppstarts-/innloggingstrigger; kjøring uten innlogging krever riktig
  konto-/legitimasjonsoppsett i Windows. Ikke legg passord/API-nøkkel i argumentene.
- Kjør skjult i bakgrunnen, ikke opprett en ny instans hvis oppgaven allerede kjører.
- Tillat langvarig kjøring og restart ved feil med forsinkelse; ikke en rask restartsløyfe.

Ingen oppstartsoppgave er installert av leveransen. Kontroller først manuelt at
konfigurasjon og ekte API fungerer. PC-en må være på og ikke sove under drift.

Ved restart feiles avbrutte bygg. Historiske PC-current-pekere blir simulert
historikk. Fysisk kjørestatus blir unknown, og gamle kommandoer blir ugyldige.
Klienten må gjenoppta/avstemme status; ingen app startes automatisk igjen.

## Data, lagring og feilsøking

- workspace inneholder prosjekter, kildeforsøk, manifester, ZIP-er, versjoner,
  historikk, event-/kommandokvitteringer og redigerte logger. Ta backup når serveren
  er stoppet for et konsistent filsett. Ikke synkroniser en aktiv workspace mellom PC-er.
- .env, .venv og workspace er ignorert av Git. JSON-skjemaer og konfigurasjons-
  eksempler er kildekode; faktiske nøkler er ikke det.
- Lyd lagres kortvarig, aldri i app-pakker/vanlige logger. Innkommende WAV slettes
  etter behandling; utgående PCM slettes ved avbrudd/utløp/restart. Dette er vanlig
  filsletting, ikke garantert sikker sletting fra disken.
- Ved diskgrensen stoppes nye operasjoner med feil; historikk slettes ikke blindt.
  Stopp tjenesten, ta backup og arkiver gamle prosjekter/bygg eller øk grensen.
  Behold enhetens installerte/current/previous/backup-versjoner og deres metadata.
- Ved 401/403: kontroller eget enhetstoken og device_id. Admin-token kan ikke
  impersonere en fysisk enhet. Ved feil boot_id: ny oppstart krever ny sesjon.
- Ved ukjent startresultat: ikke send ny run_confirm blindt. Gjenoppta og les
  snapshot/pending_commands; stopp og kvitter gammel kjøring før et nytt forsøk.
- Ved OpenAI-feil: se lokal sesjons-/byggelogg og request_id/status der tilgjengelig.
  Rå provider-feil og Authorization-headere skrives ikke ut. Bekreft modellnavn,
  kreditt, konto-/prosjekttilgang med den eksplisitte live-sjekken.
- Ved Lua-feil: inntil tre korrigeringer etter første kodeforsøk. Full begrenset
  stdout/stderr er lokal; mislykkede pakker er ikke tilgjengelige for installasjon.

Den begrensede Lua-tolken og prosessfristen er prototypetiltak. Ikke eksponer
denne tjenesten for ubetrodde eksterne brukere uten egen OS-isolasjon og TLS.

# FIRE Studio: PC, mobil og sikker tilgang utenfra

FIRE Studio leveres av samme FastAPI-prosess som Windows-programmet. Ingen
ekstern nettside eller Codex-installasjon kreves for drift. Modeller, API-nøkkel,
enheter, kostnader, samtaler, bygg og versjoner bruker de eksisterende lagrene.

## På denne PC-en

1. Start `start-ui.ps1` i M5Stack-backend som vanlig.
2. Klikk **Åpne FIRE Studio ↗** øverst i Windows-programmet.
3. Nettleseren åpner `http://127.0.0.1:8765/ui/` (eller lagret port).
   Innloggingslenken virker én gang i 60 sekunder. Den midlertidige koden ligger
   i URL-fragmentet, slettes straks fra adressen og sendes deretter med POST.
4. Velg AI Developer. Velg enhet og **Utvikle app** eller **Kun samtale**.
   Forklar ønsket, kontroller forslaget og velg **Bekreft og bygg**.
5. Du kan lukke nettleseren. Byggingen fortsetter. Samtalen og samme jobb finnes
   igjen under AI Developer og Jobber. **Fortsett samme jobb** lager ikke en ny
   byggejobb; betalt arbeid krever en ny eksplisitt byggebekreftelse.
6. Appbiblioteket grupperer versjoner, med sist oppdaterte app øverst. Cost er
   hele appens registrerte livsløpskostnad, også rettinger og tidligere versjoner.
   Velg versjon før nedlasting, installering eller sletting. Sletting krever
   fortsatt at backend har tilstrekkelig bevis for at appen er borte fra FIRE.
7. Installer krever tilkoblet FIRE og ny kapabilitetskontroll. **Kjør på FIRE**
   krever separat eksplisitt bekreftelse for den testede, installerte pakken.
   Offline utvikling bruker sist rapporterte kapabiliteter, eller den konservative
   FIRE-baseline hvis enheten aldri har meldt seg. Ingen fysisk støtte oppdiktes.

API-nøkkel er write-only i webUI. Tomt nøkkelfelt beholder eksisterende nøkkel.
Enhetstoken og administratortoken eksporteres ikke til webUI. Innstillinger er
samme DesktopStore/Windows Credential Manager som Windows-programmet. Lagre
skriver verdier; **Bruk innstillinger og start på nytt** er en separat handling.
Aktive bygg/tale/samtalekall blokkerer omstart. Inngangen stenges for nye kall
mens omstart klargjøres, og aktivt arbeid kontrolleres på nytt før stopp.
Nettleseren logger inn igjen etter omstart.

Lokal LAN HTTP beholdes for eksisterende enhetstilkobling. Nettleseradmin på
mobil bruker HTTPS-oppsettet under; ingen anonym LAN-innlogging åpnes.

## Én gang: mobil og internett

Du trenger et domene administrert i Cloudflare, en Cloudflare-konto og en Access
innloggingsmetode. Disse er ikke opprettet eller kjøpt automatisk.

1. På denne PC-en er offisiell Cloudflare `cloudflared` 2026.11.2 allerede hentet
   til ignorert `workspace/tools/cloudflared/`, kontrollert mot publisert SHA256
   og prøvd med kun `--version`. Bruk `scripts/cloudflare.ps1` fra backendmappen;
   den kontrollerer hash/størrelse før kjøring og endrer ikke PATH.
2. I Cloudflare Zero Trust: opprett en **Self-hosted Access application** for
   `studio.dittdomene.no`. Tillat bare din innlogging. Ikke lag en Bypass-policy.
   Noter teamnavn/issuer `https://TEAM.cloudflareaccess.com` og application AUD.
3. Opprett en named tunnel på PC-en. For lokalt administrert tunnel bruker du
   `.\scripts\cloudflare.ps1 tunnel login`, deretter
   `.\scripts\cloudflare.ps1 tunnel create fire-pc`.
   Konto- og tunnellegitimasjonen blir i brukerens `.cloudflared`-mappe.
4. Kopier `deployment/cloudflare/pc.yml.example` til `.cloudflared/fire-pc.yml`.
   Erstatt UUID, credentials-file, domenenavn, Access team og audience. Behold
   to ulike vertsnavn og avsluttende 404-regel. Behold `httpHostHeader` lik det
   offentlige vertsnavnet, aldri `localhost`. Browser-ruten krever Access ved
   tunnelinngangen OG signaturkontroll i applikasjonen.
5. Legg DNS-rutene til tunnelen:
   `.\scripts\cloudflare.ps1 tunnel route dns fire-pc studio.dittdomene.no` og tilsvarende
   `fire.dittdomene.no`. Bare studio-verten har interaktiv Access-innlogging.
   Enhetsverten bruker sitt eget begrensede device-token; et admin-token avvises
   på denne flaten. Ikke legg browseradmin eller andre apper på enhetsverten.
6. Åpne lokalt FIRE Studio → Innstillinger → Sikker nettilgang. Legg inn de samme
   vertsnavnene, issuer og audience, aktiver offentlig HTTPS/WSS, lagre og bruk
   innstillingene når aktive jobber er ferdige. Alternativt bruk
   `scripts/configure_public.py` med de fire navngitte argumentene og `--save`.
   Etter CLI-alternativet avslutter og åpner du Windows-programmet igjen, slik
   at konfigurasjonen leses fra disk. Ingen hemmeligheter skal gis som argument.
7. Kontroller tunneloppsettet med
   `.\scripts\cloudflare.ps1 tunnel --config <sti-til-fire-pc.yml> ingress validate`.
   Start med `.\scripts\cloudflare.ps1 tunnel --config <sti-til-fire-pc.yml> run fire-pc`.
   Cloudflared holdes i gang på PC-en; ingen inngående ruterport åpnes.
8. Åpne `https://studio.dittdomene.no/ui/` på mobil/PC, logg inn med Access og
   velg **Logg inn med Cloudflare Access** i Studio. Nettlesersesjonen varer
   maksimalt én time og aldri lenger enn Access-tokenet. Origin/CSRF kontrolleres
   ved alle endringer. Access-JWT kontrolleres også på hver beskyttet forespørsel.
9. På FIRE velges den offentlige backendadressen med HTTPS/WSS, port 443 og eget
   device-token. Lyd og Lua-pakker bruker samme sikre vertsnavn. Enhetens
   sertifikat-/klokkekontroll og firmwareversjon må verifiseres separat.
10. Test fra mobilnett: nettside, samtale, bygg, gjenopptak og nedlasting. Ta også
    bort/utløp Access-tilgangen og kontroller at admin-API-et nekter adgang.

PC-en må være på for AI/UI. Cloudflare kan bryte WebSocket ved vedlikehold eller
inaktivitet; enheten må gjenoppta samme kontekst uten å repetere betalte kall.
Fysisk test av denne stien krever ferdig domene/tunnel og aktuell firmware.

## Home og firmware

Home/MQTT får en egen tunnel ved HA-/brokerverten, **ikke PC-tunnelen**.
Se `home_assistant/README.md` og `docs/HOME-v1.md`. Nabu Casa-adressen er ikke
en MQTT-endpoint. Home og installerte selvstendige apper skal fungere med PC av.

Firmwarevisningen er bare lesbar metadata fra repoets `firmware/index.json`
og `firmware/legacy-index-v1.json`, samt GitHub Releases. Gjeldende versjon har
prioritet ved duplikater. Manglende eldre arkiv påvirker ikke gjeldende katalog.
Eldre katalog merkes usignert og ikke for ny recovery-layout; v2 er signert metadata,
men backend påstår ikke å ha verifisert signaturen eller fysisk firmware.
FIRE kontrollerer sin egen target/hash/signatur og håndterer installering,
tilbakeføring og recovery direkte. Ingen firmwarebinær lastes ned av webUI.

## Bevis og begrensninger

Offline HTTP-tester dekker signerte test-JWT-er, feil issuer/audience/utløp,
forfalskede proxyheadere, tokenskille, CSRF/Origin, engangskoder, samme config,
frakoblet utvikling og lagret samtale. Dette er ikke en live Cloudflare- eller
HA-godkjenning. Isolert mock-nettlesertest har prøvd dialog/bygg/bibliotek og
mobilbredde. Ingen betalte AI-kall kreves for disse kontrollene.

Offisielt oppsettsgrunnlag:
[Cloudflare JWT-validering](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/),
[tunnelens origin-parametere](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/).
Den lokalt kontrollerte versjonen kommer fra
[Cloudflares offisielle 2026.11.2-utgivelse med SHA256](https://github.com/cloudflare/cloudflared/releases/tag/2026.11.2).
Ingen Cloudflare-innlogging, tunnel, tjeneste, DNS-rute eller offentlig åpning er
gjort av klargjøringen. Stegene over utføres først med brukerens konto/domene.

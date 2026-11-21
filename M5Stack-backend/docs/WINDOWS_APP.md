# FIRE Backend på Windows

Åpne **FIRE Backend** fra skrivebordsikonet. På denne PC-en bruker ikonet den
allerede installerte Python-kjøringen (`pythonw.exe`), uten terminalvindu.
Windows Application Control blokkerte den siste usignerte exe-pakken. Ingen
sikkerhetsinnstillinger er endret for å tillate den. Programmet kjører derfor
direkte fra backendmappen med samme grensesnitt og funksjoner.

En PyInstaller-pakke er også bygget i `dist/FIREBackend/`, med avhengigheter i
`_internal`. Første pakke bestod fire flyter; den siste exe-filen er blokkert av
Windows her. En separat distribusjon krever godkjent/signert pakke eller vanlig
Python-installasjon. Behold hele FIREBackend-mappen samlet ved distribusjon.

## Første bruk

1. Programmet starter backend automatisk i **Test uten API**. Oversikt viser
   grønn «Kjører». Denne modusen bruker faste Lua-eksempler og ingen OpenAI-kall.
2. Åpne **OpenAI**, lim nøkkelen inn i «Ny API-nøkkel», velg **OpenAI** og trykk
   **Lagre og bruk**. Backend starter på nytt med endringene. Et tomt nøkkelfelt
   beholder en tidligere lagret nøkkel.
3. **Test API-nøkkel** henter OpenAIs modelliste med den nye eller lagrede nøkkelen.
   Resultatet skiller godtatt nøkkel fra utilgjengelige modellnavn. Dette tester
   ikke full dialog, tale, kreditt til generering eller en fysisk M5Stack.
4. Åpne **M5Stack** og bruk PC-adresse, port, enhets-ID og enhetstoken i enhetens
   backend-oppsett. Standard ID er `m5stack-fire-01`, som i gjennomgått firmware.
   Standard port er 8765. Kopieringsknappene gjør det enklere å overføre verdiene.
5. PC og FIRE må kunne nå hverandre på samme nettverk. Godkjenn eventuell
   Windows-dialog for programtilgang på et betrodd nett. Knappen **Tillat FIRE
   gjennom brannmuren** kan opprette en regel for akkurat programmet/porten og
   lokalt subnett; Windows ber om administratorgodkjenning. Ingen ruterport åpnes.
6. Åpne AI Developer på FIRE. **Oversikt** og **Aktivitet** viser tilkoblingen
   når protokollens session_start er mottatt og godkjent.

Å lytte på LAN betyr ikke at enheten er tilkoblet. Feil token/ID, Wi-Fi-isolasjon,
Windows-brannmur eller kildefeil i firmware må fortsatt avklares ved faktisk test.

## Tekst, bygging og kjøring

**Aktivitet** lar deg velge en tilkoblet FIRE-sesjon og sende tekst til samme
samtale. Dette virker både med eldre audio_input=false/audio_output=false og
nyeste kildes audio_input=true/audio_output=false. Sistnevnte har WAV-opplasting,
men fysisk mic-test gjenstår. Hver enhet må annonsere faktisk støttede funksjoner.

Backend gir et forslag. **Bekreft bygging** aktiveres bare for et gyldig forslag.
Fremdriften og samtalen oppdateres automatisk. Pakken tilbys deretter til FIRE.
**Bekreft kjøring** aktiveres først når enheten har kvittert for installasjon.
Knapper på FIRE kan også brukes. Tekst alene utløser aldri bygg eller kjøring.
Kvitteringene fra enheten avgjør installert/startet/current; PC-simulering og
enhetsemulering er alltid fysisk uverifisert.

## Innstillinger og lagring

- Modellnavn og stemme kan redigeres under **OpenAI**. Kontoens modelliste
  avgjør hvilke navn som er tilgjengelige; programmet bytter ikke modell i skjul.
- **Innstillinger** har datamappe, lagringsgrense og backendens lydtransport.
  Lydtransport er på som standard i Windows-programmet og overstyrer aldri
  enhetens lydflagg. CLI-utgaven beholder sin standard false.
- Innstillinger ligger i `%LOCALAPPDATA%\FIRE Backend\settings.json`.
  Standard prosjekt-/pakkemappe er `%LOCALAPPDATA%\FIRE Backend\workspace`.
  Denne desktopprofilen er uavhengig av utviklerens `.env` og tidligere mock-data.
- OpenAI-nøkkel, administratortoken og hvert enhetstoken lagres i **Windows
  legitimasjonsbehandling**, under FIREBackend/profilens tilfeldige ID.
  De lagres ikke i settings.json, Git, kommandolinjer eller app-pakker.
  Windows-brukeren din kan bruke legitimasjonen; dette er ikke en sperre mot
  skadevare som allerede kjører som samme bruker.
- «Kopier token» bruker Windows-utklippstavlen. Programmet tømmer den etter
  ett minutt dersom innholdet ikke er endret og programmet fortsatt kjører.
- Ny datamappe flytter ikke gamle prosjekter. Eksisterende backenddata beholdes.
- **Fjern lagret nøkkel** fjerner OpenAI-nøkkelen og bytter tilbake til testmodus.
- Lukk vinduet for å stoppe backend kontrollert. Ingen automatisk Windows-
  oppstartsoppgave eller bakgrunnstjeneste er installert. PC-en må være våken.

## Bygg og kontroll for utvikling

Kjør `build-windows.ps1 -Shortcut` fra backendmappen. Skriptet bruker den eksisterende
venv-en og en versjonslåst PyInstaller. Resultatet legges i ignorert `dist/`.
`start-ui.ps1` bruker den installerte Python-versjonen når den finnes, og pakken
ellers. Skrivebordsikonet på utviklingsmaskinen bruker alltid pythonw.exe.

Den pakkede appen kjører samme FastAPI-/protokollbackend som kommandolinjeutgaven.
Lua kjører i en egen prosess via samme exe med avgrensede midlertidige filer;
nøkler arves ikke av workerprosessen. Desktopens kontrollruter krever både
administratorlegitimasjon og lokal forbindelse, avviser nettleser-Origin, og er
avslått i vanlig start.ps1-drift. Enhetens protokoll og autentisering er videreført.

Tester: `python -m pytest -q`. Med Windows-programmet kjørende i testmodus:
`python scripts/desktop_smoke_test.py --input-audio`. Testen bruker en PC-peer,
eldre lydflagg false, tekst fra desktop-API, fire pakket Lua-bygg og korrelerte
kvitteringer, pluss ny input-only-profil med syntetisk WAV.
Den er ingen fysisk FIRE-test og gjør ingen ekte OpenAI-kall.

Kildegrunnlag: [OpenAI modelliste](https://developers.openai.com/api/reference/python/resources/models/methods/list),
[Windows Credential API](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew),
[PyInstaller runtime](https://pyinstaller.org/en/stable/runtime-information.html).
Enhetsbegrensninger: [DEVICE_HANDOFF_RESPONSE.md](DEVICE_HANDOFF_RESPONSE.md).

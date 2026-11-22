# Fast skjermregel for alle genererte og reparerte apper

Oppdatert kvalitetsport: release-v4 viderefører reglene nedenfor og begrenser
dessuten samlet tekst til 256 UTF-8-byte per callback. Se
[TETRIS_RUNTIME_REPORT.md](TETRIS_RUNTIME_REPORT.md) for konkret native feil som
passerte v3 og nå fanges. Utvidede hardwareapper får også tre I/O-feilprofiler.
Gamle uendrede pakker kan testes på nytt uten AI med
`python scripts/revalidate_packages.py --desktop --apply`, mens backend er
stoppet. Skriptet tar arbeidsmappelås, endrer kun valideringsmetadata og sperrer
nylig påviste feil; allerede quality-blocked versjoner forblir sperret.

22. november 2026. Kun backend er endret. Device-kilden er lest fra main
5b7d6ee; fysisk firmware kan være nyere enn innsendt kilde.

## Påvist årsak til flimring / forsvinnende innhold

FireOS::drawLuaApp i M5Stack-device/src/fire_os.cpp kjører
ui.fillSprite(TFT_BLACK) før updateLuaApp. Hostfunksjonene tegner i samme sprite;
OS presenterer den med ui.pushSprite(0,0). Dette er allerede en offscreenbuffer.
Det er derfor ikke riktig å anta at en full clear i RAM alene beviser synlig
flimring. Det sikre kildefunnet er at tidligere bilde IKKE overlever update.

En app med «if elapsed < 160 then return end» før tegning gir blanke bilder
mellom bevegelsene. Init-only tekst/rutenett forsvinner. Tegning kun ved endring
virker heller ikke med denne hosten. Den gamle PC-simulatoren modellerte ikke
dette og kunne godkjenne slike apper. Dette er en backendkontraktfeil som nå
fanges før ny levering.

Den lagrede Slangespill 0.1.3-pakken build-3a584991e5314fe5b52b ble kontrollert
uten å endre kilde/device: release-v3 avviste den i idle-profilen med «no visible
output in update». Det underbygger brukerens flimrerapport med et konkret
kodefunn; det er ikke en fysisk måling av skjermen.

## Permanent genereringsregel

fire_backend/rendering.py inneholder VISUAL_POLICY. Den legges til alle
byggeforsøk, nye apper og reparasjoner, også uten tidligere feilhistorikk.
OpenAI-generering bruker samme regel. Ikke hent sikkerhetspolicy fra rå logger.

- Skill spill-/sensortid fra tegning. Hele bildet tegnes ved HVER update,
  også i pause, game over og mellom langsomme simuleringssteg.
- Bruk en render-funksjon som alltid kalles. on_button endrer bare tilstand.
- Tegn én sammenhengende ramme i OS-bufferen. Maks én clear før tegning;
  ingen clear etter tegning og ingen bevisst veksling mellom tomt og synlig bilde.
  Utelat clear hvis hostens svarte bakgrunn er nok.
- Behold lesbare, korte etiketter, en konsistent palett og hele figurer innenfor
  skjermen. Teksttesten reserverer konservativt 6 piksler per UTF-8-byte og
  8 i høyden; den gjengir ikke den faktiske fonten.
- Forenkle hele scenen for å overholde callbackbudsjettet. Ikke fordel tegning
  av én synlig scene over flere updates eller finn opp nye Lua-tegne-API-er.

Mockeksemplene Sirkel, Snake og IMU følger samme kontrakt. Ingen brukerpakke
eller device-fil er omskrevet. Nye regler gjelder ved neste bygging/reparasjon.

## Leveringsport release-v3

Sju input-/tidsprofiler kjøres fortsatt i egne Lua-VM-er. For displayapper
avvises en update uten synlig tegneoperasjon, on_button-tegning, dobbel clear,
clear etter tegning, avklippede sirkler/rektangler og tekst som overskrider den
konservative tekstflaten. Regelen gjelder også aliaser og hjelpefunksjoner fordi
kontrollen gjøres i de faktiske hostkallene. Feil mates automatisk tilbake til
eksisterende, begrenset kodekorreksjon før en ZIP kan publiseres. Ved vedvarende
feil leveres ingen pakke. Rendering-feil har egen kategori i feilminnet.

Resultatet lagrer cleared-sprite-v1, antall faktiske update-rammer, minste antall
synlige tegneoperasjoner per update og maksimalt antall clear. Eldre release-v2
og v1 slipper ikke gjennom ny nedlasting/installasjon/kjøring fra backend;
de må bygges/testes på nytt. Allerede installerte apper endres ikke automatisk.

Dette påviser kjente kodefeil, ikke at hvert bilde er komplett eller vakkert.
Én synlig operasjon beviser ikke at alle etiketter/objekter finnes. PC-testene
måler heller ikke faktisk oppdateringsfrekvens, paneltearing, native font,
ESP32-tid eller fysisk glatt bevegelse. Ingen garanti om alle mulige feil.

## Device-agent: behold en avtalt tegnemodell og verifiser presentasjonen

Backend bygger nå for dagens cleared-sprite-modell. Ikke fjern fillSprite
isolert: gamle full-frame-apper uten clear vil da etterlate spor. En overgang
til retained canvas må avtales/annonseres eksplisitt i kapabiliteter og testes
med begge appgenerasjoner; ingen slik capability er innført her.

1. Presentér bare ferdigtegnet sprite, én gang per update. Ikke push en tom
   mellomramme fra clear, statusbar, bakgrunnstask eller init.
2. Kontroller tekstfont/datum og clip før Lua-kjøring; ikke la en forrige
   OS-side endre etikettplassering eller fontstørrelse.
3. Kontroller rytme, SPI-/DMA-synkronisering og at sprite ikke endres mens en
   asynkron overføring leser den. Unngå ekstra framebuffer hvis det ikke trengs.
4. Mål callbacktid og faktisk presentasjon med den eksisterende lette feedbacken,
   ikke logging per frame. Backendkvittering er ikke en visuell test.
5. Test statisk tekst, sakte Snake (160ms steg), pause/game over, IMU-graf,
   raske knapper, jitter og Home/Back. Ingen mellomliggende blanke bilder,
   spor, hoppende etiketter eller avklipping. Test både Apps og AI Developer.

Oppdater device-handoff med testet SHA og resultat. Backend-agenten endrer
ikke firmware eller flasher for å oppfylle denne oppgaven.

## Backendverifisering

En isolert ekte OpenAI-dialog/generering laget Sprettsirkel, 2128-byte ZIP,
som passerte release-v3 i alle sju profiler. Ingen fysisk installasjon ble
forsøkt. Lokale artefakter: verification/pipeline-094be5024184 i Windows-profilens
FIRE Backend-mappe. Testene inkluderer også automatisk korreksjon av et blankt
første forsøk før én godkjent pakke blir opprettet, og alle tre displayeksempler
kjøres over 60 sekunders testhorisont med varierende knapper/tidssteg.

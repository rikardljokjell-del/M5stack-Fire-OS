# Device-agent: enhetstilpasset appopplevelse og pålitelig feilrapportering

Dato: 22. november 2026. Kildeaudit av GitHub `dae75bf` etter device-endring
`74ac26a`. Dette dokumentet beskriver påviste kildeforhold og nødvendig
firmwarearbeid. Ingen av tiltakene nedenfor er implementert eller fysisk
verifisert av denne auditen. Backendagenten endrer, bygger og flasher ikke device.

Les også brukerens nye felles UX-standard, `PROTOCOL-v0.2.md`,
`HARDWARE_API_HANDOFF.md`, `DISPLAY_QUALITY.md`, `FIRST_DELIVERY_QUALITY.md` og
`TETRIS_RUNTIME_REPORT.md`. Senere firmwareendringer må vurderes mot faktiske
diff-er; linjene her refererer til den auditerte revisjonen.

## Felles utgangspunkt for apper og spill

- Venstre **A: Forrige / opp**. Midten **B: Velg / bekreft**. Høyre
  **C: Neste / ned**. Menyer og innstillinger beholder denne rekkefølgen.
  Spillmekanikk kan bruke naturlig venstre/høyre og B-handling, men skal ikke
  kreve chords, app-egne dobbeltklikk eller lange trykk som kolliderer med OS.
- Langtrykk og konfigurerte dobbeltklikk eies av FIRE OS. Genererte apper skal
  ikke prøve å overstyre Home, Back, Quick Settings eller brukerens OS-snarveier.
- Bruk hele **320×240** som et balansert oppsett: tydelig hovedinnhold, korte
  statuser, romslige grafiske elementer og konsekvent knappetilknytning. Det
  betyr ikke å fylle alle piksler med detaljer eller tekst.
- Prioriter et enhetlig visuelt uttrykk, lesbar kontrast, sparsom palett,
  gjennomtenkte ikoner og rask feedback. Ingen lange introduksjoner, små
  debugtekstdumper, unødvendig blink eller treg pynt.
- Spill skal fungere både i korte og lange økter uten automatisk lukking.
  Tilby Nytt spill og relevante innstillinger før oppstart; RGB og spilllyd skal
  kunne slås av når funksjonene faktisk finnes. Ikke vis et virksomt lydvalg
  når Lua-lyd ikke er implementert.

## Faktisk kontrakt i auditerte kilder

| Område | Kilde og funn |
| --- | --- |
| Fysiske knapper | `M5Stack-device/src/fire_os.cpp:32`: A/B/C bruker GPIO39/38/37. |
| Tidsgrenser | `src/fire_os.h:113–115`: langtrykk 650 ms, dobbeltklikkvindu 350 ms, debounce 18 ms. `:141`: dobbeltklikkhandlinger har standardverdi 0, men kan konfigureres av brukeren. |
| Korttrykk til Lua | `src/fire_os.cpp:2988–3040`: behandling skjer etter debouncet slipp. Med OS-dobbeltklikk konfigurert venter et enkelttrykk til vinduet er utløpt. `:3102–3109`: bare `on_button(button,"pressed")` sendes til Lua. Dette er ikke en fysisk nedkant og ikke en released-callback. |
| OS-reserverte handlinger | `src/fire_os.cpp:3047–3084`: lang A=Home, lang B=Quick Settings, lang C=Back. `:3263–3295`: dobbeltklikk åpner konfigurerte OS-skjermer. |
| Lua-knappepolling | `src/fire_os.cpp:5418–5423`: `fire.buttons.pressed` returnerer debouncet `buttons_[index].down` uten kontroll av skjerm eller OS-gestureierskap. |
| Skjerm | `src/fire_os.cpp:1007–1008`: 16-bit 320×240-sprite. `:8111–8127`: appen har hele skjermen og spriten tømmes før hver update. `:6981–6994`: ferdig sprite presenteres én gang. |
| Tekst | `src/fire_os.cpp:5377–5384`: textSize er alltid 1 og tekstbakgrunnen er svart. Ingen Lua-font-/tekststørrelse-/transparenttekst-API er implementert. |
| Nye primitive | `src/fire_lua_runtime.cpp:120–133`, `src/fire_os.cpp:5386–5415`: fill_rect, fill_circle, pixel og grid finnes i API 0.2. Grid fyller celler i samme sprite uten skjermflush per celle. |
| Annonserte tjenester | `src/fire_backend_client.cpp:759–762`: fire-lua-0.2, hash `0b29618a077256268c1dc78512ccf2700517e6c162cbe72f2f4a171dcfc3cd40`, display/buttons/rgb/imu/time/jobs/gpio/pwm/i2c/uart, Lua-minne 131072 byte, lifetime 0. Samtalens audio_input/audio_output er true, men dette gir ingen Lua-speaker/mic-tillatelse. |
| Ressurser | Samme handshake: gpio_read 26/35/36, gpio_write 26, pwm26, i2c0, write-adresse64 og uart2; øvrige ressurslister er tomme. Dette er ikke bevis på fysisk loopback-/bussverifikasjon. |
| Native begrensninger | `src/fire_lua_runtime.h:66–71`: kilde maks100000 byte, Lua-minne131072, instruksjonsgrense200000, callback12ms. `src/fire_lua_runtime.cpp:555/563/574`: load1000ms og top-level/init250ms. `platformio.ini:47–48`: LUA_32BITS=1/LUA_USE_C89=1. |

## Prioritet 1: én eier av knapper og appens pause-/stopptilstand

### Påvist kildeforhold

Quick Settings åpnes i `src/fire_os.cpp:3498–3503`. `draw()` ved
`:6989–6992` tegner forrige skjerm under overlegget. Hvis den var LuaApp,
går dette via `drawLuaApp():8111` til `updateLuaApp():4707`.
Samtidig ser den rå Lua-knappeadapteren ved `:5418` alle debouncete down-verdier.
Det betyr at Lua-kode som poller knapper kan behandle OS-menyknapper som
spillhandlinger mens overlegget er åpent. Dette er en kildebasert
interaksjonsrisiko, ikke en fysisk måling av en bestemt brukerapp.

`onDoubleClick():3263` navigerer via `open():3312–3436`. Denne open-funksjonen
har ingen generell stopp-/frigjøring av aktiv Lua-app ved overgang til annen
OS-skjerm. En app kan dermed beholde aktive tilstander og ressursleases bak
den nye skjermen. Til sammenligning stopper Back/Home eksplisitt appen i
`:3464–3484`, og `stopLuaApp():4595` frigjør maskinvaren.

### Firmwarearbeid

1. Etabler eksplisitt OS-eierskap: Lua får app-input bare når appflaten er
   interaktiv og ingen OS-dialog/overlay/reservert gest eier knappene.
2. Definer Quick Settings som en reell suspend/resume-overgang. Ikke kjør
   spillmekanikk bak overlegget bare for å kunne tegne bakgrunnsbildet.
   Bevar et ferdig bilde eller en avtalt statisk tegnevei uten state-update.
   Ingen ny stor framebuffer må innføres uten målt minnebudsjett.
3. Ved resume: synkroniser tid og knappetilstand. Ikke lever gammel deltaverdi,
   slippkant, pending korttrykk eller menytrykk som en ny spillhandling.
4. Håndter lang-/dobbelgest før apphandlinger. Ikke tell én fysisk interaksjon
   både som polling-edge og senere on_button-callback. Appen må ikke miste
   OS-navigasjon selv om den poller en knapp.
5. Definer en generell overgangspolicy for OS-dobbeltklikk og annen navigasjon
   ut av LuaApp: eksplisitt stopp med normal exit-kvittering og cleanup, eller
   eksplisitt suspend/resume med sikre maskinvaretilstander. Ikke la skjult
   gameplay, PWM, UART, lyd eller uavsluttede jobber fortsette utilsiktet.
6. Ikke endre korttrykksemantikken stille for eksisterende apper. Hvis en ny
   lavforsinket, OS-filtrert inputmodell innføres, må backendkontrakt, simulator
   og capabilities oppdateres sammen. Nåværende backend kan bare stole på
   callbacktypen pressed og dagens pollingmodell.

### Test før fysisk godkjenning

- A/B/C enkelttrykk i meny: nøyaktig én bevegelse/bekreftelse, også etter hold
  og slipp av startknappen. Raskt bytte til en annen knapp mister ikke handlingen.
- Konfigurer OS-dobbeltklikk på hver knapp og test enkelt-/dobbeltrykk på begge
  sider av 350-ms-vinduet. Ingen dobbel spillhandling eller blokkert OS-snarvei.
- Test lang A/B/C rundt 650ms. Home/Quick Settings/Back fungerer alltid; ingen
  ekstra bekreftelse, poeng eller game-over fra gesten som OS konsumerte.
- Åpne Quick Settings midt i en aktiv runde og bruk alle menyknapper. Spillet
  endrer ikke state bak overlegget. Resume gir ingen sprang eller spøkelsesinput.
- Åpne annen OS-skjerm med dobbeltklikk mens PWM/jobber/RGB er aktive. Verifiser
  definerte sikre tilstander, rett kvittering og frigitte/suspenderte ressurser.

## Prioritet 2: faktisk spilllyd og av/på-meny uten konflikt med systemlyd

Lua-speaker/mic er ikke bundet i `registerApi()` ved
`src/fire_lua_runtime.cpp:116–207`, og de er ikke med i handshaken ved
`src/fire_backend_client.cpp:759–762`. Ikke annonser dem eller lag et
tilsynelatende fungerende lydvalg bare fordi AI-samtalen kan spille av PCM.

Firmwarearbeid når Lua-lyd innføres:

- Følg det versjonerte registerets speaker/jobs-signaturer og feilkoder.
  Bruk OS-audiomegler, korte ikke-blokkerende lyder og begrensede jobber.
  Håndter busy og prioriter samtaleopptak/talesvar. Ingen lydarbeid i Lua/UI-task.
- La spillmenyen styre spilllyd før første runde. Ingen oppstartslyd eller
  prøve-tone før brukeren har kunnet velge av. Behold valget ved Nytt spill;
  varig lagring krever faktisk app-private lagringstjenester.
- App-mute må stoppe aktiv spilllyd og hindre ny lyd. Stopp/resume/exit må ikke
  etterlate en tone eller overføre mute-tilstand utilsiktet til andre apper.
- OS-knappelyd er separat: `onButton():3044–3048` kaller
  `playButtonSound():3300–3309` også for LuaApp. Avklar om spill-mute skal
  undertrykke slike pip mens appen eier skjermen, eller om menyen må si
  uttrykkelig «Spilllyd» mens OS-systemlyd følger egen innstilling.
  Ikke endre brukerens globale OS-lydinnstillinger for å implementere app-mute.

Test mutet oppstart, av/på før spill, av mens lyd spiller, appbytte, langtrykk,
AI-talesvar samtidig, opptatt høyttaler og gjentatt start/stopp. Lytt fysisk;
en transport- eller avspillingskvittering alene beviser ikke god lyd.

## Prioritet 3: dokumentert typografi og effektive visuelle virkemidler

Behold dagens API ærlig: textSize1 med svart bakgrunn er det faktisk støttede
tekstuttrykket. Ingen `setTextSize`, nye fonts, transparente etiketter eller
spritebibliotek må dukke opp i generert Lua før de finnes i kontrakten.
Store scoreverdier/enkle ikoner kan eventuelt tegnes som små bitmaprutenett
gjennom eksisterende grid, innenfor celle-/draw-/minnegrensene.

En valgfri typografiutvidelse kan gi merkbart bedre lesbarhet, men må planlegges
som en eksplisitt versjonert kontrakt med målbare glyph-/tekstgrenser,
tekststørrelse, bakgrunns-/gjennomsiktighetssemantikk og fontmål. Ikke bare endre
`luaDisplayText` globalt: gamle apps og backendens clipping-/budsjettkontroll
ville da få annen oppførsel. Behold 0.1/0.2 bakoverkompatibilitet.

Fysisk test hele 320×240-layouten, tekstoverløp, kontrast, sort tekstbakgrunn på
fargede paneler, menyvalg og tall på faktisk skjerm. Test at tekst/rutenett
overholder callbackbudsjettet under lyd-/radio-/SD-belastning. Ikke øk/fjern
watchdog for å skjule treg grafikk.

## Prioritet 4: passende RGB med av/på og lav kostnad

`src/fire_os.cpp:5425–5445` skriver hele RGB-arrayet ved hvert pixel-settkall
med brightness180 i BLE-bygget. Ti set-kall per frame betyr ti strip-flusher,
ikke én batch. `stopLuaApp():4600–4608` nullstiller stripen.

- Bruk RGB ved tilstandsendring eller lav, avtalt effektfrekvens; unngå ti
  komplette oppdateringer per tegnet skjermbilde. Vurder OS-batching av endrede
  piksler før én flush, med tydelig semantikk og regressionstest.
- RGB av må straks slukke appens lys og hindre effekter videre, også etter
  restart av en runde. Behold brukerens valg ved Nytt spill.
- Status må også vises på skjermen; lys alene må ikke være nødvendig for å
  forstå feil, valg eller fremdrift. Unngå strobe og forstyrrende effekter.
- Verifiser slukking ved Home/Back/feil, OS-overlay og dobbeltklikk-navigasjon.

## Prioritet 5: bounded offline-kø med reell mottakskvittering

### Påvist tap-/duplikatrisiko i dagens kilde

`queueLuaDiagnostic()` ved `src/fire_os.cpp:4656–4682` lagrer bare ett sett
pending-felter i NVS. Neste offline-feil overskriver forrige rapport.
`flushLuaDiagnostic():4684–4705` sletter feltene når `appDiagnostic()` returnerer
true. Men `appDiagnostic()` ved `src/fire_backend_client.cpp:581–592` returnerer
resultatet fra `sendEvent():434–450`, altså skriving av WebSocket-frame, ikke
bekreftet serverlagring. `event_ack`-håndteringen ved `src/fire_os.cpp:4950–4958`
har ingen korrelert tømming av diagnostikkøen. Et forbindelsesbrudd etter lokal
send kan derfor miste rapporten. Nye sendEvent-forsøk får dessuten ny event-ID
via `eventId():392–396`.

### Firmware-/protokollarbeid

1. Erstatt enkeltplassen med en liten vedvarende FIFO, eksempelvis 4–8 korte
   poster innenfor et eksplisitt bytebudsjett. Ingen PCM, full appkilde eller
   per-frame-logg. Behold eksisterende begrensede feil-/fase-/heap-/timingfelt.
2. Hver post skal bevare faktisk app-ID/pakke-ID, lokal stabil rapportidentitet,
   årsak, fase og tidspunkt/boot-opprinnelse der kjent. Ikke fabrikker pakke-ID
   for ukjente lokale filer; behold slike funn lokalt til identiteten kan knyttes
   legitimt. Appfeil etter første healthy må fortsatt registreres.
3. Ikke slett en post ved sendFrame=true. Vent på backendens korrelerte positive
   lagringskvittering. Mistet ack skal kunne prøves på nytt uten dobbelregistrert
   feil. Hold bare et begrenset antall in-flight-poster.
4. Koordiner stabil rapport-ID/deduplisering og eventuell opprinnelsesmetadata
   med backendens eksporterte schema/PROTOCOL før nye felter sendes. Ikke send
   gamle session_id/boot_id som en gyldig ny sessions envelope etter reboot.
   Innen samme session kan identisk hendelse retransmitteres med samme event-ID;
   på tvers av sesjoner kreves en avtalt stabil diagnostikkidentitet.
5. Negative/rejected kvitteringer må ikke behandles som lagret suksess. Sett
   posten i en begrenset feil-/karantenetilstand og gi presis status; ikke la
   evig retry blokkere FIRE OS eller konsumere flash/nett uten grenser.
6. Ikke overskriv uavsendte rapporter stille ved full kø. Definer en bounded
   overflow-/sammenslåingspolicy med synlig antall tapte/sammenslåtte hendelser
   og første/siste tidspunkt. En endelig kø kan ikke garantere uendelig offline
   historikk; dette skal rapporteres ærlig, ikke skjules som «alle feil lagret».
7. Skriv ved enqueue/ack eller sikkert avgrenset batch, ikke hver frame.
   Oppdateringer skal tåle reboot/strømbrudd. Prioriter normal UI og minnebruk.

### Tester

- To ulike appfeil offline beholdes begge, med korrekte pakkeidentiteter.
- Reboot før send, under send og etter serverlagring/før ack mister ikke posten.
- Mistet ack/reconnect gir én backendregistrering per avtalt stabil rapport-ID.
- Feil session/boot, annen enhets pakke eller negativ ack sletter ikke posten
  som om rapporten var godtatt.
- Fyll køen og kontroller dokumentert overflow-/count-status uten stille
  overskriving eller ubegrenset vekst.
- Bekreft at appen kan avsluttes og OS navigeres mens køen er offline/full.

## Hva device-agenten skal rapportere tilbake

For hvert tiltak: commit/firmwareversjon, faktisk annonsert capabilityprofil,
konkret test og resultat, samt hva som bare er kilde-/byggeverifisert.
Fysisk godkjenning krever ekte FIRE, faktiske knapper/skjerm/høyttaler/RGB og
avbrudds-/reconnecttester. PC-release eller en tidlig app_healthy erstatter ikke
dette. Backend skal fortsatt kreve eksplisitt BUILD og RUN; disse endringene
gir ingen autorisasjon til automatisk kjøring eller firmwareflashing.

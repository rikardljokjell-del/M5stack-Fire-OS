# Felles standard for apper og spill på FIRE

Denne standarden gjelder automatisk ved ny app, oppdatering og reparasjon. Målet
er en app laget spesielt for M5Stack FIRE og FIRE OS, ikke et nedskalert
skrivebordsprogram. Backend bruker versjonen `fire-experience-v1` i planlegging,
kodegenerering, test og separat kildegjennomgang.

## Knapper og menyer

| Fysisk knapp | I menyer, lister og innstillinger |
| --- | --- |
| Venstre / A | Forrige / opp |
| Midten / B | Velg / bekreft |
| Høyre / C | Neste / ned |

Valgt element skal være tydelig markert, og handlingen gi rask feedback. Gameplay
kan tilpasses mekanikken, normalt A/C for retning og B for hovedhandling. Samme
korte trykk skal ikke bety både spillhandling og en motstridende pause/restart.
Ingen nødvendige kombinasjoner, dobbelttrykk eller hold-for-bekreft.

OS eier lange trykk på 650 ms: A=Hjem, B=Hurtiginnstillinger, C=Tilbake. OS eier
også konfigurerte dobbeltklikk med 350 ms vindu. Native `on_button(...,"pressed")`
leveres etter slipp, eventuelt forsinket av OS-dobbeltklikk. Ikke behandle den som
fysisk nedtrykk, finn på released/long/double-events eller utfør samme handling
via både callback og polling. Kontinuerlig gameplay-polling må ha ett tydelig
ansvar og respektere OS-eierskapet.

## Skjerm og visuell kvalitet

Hele 320×240-flaten er tilgjengelig. Bruk den med balansert komposisjon, korte
tekster, tydelig hierarki og konsekvent spacing/ikoner. Full skjerm betyr ikke
at hver piksel skal fylles med innhold. Ha lesbar kontrast, en gjennomtenkt
begrenset palett, tydelige tilstander og stor nok sentral spill-/verktøygrafikk.
Bevegelse skal forklare handling/status eller gjøre opplevelsen bedre; ingen
langsomme introduksjoner eller overdrevne overganger.

Faktisk API må respekteres: dagens tekstfunksjon bruker fast størrelse 1 og svart
bakgrunn, uten skriftstørrelse eller transparent tekst. Bruk korte etiketter og
større figurer/ikoner/tall via eksisterende geometri/grid der egnet. Ikke finn opp
font-/sprite-/bildelastere. Bedre native typografi krever en avtalt API-utvidelse.

OS blanker spriten før hver update og presenterer den ferdige scenen én gang.
Tegn hele scenen også ved venting/pause/game-over. Ingen blanke mellomrammer.
Mellomlagre tekst/geometri/state, begrens effekter og hold deg innen faktisk
minne-/callbackbudsjett: typisk 128 KiB Lua, 12 ms callback, backend 24 outputkall,
256 tekstbyte og 120000 estimerte displayarbeidsenheter. PC måler ikke fysisk
skjerm eller native tidsbruk.

## Spill og effektinnstillinger

Før spillet starter: en rask meny med Nytt spill/Start, RGB av/på, lyd av/på og
bare relevante spillvalg. Bruk A/B/C-konvensjonen. Behold innstillinger mellom
runder. Lyd starter av og kan aktiveres i menyen hvis ekte Lua speaker+jobs finnes.
Manglende tjenester vises som utilgjengelige eller utelates; ingen falsk bryter.
Samtalens audio_output=true gir ikke Lua-lyd. Gjeldende inspiserte firmware har
ennå ikke Lua speaker.

Bruk passende korte lyder og RGB-feedback. Mute stopper/avbryter/frigir aktive
lydjobber; RGB av slukker LED-ene. Begrens RGB-oppdateringer til tilstandsendringer
eller lav frekvens; hver setter flusher stripen. Spillmute lover ikke å slå av
OS-knappelyder. OS har ansvaret for endelig ressursfrigjøring ved appstopp.

Spillmekanikken skal fungere godt med tre knapper, med klart adskilte objekter,
god respons, forståelig vanskelighetsgrad og meningsfull poeng-/nivåprogresjon.
Rask oppstart og både korte runder og lang spilling. En rundetimer kan vise
game-over; den skal ikke automatisk lukke appen. Nytt spill bekreftes eksplisitt,
og trykket som avsluttet forrige runde må ikke utilsiktet starte neste.

Ugyldige handlinger, manglende nett/modul, opptatte ressurser og avbrudd skal gi
kort tydelig status og raskt returnerende callbacks. Bevar relevant state der
API-et tillater det. Ikke påstå varig lagring når SD-tjenesten mangler.

## Håndheving før levering

- Backend lager kontrakten fra faktisk session-capabilities. Ingen ny eller
  uannonsert maskinvare gis tilgang bare for å oppfylle designønsket.
- Nye livebygg kjører vanlige releaseprofiler, fire profiler for OS-reserverte
  handlinger og én lang profil. Ubegrensede apper testes i ti simulerte minutter;
  legacy levetid forlenges ikke. Workerens tids-/minnegrenser beholdes.
- Separat `FireAppReview` må godkjenne krav, runtime, grafikk, treknappslogikk,
  OS-reservasjoner, skjerm/lesbarhet, spillopplevelse, settings/effekter og
  feil-/avbruddshåndtering. Alle feltene må være til stede og godkjent.
- Godkjenning bindes til faktisk kildehash og policyversjon. Funn returneres til
  automatiske rettinger; endret kilde testes/gjennomgås igjen. Manglende, gammel
  eller avvist kontroll godtar ikke en ny livepakke. Eldre pakker omskrives ikke.
- Mockeksempler er begrensede API-fixtures merket mock, ikke godkjent fysisk
  grafikk/UX. De må ikke rapporteres som live test av denne standarden.

Testprofilene forutsetter korrekt OS-eierskap og er syntetiske. Gjeldende
firmwarefunn om overlay/input og navigasjon må rettes av device-agenten; se
[DEVICE_EXPERIENCE_HANDOFF.md](DEVICE_EXPERIENCE_HANDOFF.md). En god PC-test alene
beviser ikke at disse firmwarefeilene er borte.

## Feil, retting og tilbakefallsvern

Hver mottatt feil klassifiseres med pakke-/kildeidentitet og relevante event-,
boot-, run- og callbackdata. Installasjonsfeil skilles fra kildefeil. Interne
avviste byggeforsøk knyttes også til første godkjente pakke.

En rettingspost viser gammel/ny kildehash, endrede funksjoner/linjer, relevante
før-/ettertestmål, kontrollregel og eventuelt modellens forklaring på rettelsen.
Modellforklaringer og rå logger blir aldri globale systeminstrukser. Bare faste,
gjennomgåtte regresjonsregler brukes i senere genereringer. Identisk kode med
korrelert native runtimefeil fra livebruk kan sperres på tvers av nye prosjekter,
uten å beholde appkilde/navn etter sletting. Brukerrapport/transportfeil alene
skal ikke forgifte alle nye apper med samme kildehash.

Tidlig app_healthy er en observasjon, ikke bevis på endelig reparasjon. En senere
feil oppdaterer rettingshistorikken. Fysisk verifikasjon må skilles fra PC-kandidat.
Device må levere feil pålitelig; én enkelt offline-loggplass er ikke tilstrekkelig.

I Windows: Apper → velg app/versjon → **Feil og rettinger** viser de siste
registrerte feilene, rettingskandidaten, endringen og tilbakefallstesten.

Verifikasjon 22. november: 361 automatiske tester besto, inkludert den utvidede
kontrollporten, feilminnet og en feil først etter ni simulerte minutter. Isolert
ekte OpenAI lagde «Fallende stjerner» fra et kort spillønske på første interne
forsøk: 12 profiler, ti minutters simulert langtidsprofil, alle UX-kontroller
godkjent. Kandidaten har meny/Nytt spill, A/B/C-navigasjon, fungerende RGB-valg
og en ærlig beskjed om at lyd er utilgjengelig. Ingen kommando ble sendt til FIRE.
Kilde-SHA256: `082eb517360f97cf79600daf03a80e4080fe6d7eda3f2952aab73ffd53fab5bc`.
Dette er kilde-/PC-verifikasjon, ikke fysisk spill-, lyd- eller skjermverifikasjon.

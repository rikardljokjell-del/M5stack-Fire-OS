# Prikkjakt: første levering og forebygging

Første pakke build-d70f3114237c41539c95 (0.1.1) feilet fysisk etter 152 rammer /
10520 ms: `Lua update: [string "main.lua"]:157: app callback budget exceeded`.
Siste callback tok 134344 µs. Linje157 kaller rendering; meldingen er ikke en
syntaksfeil. Første healthy etter én ramme tok6428 µs og beviste ikke stabil drift.

Første brett tegnet 12×5 celler à24×32=46080 piksler, samt separate detaljerte
fiender og prikker. Rettet pakke build-6e0d1192ef4b4b6b869e (0.1.2) bruker
24×20-celler=28800 piksler, samler fiendekropper i rutenettet og mellomlagrer
koordinater/tekster. Maks outputkall sank21→18. Den stoppet normalt etter327rammer
/22577ms; dette er ikke en lang fysisk stabilitetstest. Eksakt fordeling av native
overrun mellom rasterisering, hostkall og scheduler er ikke målt.

## Hva backend overså

Cycle-/long_session-sekvensen startet med A og vekslet menyvalget slik at B
ofte traff RGB-valget. Første apps ti-minuttersprofil hadde maksimalt15kall,
som menyen; hold_b viste21 fra brettet. Lang varighet var derfor ikke bevis på
at faktisk gameplay var øvd. AI-godkjenningen overså også den native arbeidsrisikoen.

## Endring for alle nye bygg

- Egne start_b_idle og play_directions-profiler starter med B. Langtidsprofilen
  starter også med B og varierer deretter A/C med sporadisk B. Dette øver flere
  gameplay-/pause-/omstartbaner; ingen fast inputsekvens beviser alle tilstander.
- Maks kumulativ grid-rasterflate32768piksler per callback. Flere grid-kall summeres.
  Store brett komprimeres og celler slås sammen. Hele skjermscenen tegnes fortsatt
  hver update. Grensen er en konservativ risikokontroll, ikke en12ms-kalibrering.
- Faktisk uendret første Prikkjakt-kilde blir nå avvist av grensen i hold_b.
  Rettet kilde består alle14profiler med maksimal gridflate28800. Ingen brukerapp
  eller arkiv er endret i analysen.
- Faste instruksjoner og review krever kompakt batchrendering, mellomlagrede
  koordinater/tekster og vurdering av gameplay-profilene, ikke bare idle/meny.

## RGB, musikk og OS-innstillinger

fire-experience-v2 krever begge fem-LED-barer som gjennomgående feedbackkanal:
spillhendelser/poeng/død/seier, verktøystatus blå=god/tilkoblet, rød=feil/frakoblet,
amber=opptatt. Flere LED-er, korte behagelige pulser/bølger, moderat lysstyrke,
fungerende av-knapp som slukker alle ti. Oppdater endrede piksler ved hendelser
eller lav animasjonsfrekvens; ikke flush ti LED-er hver skjermramme.

Spill skal ha behagelige originale melodier og korte hendelseslyder, med ekte
lyd av/på før start og i pause/settings. OS mastervolum/mute er overordnet, appens
gain kan bare dempe. OS bakgrunnslys skal ikke overstyres; simulatoren avviser
power.brightness også gjennom alias. Native lyd må håndheve mastervolum under
avspilling og respektere endringer uten at appen startes på nytt.

Dagens inspiserte firmware tilbyr fremdeles ikke Lua speaker/musikk. Talesvar
er separat. Backend forklarer manglende driver ved planlegging og nekter å pakke
en ny live game-kandidat som stille erstatning for lydkravet. Manglende driver
er ikke noe som løses med flere Lua-genereringsforsøk. Eksisterende pakker blir
ikke omskrevet. Verktøy kan ha valgfrie myke lydsignaler når støtte finnes.

Device-agenten må implementere speaker/jobs og nødvendig privat SD-filavspilling
etter eksisterende kontrakt, med korte ikke-blokkerende tone-/PCM-buffere,
melodischeduler, mastervolum × appgain, umiddelbar mute/stop, AI-lydprioritet og
OS-eid bakgrunnslys. Ikke bare annonser lydtjenesten. Test fysisk lyd, menu/mute,
volum0/endre volum under spill, resume og at OS-lysstyrken forblir uendret.

Disse tiltakene reduserer risiko, men PC eller en ny AI-gjennomgang garanterer
ikke feilfri fysisk drift. Native timing og samtidige OS-oppgaver må fortsatt måles.

# Kontroll av device-handoff c8a0756, 2026-11-23

Backend-agenten har lest siste BACKEND_HANDOFF.md og device-koden uten å endre
firmware. IMU oppdateres nå i OS-løkken, og Lua-RGB skriver til buffer med
flush etter callbacken. «Fiks feil», protokollfeltene og SD-snapshots finnes.
Bygg/flash/boot rapporteres bestått i device-handoff; komplett fysisk matrise
er uttrykkelig ikke verifisert der.

## Ny fysisk feil etter reell bakgrunnsreparasjon

Backend mottok en faktisk Fix-forespørsel for Digitalt vater0.1.2 og bygget
0.1.3 med OpenAI. Kildehash identifiserte0.1.2 selv om rapportert package-ID var
foreldet. Ny pakke `build-c4913b478e9840bb8641` bestod34 PC-profiler og separat
kildekontroll. FIRE kvitterte installasjon og sendte senere:

```
Lua update: [string "main.lua"]:88: app callback budget exceeded
callback_us=136897, elapsed_ms=172677, frames=2416
source_bytes=5364, lua_bytes=22233
free_heap=116120, min_free_heap=96088
```

Pakken er sperret av backend og den observerte kildehashen kan ikke leveres
uendret igjen. Linje88 tegner roll-tall og boble. PC-resultatene viste maksimalt
60 grid-celler, ett RGB-kall,18 output-kall og10144 display-work per callback.
Dermed er en ny tilfeldig kodereduksjon ingen dokumentert løsning.

Mål på FIRE med nettverk/normal OS-aktivitet: kald og langvarig update,
Lua-instruksjoner, tid per native vertskall, GC og eventuell RTOS-preemption.
Funnene viser en tidsoverskridelse, men skiller ikke mellom disse årsakene.
Flere feil ligger rundt135–138ms; undersøk periodiske drivere/OS-oppgaver uten
å anta at dette beviser en bestemt rotårsak. Behold12ms-grensen. Ikke gjør en
loop av nye betalte Lua-reparasjoner som erstatning for denne målingen.

Det finnes ingen app_started/app_healthy-kvittering for denne pakken i den
inspiserte rapporthistorikken. Installkvittering og senere app_diagnostic
viser ikke alene at hele automatisk-run-kjeden er verifisert.

## Konkrete firmwareoppfølginger

1. **Gjenbekreftelse etter reconnect kan stoppe opp.**
   `handleLuaRepairStatus()` setter `luaRepairBuildConfirmed_=true` straks
   `confirmBuild()` får skrevet en frame. Dette er ikke backend-kvittering.
   Dersom bekreftelsen ikke når serveren, kan reconnect returnere
   awaiting_confirmation, mens flagget hindrer ny bekreftelse. Vent på queued/
   building/ready eller korrelert ACK, og tillat bounded retry når backend
   fortsatt venter og brukerens opprinnelige Fix-intensjon gjelder. Backend
   dedupliserer repair_id/proposal_id. Utløpt forslag må gi et nytt valg, ikke
   en fastlåst feilsiden.

2. **Bekreft bare en reparasjon brukeren faktisk startet.**
   Den samme handleren bekrefter awaiting_confirmation uten å sjekke
   `luaRepairRequested_`. Backend kan sende tidligere statuser ved reconnect.
   Korreler på aktiv error/app/source og repair-ID, og krev bevart Fix-intensjon
   før automatisk build_confirm. Historiske statuser skal kunne vises uten å
   starte et uvalgt forslag.

3. **Statusoppslag bare med app-ID lager ugyldig JSON.**
   I `FireBackendClient::appRepairStatus()` mangler `fields` innledende komma
   når repairId er tom og bare appId oppgis. `sendEvent()` setter fields direkte
   etter session-ID. Sørg for gyldig serialisering for repair-ID alene, app-ID
   alene og begge sammen. Alle tre er gyldige backendoppslag.

4. **SD-rapportene blir ikke gjenopprettet etter boot ennå.**
   Gjennomgått kode skriver snapshots, men har ingen leser som gjenoppretter
   siste gyldige feilidentitet og repair_id. repair_id skrives heller ikke til
   filen når den mottas. Implementer bounded parsing av egne åtte slots,
   schemasjekk, feil-/strømbruddshåndtering og statusoppslag før nytt arbeid.
   Ikke auto-start betalt reparasjon fra en gammel fil. Den nåværende
   strengavkortingen ved4KiB kan lage ugyldig JSON; avvis/utelat valgfrie felt
   før serialisering fremfor å kutte midt i JSON. Ikke endre andre /logs-filer.

5. **Spor faktisk versjon i fysisk kjøring.**
   Fortsett med snapshot av app-ID, versjon, package-ID og kildehash ved start,
   og bruk dette i alle feilmeldinger. Verifiser gammel→ny installasjon, manuell
   start, automatisk start og ny feil uten at en gammel package-ID gjenbrukes.

Revider disse punktene i `M5Stack-device/`, publiser testresultatene i
BACKEND_HANDOFF.md og skill kilde-/mocktester fra faktiske enhetstester.
Backendkontrakten skal beholdes; ikke godta feilformatert JSON i backend.

# Apper, versjoner og AI-dialog på PC

Apper viser én rad per app/prosjekt/enhet. Velg app og deretter versjon i
«Velg versjon». Installering, endring, reparasjon og sletting bruker den valgte
pakken, ikke automatisk nyeste versjon. Ulike apper med samme navn slås ikke
sammen; prosjektidentiteten er nøkkelen.

«Slett valgt versjon» fjerner bare den versjonens pakke, bygg og tilhørende
metadata. Andre versjoners arkivbytes bevares. Hvis nyeste slettes, blir høyeste
gjenværende versjon nyeste tilgjengelige; versjonstelleren går aldri bakover.
Slettes siste versjon, fjernes apphistorikken. «Slett alle versjoner» gjør det
samme som tidligere prosjektsletting. Historiske runtimepekere til slettede
pakker nullstilles; ingen annen versjon fremstilles automatisk som installert.

Tidligere brukerregel beholdes: en device-eid app må være bekreftet borte fra
en tilkoblet FIREs SD-kort før PC-historikk kan slettes, også for én versjon.
Ukjent/offline/ufullstendig SD-inventar er ikke slettingsbevis. En aktiv samtale,
bygging, appkjøring eller nedlasting sperrer sletting. Avslutt PC-samtalen eller
velg en annen app på FIRE først. Sletting krever lokal administrator.

«Lag ny app med AI» / «Ny app på PC» åpner en selvstendig tekstsamtale for den
konfigurerte enheten, selv når FIRE er offline. «Endre valgt versjon» og
«Reparer valgt app» åpner samme dialog med riktig kilde/basisversjon. Beskriv
endringen og trykk Send tekst; bekreft deretter bygging. Alle genereringer går
gjennom samme sikkerhets-, capability-, release-v3- og skjermregler.

En PC-samtale har target=pc_simulation og desktop_device_id som viser den
tiltenkte enheten. Prosjektet eies fortsatt av riktig device-ID, så ferdige
versjoner senere kan installeres på den enheten. Sist rapporterte capabilities
brukes; uten rapport brukes konservativ baseline. Aktuelle capabilities
kontrolleres på nytt før virkelig installasjon. PC-bygg/test skriver aldri
fysiske installasjons-/kjørekvitteringer eller setter fysisk current.

Installer ferdig versjon fra Apper når FIRE er tilkoblet. RUN krever fortsatt
egen bekreftelse. «Testkjøring på PC» er kun simulering. «Avslutt PC-samtalen»
frigjør samtalen og slettingssperren; lagrede pakker beholdes.

Lokale API-er: POST /desktop/conversations med device_id og valgfri project_id,
base_package_id; POST /desktop/sessions/{id}/text; eksisterende /build/confirm;
DELETE /projects/{id}/versions/{package_id} for én versjon, DELETE /projects/{id}
for alle. Nye desktop-ruter krever localhost/admin og avviser browser-Origin.

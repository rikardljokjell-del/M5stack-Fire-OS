# Jobber i Windows-programmet

Jobber viser aktive og tidligere bygg, oppdateringer og reparasjoner, samt
pågående samtale eller taletolkning og feil før et bygg har startet.
Aktive jobber kommer først. Oversikten hentes lokalt omtrent hvert andre sekund
uten betalte API-kall. Velg en rad for fase, fremdrift, forsøk, plan,
siste kontrollfunn, stoppårsak, kapasitetens retry-tid og anslått jobbpris.
API-konto/kvote, lokale kostnadsgrenser, tidsavbrudd og kansellering bevares
med redigerte diagnostikkdetaljer. Ferdige/feilede bygg beholdes etter omstart.

## Manuell kontekst

Velg aktivt bygg og skriv opptil2000 tegn. Maks åtte tillegg per jobb.
Tillegget lagres separat fra den opprinnelige bekreftede planen og merkes
ventende. Neste generering tar med alle tillegg i rekkefølge. Et allerede
pågående modellkall kan ikke endres. Endres kontekst under generering eller
kontroll, godtas ikke den gamle kandidaten som oppfylt ny plan. Neste tillatte
forsøk bygger/kontrollerer på nytt; ved brukt rettingsgrense stoppes jobben med
ventende kontekst bevart. Ingen ekstra automatisk omgåelse av budsjett eller
rettingsgrense. Vanlige Lua-, maskinvare- og kvalitetsporter gjelder fortsatt.

Pakkefasen låser tilleggsfeltet for å unngå endring etter siste kontroll.
Et ferdig/feilet bygg endres ikke; fortsett utviklingen i Aktivitet. Ingen ny
modellforespørsel startes bare ved å lagre kontekst. Installasjon og kjøring
bruker fortsatt den vanlige eksplisitte bekreftelsesflyten.

Admin-API: GET /desktop/jobs, POST /desktop/jobs/{build_id}/context med
{"text":"..."}. Vanlig device-token kan ikke lese eller skrive her.
Kontekst og kontrollfunn lagres lokalt; hemmeligheter maskeres som ellers.

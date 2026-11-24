# Godkjent leveranse for FIRE OS

Godkjent av Rikard 24. november 2026. Arbeidet skal fortsette uten nye
brukeravklaringer underveis. Kontooppsett, manglende ekstern tilgang og manuelle
sluttester samles til slutt; uavhengig arbeid fortsetter. Manglende testbevis
skal aldri erstattes av en påstand om produksjonsklar eller fysisk verifisert.

## Fast arkitektur

| Funksjon | Datavei | Avhengig av backend-PC |
| --- | --- | --- |
| Home | FIRE direkte til Home Assistant-infrastruktur via begrenset MQTT | Nei |
| Firmware | FIRE direkte til signert GitHub-katalog og firmware | Nei |
| Selvstendige installerte Lua-apper | Lokalt på FIRE | Nei |
| AI-dialog, tale, kontekst og Lua-generering | FIRE/nettleser til backend til OpenAI | Ja |
| Appbibliotek og backendinnstillinger | Nettleser til samme lokale backendprosess | Ja |
| Firmwareoversikt i backend | Kun GitHub-metadata og rapportert enhetsversjon | Ja, for denne visningen |

Ingen egenutviklet HA-app eller custom integration. Gjenbruk eksisterende
MQTT-broker, eller tilby ferdig standard Mosquitto med tydelig oppsett.
Ekstern Home-tilgang må være uavhengig av Windows-PC-en. Ingen generell
HA-legitimasjon eller OpenAI-nøkkel på FIRE eller i genererte Lua-pakker.

## Arbeidsdeling

- Device-agent: `M5Stack-device/` og `firmware/`, native Home, sikre klienter,
  respons, oppstart, direkte GitHub-oppdatering, tilbakeføring og recovery.
- Backend-agent: `M5Stack-backend/`, browser-/device-autentisering, webUI,
  appbygger, varig AI-kontekst, native HA-oppsett og versjonerte kontrakter.
- Master: delt baseline, integrering, rotveiledninger, uavhengig vurdering,
  samlede kontroller og sluttrapport. Master eier git-integrering/publisering.

Ingen agent skal tilbakestille eller overskrive en annen agents arbeid.
Grensesnitt avtales tidlig og endres samordnet. En lokal simulasjon, vellykket
kompilering eller annonsert kapabilitet beviser ikke fysisk funksjon.

## Leveranser og akseptanse

1. **Responsiv grunnplattform:** ingen ventende connect/TLS-/SD-sløyfe i
   knapp-/skjermløkken; begrensede køer og avbrudd; separat tidsmåling av
   callbacks og OS-løkke; riktige ferdigvarsler og gjenoppretting.
2. **Sikker global AI:** HTTPS/WSS for kontroll, lyd og pakker; sertifikat og
   vertsnavn valideres; enhetsidentitet isoleres; reconnect beholder samme
   kontekst/jobb uten automatisk nytt betalt kall eller appstart.
3. **WebUI:** mobil-/PC-visning av status, innstillinger, samtaler, bygg,
   bibliotek, versjoner og kostnad. Hemmeligheter er write-only. Nettleser og
   enhet har adskilt autentisering. Proxytrafikk fra loopback er aldri i seg
   selv administrator. Eksplisitt BUILD/RUN beholdes.
4. **Firmware:** backend viser bare GitHub-versjoner og kort info. FIRE henter
   direkte; target, størrelse, hash og signatur kontrolleres. Inaktiv OTA-slot,
   forsinket helsegodkjenning og tidligere fungerende versjon beholdes.
   Separat redningsapp velges før vanlig firmware. Engangs USB-migrering må
   være sikker, dokumentert og gi backup/kompatibilitetskontroll.
5. **Direkte Home:** native pen kort-/flisvisning med Home/Camper, innstillinger,
   favoritter og layout. HA eier katalog og tillatelser. Broker-ACL og faste
   HA-automations validerer lesing/styring, profil, handling og verdigrenser.
   Ingen retained kommandoer eller automatisk repetisjon ved ukjent resultat.
   Lokal/Internett/Auto og HA-styrt fjernaksess håndheves reelt.
6. **Enkelt oppsett:** samlede norske steg for backend, Cloudflare/DNS/innlogging,
   MQTT, HA-pakke/merking, paring, engangs USB og fysisk sluttkontroll.

## Bevis som skal registreres

- Eksakt kildeversjon og testkommando med resultat.
- Firmware-build, binærstørrelse, SHA256, bootloader/partisjoner og signatur.
- Hva som er mock, ekte lokal transport, nettleserprøve, fysisk FIRE eller
  brukerbekreftet HA/eksternt nett.
- Nettbrudd under tale, bygg, nedlasting og installasjon; duplikater og tapte ACK.
- Home lokalt og eksternt med Windows av; fjernede HA-tillatelser og feil token.
- Firmwarefeil før godkjenning, ødelagt normal Wi-Fi/UI, og redning uten backend.

## Eksterne forutsetninger til samlet sluttoppsett

- Fast domene og innlogging/kontotilgang for offentlig backend/webUI.
- HA-installasjonstype, eksisterende MQTT og egnet alltid-på vert for ekstern Home.
- Valg av faktiske HA-entiteter og handlinger av HA-administratoren.
- Fysisk FIRE for engangs migrering og de testene som krever enhet/strøm/knapper.

Ingen kontoer, domener eller betalte tjenester kjøpes som følge av planen.
Maler og installasjonssteg klargjøres selv når disse opplysningene mangler.

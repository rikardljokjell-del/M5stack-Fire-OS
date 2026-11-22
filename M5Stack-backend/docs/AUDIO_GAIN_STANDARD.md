# Hørbar applyd under OS-mastervolum

Melodiverksted0.1.2 brukte `speaker.tone(...,44)`. Firmware sender dette til
M5Unified.setChannelVolume: en ekstra app-/kanaldemping i området0..255, ikke
prosent og ikke OS-mastervolum.44 er bare omtrent17% av kanalinnstillingen;
det bidrar til den nesten uhørbare lyden brukeren rapporterte.

Ny permanent standard: primær melodi/musikk/applyd bruker255/255 som utgangspunkt.
Brukeren styrer samlet lydstyrke med OS-hovedvolumet. OS-mute/volum0 forblir stille;
appen endrer aldri mastervolum eller bakgrunnslys. Lavere appgain er bare for
et tydelig valgt dempingsnivå eller bevisst svakere sekundære effekter. Behagelige
melodier oppnås gjennom toner, rytme og arrangement, ikke skjult nær-mute.

AI får både eksplisitt gain-kontrakt og faste instruksjoner. Separat
FireAppReview har audio_level_ok som eget vilkår. Lydsekvenser skal aktivere
lydvalget og faktisk starte tonejobber; stille animasjon er ikke lydtest.
Feilminnet har egen audio_level-regel og tilbakefallskontroll.

Melodiverksted0.1.3 endrer bare kanalargumentet44→255. Avhengighetene
speaker/jobs/sd fra forrige retting beholdes. Den tidligere manifestfeilen og
den svake lyden har forskjellige årsaker; begge er nå eksplisitte backendregler.
PC og kildegjennomgang kan ikke måle fysisk lydnivå på FIRE.

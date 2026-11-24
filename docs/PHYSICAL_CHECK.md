# Sluttest på din M5Stack FIRE

Dette er testen på din fysiske enhet. USB-migrering og deler av oppstart/rollback
er nå prøvd, som beskrevet i [USB-beviset](../M5Stack-device/PHYSICAL_USB_2026-11-24.md).
De øvrige punktene er ikke dermed bestått. Bruk den
ferdige leveransepakken og gjør ett punkt om gangen. Noter firmwareversjonen
som vises under **Settings → Firmware**.

Rikards FIRE er allerede migrert og kjører RC7 i **B / app1**. Gå videre med
meny-/knappetestene og funksjonene under; første USB-migrering er utført.
Hvis du prøver redning på denne enheten, velger du **B / app1** for å komme
tilbake til valgt RC7. A inneholder også ren RC7; testutgaven er fjernet. Steg 1 nedenfor
beskriver førstegangsoppsett på en ny enhet, der pakken skriver normal til A.

A og C flytter valget. B åpner eller bekrefter. Følg også knappeteksten nederst
på skjermen; redningsmenyen har egne valg.

## 1. Første oppstart med den nye redningen

1. Følg [USB-veiledningen](../M5Stack-backend/docs/USB_MIGRATION.md) i rekkefølge:
   pakkekontroll, riktig FIRE/USB-port, forhåndskontroll og migrering med backup.
   Ta vare på backupmappen. Ikke bruk vanlig firmwareopplasting i stedet.
2. Etter migreringen skal **FIRE redning** vises. Hold A for å åpne valg av OS.
3. Velg **OS-slot A / app0**, kontroller den viste versjonen, og trykk B for å
   starte. Den nye FIRE OS-versjonen skal åpnes. At et bilde er merket gyldig,
   betyr ikke at det allerede er testet i bruk.
4. Åpne noen menyer, gå tilbake og start FIRE på nytt. Knapper og skjerm skal
   reagere, og lagrede innstillinger skal være der etter omstart.

Oppsett av nett, Studio og Home står i [Kom i gang](../SETUP.md).

## 2. Home lokalt, med Windows-backenden stoppet

1. Gjør Home-oppsettet fra [Kom i gang](../SETUP.md#3-koble-home-til-home-assistant).
   Begynn med ett lys. I Home åpner du **Innstillinger** og setter
   **Forbindelse: Lokalt**.
2. Åpne lyskortet. Velg **Slå på** eller **Slå av**, og bekreft. Kontroller både
   det virkelige lyset og oppdatert status på FIRE.
3. Stopp FIRE-backenden i Windows. La Home Assistant og Home-tjenesten være på.
   Prøv lyset igjen: Home skal fortsatt fungere.
4. Prøv **Visning: 2 x 2 kort**, **Stort kort** og **Favoritt**. Tekst og verdier
   skal være leselige, og valgene skal reagere med en gang. Har du konfigurert
   Camper, bytt profil og kontroller at riktig sted og riktige kort vises.

## 3. Tilgang bestemmes i Home Assistant

1. Fjern etiketten **fire_home_control** fra testlyset i HA. Ny styring fra FIRE
   skal ikke endre lyset. Styringsvalgene skal forsvinne når kortet oppdateres.
2. Fjern også **fire_home_read**. Kortet skal forsvinne; vent opptil 30 sekunder.
3. Legg tilbake bare etikettene du ønsker å tillate, og kontroller resultatet.
   Prøv deretter eventuell varme eller andre handlinger du har valgt i oppsettet.

## 4. Home over internett og av/på-bryteren

Dette punktet brukes etter at ekstern Home er satt opp etter
[veiledningen](../SETUP.md#4-slå-ekstern-home-av-og-på). Windows-backenden kan
fortsatt være stoppet.

1. Koble FIRE til et annet Wi-Fi, for eksempel mobilens hotspot. Velg
   **Forbindelse: Internett** i Home. Slå på HA-bryteren
   **FIRE home tillat fjernaksess** og prøv testlyset.
2. Slå bryteren av i HA mens FIRE fortsatt er på det andre nettet. Nye eksterne
   handlinger skal avvises, og kortene skal forsvinne. Slå på igjen og kontroller
   at tilgangen kommer tilbake.
3. Med bryteren av: koble FIRE tilbake til hjemmenettet og velg **Lokalt**.
   Lokal styring skal fortsatt virke. Velg **Auto** når begge forbindelser er
   kontrollert, hvis du ønsker automatisk bytte.
4. Med ekstern tilgang tillatt: la **Auto** stå på et annet nett i minst tre
   minutter. Status og styring skal fortsette uten faste minuttvise avbrudd.
   En fungerende forbindelse beholdes; nytt rutevalg skjer ved nettbrudd eller
   endret oppsett.

## 5. AI, mobilnettleser og samme jobb etter nettbrudd

1. Start Windows-backenden og AI-tunnelen igjen. La PC-en være på hjemmenettet,
   mens FIRE bruker det andre Wi-Fi-nettet. Åpne Studio fra mobilens nettleser.
2. Prøv en kort talesamtale fra FIRE. Be deretter om en enkel app. Les forslaget,
   bekreft bygging én gang, og noter hvilken jobb du åpnet.
3. Mens byggingen pågår: koble FIRE midlertidig fra Wi-Fi og lukk nettleseren.
   Koble til igjen, åpne den samme jobben og bruk **Fortsett samme jobb** hvis
   den ber om det. Jobben skal ikke bli erstattet av en ny, lik jobb.
4. Installer den ferdige pakken og bekreft kjøring separat. Kontroller at appen
   faktisk åpnes på FIRE. Prøv også å starte et appbygg fra Studio i nettleseren.

## 6. Avbrutt firmwarenedlasting og vanlig oppdatering

Den automatiserte fysiske testen har allerede hentet RC7 fra GitHub, avbrutt
ved én prosent uten å endre oppstartsvalget, prøvd igjen og startet vanlig
RC7 med lagret helsegodkjenning. Punktene under kan brukes til din egen
meny-/knappetest og nettbruddstest; førstegangs USB-migrering trengs ikke.

Fra RC7 krever vanlig GitHub-oppdatering ikke SD-kort eller Windows-backend.
Ha strøm til FIRE. Nettbruddstesten gjelder overføringen før ny firmware
aktiveres; la strømmen være tilkoblet under hele testen.

1. Åpne **Settings → Firmware → Oppdater fra GitHub**, velg den avtalte
   utgaven og **Installer direkte fra GitHub**. Kontroller versjonen og
   bekreft med **B / Installer**.
2. Under overføringen skal fremdriften oppdateres. A kan avbryte før siste
   aktivering. Ved et avtalt nettbrudd skal enheten melde avbrudd eller
   tidsavbrudd og fortsatt kunne bruke gjeldende OS.
3. Koble til igjen, velg samme utgave på nytt og bekreft installering. La FIRE
   fullføre kontrollene og starte automatisk om. Kontroller versjon og menyer.
4. Kontroller at GitHub-utgaven bare har **Installer direkte fra GitHub** og
   **Tilbake**. SD-nedlasting er fjernet. Gjenta eventuelt uten SD-kort og med
   Windows-backenden stoppet for å kontrollere uavhengigheten fysisk.

## 7. Åpne redning uten Windows eller SD-kort

1. Stopp Windows-backenden. Slå av FIRE og ta ut SD-kortet. Hold A inne mens du
   starter eller tilbakestiller FIRE, og fortsett å holde i minst tre sekunder.
   **FIRE redning** skal vises.
2. Hold A i redningsmenyen. Skjermen viser **OS-slot A / app0** eller
   **OS-slot B / app1**, med versjon. Korte trykk på A/C bytter mellom dem.
   B starter den valgte. Hold A/C for å gå tilbake uten å starte.
3. Start slotten med versjonen du har kontrollert fungerer. En ugyldig slot skal
   ikke startes. Etter første migrering er ikke den andre slotten nødvendigvis
   brukbar; etter en vanlig OTA-oppdatering kan den inneholde forrige versjon.
4. Åpne redning igjen. Hold C for separat Wi-Fi-oppsett. Koble mobilen til
   **FIRE-Recovery** med passordet på skjermen, åpne `http://192.168.4.1`, og
   lagre nettet. Hold C for å lukke oppsettet og starte om.
5. I redning: B henter GitHub-katalogen. Kontroller at versjonslisten kan hentes
   uten SD og Windows. En ny B-bekreftelse installerer valgt versjon dersom du
   ønsker å teste hele gjenopprettingen.

Dette kontrollerer manuell redning. Automatisk tilbakeføring etter en feilende
firmware er et eget testpunkt og blir ikke bevist bare ved å åpne redningsmenyen.

## 8. Samle en kort måling mens du bruker FIRE

Dette gjøres mens USB-kabelen fortsatt er tilkoblet etter førstegangsoppsettet.
Lukk andre serieovervåkere. Åpne PowerShell i `M5Stack-backend`, bytt COM3 til
FIREs port fra USB-veiledningen, og lim inn:

```powershell
.\.venv\Scripts\python.exe scripts\capture_fire_diagnostics.py --port COM3 --seconds 120
```

Bruk Home, menyer, tale og nedlasting i de to minuttene. Verktøyet viser hvor
rapporten blir lagret. Det leser bare avgrensede måletall; det skriver ingen
kommando til enheten og lagrer ikke andre serielogger. Ta vare på `summary.json`
slik at vi kan vurdere responstid og ledig minne. Målingen kan ikke i seg selv
bekrefte at lys, tale eller redning virket; det kontrolleres i punktene over.

## Send resultatet samlet

Send firmwareversjonen og **OK / feil / ikke prøvd** for punkt 1–8. Ved feil:
skriv hvilken meny og handling det gjaldt, og legg gjerne ved bilde av meldingen.
Ved treghet: noter om Home, tale, bygging eller nedlasting pågikk, og oppgi
rapportmappen fra målingen. Da kan neste retting baseres på faktiske tall.

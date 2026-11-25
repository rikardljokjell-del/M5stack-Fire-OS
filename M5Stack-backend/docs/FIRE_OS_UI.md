# Ny utforming i FIRE OS 1.4

Oppgraderingen gir FIRE OS og Home samme mørke stil, tydelige valg,
lesbare verdier og et samstemt ikonsett. Den bruker de eksisterende lokale
fontene og ikonene, uten nye nedlastinger eller en ekstra skjermbuffer.

## Hovedmenyen

- Fire apper vises per side i et 2 × 2-rutenett.
- Kort **A/C** flytter valget bakover/fremover. Siden skifter automatisk.
- Kort **B** åpner valgt app. Sidetallet viser hvor du er.
- Lagret rekkefølge, synlighet og snarveier beholdes.

Hold **A** for hjem, **B** for hurtiginnstillinger og **C** for tilbake.
Appenes egne korte A/B/C-handlinger og Lua-grensesnitt er uendret.

## Home

Home viser enten fire kontrollkort eller ett stort kort. Velg dette i
Home-innstillingene, sammen med Home/Camper, lokal/ekstern/automatisk
forbindelse og favoritter. Navigasjon og bekreftelser fungerer som før.

Målt verdi og måltemperatur skilles. En ukjent eller utilgjengelig enhet
vises tydelig, og gamle verdier fremstår ikke som ferske. Bare handlinger
som Home Assistant har gitt tilgang til kan velges. En ventende kommando
er ikke en bekreftet tilstandsendring.

Et tomt Home-oppsett viser veien til innstillinger og mobiloppsett. Denne
oppgraderingen oppretter ingen HA-forbindelse eller tillatelser på egen hånd.

## Kontrollstatus

Visningen er kontrollert med de faktiske font-, ikon- og tegnehjelperne på PC.
Dette er ikke en fysisk HA-prøve eller en måling av ytelse på ESP32.
Endelig bygg, fysisk oppstart og brukerens visuelle prøve dokumenteres i
[statusrapporten](../../STATUS.md).

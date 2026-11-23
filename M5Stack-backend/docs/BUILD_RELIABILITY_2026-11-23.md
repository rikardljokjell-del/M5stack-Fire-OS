# Byggfeil 2026-11-23: årsak og forebygging

Siste undersøkte bygg: build-b6313b67f64a4950a0cf, RPG-prosjekt.
Det stoppet på OpenAI HTTP429/RateLimitError etter tre genererte kandidater.
En tidligere forespørsel ble kansellert da devicesessionen ble avsluttet.
Ingen pakke fra det feilede bygget ble levert som testet.

En konkret motstrid i kildekontrollen økte antall unødvendige rettingsrunder:
review ba tone-appen fjerne sd, mens backendens og firmwarens tjenestebaserte
avhengighetskontroll krever speaker -> jobs+sd. Dette gjelder også tone-only,
fordi speaker.play finnes i samme tjeneste. Genererings- og review-instruksjonene
forklarer nå dette uttrykkelig. Kontrakthash/firmware-API er uendret; SD-jobber
kreves ikke som falskt testbevis for toneavspilling.

Midlertidige kapasitets-/nettverksfeil håndteres separat fra Lua-retting:
samme generation/review prøves igjen, opptil fire ventende forsøk, med
eksponentiell venting/jitter og respekt for Retry-After. Samlet ventebudsjett
er240s og maksimalt180s per serverhint. Lengre hint gir feil, aldri et for tidlig
nytt forsøk. Ytre900s byggegrense og brukeravbrudd gjelder. Nøkkel-/konto-/kvotefeil
gjentas ikke. Rå provider-svar og hemmeligheter logges ikke. Retningslinje:
[OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits).

FIRE-brudd bruker nå privat kilde/plan/kontekst og avbryter ikke bekreftede bygg.
Se DEVICE_BACKGROUND_BUILD_HANDOFF.md. Ingen kvalitetssjekk er fjernet for å
påstå at alle bygg lykkes: PC-test og kildekontroll er ikke bevis på feilfri
fysisk maskinvarekjøring. Den sanitiserte HTTP429-loggen fastslår ikke hvilken
konkret konto-/modellgrense som ble nådd. Varig kapasitets-/kontobegrensning kan
fortsatt stoppe et bygg etter begrensede forsøk, med forståelig kort status.

Etter utrulling mottok to nye taleopptak HTTP429. En liten separat kontroll
av transkripsjonsendepunktet bekreftet `code=credit_balance_exhausted`,
`type=insufficient_quota`. Dette er tom API-kreditt, ikke midlertidig kø.
Backend klassifiserer nå denne koden og quota-typen som kontofeil, uten retry,
med status `Kontroller API-kontoen`. Kontoen må fylles på utenfor backend.
Den eldre RPG-loggen lagret ikke denne koden; den eksakte tidligere årsaken
kan derfor ikke bevises retrospektivt fra HTTP-statusen alene.

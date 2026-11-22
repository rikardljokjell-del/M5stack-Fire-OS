# Første Tetris-versjon: runtimeanalyse

22. november 2026. Undersøkt lagret kilde, pakkevalidering og faktiske feedbackkvitteringer. Ingen brukerapp eller device-kode er omskrevet i denne analysen.

## Hva feilet

Appen Fallbrikker, prosjekt `app-5969a11d27d341be8c47`. Første pakke `build-a0faeb5ef72941f3b4f2`, versjon 0.1.1, 2992 kildebyte, kilde-SHA256 `fd54a941f1a89fe055a217e40f8e33c1d81972666df2961d2b9fa644ce054939`.

FIRE rapporterte `Lua update: [string "main.lua"]:120: app callback budget exceeded`:

- Første healthy: 1 frame, 234 ms elapsed, siste callback 15768 µs.
- Feil: 9 frames, 996 ms elapsed, siste callback 128592 µs.
- Lokal omstart feilet igjen: 25 frames, 2374 ms elapsed, siste callback 121041 µs.

Healthy etter første update beviste ikke videre stabilitet. Den ødelagte pakken forblir quality-blocked; PC-retesting skal aldri oppheve kjent fysisk feil.

## Hvorfor PC-godkjenningen var utilstrekkelig

Renderingen ved linje 93–110 skrev 16 spillrader à 31 byte, pluss tittel/poeng/hjelp: over 500 tekstbyte per bilde. Aktive rader ble også bygd ved gjentatt strengkonkatenering under rendering. Linje 120 kalte render-funksjonen.

Gamle release-v3 hadde grenser på 24 outputkall og 120000 estimerte displayarbeidsenheter per callback. Appen hadde 21 kall og 27756 enheter, og passerte. PC måler ikke M5GFXs faktiske tekstkostnad, ESP32-tall/minne eller OS-preemption. Native feilen er callback-overrun; fordelingen mellom tegning, strengarbeid og scheduler krever måling på enheten. Tekst alene er ikke bevist å forklare hvert mikrosekund.

## Ny generell kontroll

Release-v4 begrenser kumulativ tekst til 256 UTF-8-byte per callback ved faktiske hostkall, inklusive aliaser. Alle nye/reparerte apper får regler for kompakte komplette bilder, mellomlagrede etiketter/rader/rotasjoner og færre stateberegninger i renderstien. Feil går tilbake til den begrensede korreksjonsløkken før levering.

Hele bildet tegnes fortsatt hver update. Ingen blanke mellomrammer eller automatisk appavslutning. Det nye API-et har `display.grid` som kontrollert batchkall for rutenett; dette krever native implementering før fysisk bruk.

Den nye testen kjørt mot faktiske uendrede lagrede kilder:

| Pakke | Ny idle-test |
| --- | --- |
| Fallbrikker 0.1.1 / build-a0faeb5ef72941f3b4f2 | Avvist: Per-callback text budget exceeded |
| Fallbrikker 0.1.2 / build-576952bfa80f4e558924 | Bestått 3750 frames / 60000 ms, maks 220 tekstbyte, 21 outputkall, 11032 arbeidsenheter |

Reparert kilde: SHA256 `d72e499c5eb14968b90899a4a05ba8d2c9321a140b3a5b3cb23cb4a0a6a37487`, 3396 byte. Den mellomlagrer rotasjoner og kompakte rader, men tegner fortsatt hvert bilde. En observert første update på FIRE tok 8456 µs; dette er ikke en lang fysisk stabilitetstest.

## Device-agentens oppfølging

- Skill Lua-/hostarbeid fra scheduler-/ventetid ved måling. Rapporter fase, callback_us, frames og elapsed_ms ved feil, også lokalt startet app. Ingen stor logg fra hvert bilde.
- Kontroller hostkall mot callbackgrensen; instruksjonshook alene ser ikke blokkerende tegne-/I/O-kall. Ikke hev/fjern watchdog for å skjule feil.
- Effektiviser tekst/rutenett i OS-spriten, behold én presentasjon per bilde, test Tetris og samtidig lyd/radio/SD-belastning fysisk.
- Send senere feil selv etter healthy. Backend må beholde ødelagte versjoner sperret når en nyere versjon fungerer.

256-bytegrensen er en konservativ risikokontroll, ikke en kalibrert 12-ms-garanti. PC kan ikke garantere feilfri drift i alle fremtidige tilstander eller fysisk glatt skjerm.

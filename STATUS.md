# Status – 20. november 2026

## Fast arbeidsområde

Repo: https://github.com/rikardljokjell-del/M5stack-Fire-OS

All backendkode, tester, dokumentasjon og startskript er samlet i
`M5Stack-backend/`. Denne mappen skal brukes ved alle videre backendoppdateringer.
Lokale avhengigheter, testresultater, pakker og logger ligger også under denne
mappen, men genererte runtime-data og hemmeligheter holdes utenfor Git.

`M5Stack-device/` inneholder nå FIRE OS-firmwareprosjektet som er migrert fra
det eksisterende PlatformIO-prosjektet. Bygget er kontrollert med PlatformIO i
den nye repo-plasseringen. Genererte `.pio/`-filer og lokale avhengighetsmapper
er ikke lagt i Git.

## Implementert backend

- Lokal Python/FastAPI/Uvicorn-backend, én prosess, filbasert lagring.
- HTTP-API og én WebSocket-forbindelse per mock-enhet.
- OpenAI Realtime-tekstdialog og Responses API for strukturert Lua-kodegenerering.
- Kompakt hardwarekontekst, automatisk inkludert i kodeforespørsler.
- Backend-håndhevede bygge- og kjørebekreftelser.
- Begrenset Lua 5.4-validering/PC-simulering, timeout og diskgrenser.
- Byggestatus, logger, kontrollsummer, reproduserbar ZIP og versjonshistorikk/rollback.
- Interaktiv PC-klient og offline-eksempler for sirkel, Snake, RGB og IMU.

## Verifisering

- 35 automatiske tester bestått også fra `M5Stack-backend/` etter flyttingen; `pip check` fant ingen avhengighetsfeil.
- Fire komplette mock-flyter har bestått mot faktisk lokal server.
- Interaktiv klient med `/build`, `/run` og `/quit` er verifisert.
- Gjenskaping av sirkelpakken ga identisk SHA256.
- Backendens oppstartsskript og sperre mot to samtidige prosesser er verifisert.

Ekte OpenAI-kall er ikke testet: API-nøkkel er ikke satt. SDK-kontraktene er testet
med simulerte svar. Mock-resultater er ikke live AI-generering.

## Gjenstår

1. Sette OpenAI-nøkkel lokalt og kontrollere faktisk modell-/kontotilgang.
2. Verifisere siste firmwareendringer på fysisk M5Stack fra `M5Stack-device/`.
3. Implementere og teste device-runtime, begrensede hardwareadaptere og trygg SD-overføring etter egen autorisasjon.
4. Verifisere kjøring og rollback på fysisk M5Stack.
5. Implementere lyd først etter fungerende tekst-/device-flyt.

Ingen automatisk Windows-oppstart eller brannmuråpning er aktivert.

Detaljer: [leveranserapport](M5Stack-backend/docs/DELIVERY.md).

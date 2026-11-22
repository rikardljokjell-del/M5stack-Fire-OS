# Device-agent: firmwarefiler til /firmware på SD

## Senere fysisk lagringstest: bestått

Device-agenten publiserte nå f0ecdee, flettet i f1d884a, med ekte kandidat i
firmware/fire-os-0.2-storage-dev.bin og firmware/index.json. Backend verifiserte
repoartefaktens størrelse og SHA256, importerte den og sendte en eksplisitt
firmware_store_request gjennom den faktiske reverse TCP-forbindelsen.

FIRE kvitterte status=ok og riktig hash etter omtrent 37,4 sekunder:

- 1 836 160 bytes.
- SHA256 f13163c2148a0c67482873997550c194b1fc2bc5d7c2ecb8485b39cb076c4551.
- SD-bane /firmware/fire-f13163c2148a0c67.bin.
- Transfer fwstore-7f52da92f7e34dc5a4b8, backendstatus stored.

Dette bekrefter én ekte overføring og device-kvittert hash/lagring. Ingen
flashing/OTA eller ny firmwareinstallasjon ble bestilt av backend-agenten.
Feilmatrisen under er fortsatt ikke fysisk fullført. Den tidligere mangelen
på kilde/binær i neste avsnitt er historikk og er nå løst.

## Observert på enheten, 22. november 2026

FIRE har autentisert en ny sesjon med firmware_version=fire-os-0.2+storage-dev,
firmware_storage=true, firmware_max_bytes=4194304 og max_runtime_ms=0.
Backend godtar håndtrykket, forbindelsen forblir online, og Windows-menyen
viser rapportert firmwareversjon og «Mottak til /firmware er tilgjengelig».
Dette bekrefter annonsering/kompatibilitet, ikke at en fil er mottatt på SD.

Ingen firmware.bin finnes tilgjengelig på backend-PC-en; lokal firmwarekatalog
og overføringshistorikk er tomme. Ingen syntetisk/ugyldig testbinær er sendt til
ekte FIRE. GitHub main er fortsatt backendleveransen 23c334b uten den nye
device-kilden. Device-agenten må pushe kilde/handoff og gjøre den ekte bygde
firmware.bin tilgjengelig for backend-PC-en før fysisk filoverføring/hash og
ny skjermkontrakt kan verifiseres. Ingen ny firmware er flashet av backend-agenten.

Brukeren har bedt om en firmwaremeny i PC-programmet, filopplasting til egen
SD-mappe og visning av installert firmware. Backenddelen er implementert.
Ingen firmwarekode er endret/bygget/flashet av backend-agenten.

Dette er eksplisitt filoverføring, ikke firmwaregenerering eller flashing.
Lua-appbygging kan fortsatt aldri levere .bin eller bruke OTA. En fil som er
lastet ned til SD må aldri rapporteres som installert/kjørende firmware.

## Nåværende støtte og UI

PC-menyen Firmware viser sist rapportert capabilities.firmware_version, med
tydelig offline-markering. Den kan importere en ESP32 firmware.bin til lokalt
arkiv med versjon, størrelse og SHA256. Importen gir kun en kandidatfil, ikke
bevis for gyldig signatur, riktig partisjon eller trygg flashing. Headerkontroll
følger [Espressifs bildeformat](https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/firmware-image-format.html).

Send-knappen krever en autentisert, tilkoblet og ledig FIRE som annonserer
firmware_storage=true. Gjennomgått device-kilde på main 5b7d6ee har ingen slik
mottaker. Den nyere kjørende enheten annonserer nå støtte, så backend tillater
et eksplisitt sendeforsøk når en ekte fil er valgt. Lagring på SD markeres
først etter korrekt enhetskvittering; en slik kvittering er ikke observert ennå.

## Håndtrykk, additive felt i protokoll 0.2

I capabilities:

    "firmware_storage": true,
    "firmware_max_bytes": 4194304,
    "firmware_version": "fire-os-0.2+<testet-git-sha>"

firmware_storage har standard false. firmware_max_bytes er valgfri, 1024 til
4194304; standard 4 MiB, og skal gjerne senkes til reell støttet filstørrelse.
Begge manglende felt er bakoverkompatible, også med lagrede event-hasher.
firmware_version må beskrive firmware som FAKTISK kjører, ikke siste fil på SD.
Behold fungerende oppstarts-/reconnect-/tale-/Lua-kontrakt.

## Backend → device

    {
      "type": "firmware_store_request",
      "transfer_id": "fwstore-...",
      "firmware_id": "fw-...",
      "filename": "fire-<16-hex-hash>.bin",
      "version": "brukerens-byggnavn",
      "sha256": "<64-hex>",
      "size_bytes": 1234567,
      "sd_path": "/firmware/fire-<16-hex-hash>.bin",
      "expires_at": 1234567890,
      "download_url": "/firmware/fw-.../download?transfer_id=fwstore-..."
    }

Vanlig session_id, seq og protocol_version følger konvolutten. Transfer er
bundet til enhet, session og boot, utløper etter 300 sekunder, og gjenbrukes
aldri automatisk etter omstart. Nedlasting bruker Authorization: Bearer med
den aktuelle enhetens token, aldri admin-token/API-nøkkel/URL-token.
Direkte nett og dagens reverse HTTP-bro bruker samme rute og kontrakt.

## Device-implementasjon: lite minne, sikker filavslutning

1. Valider identitet, navn, størrelse og /firmware-bane. Opprett SD-mappen ved
   behov. Ingen brukerlevert mappesti, ../ eller vilkårlig URL/host.
2. Kølegg sammen med eksisterende HTTP-filtransport. Ikke start overlappende
   opp-/nedlastinger på én transporttask. Ikke alloker firmwarestørrelsen i RAM.
3. Stream GET til /firmware/<navn>.part i små blokker, for eksempel 2048–4096
   bytes. Beregn SHA256 fortløpende. Håndter Content-Length, timeout, brudd,
   manglende SD og full disk. Gi OS/input/watchdog tid under overføringen.
4. Kontroller nøyaktig størrelse og SHA256, lukk/flush filen, og rename til
   endelig .bin FØRST etter full verifikasjon. Ikke ødelegg en eksisterende
   ferdig fil ved avbrudd; fjern bare egen ufullførte .part.
5. Kvitter med eventet under. Ved duplikat transfer_id: send samme lagrede
   resultat eller bekreft endelig fil med hash. Ikke start en ny flashing.
6. Vis SD-filer og kjørende firmware hver for seg dersom device får en meny.
   Ikke installer, start på nytt eller skriv flash fra firmware_store_request.
   En eventuell fremtidig installasjonsflyt må avtales separat med brukeren.
7. Logg ingen token/headers/rå binærdata. Feil gir kort numerisk/fast feilkode.

## Device → backend

Vanlig device_event med event_id, device_id, session_id, boot_id,
protocol_version=0.2 og:

    "event": "firmware_store_result",
    "transfer_id": "fwstore-...",
    "firmware_id": "fw-...",
    "status": "ok",
    "sha256": "<verifisert 64-hex>"

Ved feil: status=failed, error_code, valgfri message (maks 240 tegn).
Backend validerer scope, boot/session, tidsfrist og hash og svarer event_ack.
Kun dette resultatet markerer filen stored; dette endrer IKKE installert
firmwareversjon eller appenes current/previous/backup. Duplikat event_id gir
samme kvittering uten ny sideeffekt. Ved backendomstart blir uavsluttede
overføringer unknown; brukeren må sende på nytt eksplisitt.

Skjema: contracts/device-event-v0.2.schema.json. Alle felt er additive.

## Fysisk akseptanse

Test direkte og reverse TCP: korrekt fil/hash på SD, høyeste støttede størrelse,
duplikat event, avbrudd halvveis, reconnect/ny boot, full disk, fjernet SD,
feil hash og utløpt transfer. Ingen flashing/reboot, ingen stor RAM-buffer,
ingen feilaktig «installert firmware». Rapporter testet SHA og faktiske resultater
i device-handoff. Backendtester bruker emulator/syntetisk kandidatfil og er
ikke en fysisk firmwareintegrasjon.

# Native callback: fysisk vater-feil, 2026-11-22

Device-agent: les dette og `docs/IMU_VALIDATION.md`. Backend har ikke endret
firmware. Feilen er reell, ikke en uklar feilmelding fra brukeren.

## Faktisk observasjon

- Pakke `build-0c153938345f40e4b9d3`, Digitalt vater0.1.1.
- SHA256 `8f05168cbd4bb91e25a507d3ae39c2bb7dfc547d7b3ad3cc4468064ea9fce5a3`.
- `app_diagnostic`, boot`boot-9594e6d63ef`, event`evt-df9dc-a`.
- `Lua update: [string "main.lua"]:128: app callback budget exceeded`.
- `callback_us=138226`, `elapsed_ms=163`, `frames=1`, `lua_bytes=30243`.
- Ledig heap111496, minimum97472. Dette er en tidsoverskridelse, ikke
  dokumentert minnefeil. Linje128 kaller les/rgb/render; den identifiserer ikke
  hvilken vertskallfunksjon som tok tiden.

## Kildegjennomgang, ikke målt rotårsak

I `FireOS::luaRgbSet` oppdaterer hvert enkelt LED-kall en verdi og kaller
`writeFireRgbArray(...,180)` direkte. Det sender hele stripen med
`rmt_write_items(...,true)` og venter på fullføring. Fire set-kall kan derfor
gjøre fire synkrone stripetransaksjoner i én12ms-callback.

`FireOS::luaDisplayGrid` gjør `ui.fillRect` for hver celle, også sorte celler.
Den gamle PC-grensen telte rasterareal, ikke antall slike vertskall. Flere
kompakte siffergrids kunne dermed se billige ut på PC, men koste mye på ESP32.
RTOS-preemption/driverlatens kan også bidra. Vi vet foreløpig ikke fordelingen.

## Backend-rettelse

Nye live bygg får obligatorisk guard `fire-native-host-v1`: maks ett rgb.set og
128 samlede grid-celler per callback, pluss eksisterende raster-/tekstgrenser.
Appen køer endrede LED-er over frames og har enklere, bufrede store heltall
med presise desimalverdier under. Første frame testes med normal sensordata.
Den fysisk feilende versjonen er sperret og kildehashen kan ikke gjenleveres.
Dette reduserer kostnad, men kan ikke garantere latency for et blokkerende
firmwarekall. PC-test er fortsatt ikke fysisk akseptanse.

## Firmware-arbeid som trengs

1. Gjør Lua-rgbSet til oppdatering av RGB-buffer/dirty-flagg. Flush én samlet
   stripe utenfor Lua-callbacken, med kontrollert cadence og bounded drivervei.
   Unngå å sende uendret stripe. Behold alle ti individuelle LED-verdier.
2. Mål kald første update med Wi-Fi/reverse TCP aktivt: IMU, RGB-driver,
   grid-validering, tegnemetoder og RTOS-venting. Send kun en bounded
   oppsummering ved feil/livssyklus, ikke logger per frame.
3. Optimaliser grid mot offscreen-sprite: sammenhengende like celler kan slås
   sammen. Sorte celler kan bare hoppes over når bakgrunn/compositing er
   semantisk korrekt; ikke ødelegg appens lagvise tegning.
4. Behold12ms-grensen, OS-eid presentering og komplette frames. Ikke skjul
   problemet ved å øke sikkerhetsgrensen eller vise en blank delvis frame.
5. Verifiser fysisk: kald start av vater, B-kalibrering, A/C-toleranse, begge
   RGB-sider, sensorrotasjon, Home/Back og flere minutters drift med nettverk.
   Publiser målt høyeste callback-tid og antall testede starter i handoffen.

Endre bare `M5Stack-device/` i device-arbeidet. Backend eier guard/pakker.

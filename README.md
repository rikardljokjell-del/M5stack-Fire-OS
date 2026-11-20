# M5stack Fire OS

| Mappe | Formål |
| --- | --- |
| [M5Stack-backend](M5Stack-backend/) | Lokal PC-backend for FIRE OS AI Developer. All videre backendutvikling skjer her. |
| [M5Stack-device](M5Stack-device/) | FIRE OS-firmware for M5Stack FIRE, bygget med PlatformIO. |

Backend kan startes fra repo-roten:

```powershell
.\M5Stack-backend\start.ps1 -Mock
```

I en annen terminal:

```powershell
.\M5Stack-backend\mock.ps1 -Demo
```

Firmware bygges fra `M5Stack-device/`:

```powershell
cd M5Stack-device
pio run -e m5stack-fire-ble
pio run -e m5stack-fire-ble -t upload
```

Bruk `/build` for å bekrefte bygging, `/run` for å bekrefte PC-simulering og
`/quit` for å avslutte. Mock-modus bruker ingen OpenAI-nøkkel eller betalte API-kall.

Se [status](STATUS.md), [arbeidsinstruksjoner](AGENTS.md),
[deviceveiledning](M5Stack-device/README.md),
[backendveiledning](M5Stack-backend/README.md) og
[WebSocket-protokoll](M5Stack-backend/docs/PROTOCOL.md).

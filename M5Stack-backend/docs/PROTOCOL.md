# FIRE Developer protocol

## Physical-device contract: 0.2

Use **[PROTOCOL-v0.2.md](PROTOCOL-v0.2.md)** for physical firmware integration.
It specifies scoped authentication, event/session/boot IDs, capabilities, text,
audio, explicit confirmations, package downloads, installation/start/healthy/stop
receipts, rollback, deadlines, reconnection and deduplication.

- [Device JSON Schema](../contracts/device-event-v0.2.schema.json)
- [Manifest JSON Schema](../contracts/manifest-fire-lua-0.1.schema.json)
- [Lua API and resource contract](LUA_API.md)
- [Actual verification status](DELIVERY.md)

Schemas are generated with `python -m fire_backend.contracts`. Pytest checks that
committed schemas match the implementation. JSON Schema describes field shapes
and required receipt fields; backend additionally checks identity, state, nonce,
boot, ownership, checksum and capability relationships.

Backend implementation is tested with an emulated firmware peer. Physical FIRE
and live OpenAI remain unverified; neither is implied by a successful mock test.

## Legacy PC client: 0.1

The delivered interactive mock client remains compatible. It connects to
`ws://127.0.0.1:8765/ws/device`, optionally with the administrator Bearer token.
It omits protocol_version/target, which default to 0.1/pc_simulation.

```json
{"type":"device_event","device_id":"pc-mock-01","event":"session_start"}
```

Then send text, await build_proposal, explicitly send build_confirm with its
proposal_id, await package_ready, explicitly send run_confirm with package_id.
Buttons are notifications and never substitute for confirmations.

PC run_result has target=pc_simulation. It updates only the project's simulated
history, not physical current/previous/backup. Physical receipts are rejected for
PC sessions. Disconnection stops a 0.1 session; durable resume requires 0.2.

Control messages are <=8192 UTF-8 bytes. Unknown fields/events are rejected.
Progress reports phases and repeats during long builds; ETA may be null.
session_stop explicitly cancels current work. App packages never contain firmware
binaries, and no route performs flashing or OTA.

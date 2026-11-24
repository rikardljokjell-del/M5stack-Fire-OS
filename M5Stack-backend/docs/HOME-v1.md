# FIRE Home v1 — frozen wire contract

Version `1`, 2026-11-24. Native FIRE talks directly to a broker at the Home
Assistant site. Windows and OpenAI are not in this data path. This contract
does not add a Lua API or claim physical verification.

## Transport and identity

TLS MQTT locally (8883), MQTT over validated WSS remotely (443, path `/mqtt`).
Local/Internet/Auto selects a connection, never grants permission. Use separate
broker listener password files for local and remote identities. A local
password MUST NOT authenticate on the remote listener. Broker ACL binds the
route, site and device; a message's route field is not an authority.

Identifiers `site` and `device`: `[a-z0-9][a-z0-9_-]{0,31}`. Profiles Home and
Camper each select their own site and credentials. No HA bearer token. Native
credential storage must not export passwords to generated Lua or AI context.

Prefix `fire/home/v1/{site}/{device}/{route}`, route `local` or `remote`:

| Topic suffix | Publisher | Retain | QoS | Maximum UTF-8 bytes |
| --- | --- | --- | --- | --- |
| `request` | FIRE only | false | 1 | 512 |
| `catalog` | HA only | true | 1 | 8192 |
| `state` | HA only | true | 1 | 4096 |
| `ack` | HA only | false | 1 | 512 |

FIRE subscribes only to its three exact response topics. No wildcard access to
HA topics. Broker max packet 12288 bytes; at most one unacknowledged command.
No retained commands, offline command queue, or automatic replay after an
uncertain result. Use a clean MQTT session. Exponential reconnect 1–30 seconds
with jitter; keep UI responsive and show stale data as stale.

## Catalog and state

Example catalog (timestamps are Unix seconds, integers):

```json
{"v":1,"site":"home","device":"fire01","route":"local","epoch":"9bf0a641f643e590","rev":"ab62a130","issued":1795500000,"ttl":90,"last_seq":7,"remote_allowed":false,"cards":[{"id":"desk","name":"Skrivebord","kind":"light","unit":"","ops":["on","off","brightness"]},{"id":"room","name":"Temperatur","kind":"sensor","unit":"°C","ops":[]}]}
```

At most 12 cards. Card ID same identifier grammar; name <=32 characters and
96 UTF-8 bytes, unit <=12 characters/24 bytes. Kinds: `light`, `switch`,
`climate`, `sensor`, `binary_sensor`, `script`, `scene`. Operations are the
explicit subset advertised for that card. No entity IDs, service names,
templates, URLs, credentials, arbitrary attributes or actions in the catalog.
Climate cards advertising `temperature` also carry finite numeric `min`, `max`
and positive `step`; `min < max`, and `step <= max-min`. Climate cards advertising
`heat_mode` carry `modes`, a unique nonempty subset of `off`, `heat`, `auto`.
Other card kinds never carry climate metadata. FIRE uses these limits rather
than inventing a thermostat range or mode.
`rev` is 8–32 lowercase hex characters; changes when mapping or permissions
change. `epoch` is 16 lowercase hex characters, changes on HA restart. Reject
malformed/oversized/unknown-version catalog atomically; never partially apply.

```json
{"v":1,"epoch":"9bf0a641f643e590","rev":"ab62a130","issued":1795500000,"ttl":90,"values":{"desk":{"state":"on","value":128},"room":{"state":"ok","value":21.4}}}
```

The entire retained state is replaced, so removed cards/attributes disappear.
`state` strings: `on`, `off`, `ok`, `unavailable`, `unknown`; `value` is a
finite number, boolean or null. Only a selected scalar value is exported.
Climate values may additionally carry `target` (finite number or null) and
`mode` (`off`, `heat`, `auto` or `unknown`). Here `value` is current temperature;
`target` is the selected setpoint. Other card kinds do not export these fields.
Unknown card IDs are ignored. Mismatched epoch/revision is not displayed as
current. Catalog/state refresh every 30 seconds, stale after `ttl` (<=90s).
No control without a current valid catalog and current site/profile.

HA authorization uses explicit card mapping AND current direct entity labels
`fire_home_read` / `fire_home_control` (profile-specific labels configurable).
No device/area label inheritance. An entity removed from the read label must
disappear from both catalog and state. Removing control removes `ops` and
blocks commands immediately, even before refreshed catalog reaches FIRE.
State never includes all entity attributes. Publish empty catalog/state on
configuration removal, including both routes, to replace retained old values.

## Request, sequencing and acknowledgement

Hello is non-mutating:

```json
{"v":1,"type":"hello","rid":"e14be931ab31698a"}
```

HA responds with current catalog/state. `rid` is exactly 16 lowercase hex.
After catalog, FIRE chooses `seq = last_seq + 1`. Sequence is shared between
routes for a device; HA checks it serially. On restart/reconnect get a fresh
catalog before controlling. Never reuse a sequence for another action.

```json
{"v":1,"type":"command","rid":"e14be931ab31698a","epoch":"9bf0a641f643e590","rev":"ab62a130","seq":8,"issued":1795500002,"ttl":15,"card":"desk","op":"brightness","value":128}
```

Exact fields only. seq integer 1..2147483647, issued Unix seconds, ttl 1..15;
HA rejects future issue time >2 seconds or expired request. FIRE must have
valid time. FIRE never publishes retained requests. Native HA MQTT triggers do
not expose the MQTT retain flag: replay protection uses epoch, sequence and TTL.
A first valid authorized request is handled once; re-delivery is rejected. HA
checks epoch, revision, route permission, mapping, current labels, operation
and value at execution. HA advances the consumed sequence helper BEFORE invoking
any action and changes epoch/reset sequence on every HA start and automation
reload. Native helper restoration is not immediate fsync or an exactly-once
physical execution guarantee. Repeated/lower sequence returns `unknown` without executing again;
an accepted action must never be replayed after missing ACK or restart.

| Operation | Allowed kind | Value |
| --- | --- | --- |
| `on`, `off` | light, switch | null |
| `brightness` | light | integer 0..255 |
| `temperature` | climate | finite number, mapping min/max and step |
| `heat_mode` | climate | `off`, `heat`, `auto`; explicit map subset |
| `run` | script, scene | null, explicit allowlisted target only |

No toggle, shell, template, caller-supplied entity/service, arbitrary script
arguments or URLs. Reject unsupported values, never silently clamp them.
The user initiates a fresh action after an uncertain outcome (especially run).

```json
{"v":1,"rid":"e14be931ab31698a","seq":8,"status":"executed","code":"ok"}
```

Status `executed` = HA service returned successfully, not physical proof;
`rejected` = no action started; `unknown` = may have started, do not retry.
Codes: `ok`, `schema`, `expired`, `session`, `revision`, `sequence`, `denied`,
`unavailable`, `action_failed`. ACK timeout 10 seconds -> unknown locally.
Malformed rid cannot be reflected; drop malformed/oversized payloads. No
passwords/tokens or raw rejected payload in logs/ACK. HA remote-off blocks
remote dispatch and exports an empty remote catalog/state; listener credentials
remain distinct. Disabling access is not a client-side setting.

## Native UI requirements

320x240; 2x2 cards, readable focus and larger detail view. A previous/up,
B select/confirm, C next/down; long/double OS shortcuts remain reserved.
Home/Camper profile, favorites, order/layout and route are native settings.
Show connecting / current / stale / denied / unknown. Do not show an action
as physically completed from an ACK alone. Broker secrets stay masked.

## Acceptance evidence

Schema/dispatcher/broker tests establish local implementation behavior only.
HA startup/reload, entity revocation, remote-off, duplicates, lost ACK, retained
old request, profile isolation, Windows-off local/remote operation and actual
FIRE TLS/RAM require recorded integration or physical tests. No current claim
that a user's HA, domain or broker has already been configured.

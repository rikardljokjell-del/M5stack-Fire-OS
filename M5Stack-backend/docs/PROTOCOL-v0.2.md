# FIRE Developer device protocol 0.2

Addendum: [APP_REPAIR_HANDOFF.md](APP_REPAIR_HANDOFF.md) defines app_diagnostic,
automatic selected-app diagnosis and max_runtime_ms=0 (until explicit user exit).
Zero is accepted only for devices advertising this lifetime profile. Legacy
positive lifetime limits remain distinct from callback/memory safety limits.

This is the backend/firmware implementation contract. Firmware remains owned by
the device agent. Backend implementation follows this document; physical support
is NOT verified until the complete flow has passed on a real FIRE.

Conversation modes, barge-in, retryable capture feedback and reconnect recovery
are specified in [CONVERSATION-v0.2.md](CONVERSATION-v0.2.md). These additive
fields/events are implemented by the backend; see the linked device audit for
required firmware work. Existing explicit BUILD/RUN authorization is unchanged.

## Transport and authentication

- Control: `ws://PC:8765/ws/device`, UTF-8 JSON, <=8192 bytes/message.
- HTTP uses the same host/port and `Authorization: Bearer <device token>`.
- Set `FIRE_DEVICE_TOKENS` on PC to a JSON object mapping device ID to its own
  >=24-character unique random token. A device token authenticates ONLY that ID.
- `FIRE_BACKEND_TOKEN` is an independent administrator/PC token; never put the
  OpenAI key on FIRE. Administrator credentials cannot impersonate physical devices.
- The local unauthenticated legacy PC mock remains available only when no admin
  token is set and the server is bound to loopback. LAN requires an admin token.
- Browser Origin is rejected. No tokens in URLs. TLS is needed outside trusted LAN.

All client events use `type="device_event"`, `protocol_version="0.2"`,
`device_id`, and a globally unique `event_id`. IDs match `[a-z0-9][a-z0-9_-]{0,63}`.
After start, include `session_id`. Physical-device events also include `boot_id`
from the start handshake. A reboot MUST generate a new boot ID. Payloads below
show the additional fields; the envelope is always required.

## Start, resume and identity

```json
{"type":"device_event","protocol_version":"0.2","event_id":"evt-001","device_id":"m5stack-fire-01","event":"session_start","target":"device","boot_id":"boot-001","capabilities":{"api_version":"fire-lua-0.1","services":["display","buttons","rgb","imu","time"],"max_memory":131072,"max_runtime_ms":10000,"audio_input":false,"audio_output":false,"firmware_version":"fire-os-0.2"}}
```

Capabilities are the actually implemented adapters, not a wish list. Allowed
service names: display, buttons, rgb, imu, time. Memory range 65536..262144 bytes;
runtime 16..10000 ms. The first contract deliberately limits an app to ten seconds.
Mic/speaker used for developer conversation do NOT grant Lua access to audio.
Only supported `fire-lua-0.1` sessions are accepted. Never advertise Lua support
before a restricted runtime and the advertised adapters exist on FIRE.

The example is the no-audio source profile at 069ea09e. Newer source df06c65
announces audio_input=true/audio_output=false and implements I2S capture/WAV
upload; physical verification is still pending. Both audio=false is VALID and
does not prevent text/build/install/run. Backend FIRE_AUDIO_ENABLED=true cannot
override either device audio flag. Set each flag true only after physical tests
of capture/upload or playback. Simulator support does not grant device APIs.

Snapshots include effective_capabilities (lua_services, max_memory,
max_runtime_ms, conversation_audio announced/enabled directions, backend_enabled)
and physical_verified=false. These are announced limits and backend policy,
not proof of hardware enforcement. An authenticated emulator can send receipts;
backend never labels that as independently verified physical testing.
Startup/resume sends nonfatal capability_status with effective_capabilities,
code and message. Physical sessions initially use state=idle regardless of audio
flags: listening means a real recording initiated by listen_start, never mere
readiness. Without input, code=audio_input_unavailable (or
backend_audio_disabled when only backend audio is off).
A text-only assistant_message repeats the limitation for current native UI.
Unsupported listen_start/listen_stop return error with the same code/message
without invalidating the current proposal. WAV upload returns HTTP 409 JSON
{code,message} before consuming audio. Output is independently gated.

`session_started` returns session_id, project_id, target, mode, state, boot_id,
protocol_version, proposal_id/package_id/build_id when present. Server messages
carry monotonically increasing `seq`, `session_id`, protocol_version.
Snapshots include server_time (UTC Unix seconds). Firmware should calculate
command expiry from that reference plus monotonic elapsed time if its RTC is not
configured; do not trust an unset local calendar clock.
Add `project_id` to edit a project previously owned by this device.

Reconnect with a NEW start event_id and `resume_session_id`, same target/device,
project, boot ID and capabilities. Resume window defaults to 600 seconds. The
server returns `session_started` and `session_snapshot` with last state/progress,
proposal, package, device record and pending commands. Existing confirmed builds
continue during transient disconnect. `session_stop` explicitly cancels them.
Commands are NOT blindly executed again on reconnect.

For the current native client, resume_session_id may be omitted when reconnecting
within the window with the SAME device/boot/capabilities and an offline session.
Backend resumes that session/project/history/proposal instead of creating a new
project. A live socket is never taken over. Capability changes require a fresh
session/boot; they cannot silently broaden an existing session's permissions.

On a new boot ID, pending commands for the previous boot are invalid. Start a
fresh session. Device runtime status is unknown until a new correlated command
and receipt establish it. After backend restart, old run/install authorizations
are expired; send no unsolicited app_started event to restore running status.

## Input, dialogue, confirmations and UI

| event | Required additional fields | Meaning |
| --- | --- | --- |
| text | text (1..4000 chars) | New turn; invalidates prior unconsumed proposal |
| listen_start | turn_id | Begin local recording; backend invalidates old proposal |
| listen_stop | turn_id | Finish recording; upload WAV using the same turn ID |
| cancel_turn | none | Cancel current dialogue/transcription/audio; discard proposal |
| button | button=A/B/C, action=pressed/released/long_pressed | Notification only; never authorization |
| build_confirm | proposal_id | Consume exact latest proposal; begin one build |
| run_confirm | package_id | Explicitly authorize one start of the installed package |
| install_retry | package_id | Issue a fresh install_id for the same tested package after timeout/SD/delivery failure, without another AI build |
| app_stop | none | Request stop of the current device run; waits for receipt |
| ping | none | pong + session snapshot |
| session_stop | none | End conversation and cancel its build/audio; does not assert a remote app stopped |

Intended FIRE controls: short B starts/stops recording when audio_input is true; A sends
build_confirm or run_confirm only when the matching offer is visible, C aborts.
Long A=home, long B=quick settings, long C=back (650 ms), reserved for OS.
Do not emit raw button events as a substitute for semantic confirmations.
The earlier source only sent listen events. New source includes capture/upload;
output remains false until playback exists. Announced flags remain authoritative,
while backend never promotes them to physical verification. Text may be sent by a PC
client authenticated for that device/session. Legacy PC simulation is separate.

`assistant_message`: text. `build_proposal`: proposal_id, project_id, summary.
`ui_event/assistant_state` reports workflow state. `ui_event/assistant_activity`
reports idle/listening/processing/speaking independently of workflow. Animate
REST/LISTEN/THINK/TALK locally; TALK follows actual audio playback receipts.
Natural language, including transcribed "build/run now", never authorizes actions.

## Build and package offer

`build_progress`: build_id, phase, progress (0..100), message, eta_seconds (null
when unknown). Phases preparing, generating, validating, compiling, testing,
packaging, ready, failed; repeats at least every ten seconds during long work.
"compiling" is Lua syntax compilation, never firmware compilation.

`package_ready` contains package_id (=build_id), project_id, manifest,
archive_sha256 (lowercase hex SHA256), size_bytes, download_url. Device sessions
also receive `install_request` with install_id, package_id, archive_sha256,
size_bytes, download_url, boot_id, expires_at (UTC Unix seconds, normally +300).
Offer/install expiry does not delete the immutable package.
Use install_retry with the same package_id if the install command expires or
delivery fails. It never regenerates code or authorizes a run. A delivery error
does not change a successfully tested build into a failed build.

GET download_url with Authorization. ZIP uses ZIP_STORED (no compression), layout:
`apps/<app_id>/{manifest.json,main.lua,assets/,appdata/}`. Empty assets/appdata in
this version. Manifest entry is main.lua; checksum is SHA256 of its UTF-8 bytes.
Outer archive SHA256 is independent and never embedded into itself.

New apps have a stable, purpose-based folder ID (lowercase ASCII slug, <=24
characters, for example `sprettsirkel` or `snake`). App names are short and
understandable (<=32 characters). Separate apps may get a short numeric suffix.
Updates retain the original folder ID. `manifest.id` is the filesystem app ID;
`project_id` and `package_id` remain independent internal authorization IDs.
Never assume they are equal. Legacy deployed folders are preserved. Downloads
use a readable filename such as `sprettsirkel-v0.1.1.zip`; download URLs retain
the immutable package ID. The four required filenames inside the app remain
unchanged, including `main.lua`.

HTTP Range/If-Range and ETag allow resume. If a range returns 200 instead of 206,
discard the old partial bytes and restart. Check full size/hash before extraction.
Reject duplicate/unexpected entries, traversal, absolute paths and oversized data.
Stage in a version-specific temporary folder; preserve existing appdata and old
working versions. Recover from incomplete SD renames/power loss on next boot.
NEVER use installExternalApp, OTA partitions, .bin or ESP restart for these apps.

## Device receipts and lifecycle

All receipts require package_id. Operation IDs and boot_id must match an issued,
unexpired command for this exact device/session/package. Server receipt replay
with the same event_id returns an acknowledgement, not another state change.

| event | Additional required fields | Effect |
| --- | --- | --- |
| device_install_result | install_id, status=ok/failed; archive_sha256 required for ok | ok marks package installed only after matching expected archive hash |
| app_started | run_id | Marks physically running after correct run_request; not a PC test |
| app_healthy | run_id | Device confirms successful init/first frames and no runtime error; promotes healthy current/previous/backup |
| app_failed | run_id, error_code | Device has stopped this failed run; backend offers rollback to last healthy/previous version |
| app_stopped | run_id, stop_id OR reason | stop_id confirms a stop command; without stop_id reason must be completed/user_exit/runtime_limit for the active started run |
| rollback_result | rollback_id, status=ok/failed | Confirms restoration of the offered previous package, without automatically running it |

Failed receipts may add message (<=240 chars) and error_code (identifier). If no
previous version exists, failure stops the app and records the error; no rollback
command is fabricated. A successful rollback restores selection/installed state
only; restarting it requires a fresh run_confirm. No metadata-only rollback is
reported as physical success.
For a failed installation, archive_sha256 may be absent/empty when download failed
early, or contain the observed hash (including a mismatch). Backend correlates
install_id/package_id/device/boot/expiry, records failure and clears the pending
install; it does not mark the package installed/current. For status=ok the hash
is mandatory, exactly 64 lowercase hex characters, and MUST match both the offer
and independently verified downloaded bytes. A mismatch never succeeds.

`run_request`: run_id, package_id, archive_sha256, boot_id, expires_at (+30 seconds).
Persist consumed run_id on FIRE BEFORE starting. Repeated run_request must return
the original receipt and never start twice. Expired/old-boot commands are rejected.
`stop_request`: stop_id, run_id, package_id, boot_id, expires_at.
`rollback_request`: rollback_id, package_id (restore target), failed_package_id,
boot_id, expires_at, start=false. These commands are distinct from user confirmations.

Device record separates installed_package_id, running_package_id, runtime_status,
current (last healthy version), previous, backup. On disconnect/restart online=false
and runtime_status=unknown; retained running_package_id is last observation, not
proof that the app is still running. Package validation/PC run updates only
project.last_simulated_package_id, never physical current.
Healthy version history is per device AND project, in device.projects[project_id].
The top-level current/previous/backup show the selected project_id, not a history
mixing different apps. Starting another project never rolls its failure back to
an unrelated app. Retained installed/healthy versions cannot be deleted through
the project API.

## Audio (optional capability; FIRE_AUDIO_ENABLED=true on PC)

1. listen_start/stop bind recording to turn_id.
2. POST `/sessions/<session_id>/audio/<turn_id>` with Authorization and
   Content-Type: audio/wav, raw WAV body (not multipart/base64).
3. PCM signed 16-bit little-endian, mono, 16000 Hz, 0.1..15 seconds,
   <=524288 bytes including WAV header. Stream in <=4096-byte chunks on FIRE.
   Backend reads with a deadline and bounded buffering; all ordinary HTTP bodies
   retain the 8192-byte limit. One active turn/upload per session.
4. HTTP 202 means accepted, not transcribed. `transcript` returns turn_id, text;
   it feeds the normal dialogue. Uploading the same turn and bytes returns the
   same acceptance, not a second API call. Reusing it with other bytes is rejected.
5. `audio_ready`: audio_id, turn_id, download_url, format=pcm_s16le,
   sample_rate=24000, channels=1, size_bytes, sha256, expires_at, synthetic=true.
   Output <=30 seconds/1440000 bytes. GET URL with Authorization, stream in
   4096-byte reads; use 8–16 KiB playback buffers, never the whole file in SRAM.
6. Send audio_playback_started/finished with audio_id and turn_id. Only the latest
   unexpired clip in that session may change speaking state. Inform the user the
   voice is AI-generated. Do not record while playing a response.

Malformed/empty/silent audio fails without building. Cancellation/disconnect grace
expiry closes provider sessions and expires clips; temp data is deleted. Speech
generation failure preserves the text answer/proposal and sends audio_error.
Input and output audio expire after at most 300 seconds by default; no audio goes
into application ZIPs or ordinary logs. No full-duplex requirement in 0.2.

Backend removes ADC DC bias with bounded gain and records only numeric signal
diagnostics (sample count, duration, level, clipping, capture/wall-time ratio).
Original wire bytes remain the deduplication identity. It does not invent speech
when transcription is empty or attempt to reconstruct missing capture chunks.
After audio_playback_finished, an existing unconsumed build_proposal may be
repeated with the SAME proposal_id to restore the confirmation UI. This never
builds or grants authorization. Physical conversation audio is tested separately
from the Lua app's restricted service permissions.

## App selection, versions and deletion

The additive 0.2 app lifecycle contract is [APP_LIFECYCLE.md](APP_LIFECYCLE.md).
It covers app_list/app_versions/app_select, explicit new/update startup,
device app_deleted/app_inventory and administrator-only backend deletion.
No automatic device reinstall follows deletion. Backend purge requires fresh
absence evidence from a currently connected device and no active operations.
Unknown/offline/unavailable SD never establishes deletion. Build/run confirmations,
ownership, immutable package hashes and current/previous/backup semantics remain.

## Idempotency, failure and version compatibility

`event_ack` contains event_id, status=accepted/duplicate/unknown, result (operation
IDs where relevant). Persist before/after handling. Reusing event_id with altered
payload or another device is rejected. A crash during handling yields unknown;
query session_snapshot and pending commands instead of blindly repeating effects.
Replay acknowledgement applies to active/resumed sessions; events for explicitly
closed/expired sessions may be rejected, and must never be moved to a new session.
Errors: type=error, code, message; no provider secrets or raw request objects.
Protocol 0.1 remains PC-only; it cannot send device receipts or claim installations.

Workflow: listening -> processing -> clarification_needed OR
awaiting_build_confirmation -> building/testing -> awaiting_install -> installed
--run_confirm--> starting --app_started--> running. Failures -> failed or
rollback_pending; app_healthy establishes current; app_stopped -> installed.
For PC-only sessions ready_to_run/run_result remain explicit pc_simulation.

The JSON Schema in `contracts/device-event-v0.2.schema.json` defines field shapes;
this document defines additional event-specific and stateful requirements. The
backend validates both. Package/Lua contract: `LUA_API.md` and FIRE_DEVICE_CONTEXT.md.

## Lightweight lifecycle and audio diagnostics

Firmware SD storage is an additive, capability-gated contract:
[FIRMWARE_STORAGE_HANDOFF.md](FIRMWARE_STORAGE_HANDOFF.md). It uses
firmware_store_request/firmware_store_result and device-scoped binary download.
It never authorizes flashing, and stored files never establish installed firmware.
PC authoring and version deletion: [DESKTOP_APPS.md](DESKTOP_APPS.md).

Existing install/start/healthy/stop/failure events and app_diagnostic may include
optional diagnostics. Allowed phase values: load, init, update, on_button,
install, start, stop, audio_download, audio_playback. Optional strict integer
fields: elapsed_ms and frames (0..4294967295), callback_us (0..60000000),
free_heap, min_free_heap, lua_bytes (0..16777216), source_bytes (0..100000).
Unknown fields are rejected. Report transitions/errors only; no raw log file or
per-frame reporting is needed. Retain original event, boot, session and package
identity. Backend retains up to 100 lifecycle reports per device. app_healthy
proves startup health only, not future bug-free execution.

audio_playback_failed requires audio_id, turn_id and error_code, plus optional
bounded message/diagnostics. Backend retires that clip and restores the SAME
existing build_proposal. Text remains usable. A missing start acknowledgement
times out after 35 seconds; a missing finish after at least 60 seconds. One
audio_ready retry after 12 seconds is allowed only when no complete HTTP body
has been sent. Server transfer completion is not proof of device receipt or
audible playback. Late acknowledgements of retired clips are ignored.

Local administrator POST /desktop/sessions/{id}/voice with {"test":true} plays
a fixed speaker test; false repeats the last assistant reply. A connected idle
session with an existing turn and advertised audio_output is required. Turn,
app selection and proposal are retained; every replay has a new audio_id.

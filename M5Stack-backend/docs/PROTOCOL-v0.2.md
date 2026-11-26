# FIRE Developer device protocol 0.2

Optional [FIRE App SDK](FIRE_APP_SDK.md) adds
`capabilities.app_sdk: {version: "fire-app-sdk-1.0", contract: "<SDK SHA256>"}`.
The protocol stays 0.2 and the hardware `api_version`/`api_contract` remain the
unchanged `fire-lua-0.2` contract. An SDK manifest instead uses
`api_version=fire-app-sdk-1.0` and the separate hash from
[APP_SDK-v1.json](../contracts/APP_SDK-v1.json). Require exact SDK advertisement,
normal services/permissions and existing build/run confirmations. A missing SDK
field preserves legacy behavior. Backend/PC implementation is not physical proof;
fresh SDK hardware verification remains separately recorded.

Hardware extension: [HARDWARE_API_HANDOFF.md](HARDWARE_API_HANDOFF.md) adds
negotiated `fire-lua-0.2`, `capabilities.api_contract`, resource allowlists in
`capabilities.hardware` and matching manifest hash. This does not change the
transport version or grant hardware support to legacy firmware. Missing
adapters produce assistant feedback and additive `capability_required` with
`missing_services`, `request_saved=true`, `required_api_version`; no build
proposal is issued until the required services are available. The exact request
is retained in the project. Unknown additive output types may be ignored.

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

Device snapshots are bounded views, not full database records: capabilities occur
once, redundant device diagnostics stay in desktop status, and a long summary is
represented by a complete short notice that the full plan is retained. Up to four
pending-command references contain IDs/type/package/boot/expiry for reconciliation;
they are not executable replay requests. Full stored commands and actual separate
install/run requests retain their original source/archive checksums and guards.
Native control frames remain within 8192 UTF8 bytes, 1024 JSON guard tokens and
depth 12. Desktop status and the retained plan are not shortened or mutated.

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
source_sha256, archive_sha256, boot_id, expires_at, start=false. Both hashes come
from the verified restore package, never the failed candidate. These commands
are distinct from user confirmations.

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

Device App Manager supports app_download for an explicitly selected tested
package and app_backend_delete_prepare/app_backend_delete_confirm for its own
history. This additive extension keeps SD absence checks, revision/boot/session
binding and event idempotency. Read-only app_list/app_versions include bounded
downloadability and device deletion flags. See
[DEVICE_APP_MANAGER_HANDOFF.md](DEVICE_APP_MANAGER_HANDOFF.md) for exact fields,
confirmation TTL and device UI requirements. Direct DELETE routes retain their
existing administrator restrictions.

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

## Background repair from APP ERROR

See [DEVICE_FIX_ERROR_HANDOFF.md](DEVICE_FIX_ERROR_HANDOFF.md) for the complete
device UI flow and examples. Additive events: app_repair_prepare requires app_id;
optional package_id, app_version, sha256 (Lua source), error_code, message and
typed diagnostics identify the actual failed source. Missing log/version is
allowed; missing app identity must be resolved by the device error context or
an explicit fallback app choice. Never infer another app from the AI dialogue.

Backend emits app_repair_status with repair_id, proposal_id and a300s proposal
TTL. The Fix user action explicitly sends build_confirm with both proposal_id
and repair_id; prepare alone never invokes generation. Status can be queried
with app_repair_status and repair_id or app_id, including after reconnect.
Jobs outlive device page/session closure and use the normal immutable package,
versioning, quality and capability gates. New code is based on the latest saved
version with original failure evidence retained. A ready job does not execute
code: app_download, install receipt and explicit run_confirm still apply.

Diagnostic sha256/source_bytes inconsistent with the named package are retained
as identity_conflict and trigger an inventory request. They do not create a
known-bad source guard or block a different immutable source. Firmware must
capture app/package/version/checksum at actual runtime start, before teardown.

## Device-independent builds, Resume and one-line statuses

See [DEVICE_BACKGROUND_BUILD_HANDOFF.md](DEVICE_BACKGROUND_BUILD_HANDOFF.md)
for the device UI and verification matrix. `backend_features` in snapshots and
session_started advertises `background_builds_v1` and `status_text_v1`.
The Lua API fingerprint is unchanged.

Confirmed device builds use private generation snapshots and a bounded queue
(max8). Closing a page, session_stop, disconnect or a changed FIRE boot detaches
the UI; generation/testing/package publication continue on the running PC.
No detached job issues install/run commands. Reconnect/session snapshots publish
background progress and pending ready notices. Completed jobs, notices and
bounded dialogue/plan snapshots persist on disk. An actual PC backend shutdown
interrupts unfinished work without silently replaying paid requests.

Additive device events require the usual scoped v0.2 envelope:

| Event | Additional required fields | Behavior |
| --- | --- | --- |
| build_background | build_id | Detach foreground; keep job running |
| build_jobs | none (offset optional) | List scoped jobs, four per page, plus active_run |
| build_resume | build_id | Restore project/dialogue and current progress/package |
| build_cancel | build_id | Cancel only that active/queued job; preserve completed packages |
| build_notice_ack | build_id, notification_action=open/dismiss | Open Resume or dismiss completed popup |
| job_control | job_action; exactly one build_id or repair_id | Same existing job actions from the native control menu |

`job_controls_v1` announces `job_action=resume|pause|cancel|background|context|delete`.
`build_jobs` is one list, newest `created_at` first, four rows per page. A repair
with a child build appears once with both references; a repair without a build
uses `job_kind=repair`. Rows expose actual app name and `can_resume`, `can_pause`,
`can_delete`, `can_add_context`. `next_offset` retains normal pagination.

Pause prevents the next model request and lets an already sent reply finish.
Received code and completed usage remain stored; paused source is locally tested
before its reusable checkpoint is exposed. Resume restores the existing job and
requires its current explicit BUILD confirmation; no generation is triggered by
listing, reopening or changing settings. Cancel retains unknown usage/reservations.
Delete hides only a finished Resume row; active work must first be cancelled, and
app packages, source, data, logs and usage are retained. Evolution children still
use their original mandate/control/permission gates.

`context` with `text` accepts 1..2000 UTF8 bytes through the existing Jobs context.
Without text it arms a server-owned, device/job-bound target for five minutes and
returns `job_control_result(status=context_ready, display_text="Si mer kontekst")`.
The next ordinary audio recording/transcription adds the note directly to that
job without a DialogReply call. Explicit app selection clears this target; expired
or wrong-owner targets are rejected. In-flight model inputs remain immutable.

Other controls return `job_control_result` with job_action, build_id/repair_id,
status and a short message; Resume/cancel/background may reuse the established
build/repair response. No control installs or starts an app by itself.

Job views contain build_id, project_id, app_id, name, status, phase, progress,
message, background, package_id/version, can_open, created_at and status_text_version.
No source, dialogue history or credentials are included. `build_job_status`
pushes progress; `build_ready_notice` announces ready packages. Notices repeat
until acknowledgement; firmware deduplicates by build_id. Dismissal preserves
Resume/library access. `build_resumed` includes state/progress/package identity
and history_restored. Ready Resume uses normal install_request/receipt handling;
only explicit run_confirm starts the app. A new boot never inherits old command
authority. Native runs require app_stop and a matching receipt before switching.

### Failed-build Resume (`failed_build_resume_v1`)

Failed jobs remain in `build_jobs` with `can_open=true`, `can_resume=true` when
a plan is retained. Views/status events add `error_code`, `error_status`, a
redacted `diagnostic_message` (at most 240 characters on device) and `retryable`.
Short errors distinguish `ai_output_limit`, `ai_refused`, `ai_invalid_response`
and `ai_incomplete` from account/budget/network failures. PC details can be longer.

`build_resume` for a failed job restores its project, app/base version, dialogue
and manual notes, without generating content. `build_resumed` returns
`state=awaiting_build_confirmation`, a fresh `proposal_id`, `can_retry=true`,
`package_id=null`, `history_restored=true`, and previous failure information.
An ordinary `build_proposal` follows; full notes stay server-side to preserve
the 8 KiB control-event limit. A new explicit `build_confirm` continues the SAME build_id. Failed execution
metadata is appended to run_history, source/test artifacts keep their attempt
numbers, and attempts continue upward. The latest source and validation error
are supplied to correction; locally passed source can be revalidated/reviewed
without regeneration when its identity/context still match. Existing legacy
retry_of children remain readable but new confirmations do not create them. Merely opening Resume never spends tokens.
Repeat Resume before confirmation reuses the pending proposal. Event replay
cannot consume the same confirmation twice. Old failures cannot replace active
progress on reconnect. See [device handoff](DEVICE_FAILED_BUILD_RESUME.md).

Default backend policy now uses adaptive corrections: `total`/`max_attempts`
can be null instead of a fixed candidate count. Render the supplied single-line
message; do not invent a 1/4 counter. Technical device/runtime limits remain.
Conversation `effective_capabilities.conversation_audio.output_enabled` can be
false because AI speech is disabled on PC, while `input_enabled` remains true.
In that case assistant text/proposals complete normally and no `audio_ready`
follows. The UI must allow the next turn without waiting for an audio event.

build_progress.message, app_repair_status.message, error.message/status_message
and last_error_status are complete NFC Norwegian lines, at most28 characters AND
28 UTF-8 bytes. status_text_version=fire-status-text-v1. error.diagnostic_message
retains redacted PC detail. Assistant messages, transcripts and audio_ready text
retain their full dialogue semantics. Firmware measures actual font width,
renders æøå, and shows no DOWNLOADING AI VOICE transport status.

Transient provider failures retry the same generation/review up to four times
with bounded exponential backoff/jitter, respecting Retry-After. Quota/billing/auth
errors are not replayed. Waiting shows Venter på AI-kapasitet and consumes no Lua
correction. All compile/runtime/review/delivery gates remain authoritative.


### Durable continuation and boot discovery (2026-11-23)

`build_progress`/`build_job_status` include resume_count (0 initially). A job
can transition failed -> queued -> building -> ready with the SAME build_id.
Firmware must clear prior active errors on queued/building/ready, even if the ID
does not change; older resume_count events cannot overwrite the current run.
`build_resumed.progress` remains an object; top-level phase, status,
progress_percent and resume_count are additive scalar fields for device UI.
`build_progress.progress` and job-view progress remain numeric percentages.

Boot/session snapshots discover owned active jobs including foreground jobs,
even if a Background acknowledgement was lost. Catalogs prioritize building
before queued; progress pushes retain deterministic order. Pending completion
notices also cover jobs whose Background message was lost and repeat until
explicit open/dismiss ACK. Firmware owns the On/Auto/Off connection policy;
backend never initiates an outbound device event without an authenticated
session. Auto must finish the boot job query before dropping an idle connection.
See DEVICE_BUILD_CONTINUATION_HANDOFF.md for the firmware state machine and tests.


### Cancel/minimize device-error repair (`repair_cancel_v1`)

A short press minimizes the repair UI without cancelling the PC task. Restore
by app_repair_status(repair_id); session snapshots prioritize active repairs.
Once assigned, build job views include repair_id and operation=repair so Resume
can restore the same repair UI. Top-bar progress and ready notices use normal
build lifecycle events. A queued repair need not have a build_id yet.

C explicitly sends app_repair_cancel with repair_id and the standard v0.2
identity envelope. Only the owning device can cancel. It stops a prepared,
queued or building repair, including a resumed build, and returns the ordinary
app_repair_status with status/phase=cancelled. Repeated cancellation is safe.
A publication which won the race returns ready; cancelling never deletes a
completed tested package. Firmware must negotiate repair_cancel_v1 before
using the new event. See the exported device-event schema and device handover.

## Optional Runtime AI transport

See [canonical Runtime AI](../contracts/RUNTIME_AI-v1.json). Events
`runtime_ai_request` and `runtime_ai_cancel` use the existing authenticated
device envelope/dedup. OS supplies `request_id,app_id,package_id,source_sha256,
run_id,boot_id`. Request adds `instructions,data_json,schema_json,timeout_ms`.
`runtime_ai_result` echoes identity plus `state=completed|failed|cancelled`,
`result_json,error_code`. Only the actual current run/package/source and owner
may request or receive results. Stop, reboot and disconnect cancel; reconnect
never automatically replays a charged request. OFF cancels and returns an error
only to the same valid run, never stale result data.

Apps-list opening uses explicit `run_confirm(package_id)`. Existing SD AI apps
require complete fresh current-boot/current-epoch inventory with exact package,
version and checksum, plus verified backend archive. `run_request` includes
`source_sha256`; actual native `app_started` must confirm it. Identical already
running native source may bind without resetting local app state.

AI Developer sends `mode_select` with `runtime_ai_mode=auto|off` independently of
`conversation_mode`; SessionStart also accepts it. `ui_event/runtime_ai_policy`
acknowledges mode/available/enabled. OFF binds generation; global/per-app runtime
authorization remains separate. Old events omit the optional fields.

Assistant/progress/ready/error events include `display_text`: one complete LCD
line, at most28 UTF-8 bytes. Full assistant `text` remains the spoken reply.
The same model call supplies both; fixed phases/fallback never need another call.

## Optional Data Engine and iterative development

[DATA_ENGINE-v1.json](../contracts/DATA_ENGINE-v1.json) is the canonical optional
extension. `capabilities.data_engine` includes the exact version/hash and actual
capture sources/limits; manifest contains only version/hash. Optional
`service_methods` and `service_modes` narrow real adapters/modes without changing
the old hardware hash. Absent fields preserve old profiles; unsupported declared
methods/modes fail generation validation and delivery compatibility checks.

`data_request` operations are `process`, `develop`, or internal `sync`.
`data_cancel` and `data_result` share existing authenticated socket identity:
request_id/app_id/package_id/source_sha256/run_id/boot_id. The current verified
app run must match before admission and after asynchronous work. Immutable sealed
captures from an older version of that same app retain their original source.

Each descriptor binds `components={data,index,events}` with size/SHA per part;
top size/SHA equals data. POST `/sessions/{session_id}/data/{request_id}/{dataset_id}`
uses the existing device credential, octet-stream, X-Data-Part, X-Data-Offset and
X-Data-SHA256 (CHUNK hash). Chunks are at most8192 bytes. Empty sidecars use an
empty POST and SHA256(empty). Response has exact Content-Length and
`{offset,complete,next_upload}`; complete refers to that part. upload_required
contains only one next instruction. Completion requires all three whole-file
hashes. Active authorized duplicate chunks are idempotent; cancel drains raw-file
work before releasing its lock. Missing transfers resume at a verified offset.
No AI call occurs during sync. Runtime AI refs automatically use this same sync.

`app_develop_request` carries mode update/fork/feedback, instruction and optional
dataset descriptors. `app_develop_ready` returns context_id. A normal subsequent
SessionStart may provide development_context_id; server resolves the frozen base
and ownership rather than trusting client-selected parent source. A desktop/web
conversation can open the same context. No generation starts before the current
proposal is confirmed. Legacy OS Improve without datasets remains supported.
`app_observation_confirm` carries context_id and confirm/reject. Server preserves
the original snapshot and stores a separate source/run/boot/hash-bound user
observation. AI hypotheses and user observations never become protocol proof.

Backend Data/Studio Data and improvement show datasets, processing, assessments,
confirmation state and frozen development contexts. Raw downloads use existing
authenticated UI routes and attachment responses. Updates/rollback/version deletion retain raw app data. Explicit deletion of all app history removes its
own data components/results/jobs/contexts; active work blocks that deletion.
A parent fork grant becomes unavailable if its explicitly deleted source history
is removed. There is no automatic purge or cross-owner data grant.

Implementation and offline integration tests are not physical Data Engine
verification. Actual capture/radio/AI/Improve end-to-end status is recorded
separately with firmware and user-triggered measurements.

BLE `ble-ad-jsonl-v1` keeps the full payload_hex; optional integer adv_length
marks the advertising/scan-response boundary within those same bytes. Legacy
records without that field remain accepted. A received combined62-byte payload
is not automatically a valid31-byte advertising replay.


## Optional Evolution and native backend settings

The optional `capabilities.evolution` must match the exact version/contract in [EVOLUTION-v1](../contracts/EVOLUTION-v1.json). Existing Lua SDK, hardware, Runtime AI and Data Engine contracts remain unchanged. The extension is OS-only; Lua cannot submit these controls.

`evolution_status/prepare/confirm/control/telemetry` reuse the authenticated session, durable event deduplication and ordinary Builder. Settings use `backend_settings_status/prepare/confirm` over the same transport and existing DesktopStore/model catalog/UsageLedger. Status never spends money. Confirm checks the current revision/proposal and records the actual confirmation event. A changed model, source, context, permission or evaluation invalidates a mandate before another paid request. Manual builds retain current-proposal `build_confirm`; physical install/run remain separate and require real receipts.

Pause prevents the next action while allowing an already sent response to be journalled. Stop can cancel it; an unknown result cannot be automatically repurchased on reconnect/Resume. A known monetary admission failure can be resumed explicitly after a settings change. Disable all monetary limits does not disable output/resource/iteration/security limits or OpenAI account quotas. Provider cost, unknown usage, empirical estimates and internal reservations remain distinct.

All five Evolution features and telemetry default off. A candidate must pass ordinary local tests/review and independent frozen comparison before delivery. Non-improving versions remain archived without becoming the recommended basis. Owner-wide strategies require an explicitly approved, source-bound trial on at least three apps, then a separate adoption confirmation; trials do not install/run or replace those apps' recommended versions.

A `permission_required` snapshot provides `permission_request={operation,prepare:{permission_job_id},permissions,display_text}`. Native OS may offer “Vurder tillatelser”, echo only that prepared reference through ordinary `evolution_prepare`, show the resulting exact scope/model/permission proposal, and require a separate confirmation. Only then is the old mandate superseded. The same stored candidate is revalidated/reviewed, without purchasing identical source again or reusing its former verdict.

`settings_json` is revision-checked and whitelisted; it never contains keys, credentials, endpoints or arbitrary configuration. Model choices and monetary bounds come from the backend. AUTO/OFF updates both global Runtime AI authorization and developer inclusion while preserving per-app OFF. Active model calls retain their selection; model changes report busy instead of pretending to save. Money-only disable affects the next admission, never silently restarts an Evolution job. Read views show active backend settings, even when unrelated PC settings are saved pending an explicit apply.

This describes candidate source/offline verification. Production activation and fresh physical capability/receipt evidence remain separate delivery gates.

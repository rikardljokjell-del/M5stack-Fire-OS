# Negotiated Lua runtime contract

Optional FIRE App SDK: [FIRE_APP_SDK.md](FIRE_APP_SDK.md) and
[APP_SDK-v1.json](../contracts/APP_SDK-v1.json) define shared UI, fonts, assets and
native graphics for `fire-app-sdk-1.0` packages. The device still advertises the
unchanged `fire-lua-0.2` hardware contract, plus optional
`app_sdk: {version: "fire-app-sdk-1.0", contract: "<SDK SHA256>"}`. Both version and
SDK hash must match before delivery. Old packages remain valid. See
[backend/preview details](FIRE_APP_SDK_BACKEND.md). SDK physical verification is
tracked separately; PC rendering is not physical runtime or timing proof.

The older baselines below are historical contracts; actual fresh capabilities
and the negotiated version take precedence over their historical service lists.

The baseline below documents fire-lua-0.1. For the new fire-lua-0.2 contract, all exact method arguments/result shapes, OS resource ownership and firmware work, see [HARDWARE_API_HANDOFF.md](HARDWARE_API_HANDOFF.md) and [the exported registry](../contracts/HARDWARE_API-v0.2.json). Never infer physical hardware support from the PC simulator. Current inspected firmware dae75bf / 74ac26a exposes display/buttons/rgb/imu/time/jobs/gpio/pwm/i2c/uart, with the limited resource profile in the device handoff. Other registered services remain unavailable. Conversation audio is independent of Lua mic/speaker permissions. Release-v4 adds a cumulative 256-text-byte callback limit and three I/O failure profiles for hardware apps.

## Optional Data Engine

The exact optional API and bounds are in [DATA_ENGINE-v1.json](../contracts/DATA_ENGINE-v1.json).
SDK apps require `data`, `sd`, `jobs`, `fire.data` permission and the exact
`data_engine` version/hash advertised by firmware. This does not change the
hardware, SDK or Runtime AI contracts. Missing extensions grant no data access.

`fire.data.create/append/mark/seal/info/read/record/process` use existing jobs.
Read returns at most112 raw bytes as an array. Append accepts at most512 bytes;
metadata and options are bounded JSON strings, not a general Lua JSON/loader API.
Use actual `capture_sources` and `capture_limits`; requested rate is not measured
rate. `process` provides deterministic stats, filtering, spectrum and comparison.
Unknown timing produces cycles/sample rather than unsupported physical Hz.
Raw data, OS index and markers remain separate SHA-bound immutable components.

A Runtime AI request may include `dataset_refs`; the OS first synchronizes any
missing components. Backend resolves authorized refs to selected real content or
finite multi-axis statistics within the existing768-byte data and1536-byte total
AI bounds. Raw logs/packet bytes/labels are untrusted data. No model call is made
for sync or deterministic processing. Results remain AI assessments, not facts.

`fire.data.develop('update'|'fork'|'feedback', instruction)` is a user-button
intent. OS prepares a frozen app/package/source/run/data context and opens the
existing AI Developer. It does not buy generation or bypass the current proposal
`build_confirm` or tested-package `run_confirm`. Fork grants only frozen readonly
parent references. Existing apps without this API can still use OS Improve
without gaining upload permission. User confirmation/rejection is a separate
OS-controlled observation, never an app-provided physical-proof flag.

PC Data Engine jobs use bounded synthetic fixtures, not actual recording/SD/BLE.
Record fixture metadata uses bounded synthetic duration/rate sample counts and
the matching csv/audio/text kind; these counts are not physical acquisition.
A read outside retained fixture content fails rather than inventing raw bytes.
No PC output establishes physical capture, radio delivery or native timing.

# fire-lua-0.1 runtime contract

The authoritative signatures/restrictions are also in the injected
`fire_backend/data/FIRE_DEVICE_CONTEXT.md`. Firmware and PC must use Lua **5.4**,
text-only source (no bytecode), DOT calls, and an app-private environment.
Firmware source inspected: 2d47b0a (see DEVICE_E2E_ACTIONS.md). It now
contains a native runtime and adapters. Source implementation is distinct from
physical verification. Current handshake: all five services below, 131072 bytes,
10000 ms, conversation audio_input=true/audio_output=false. The source includes
capture/WAV upload; physical input verification is still pending. Older false/false
profiles remain supported. Neither conversation flag grants Lua audio access.

## Lifecycle and budgets

Display lifecycle: the reviewed FireOS::drawLuaApp clears the offscreen sprite
BEFORE every update; it is NOT a retained canvas. Render the complete scene on
EVERY update, even when simulation does not advance. Init-only graphics and
early returns before drawing disappear. on_button changes state only. Presenting
the finished sprite is OS-owned. See DISPLAY_QUALITY.md for mandatory release-v3
visual checks and physical verification limits.

Define `init()` and `update(dt_ms)`, optionally `on_button(button, action)`.
Call top-level initialization, then init, then updates; every callback must
return. OS owns scheduling, display, audio, input, SD and stop/navigation.
Accumulate dt_ms or subtract a captured uptime baseline for relative animation;
do not assume time.millis() starts at zero or a fixed FPS.
Release tests run seven fresh-VM input/timing profiles over the full positive lifetime, or a 60-second test horizon for max_runtime_ms=0. The old 180-frame worker is a smoke test only. No finite PC test proves every future state, native 32-bit arithmetic, physical heap or hardware correctness. See APP_REPAIR_HANDOFF.md.

- max_memory: Lua allocator hard cap, 65536..262144 bytes, no higher than
  advertised device capability. Firmware must account for VM allocations too.
- max_runtime_ms: 0 means run until user exit; positive values are legacy per-start lifetime limits up to 10000ms. This is separate from callback safety. Never insert an app auto-close timer. Devices must explicitly advertise 0 before backend issues unlimited manifests. Firmware changes are required; see APP_REPAIR_HANDOFF.md.
- max callback instruction count: 200000, hook every 1000 VM instructions;
  includes top-level initialization and button callbacks. Hook inaccessible to app.
- max API calls per start: 20000. Stop on bounds/quota errors.
- Backend worker process deadline: eight seconds (PC-only guard).
- Only OS-reserved long actions may interrupt/stop without waiting for Lua.

These are the backend validation limits and the required firmware contract.
Current source caps allocation at 131072 bytes and total runtime at 10000 ms;
its callback hook also checks 12 ms. The runtime-limit path currently reports
failure rather than normal stop; see the device handoff. PC timing does not prove ESP32 timing.
Native Lua is built with LUA_32BITS=1/LUA_USE_C89=1; desktop Lua uses wider
numbers. Avoid precision-sensitive math and large integer/bit patterns.

## Allowed environment

`fire`, `type`, `tonumber`, `tostring`, `pairs`, `ipairs`, `next`, and a restricted
math table: abs/floor/ceil/min/max/sqrt/sin/cos/pi. Local variables and tables work.
No Python objects/callbacks, io, os, debug, require, package, load, dofile,
ffi, metatables, raw table access, pcall/xpcall, coroutines, GPIO, network, flash,
OTA, ESP restart, credentials or other apps' data. No Lua app audio/SD in 0.1.
Do not expose native FireOS/M5 objects, even if a corresponding OS service exists.

## Services (all numeric inputs must be finite)

| Service | Methods | Bounds/results |
| --- | --- | --- |
| display | clear(c); circle(x,y,r,c); rect(x,y,w,h,c); line(x,y,x2,y2,c); text(x,y,s,c) | x 0..319, y 0..239, r 0..160, w 0..320, h 0..240; RGB565 c 0..65535; text <=80 UTF-8 bytes |
| buttons | pressed(b) | A/B/C boolean down-state |
| rgb | set(i,r,g,b) | i 0..9; channels 0..255 |
| imu | accel() | table {x,y,z} in g, finite numbers; synthetic on PC |
| time | millis() | native OS uptime in ms, may wrap; PC uses synthetic uptime |

Display circle and rect are outlines (native drawCircle/drawRect); clear fills
the screen. Lines are one
pixel wide. The OS adapter clips drawing to the 320x240 app surface. Text uses a
fixed device font; PC simulator records text, it does not guarantee glyph support.
All numeric display arguments and RGB indices/channels must be integer-valued;
use math.floor/ceil after animation calculations. Native luaL_checkinteger rejects
fractions; backend now rejects them too. Do not rely on native clamping.
Text must be a Lua string (no implicit conversion of tables).

Each used service must appear exactly once in required_services. Permissions
must be exactly `fire.<service>` for those entries, with no extras or duplicates.
Capabilities are authoritative and missing services remain unavailable.
Current rgb host stores pixels but renders the whole strip on every set call,
at brightness 180. Use uniform-strip effects; independent pixels/gradients are
not established. The rgb service name alone does not promise per-pixel rendering.
Unknown or undeclared methods must fail, including access through aliases.

Buttons: native callback action is pressed only; names A/B/C. Poll pressed()
for release transitions. OS long A=home, long B=quick
settings, long C=back (650 ms) are NEVER passed into Lua. A short action may
arrive after release because the existing OS reserves double-click handling.
The simulator exercises synthetic A/B/C presses and release polling, without
inventing released callbacks. Firmware owns physical debouncing/timing.
IMU values are synthetic on PC; native host falls back to zeros if IMU is absent.

## Physical receipts

Report app_started after successful init. Report app_healthy after at least one
successful update with no runtime error. These require the issued run_id.
On error, stop/clean up first, then app_failed with the same run_id and a short
error_code. On normal exit send app_stopped with run_id and reason=completed,
user_exit or runtime_limit. A backend-requested stop includes its stop_id instead.
Rollback restores files/selection only; another run requires explicit run_confirm.

## Package installation

Only four ZIP_STORED entries are accepted: apps/<id>/manifest.json, main.lua,
assets/ and appdata/. manifest.entry=main.lua. Validate CRC, exact file list,
manifest schema, permissions, source checksum and full archive SHA256/size.
Never extract arbitrary names or overwrite live appdata. Store versioned code
and retain current/previous/backup per app. A partial download/extraction must
not change the active version, and recovery must tolerate power loss during SD
updates. Do not use the firmware .bin loader or OTA API.

## Optional Runtime AI

The separate [Runtime AI contract](../contracts/RUNTIME_AI-v1.json) owns the
version, hash, limits and signature of
`fire.ai.request(instructions,data_json,schema_json,timeout_ms?)`.
Only SDK apps with `ai`, `jobs`, permission `fire.ai` and the exact optional
`runtime_ai` extension may call it. Old hardware/SDK hashes remain unchanged;
old and non-AI manifests omit the extension.

The call returns a job ID or `nil,error_code`. Load/init requests return
`stale_run`; request from update/button after actual run binding. Use existing
`fire.jobs.poll/result/cancel/close`, never wait. Ready result is
`{ok=true,data=<bounded Lua object>}`; failure is `{ok=false,error_code=...}`.
One pending AI job occupies one of the existing four job slots. Results are
validated, never truncated. No general JSON/file/loader API is exposed.

Aggregate relevant real observations locally. Call on a real button/event with
fresh basis, cache the last result, and retain useful local/offline behavior.
Use short app-specific labels, enums/numbers and button pages; never dump JSON,
Markdown or unsupported symbols on the LCD. Mark AI assessment separately from
measurements. See [Runtime AI usage](RUNTIME_AI.md).

# fire-lua-0.1 runtime contract

The authoritative signatures/restrictions are also in the injected
`fire_backend/data/FIRE_DEVICE_CONTEXT.md`. Firmware and PC must use Lua **5.4**,
text-only source (no bytecode), DOT calls, and an app-private environment.
Firmware source inspected: 65f8f3e; it does not implement this runtime yet.

## Lifecycle and budgets

Define `init()` and `update(dt_ms)`, optionally `on_button(button, action)`.
Call top-level initialization, then init, then updates; every callback must
return. OS owns scheduling, display, audio, input, SD and stop/navigation.
Use monotonic elapsed milliseconds, not wall-clock or a fixed FPS assumption.
PC tests use 180 frames at 16 ms, limited further by manifest.max_runtime_ms;
these tests do not prove future frames, physical heap or hardware correctness.

- max_memory: Lua allocator hard cap, 65536..262144 bytes, no higher than
  advertised device capability. Firmware must account for VM allocations too.
- max_runtime_ms: TOTAL per-start wall runtime, 16..10000 ms. It is not a
  per-frame allowance. At expiration stop with reason=runtime_limit.
- max callback instruction count: 200000, hook every 1000 VM instructions;
  includes top-level initialization and button callbacks. Hook inaccessible to app.
- max API calls per start: 20000. Stop on bounds/quota errors.
- Backend worker process deadline: eight seconds (PC-only guard).
- Only OS-reserved long actions may interrupt/stop without waiting for Lua.

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
| time | millis() | monotonic ms since app start |

Display circle is filled; rect is filled; clear fills the screen. Lines are one
pixel wide. The OS adapter clips drawing to the 320x240 app surface. Text uses a
fixed device font; PC simulator records text, it does not guarantee glyph support.
PC numeric coordinates may be fractional; firmware truncates toward zero before
drawing (after bounds validation). RGB indices/channels/colours must be integer
values; text must be a Lua string (no implicit conversion of tables).

Each used service must appear exactly once in required_services. Permissions
must be exactly `fire.<service>` for those entries, with no extras or duplicates.
Capabilities are authoritative: rgb requires per-pixel control, not just current
firmware's all-strip RMT helper. Unavailable adapters must not be advertised.
Unknown or undeclared methods must fail, including access through aliases.

Buttons: actions pressed/released; names A/B/C. OS long A=home, long B=quick
settings, long C=back (650 ms) are NEVER passed into Lua. A short action may
arrive after release because the existing OS reserves double-click handling.
The simulator exercises A/B/C edges; firmware owns physical debouncing/timing.

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

# FIRE App SDK: device integration

The authoritative API and quotas are in [APP_SDK-v1.json](../M5Stack-backend/contracts/APP_SDK-v1.json).
Canonical UI/fonts/assets/licenses live in [app_sdk](../M5Stack-backend/fire_backend/data/app_sdk).
`M5Stack-backend/scripts/build_app_sdk.py --check` checks the generated
`src/fire_app_sdk_data.h` against those sources. Do not edit the generated header.

SDK development has not been installed or physically verified. The current
physical RC9 delivery remains documented in PHYSICAL_SD_2026-11-25.md. The newly
reported firmware SD-write fault is a separate deferred TODO; this SDK change
does not investigate or repair firmware download, SD storage or OTA.

## Compatibility and ownership

SDK packages opt in using `api_version="fire-app-sdk-1.0"` and the separate
canonical `api_contract`. FIRE OS checks the exact version and contract before
starting Lua. Older firmware rejects this version. Existing fire-lua-0.1 and
fire-lua-0.2 apps retain their API and argument limits; the old hardware hash is
unchanged. The capability extension is only `app_sdk={version,contract}`, matching
the backend strict model. Display permissions gate both native SDK methods and
`fire.ui`; hardware permissions and brokers are unchanged.

The trusted flash UI source returns a table and is loaded through a protected
call into `fire.ui`, inside the app-private Lua VM and its existing memory and
instruction budgets. Apps receive no general loader, require, OS or filesystem
access. UI state is destroyed with the app VM. The OS still clears the existing
320x240 M5Canvas before every update and presents the completed frame.

## Native implementation

- `fire_app_bitmap.h` reads the canonical glyph masks and palette-RLE directly.
  UTF-8 is validated before any text is drawn. Unsupported scalars use `?`.
  Text is transparent, aligned and clipped inside the specified box; no inherited
  M5GFX font, text datum, background or size state is used. Palette index0 is
  transparent; black at another index remains opaque. Scale and flips use source
  coordinates, and tint applies only to tintable entries.
- `fire_app_graphics.h` provides clipped gradients, pixel-center even/odd polygon
  fills, rounded rectangles and bounded three-degree arc tessellation. RGB565
  interpolation rounds to nearest. Arc vertices use C++ lround (ties away from
  zero); polygon fixed-point division truncates toward zero. These details matter
  for simulator comparisons. Outline lines use the existing M5GFX line renderer.
- Point lists use at most256 stack bytes and filled polygons at most16 vertices.
  There is no heap allocation, decoded atlas cache, SD read, extra framebuffer or
  new worker in these native renderers. Trusted font/asset data stays in flash.
- Existing grid output is preserved while adjacent identical colors are merged
  into longer fills. SDK-only cumulative limits are384 cells/32768 cell-pixels
  per callback; the old384-cell per-call behavior remains for legacy apps.
- Existing64-call/2048-byte/256-text-byte,200000-instruction,12ms callback and
  131072-byte VM ceilings are not raised. Text and measurement both charge text
  bytes, points charge4 bytes/point, assets charge ID bytes. Native elapsed time
  is included by the existing post-callback check. Integral float coordinates
  from safe math helpers work; numeric strings and nonintegral values are errors.

## Checks and remaining evidence

The actual normal target compiled and linked locally. IRAM end remains
`0x4009fb98`, leaving1128 bytes; static RAM remains63796 bytes. Normal firmware
now explicitly uses C++17 for the generated inline constexpr data (recovery and
bootloader flags are unchanged). The local build with VM peak accounting used
2646645 program bytes. The latest cosmetic UI/header update followed compilation
of that header; CI must verify the final frozen sources/data. These are build facts,
not runtime heap or callback measurements. Local logs and source hashes are in
ignored `M5Stack-backend/workspace/app-sdk-check/`.

Tests include portable raster clipping/gradient/polygon/round-rect/arc behavior,
legacy-grid pixel equivalence, actual generated font/asset validation, UTF-8,
text alignment, transparent/black palette handling, flips and tint. The actual
production Lua runtime is compiled with the vendored Lua5.4 core and LUA_32BITS,
using host-only allocator/clock adapters. It checks SDK gating, trusted UI load,
old profile behavior, sandbox, invalid inputs, quotas, grid accumulation and the
native elapsed-time guard. Host compilation/linking succeeded; Windows blocked
execution with Application Control4551. Linux CI execution is required and no
local runtime pass is claimed.

The host test loads the actual gallery (all six pages), stopwatch and racing
fixtures and exercises their buttons. CI output records registration/UI+app VM
bytes, host pointer size, sampled and allocator-peak VM bytes, and native
fill-span/pixel counts. The allocator peak includes short-lived UI-load allocations.
The clock is a deterministic host fixture: these counts are work observations,
not measured ESP32 callback time or physical heap. Legacy line/circle adapters
in the host canvas are approximate and do not establish M5GFX pixel parity.

Pending physical acceptance: callback/render timing, real VM/heap peaks, a
200-cell board, representative UI/asset screens, navigation/cleanup, and legacy
app regression. Simulator output and host adapters cannot establish any of these
physical results. No USB/COM opening or flash operation has been done for SDK.

# FIRE OS AI Developer — hardware-first context, negotiated fire-lua-0.1 / fire-lua-0.2

## Source baseline and verification
Authoritative handoff: M5Stack-device/BACKEND_HANDOFF.md.
Read-only source review: commit 9dda9d9 (and preceding voice/lifecycle changes),
fire_backend_client.*, fire_lua_runtime.*, fire_lua_package_manager.*, fire_os.*,
platformio.ini and the handoff. Actual FIRE observations take precedence over
this source review and the PC simulator. physical_verified=false for PC tests.

The source NOW contains a WebSocket protocol-0.2 client, local Lua 5.4 runtime,
restricted hardware adapters and a ZIP_STORED SD package manager. This is source
implementation, NOT proof of physical installation, sound or successful app use.
Never claim device installation/running/rollback without matching receipts.

Additional read-only transport review: device commit 90028a9 implements a
four-slot authenticated reverse TCP listener on port 8766. The PC can initiate
these streams through USB tethering; FIRE remains the HTTP/WebSocket client.
This does not grant additional capabilities or prove microphone/package/runtime
operation. Existing protocol-0.2 authorization and receipts remain mandatory.

## Board, build and pins
M5Stack FIRE, ESP32-D0WDQ6-V3, dual core 240 MHz, 16 MB flash, PSRAM
(nominally 4 MB; free memory is not measured here), about 520 KB internal SRAM.
320x240 ILI9342C, M5Unified/M5GFX, Arduino. Stable PlatformIO default:
m5stack-fire-ble, espressif32@6.6.0, default_16MB.csv. The external-loader partition
CSV is for isolated PoC environments, not the stable baseline.
M5Unified dependency ^0.2.7; exact resolved M5Unified/M5GFX not established by
the committed build output. NimBLE-Arduino 2.5.2. Lua 5.4 with LUA_32BITS=1 and
LUA_USE_C89=1: 32-bit integer/float behaviour differs from desktop Lua doubles.
Avoid large integer/bit patterns, precision-sensitive math and excessive work.

Buttons A/B/C: GPIO39/38/37; RGB: GPIO15, ten LEDs; mic GPIO34; speaker GPIO25;
SD CS GPIO4; I2C SDA/SCL GPIO21/22; Grove B GPIO36/26, Grove C GPIO16/17.
GPIO16/17 are connected to PSRAM on FIRE: do not assign them to UART while PSRAM is active. GPIO34..39 are input-only without internal pull resistors. Pins are context, NOT a permission grant. Only the negotiated fire-lua-0.2 OS adapters may use explicitly announced pins/buses. FIRE has no built-in GPS: an external GNSS module can use a free announced UART. Never expose raw OS/M5 pointers.

## Version negotiation and authoritative session capabilities
The injected session policy and exact host registry are authoritative. fire-lua-0.2 is a versioned contract. Latest inspected firmware implements a SUBSET, not all registered services. The actual session handshake remains authoritative. It covers display/buttons/rgb/imu/time/jobs/gpio/adc/dac/pwm/i2c/uart/spi/wifi/bluetooth/mic/speaker/sd/power/rtc. Use its exact signatures, dependencies, advertised resource allowlists and contract fingerprint ONLY when api_version=fire-lua-0.2 and the matching service is announced. Async jobs must be polled without waiting, result errors handled, and handles closed after every outcome. Never replace a requested hardware toolbox with an unrelated demo when firmware support is missing; retain its requirements and explain the adapter prerequisite.

The current source advertises api_version=fire-lua-0.2 with the matching registry hash, services=[display,buttons,rgb,imu,time,jobs,gpio,pwm,i2c,uart,adc,dac,spi,sd,rtc,speaker], max_memory=131072, max_runtime_ms=0 (until user exit). GPIO read26/35/36, write26, PWM26, I2C0 (writes64), UART2. ADC36, DAC26, SPI2, private SD and RTC are implemented. Lua speaker tone/play/stop is now implemented; Lua mic/Wi-Fi/Bluetooth and power.sleep remain unavailable. Source presence is not physical audio or I/O verification. Legacy devices can still announce 0.1 and positive lifetime. Conversation flags:
audio_input=true, audio_output=true, firmware_version=fire-os-0.2. Source now
contains ADC capture on FIRE GPIO34, WAV upload and hashed PCM reply playback.
Latest timed-ADC captures produced about 4.6 s audio from 4.8 s event intervals,
after earlier capture gaps and a wrong-rate DMA stream. Some transcripts remain
inaccurate; do not assume reliable recognition or correct language from a nonempty
transcript. One speaker reply was downloaded/acknowledged and confirmed
understandable by the user. Neither fact grants Lua audio APIs. Older input-only or no-audio firmware
remains valid and must receive the appropriate fallback.
Generate and declare ONLY the services actually advertised in this session.
Never substitute all simulator services for a missing device capability.
Keep within the advertised memory/runtime budget, even when the source has
not yet demonstrated hardware enforcement. No guarantee of free heap is implied.

Audio flags are for developer conversation, NOT Lua permissions. No-audio
handshake is valid: explain that text can be sent from PC and do not attempt
recording or speech output. Firmware may set each audio flag true only after
that input/output path has been physically tested. Backend audio enablement alone
does not grant hardware support. Do not fabricate a transcript or a spoken reply.

## Lua lifecycle, limits and OS ownership
Mandatory display model: FireOS::drawLuaApp clears the OFFSCREEN sprite to black
before EVERY update. Previous drawings do not persist. Render the entire scene,
including static text, on every update, also while waiting/paused/game-over.
Separate simulation ticks from unconditional rendering; never early-return before
drawing. on_button only changes state. At most one clear before drawing; no
clear after drawing. One completed sprite is presented by OS, never by Lua.
Full redraw in one offscreen frame is safe; empty intermediate frames are not.
Keep text readable and within a conservative 6-pixel-per-byte by 8-pixel-high
single-line footprint; keep full shapes on screen. Simplify the complete scene
to meet budgets instead of splitting its rendering across updates. No sprite, flush, swap or camelCase fillRect APIs are exposed. fire-lua-0.2 additionally offers the exact fill_rect/fill_circle/pixel/grid signatures from its registry; never call those on 0.1. Limit cumulative rendered text to 256 bytes per callback; cache labels/rotations/row representations and use compact complete frames. This rule applies to ALL apps.

Define init() and update(dt_ms); optional on_button(button, action). Use local
state, short returning callbacks, bounded tables and simple math. Never create
your own event loop. Firmware owns Wi-Fi/BLE/SD/IMU/audio/RGB and UI scheduling.
The OS uses a 320x240 16-bit canvas (153600 pixel bytes before overhead).
The runtime source has a 200000-instruction hook and 12 ms update callback check;
source also caps Lua allocation at 131072 bytes; positive lifetimes up to 10000 ms apply to legacy firmware only. New backend contract max_runtime_ms=0 means run until user exit; use it ONLY when advertised by this device. Never add an auto-close timer. Callback and memory limits remain mandatory. Test horizons are not app lifetime. These source limits do not prove physical enforcement.
neither PC timing nor source inspection proves actual ESP32 timing/enforcement.
PC guards additionally cap allocator use, API calls and process duration.
Use the actual manifest/session lifetime policy (0=until user exit, positive=legacy limit).

Legacy 0.1 globals: fire, type, tonumber, tostring, pairs, ipairs, next; math only abs/floor/ceil/min/max/sqrt/sin/cos/pi. No string/table libraries or loaders in 0.1. Version 0.2 adds ONLY the bounded string/table helpers in the registry, never unrestricted standard libraries. Any earlier 0.1-only limitation applies to that legacy profile, not to negotiated 0.2 services.
Prefer pairs/ipairs over low-level next calls. Native and desktop base-function
details are not bit-for-bit equivalent; use this conservative subset.

## Hardware adapters usable only when their service is advertised
- fire.display.clear(c), circle(x,y,r,c), rect(x,y,w,h,c),
  line(x1,y1,x2,y2,c), text(x,y,s,c). DOT calls. All numeric display arguments
  must be finite integer-valued numbers; explicitly use math.floor/ceil where
  needed. Safe bounds: x=0..319, y=0..239, r=0..160, w=0..320, h=0..240,
  c=RGB565 0..65535; text <=80 UTF-8 bytes. Do not rely on native clamping.
  Baseline circle/rect use drawCircle/drawRect OUTLINES. 0.2 additionally supports fill_rect/fill_circle/pixel/grid from the registry. Text size 1 has an opaque BLACK background; no scalable-font or transparent-text API is available. Use supported geometry/grid for larger emphasis; do not invent font functions.
- fire.buttons.pressed("A"|"B"|"C") gives current down-state. Current OS forwards
  only "pressed" to on_button AFTER RELEASE; do not rely on a "released" callback. An OS double shortcut may delay short delivery beyond 350 ms. In menus use one short-action path; never duplicate it through raw polling. Raw gameplay polling must not claim OS gestures. Long A=home, long B=quick settings,
  long C=back, threshold 650 ms; double-click window 350 ms where configured.
  OS navigation remains reserved and cannot be intercepted by generated apps.
- fire.rgb.set(index,r,g,b), integer index 0..9/channels 0..255. Latest reviewed firmware implements per-pixel rendering; actual output still needs physical verification on the connected build.
- fire.imu.accel() returns {x,y,z} in g. Native host reads M5.Imu when enabled;
  source fallback is zeros if unavailable. PC values are synthetic, not telemetry.
- fire.time.millis() returns native OS uptime (may wrap), not time since app init.
  Prefer accumulated dt_ms for animation; capture a start value for relative time.

Permissions must exactly equal fire.<service> for required_services. Mic, speaker,
Wi-Fi, Bluetooth and SD do NOT become Lua services because the OS has them.
Never expose credentials, raw filesystem/radio handles, OS settings, Python bridge, io/os/debug,
require/package/load/dofile, FFI, metatables, raw access, pcall/xpcall, coroutines,
flash, partitions, OTA, ESP restart, unannounced GPIO or other apps' data. In 0.2, SD operations are app-private and Bluetooth handles are bounded OS-managed identifiers, not native pointers.

## Package and workflow
ZIP_STORED: apps/<app_id>/{manifest.json,main.lua,assets/,appdata/}; only main.lua
is generated; assets/appdata start empty. Manifest has id/name/version,
negotiated api_version (0.1 baseline or 0.2 plus exact api_contract SHA256), entry=main.lua, required_services, max_memory,
max_runtime_ms, permissions, checksum=SHA256(main.lua UTF-8 bytes). Outer archive
size/SHA256 are separate metadata. No .bin, firmware flashing, OTA or WASM.
Mandatory naming: every generated app gets a short, understandable purpose-based
name (1-3 words, <=32 characters). Backend assigns a stable lowercase ASCII folder
slug of at most 24 characters, e.g. sprettsirkel or snake, with a short numeric
suffix only to distinguish different apps. Updates keep the original folder.
Technical project/package IDs are internal and must never be invented as app names.
The user explicitly chooses new app versus update before providing a request.
For updates the selected base_package_id and its source are authoritative;
do not silently change apps, use a newer unrelated draft or reset version history.
Deleting an app from FIRE does not delete PC history or authorize automatic
reinstallation. PC deletion requires fresh device absence evidence and an
explicit administrator action. Historical receipts do not imply present SD files.

Speak Norwegian. Retain requested hardware features; explain a missing firmware adapter without suggesting unrelated substitutes. Ask only essential clarifications.
Present a concrete supported plan. No code generation/build without explicit
build_confirm, and no run without explicit run_confirm. Simulator success never
establishes physical current/installed/running. Device acknowledgements and actual
hardware checks determine those facts. Never weaken the contract to hide a
firmware problem; record outstanding source/hardware gaps for the device agent.

## Mandatory FIRE experience
A/left=previous/up, B/middle=select/confirm, C/right=next/down in all menus. OS owns long and configured double gestures; no required chords/holds/doubles. Use the whole 320x240 scene with coherent spacing and hierarchy, not a tiny desktop panel. Every game needs a quick New game and available RGB/sound settings menu before play; sound defaults off and requires actual Lua speaker+jobs (now implemented in inspected source; use only when announced). RGB updates are rate-limited/state-based. Full standards are injected as fire-experience-v2 and enforced by the source-bound review. Settings persist over rounds; long sessions must not auto-close.

## Native game audio follow-up
Speaker tone/play/stop use asynchronous jobs and a dedicated M5Unified channel. App volume is relative gain under OS master: master zero/mute always silent, live OS volume changes apply, and app stop must not stop AI/system channels. AI capture/playback may return busy; retry safely without blocking or overlapping tones. New generated melodies should sequence short original tones with elapsed-time scheduling and close jobs. There are no automatically supplied WAV music assets: never play an invented file path. Existing private WAV files must be RIFF PCM16 mono 8/16/24kHz, at most 512KiB, streamed by OS. OS backlight is never changed by game audio. Source build passed; melody/mute/master-volume/AI-conflict/start-stop/backlight tests on FIRE are still outstanding.

# FIRE App SDK 1.0

Status: implementation and integration testing in progress. Physical SDK verification is pending.

The canonical contract is [APP_SDK-v1.json](../contracts/APP_SDK-v1.json).
The packaged `data/app_sdk/contract.json` and native flash header are generated
from it. Legacy fire-lua-0.2 apps and their hardware hash remain supported.
SDK apps require the explicit fire-app-sdk-1.0 profile and matching advertised
`app_sdk.version` and `app_sdk.contract`.

## Screen and sandbox

Render the complete 320×240 scene on every update. The OS owns the existing
offscreen framebuffer, presentation and long A/B/C gestures. UI functions do
not present or schedule frames. `ui.screen` and `ui.background` explicitly
clear within that same update; never clear after drawing the scene.
No require, arbitrary loading, filesystem or Python callbacks are exposed.
Calling UI requires display permission. Module initialization and native calls
use the existing memory, instruction, text, I/O and time budgets.

```lua
local ui=fire.ui
local count=0
function init() ui.set_theme("modern_dark") end
function on_button(button,action)
  if action~="pressed" then return end
  if button=="B" then count=count+1 end
  if button=="C" then count=0 end
end
function update(dt_ms)
  ui.screen("Teller", "Trykk B for a telle")
  ui.card(10,55,300,135,"ANTALL",count,{font="digits28",icon="icon.activity"})
  ui.buttons("","Tell","Nullstill","B")
end
```

Reserve the bottom button bar at y=211. The usual body is y=48..201.
Button labels follow the physical left/middle/right A/B/C order. UI helpers
draw controls; the app implements their actions in `on_button`. A label
must never advertise an action that the app does not handle.
Layouts are composition starting points, not restrictions on custom drawing.
Do not use init-only graphics, partial redraws or automatic app-close timers.

## Native graphics and UI

The nine new display methods are `text_style`, `measure_text`, `asset`,
`round_rect`, `triangle`, `polyline`, `polygon`, `gradient_rect` and `arc`.
Exact arguments, optional defaults, bounds and raster semantics are in the
canonical registry. They use RGB565 and the same shared bitmap/palette data.
PC raster is a preview, not proof of hardware timing or perfect legacy parity.

The UI module includes titles, labels, panels, cards, A/B/C button bars, menus,
tabs, toggles, checkboxes, selectors, dialogs, toast messages, loading screens,
progress bars, rings, gauges, battery/signal indicators, line/bar charts,
clocks/timers, HUD, start/pause/game-over screens, sprites, particles, compass,
radar, tables, empty/error states, navigation, layout and animation helpers.
`sdk.json.ui_signatures` supplies the exact argument names without loading
the whole module into a generation prompt.

Common card options: background, icon, accent, color, font, detail.
Label options: color, font, width, align. Panel options: color, radius, border.
Sprite options: scale, tint, flip_x, flip_y, fps. Progress/ring/chart options:
color, track/background; ring also accepts label, font, thickness.
Oversized chosen fonts fall back to ui12; text still too long is clipped.
Generation must use concise labels. A bounded eight-entry metric cache avoids
repeated measurements of static text.

Themes: modern_dark, modern_light, minimal, professional_instrument, industrial,
retro_arcade, pixel_art, sci_fi, adventure, nature, neon, classic_console.
`ui.theme()` returns the current app-private palette, which can be customized.
Fields: bg, panel, fg, muted, accent, good, bad, border.

## Asset Library

805 resources: 287 curated Lucide icons, 495 Kenney dungeon/town/platform tiles
and 23 reviewed vehicle/item sprites. Device rendering uses local flash tables,
without per-frame SD reads. `assets.json` supplies canonical ID, category,
dimensions, style, description, license and palette runs. Palette index0 is
transparent; black at another index is opaque. Tint only affects tintable
assets. Aliases help search and are never accepted as runtime identifiers.

Examples: icon.thermometer, icon.battery, icon.car, tiny-dungeon.096 (knight),
pixel-platformer.024 (alien), pixel-platformer.202 (coin), one-bit.car-top,
one-bit.bus-top, one-bit.ufo and one-bit.projectile. UI animation IDs:
alien.walk, coin.spin, flag.wave. `ui.sprite` chooses their frame IDs from
elapsed time; direct native drawing always receives a canonical asset ID.

Fonts: ui12, ui12b, ui16, title20, digits28, pixel8, legacy6x8.
New fonts include ASCII, Norwegian letters, degree, multiplication and minus.
Unsupported Unicode scalars use question-mark fallback. Bitmap masks and
metrics are shared, without runtime dependencies on installed system fonts.

## Licenses and provenance

Retain the entire `data/app_sdk/licenses` directory in distributions.

- Lucide: ISC plus the included Feather MIT notice. Pinned source:
  https://github.com/lucide-icons/lucide/commit/164efbaf879fb29f55d88047efd49fc7725f53ab.
- Kenney: CC0. Original License.txt files from tiny-dungeon, tiny-town,
  pixel-platformer and 1-bit-pack are included. Source packs came from a
  pinned mirror, with original licensing inspected. URLs and SHA256 are
  recorded in sources.json.
- Atkinson Hyperlegible and Press Start 2P: SIL OFL1.1, with original copyright
  and license files. Legacy Adafruit5x7 via M5GFX: BSD3.

Third-party artwork/font licenses do not define licensing of unrelated project code.

## Rebuild and acceptance

Run `python scripts/build_app_sdk.py` to regenerate the flash header and
packaged contract. `--check` rejects stale copies. No device I/O or network
is used. The one-time offline `scripts/import_app_sdk_assets.py` uses pinned
artifacts in ignored workspace/sdk-sources, Pillow12.3.0 and resvg-py0.5.0.
Normal installation never imports resvg or downloads source packs.

Both hosts must reject unsupported capabilities, unknown IDs/fonts, malformed
point lists, wrong booleans, invalid UTF8 and over-budget calls. Screenshots
are bound to the exact source/package and scenario; they never establish
physical installation, running or health.

Representative app quality, generation/review cost, native memory/IRAM,
callback/render timing, old-app regressions and physical response must be
recorded before this delivery is declared complete. The firmware SD-write
issue remains a separate open TODO and is explicitly outside this task.

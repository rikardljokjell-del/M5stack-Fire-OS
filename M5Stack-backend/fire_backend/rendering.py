"""Permanent generation policy for the native, cleared-per-update sprite host."""

NATIVE_HOST_POLICY = "fire-native-host-v1"

VISUAL_POLICY = """
Mandatory display quality for EVERY new app and repair, regardless of the user's request:
The reviewed FIRE host clears its OFFSCREEN sprite to black before EACH update,
then presents the completed sprite. It does NOT promise a retained app canvas.
Render the COMPLETE visible scene in EVERY update callback, including unchanged,
paused, game-over and waiting states. Never return early from update before drawing.
Separate simulation/state timing from rendering: a game may advance every 160 ms,
but its scene must still be drawn on every update between those steps. Draw static
labels, borders and all live objects every frame too. init-only graphics disappear.
Use a render() helper called unconditionally at the end of update. Button callbacks
only change state; the next update renders that state. No drawing in on_button.
Draw one coherent frame. At most one display.clear per callback, only BEFORE drawing,
and omit it when the black host background suffices. Never alternate empty and drawn
frames, flash backgrounds or toggle visibility as a refresh technique. A clear and
complete redraw in the SAME offscreen frame is safe; never split those across updates.
Keep text readable, short, aligned and within bounds, with a consistent palette and
layout. Reserve at least 6 pixels per UTF-8 byte and 8 pixels of height for each
single-line label; use simple supported glyphs. Keep entire circles/rectangles
inside the screen, not merely their anchors. Never redraw only a changed object
assuming the old canvas survives. Stay
within callback budgets; choose a simpler complete scene over partial/blank frames.
Each callback has a cumulative 256-byte text budget, including unchanged labels.
Native host safety gate (also applies on the FIRST frame): at most ONE rgb.set
call per callback, at most 128 total grid CELLS and 32768 grid pixels per callback.
rgb.set currently transmits the whole ten-LED strip synchronously, not just one
pixel. Queue desired colours and advance one changed pixel per update; do not
rewrite unchanged LEDs. Both bars must settle over bounded successive frames.
Use a single RGB output helper, called ONCE from update, including menu/paused
states. init/on_button may update desired colours but must NOT call rgb.set.
Reference pattern (adapt desired values; preserve one physical call per callback):
local wanted, sent, cursor = {}, {}, 0
local function rgb_tick()
  for step=1,10 do
    local i=cursor; cursor=(cursor+1)%10
    local c=wanted[i]
    if c and sent[i]~=c then
      fire.rgb.set(i,c[1],c[2],c[3]); sent[i]=c; return
    end
  end
end
Assign a NEW colour table when a desired colour changes; do not mutate a sent
table. Never call rgb_tick twice, or combine it with another direct rgb.set.
Native grid calls invoke fillRect once per cell INCLUDING black/empty cells;
count cells as well as pixels. Precompute glyphs and cached display values;
prefer compact large integer readouts plus precise native text where useful.
These conservative limits reject known cost patterns; they do not measure ESP32
wall time or prove that a synchronous firmware adapter is nonblocking.
Cache labels and composed game rows when state changes, then redraw cached strings.
For large game boards use the negotiated 0.2 display.grid batch API if available;
on 0.1 use short cached rows instead of concatenating wide ASCII boards every frame.
No invented APIs: use only the exact negotiated registry. 0.2 fill_rect/fill_circle/
grid are available only on 0.2; 0.1 has outline primitives. No app sprite, swap or flush.
The OS alone presents frames. PC checks detect known rendering defects, not physical
tearing, actual display refresh timing, or every possible visual defect.
"""

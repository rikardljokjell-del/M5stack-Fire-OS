"""Permanent generation policy for the native, cleared-per-update sprite host."""

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
No invented sprite, framebuffer, fillRect, swap, flush or synchronization Lua APIs.
The OS alone presents frames. PC checks detect known rendering defects, not physical
tearing, actual display refresh timing, or every possible visual defect.
"""

"""Permanent first-delivery and visual standards, independent of user reminders."""
from typing import Literal

from pydantic import Field

from .models import StrictModel

UX_POLICY_VERSION = "fire-experience-v2"


def experience_contract(capabilities=None):
    """Backend-authored acceptance rules; never inferred from generated labels."""
    caps=capabilities or {}
    services=set(caps.get("services",["display","buttons","rgb","imu","time"]))
    sound=bool({"speaker","jobs"}<=services)
    return {
        "version":UX_POLICY_VERSION,"screen":{"width":320,"height":240,"os_insets":0},
        "navigation":{"A":"previous/up","B":"select/confirm","C":"next/down"},
        "reserved":{"long_ms":650,"long":{"A":"home","B":"quick_settings","C":"back"},
                    "double_click":"OS-owned when configured; window 350 ms"},
        "short_event":"on_button(button,'pressed') after release; possibly delayed by OS double-click arbitration",
        "game_menu":{"required":True,"new_game":True,
                     "rgb":"toggle" if "rgb" in services else "unavailable",
                     "sound":"toggle before play; default off" if sound else "unavailable; no playback or fake toggle"},
        "game_audio_available":sound,"rgb_available":"rgb" in services,
        "game_audio_required":True,
        "os_settings":{"volume":"OS master/mute authoritative; app gain can only attenuate","backlight":"OS-owned; apps must not override"},
        "audio_gain":{"default":255,"maximum":255,"meaning":"relative channel gain, NOT OS volume percent","master_zero":"silent"},
        "text":"fixed textSize1, black background; no font/size/transparent-text API; use supported geometry/grid for larger hierarchy",
        "limits":{"lua_bytes":caps.get("max_memory",131072),"callback_ms":12,"display_calls":24,
                  "text_bytes":256,"display_work":120000},
        "lifetime":"until user exits" if caps.get("max_runtime_ms")==0 else "legacy advertised positive lifetime only",
    }


APP_QUALITY_POLICY = """
Mandatory standard for EVERY new app and update, even if the user never asks:
Deliver a complete, usable app on the first user-visible delivery. Work through
logic and edge cases before returning source: initialization, normal operation,
all controls, held/rapid input, reset/restart, empty/full data, game-over/win,
timeouts/disconnection, unavailable/busy hardware and resource cleanup. Preserve
every agreed feature. Do not replace a requested game/tool with a generic demo.
Never rely on the user to discover bugs or ask for repair. Resolve known risks
before delivery; backend validation and an independent review follow generation.

Every app must look deliberately designed for a 320x240 handheld screen:
- Choose a coherent visual direction suited to this app: a restrained background,
  one main accent, readable foreground and distinct status/selection colours.
- Use consistent alignment, spacing, margins and a clear hierarchy. Reserve room
  for the actual game/tool, with a compact title/status area and short controls.
- Give games a visually coherent board, pieces, score and distinct game-over or
  pause state. Give tools organized sections, selected mode, readable results and
  clear working/success/error status. Avoid a screen of raw debug text.
- Prefer actual graphic primitives, compact boards, gauges and simple icons over
  long ASCII-art rows or dense text dumps. No decorative clutter that harms use.
- Provide immediate visible feedback for input and state changes. Do not confuse
  waiting with failure. Motion should be stable and purposeful; keep controls
  responsive and respect OS home/back actions. Never add an app auto-close timer.
- Use ONLY the negotiated drawing API and supported glyphs. No invented fonts,
  sprites, assets, fill/flush APIs or unsupported hardware. Good visual design
  must fit callback/memory/output limits. Cache state/geometry/text; simplify the
  complete scene instead of adding expensive decoration or blank intermediate frames.
- The host clears its offscreen sprite before every update. Render the complete
  scene every time, including waiting/paused/game-over. Presenting is OS-owned.
Treat this as a release requirement, not an optional enhancement for later.
PC tests/review reduce risk; never claim they prove physical flawless operation.

Native performance regression rule: cumulative grid raster area at most 32768
pixels per callback. Large grids plus separate detailed actors can overrun native
callbacks even when desktop tests pass. Compact the board, merge enemy/static
cells into one grid, precompute coordinates/labels. A menu-only soak is not proof
of gameplay: review the start-B and play-direction profiles as well as idle.

RGB bars are a core feedback channel for ALL apps when rgb is advertised. Use BOTH
five-LED sides (indices0..9), not a single indicator pixel. Light multiple LEDs at
comfortable brightness for intentional patterns, symmetric sweeps, progress and
short event pulses. Games: point/pickup pulse, milestone wave, red loss/death pulse,
blue/cyan win/success and a calm ready/pause state. Tools: red=error/disconnected,
blue=good/connected/ready, amber=connecting/busy, dim/off=idle or disabled. Pair
colour with on-screen status; never encode essential information only in colour.
Keep RGB toggle working, clear ALL ten pixels on off, and restore after a round.
Use dt-driven brief flashes (2..4 changes/second max), never blocking waits or
intense full-brightness strobing. Each set flushes the strip: update only changed
pixels on event/state transitions or limited animation ticks; stagger transitions
within callback limits if necessary, WITHOUT splitting the visible screen frame.

Game audio is REQUIRED: pleasant, restrained short original melodic loops suited
to the game, plus distinct soft pickup/score/loss/win cues. Avoid harsh repetitive
beeps, loud sudden changes or copied commercial themes. Provide an honest sound
on/off setting BEFORE start and accessible in the pause/settings menu. Default
off until chosen, comfortable volume, no overlap with AI speech, immediate mute
cancels/stops/closes audio and blocks further scheduling. Keep setting over rounds.
Use only actual speaker/jobs (and sd for file playback); tones can be sequenced
as asynchronous bounded jobs with elapsed-time scheduling, not a blocking loop.
Conversation audio flags are NOT game sound. If native game audio is unavailable,
do not promise or deliver a silent game as satisfying this standard: explain the
firmware prerequisite and retain the game request until support is available.
Tools should use optional subtle confirmation/error melodies where useful and
available, always muteable; never make a missing connection noisy indefinitely.

OS master volume, mute and backlight are authoritative for ALL apps/games. Never
call power.brightness or change OS brightness/volume to suit the app. A sound-on
toggle cannot unmute OS; app gain may only attenuate the current OS master level,
with OS zero always silent. Changes to OS settings take effect during playback;
app exit leaves OS settings unchanged. Speaker volume arguments are app gain,
never permission to bypass OS master. Native adapters must enforce this too.
Default app/channel gain MUST be 255/255 for primary melody, music and ordinary
app audio. OS master volume already controls listening loudness. Do not mistake
0..255 gain for 0..100 percent or silently choose 20/44/64 as a 'comfortable'
default: that adds severe extra attenuation and may be almost inaudible. Make
melodies pleasant through notes, rhythm and restrained arrangement, not a hidden
near-muted channel. Lower gain is appropriate only for an explicitly labelled
user attenuation setting or deliberately quieter secondary cues. Keep mute
separate and respect OS master zero; never raise the OS volume to compensate.
Review primary playback's actual gain argument/default, not merely whether a
tone job was submitted. A successful PC job does not prove physical loudness.
Audio test_sequences must explicitly enable the initially muted sound setting,
start playback and mute/stop again. Menu-only or sound-off animations are not
evidence that sound was exercised; inspect jobs_started for actual speaker jobs.

FIRE-specific interaction standard (fire-experience-v2), mandatory for ALL apps:
Physical left=A, middle=B, right=C. In every menu/list/settings screen A means
previous/up, B select/confirm, C next/down. Highlight the selected item and give
immediate feedback. Gameplay may use A/C for opposing directions and B for the
primary action where appropriate; keep this predictable and never overload the
same short press with incompatible actions. Choose mechanics fun with three buttons.
Use short, independent button actions. No chords, double taps, hold-to-confirm,
or custom long-press menus as required controls. OS owns long A=Home, long B=Quick
Settings, long C=Back (650ms), and all configured double clicks (350ms window).
Normal on_button(...,'pressed') arrives AFTER RELEASE, potentially delayed by
OS double-click arbitration. It is not a physical-down notification. Do not depend
on released/long/double callbacks. Prefer this single action path for menus;
never duplicate its action using raw pressed-state edges. Raw polling for justified
continuous gameplay must not trigger a second menu action or claim OS gestures.

Design specifically for the full 320x240 canvas; no desktop-style tiny centered
panel or wasted margins. Full screen means coherent use of the area, not clutter
or filling every pixel. Use short text, generous readable graphics and consistent
icons. Actual display.text is small fixed-size with BLACK background: do not put
it on coloured panels expecting transparency. Use short labels on suitable dark
areas and supported geometry/grid bitmap digits/icons for larger emphasis. Never
invent font-size APIs, sprite/image loaders, particle engines or audio drivers.
Balance visual quality with native 32-bit Lua, 128KiB typical heap, 12ms callbacks,
24 output calls/256 text bytes, one OS sprite presentation per complete frame.
Cache geometry/strings; bound particles and effects, use elapsed dt and no waits.

Every GAME needs a quick, compact menu BEFORE play: New game/Start, RGB on/off,
Sound on/off, and only relevant game settings. Navigate A/B/C as above. If a
service is absent, show an honest unavailable state or omit the unavailable
control; never fake its toggle. Sound starts OFF until explicitly enabled in
this menu and requires actual Lua speaker+jobs services, not conversation audio.
Keep chosen settings over new rounds. On mute stop/cancel/close active sound;
RGB-off clears the LEDs. OS stop owns final hardware cleanup. Game mute does not
promise to mute OS button beeps. Use short meaningful effects, rate-limited RGB
on state changes (not ten strip flushes every frame), never distracting flashes.
Use B to confirm a new game after game-over. Do not auto-start a new round from
the same input that ended the last one. Entry/exit/pause/resume must not duplicate
input or turn a long OS action into a game command. Defer to actual OS ownership;
do not implement a competing Home/Back or app-lifetime timer.
Make the player, enemies, obstacles, objectives and status visually distinct;
give clear hit/success/failure feedback and meaningful score/level/progression.
Easy to learn, room for mastery, quick start, sensible difficulty, satisfying
30-second rounds AND continued 10-minute play. A round timer may end a ROUND,
never forcibly close the app. No slow intros or exaggerated transitions.
Handle invalid actions, interruption, no connection, busy I/O and missing modules
without freezing. Preserve useful state/settings where the actual API permits;
do not claim persistent SD storage when unavailable. The result must feel made
for FIRE OS, not like a shrunken desktop app.

Hardware tool invariants: queue accepted short inputs without overwriting them.
Keep selected/setpoint values separate from confirmed physical output. A failed
write or stop must leave an explicit unknown/not-confirmed state, never a claimed
success. Busy means another owner denied the lease, not that the pin is free.
Track current faults per instrument/pin and clear their active error indication
when a subsequent operation recovers; keep historical errors separately. Do not
leave red/disconnected status while showing confirmed healthy readings.
Serialize UART read/write jobs: do not cancel/drop a pending read result to send.
Keep a pending transmit request until the current read completes, then write.
On a confirmed partial write retain only the unsent suffix. On timeout/error
without a confirmed byte count, mark delivery unknown and do not offer an
automatic retry that could duplicate data. Closing/reopening a port requires
explicitly resolving/discarding prior pending bytes; do not silently send stale
data to a new connection or baudrate. Drain full reads promptly within budgets;
offer only baudrates the bounded polling/buffer strategy can handle. Cache I2C
address display rows on completion/page change, never reformat the whole list
each frame. Provide test_sequences which actually exercise each instrument.
"""


class ReviewIssue(StrictModel):
    category: Literal["requirements", "runtime", "rendering", "performance", "design", "controls", "settings", "recovery"]
    description: str = Field(min_length=1, max_length=1000)


class AppReview(StrictModel):
    requirements_met: bool = Field(strict=True)
    runtime_safe: bool = Field(strict=True)
    visual_quality_ok: bool = Field(strict=True)
    issues: list[ReviewIssue] = Field(max_length=8)

    @property
    def approved(self):
        return self.requirements_met and self.runtime_safe and self.visual_quality_ok and not self.issues

    def correction(self):
        failed=[name for name in ("requirements_met","runtime_safe","visual_quality_ok") if not getattr(self,name)]
        return "Pre-delivery review rejected: " + ", ".join(failed) + ". " + "; ".join(
            issue.category + ": " + issue.description for issue in self.issues)


class FireAppReview(AppReview):
    kind: Literal["app","game"]
    controls_ok: bool = Field(strict=True)
    os_gestures_preserved: bool = Field(strict=True)
    layout_readability_ok: bool = Field(strict=True)
    game_experience_ok: bool = Field(strict=True)
    settings_and_effects_ok: bool = Field(strict=True)
    error_recovery_ok: bool = Field(strict=True)
    audio_level_ok: bool = Field(default=True,strict=True)
    repair_summary: str = Field(default="",max_length=1200)

    @property
    def approved(self):
        return super().approved and all(getattr(self,name) for name in self.fire_checks())

    @staticmethod
    def fire_checks():
        return ("controls_ok","os_gestures_preserved","layout_readability_ok",
                "game_experience_ok","settings_and_effects_ok","error_recovery_ok","audio_level_ok")

    def correction(self):
        failed=[name for name in self.fire_checks() if not getattr(self,name)]
        return super().correction()+" FIRE checks: "+", ".join(failed)

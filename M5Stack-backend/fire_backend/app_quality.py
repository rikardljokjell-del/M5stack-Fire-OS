"""Permanent first-delivery and visual standards, independent of user reminders."""
from typing import Literal

from pydantic import Field

from .models import StrictModel

UX_POLICY_VERSION = "fire-experience-v1"


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

FIRE-specific interaction standard (fire-experience-v1), mandatory for ALL apps:
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
    repair_summary: str = Field(default="",max_length=1200)

    @property
    def approved(self):
        return super().approved and all(getattr(self,name) for name in self.fire_checks())

    @staticmethod
    def fire_checks():
        return ("controls_ok","os_gestures_preserved","layout_readability_ok",
                "game_experience_ok","settings_and_effects_ok","error_recovery_ok")

    def correction(self):
        failed=[name for name in self.fire_checks() if not getattr(self,name)]
        return super().correction()+" FIRE checks: "+", ".join(failed)

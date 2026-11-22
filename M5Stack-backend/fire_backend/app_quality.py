"""Permanent first-delivery and visual standards, independent of user reminders."""
from typing import Literal

from pydantic import Field

from .models import StrictModel


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
"""


class ReviewIssue(StrictModel):
    category: Literal["requirements", "runtime", "rendering", "performance", "design"]
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

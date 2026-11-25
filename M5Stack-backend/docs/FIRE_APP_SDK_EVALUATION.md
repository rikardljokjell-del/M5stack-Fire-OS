# FIRE App SDK: evaluation record

Delivery is still in progress. Passing adapter tests does not establish that
AI app generation meets the delivery target. This record preserves negative
results as well as subsequent improvements.

## First controlled AI cohort, 25 November 2026

The frozen integration is commit `ff08ac1`, using SDK contract
`e6972ef535053a898babec4b532be7418941d6adc00c5fd477828bb0b9940e57`.
Both generation and the existing multimodal review used the configured
`gpt-6-luna` model. Saved user settings were unchanged.

Eleven short requests covered stopwatch, weather, calculator, sensor dashboard,
instrument, Snake, Tetris, racing, space shooter, platform and adventure.
Stopwatch, calculator and racing also had matched legacy controls, giving
14 isolated builds. Each used the normal proposal confirmation and delivery
gates, with at most two generation attempts. No package was installed or run
on FIRE. Screenshots and hardware-service responses were PC simulation.

| Measure | Observed result |
| --- | ---: |
| Ready packages / builds | 0 / 14 |
| Ready within two generation attempts | 0 / 14 |
| SDK first candidates passing local checks | 6 / 11 |
| Legacy first candidates passing local checks | 1 / 3 |
| SDK first candidates using `fire.ui` | 8 / 11 |
| Generation / review requests | 28 / 14 |
| Input tokens, including cached tokens | 954,882 |
| Cached input tokens | 522,421 |
| Output tokens | 75,649 |
| Summed build wall time | 788.184 s |
| Estimated list-price cost | USD 0.087660410 |
| Requests with provider-reported usage | 42 / 42 |
| Physical device commands | 0 |

Local-check passes are intermediate results, not approved deliveries. The
different SDK and legacy case counts must not be compared as a statistical
success-rate study. The estimate uses the recorded model catalog rather than
an invoice; raw usage, sources, reviews and screenshot hashes remain locally
in ignored `workspace/sdk-benchmark/`.

Real app defects included clipped centered text, A/B/C legends disagreeing
with handlers, incorrect sensor units/rounding, stale readings after errors,
and invalid API bounds. The original results remain rejected.

Review also gave incorrect repair instructions: it inferred violation of the
physical 12 ms callback limit from a PC drawing-work estimate, and required
sensor I/O inside a button callback even when the button correctly scheduled
sampling on the next update. Those findings require correcting the shared
instructions, while retaining actual sandbox, resource and quality gates.

## Next evaluation

A separate prompt revision is being tested with consistent SDK-specific
bounds, selected hardware-method details, explicit text-box and A/B/C
semantics, and short reusable UI examples. Any subsequent cohort must retain
its own prompt/data fingerprints and report costs and outcomes separately.
The category selector was also tested against ordinary Norwegian compounds.
Before correction, bilspill, plattformspill, eventyrspill, sensordashboard,
måleinstrument and værapp incorrectly fell back to a generic dashboard.
The revised selector has explicit coverage for all eleven literal requests
and English equivalents, including relevant assets and layouts.

The second cohort is running with `fire-sdk-generation-v2`, the same models
and literal requests, and a new SDK-data fingerprint. It starts with stopwatch,
sensor dashboard and racing sentinels and stops for analysis if at least two
of those three SDK builds fail. The original cohort remains unchanged.
No improved success rate has yet been established.

One simulator accounting defect was reproduced with the same gallery source
and duration: retaining more diagnostic frames increased the reported app
memory, and eight captures could falsely exhaust the 128 KiB quota. The
corrected accounting reports 73,576 app bytes with zero, one or eight captures
and records private host diagnostics separately. Actual app/UI allocations
and the native 128 KiB limit remain constrained. This correction is not a
claim about native memory usage or generated-app success.

A separate deterministic check found low contrast in some shared themes.
RGB565 palette corrections now give at least 4.5:1 contrast for small primary
and secondary text, focused controls and toast text across all 12 themes.
All 85 palette checks pass. This establishes color contrast for those actual
foreground/background combinations, not visual quality of every composition.

## Verification boundaries

The original integration passed 719 backend tests. The revised backend passed
835 tests in 292.45 seconds, plus focused tests for the final font-metadata
label refinement. The native CI
snapshot `8547e46ea26b3c4c9db9a71b0b6d1a4757d9047d` passed 19 tests and three
firmware builds. These results do not establish physical callback time,
display output, memory headroom, package installation or recovery behavior.
Physical SDK acceptance and an actual device canvas image are pending.

The coordinator also exercised the actual updated Windows program and its
authenticated Chrome Studio session. An existing legacy0.2 level app rendered
three preview frames. Virtual C increased its visible tolerance from 1 to 2,
A restored 1, and B set a reference. The displayed input trace matched C/A/B.
New start cleared the trace, Advance1s reached 2.00s, and Close returned to
the library with delivery blocks retained. No AI, physical install/RUN or
settings action was taken. This verifies the preview interaction with one
existing app; SDK-specific app quality remains a separate gate.

## First physical SDK probe

The private, one-shot image derived from CI `8547e46` passed ordinary local
boot health, consumed its dedicated test arm and then stopped on the existing
12 ms callback guard in the first gallery scene. No complete gallery timing
or device image was obtained. The device agent observed no panic, watchdog
or additional reset in that probe. This is a real performance failure and
prevents approving the SDK firmware for delivery.

The actual 32-bit VM measured 5,807 bytes after API registration, 60,377 bytes
after UI and gallery loading, and a 60,452-byte allocation peak during loading.
Loading took 66,662 microseconds. These are measurements of that exact private
fixture/image, not of arbitrary generated apps or the later color revision.
The retained RC9 image remains the fallback; native rendering optimization
and a new guarded physical check are required. No runtime quota is raised.

## Compile-time footprint

Exact production CI linker maps provide this compile-time comparison:

| Measure | RC9 (`b77c579`) | SDK RC1 (`1f89c83`) |
| --- | ---: | ---: |
| Firmware binary bytes | 2,427,328 | 2,652,912 |
| Static data + BSS bytes | 63,796 | 63,796 |
| IRAM space remaining in linked segment | 1,128 | 1,128 |
| Flash text section bytes | 1,541,183 | 1,551,891 |
| Flash read-only data section bytes | 723,368 | 938,240 |

The new bitmap/UI data chiefly occupies flash. Static RAM and linked IRAM
usage did not grow. The existing small IRAM margin still limits future
interrupt-resident additions; it does not measure runtime free SRAM or PSRAM.
The contrast-corrected `1f89c83a7f6608cc160cd17198b017a4a55abcff` snapshot also
passed 19 native tests and all three builds in CI run 45591188634. Its exact
normal image is 2,652,912 bytes, SHA256
`8c947d2172584b134ea72d1500fb0a2eb8d620a5ccbc1b3748e897778efe6cce`.
The signed migration bundle and a fresh extraction of its nine-file ZIP
(eight required migration files plus the asset/font license notice) passed
signature, hash, image and layout checks without device access. These files
are local candidates until the remaining acceptance gates pass.

The user's reported firmware download-to-SD write failure remains open and
is outside this SDK task. Earlier isolated SD tests do not close that issue.

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

The second cohort used `fire-sdk-generation-v2`, the same models and literal
requests, and a new SDK-data fingerprint. It stopped at the negative sentinel
gate: five builds (three SDK and two legacy), zero ready, 11 requests,
136,431 input tokens (49,171 cached), 17,454 output tokens, 158.216 seconds
and USD0.018663935 estimated cost.

That cohort exposed a genuine context regression: the consolidated policy
had omitted the explicit requirement to define both `init()` and
`update(dt_ms)`. The first stopwatch and dashboard repair opportunities were
spent on that omission; later candidates then failed on invented `ui.asset`
and `ui16b` names. Native `fire.display.asset` and the seven real font IDs
were present in the request. Racing failed actual speaker-test coverage.
Version3 restores executable lifecycle boilerplate and gives precise unknown
font errors; the original failed results remain unchanged.

## Version3 pilot

| Literal request | Generation / review models | Generations / reviews | Seconds | Estimated USD | Pipeline result |
| --- | --- | ---: | ---: | ---: | --- |
| Stopwatch | Luna / Luna | 1 / 1 | 24.262 | 0.002874225 | Ready, standard-RGB gap below |
| Stopwatch | Sol / Terra | 2 / 2 | 49.469 | 0.0730548 | Ready |
| Sensor dashboard | Sol / Terra | 2 / 2 | 92.091 | 0.0964116 | Ready |
| Racing | Sol / Terra | 1 / 1 | 46.011 | 0.0512823 | Ready |

Model IDs are `gpt-6-luna`, `gpt-6.2-sol` and `gpt-6.1-terra`. The stronger
pilot used a temporary 8,000-token generation cap and the existing 6,000-token
review cap; the Luna control retained its uncapped configuration. Saved
Windows settings and models were unchanged. Twelve actual requests used
168,532 input tokens (16,108 cached) and 7,760 output tokens. Summed duration
was 211.833 seconds and estimated cost USD0.223622925. No physical command
was created. These small, differently configured samples cannot establish a
general model ranking or isolate model effects from the version3 correction.

All four passed local runtime tests and independent review. Manual follow-up
found that the Luna stopwatch omitted RGB entirely even though the actual
profile advertised it and the existing platform standard required feedback.
Its working stopwatch/UI core and pipeline-ready result are preserved, but
this is a real review/default-enforcement gap. It must not be counted as
fully satisfying every platform standard until corrected and retested.
The other three declared and exercised RGB. No result here proves physical
timing or integration.

## Remaining version3 Luna cases

The frozen follow-up measured the other ten literal SDK requests with the
same Luna/Luna version3 setup. Calculator and sensor dashboard became
pipeline-ready after two generations each; eight cases failed and none was
ready on its first generation. The run made 20 generation and nine review
requests, using 345,250 input tokens (55,812 cached) and 46,922 output tokens.
Summed build time was 644.509 seconds and estimated cost USD0.052962920;
all 29 requests had provider-reported usage and created zero device commands.

Together with the earlier Luna stopwatch, this gives 3/11 pipeline-ready
and 1/11 first-generation-ready for the version3 Luna requests. All three
ready candidates omitted the required RGB feedback. They therefore remain
unverified against the platform standards despite their historical ready
status. This is not an acceptable final generation-quality result.

Remaining defects included invented font/UI names, incorrect rounding,
missing speaker test coverage, controls or graphics left visible in the
wrong game state, lives lost independently of collisions, and audio jobs
not stopped on pause/mute/menu transitions. Original sources, reviews and
screenshots are retained. None of the final failures in this cohort was
the separately identified SDK edge-clipping simulator mismatch.

A deterministic SDK-only standards gate is being implemented after this
frozen measurement. It binds requirements to actual capabilities and the
confirmed request, verifies both RGB sides and required started audio jobs,
and preserves the working candidate for targeted repair. Existing legacy,
build-confirmation and run-confirmation gates remain in force. Historical
results above will not be rewritten to incorporate later repairs.

Offline revalidation of the six historical ready sources preserved all six
working cores. The three Sol/Terra candidates passed the new deterministic
RGB/audio gate; the three Luna candidates failed its RGB requirement. The
combined audit contains six unique source-bound records; one duplicate local
calculator recheck is recorded separately. No AI request or device command
was used. A deterministic gate pass is not an exhaustive semantic approval:
manual source review also found no RGB on/off control in the Sol stopwatch,
despite the existing experience policy and its earlier approved settings
review. This remaining review gap is retained explicitly.

The following version3 Luna measurements cover all eleven requests. Source
bytes describe the final candidate in that build, including rejected code;
they are not a count of delivered or physically installed code. Memory is
reported only where the full ready validation supplied a peak, and includes
the actual UI prelude under the PC VM's existing 128 KiB quota.

| Request | Historical pipeline result | Generations | Source bytes | PC app peak bytes | Seconds | Estimated USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Stopwatch | Ready; RGB gap | 1 | 872 | 68,823 | 24.262 | 0.002874225 |
| Weather | Failed | 2 | 5,525 | Not established | 53.180 | 0.004536160 |
| Calculator | Ready; RGB gap | 2 | 2,794 | 74,486 | 107.469 | 0.007472940 |
| Sensor dashboard | Ready; RGB gap | 2 | 1,775 | 72,047 | 59.651 | 0.005532540 |
| Technical instrument | Failed | 2 | 2,852 | Not established | 46.849 | 0.004349960 |
| Snake | Failed | 2 | 5,261 | Not established | 88.514 | 0.006560160 |
| Tetris | Failed | 2 | 5,465 | Not established | 67.366 | 0.003989580 |
| Racing | Failed | 2 | 4,980 | Not established | 34.447 | 0.003549280 |
| Space shooter | Failed | 2 | 5,441 | Not established | 63.338 | 0.006412160 |
| Platform game | Failed | 2 | 5,965 | Not established | 64.219 | 0.006596560 |
| Adventure | Failed | 2 | 5,974 | Not established | 59.476 | 0.003963580 |

For the original matched legacy/SDK controls, final source sizes were
3,646/2,577 bytes for stopwatch, 4,088/3,327 for calculator and 5,375/6,140
for racing. All six builds failed. Those observations alone establish
neither a successful before/after delivery nor general code-size savings.

## Targeted repairs after the standards checkpoint

These runs reuse the same projects, builds and retained source, rather than
starting new apps. The historical cohorts remain unchanged. Temporary
Sol/Terra roles apply only to evaluation; saved Windows models are unchanged.

| Retained case | New generations / reviews | Seconds | Estimated USD | Result |
| --- | ---: | ---: | ---: | --- |
| Weather: font repair | 1 / 1 | 64.064 | 0.073389000 | Rejected: stale data without freshness/date |
| Weather: freshness continuation | 1 / 1 | 69.871 | 0.072275000 | Rejected: local timestamp comparison across autumn DST |
| Platform game: audio cleanup | 2 / 2 | 107.027 | 0.135415200 | Pipeline-ready and deterministic RGB/audio pass |

The first repair's next request was blocked before API access by the
benchmark's conservative USD0.25 per-case reservation, rather than a provider
outage. Only the temporary evaluation limits then changed to USD0.35 per case
and 4,000/2,000 output tokens for generation/review; the production ledger
and profiles were preserved. The global experimental USD1 admission guard
remained. Expected completion of a bounded case is now distinguished from
an API/adapter failure in the test runner.

The platform source is
`f4a16ec14dc5cf55bd7942e97f7938f4374ca7cc20a90e06ceb2e6b461c3fbe5`.
Seven source-/PNG-verified images show menus, settings, play and LED off/on.
The coordinator independently inspected all seven. An initial suspicion of
title/score overlap was withdrawn after image and pixel-coordinate checks:
title ink occupies x13..183, while score ink occupies x256..303. No source
or measured result was changed because of that mistaken suspicion. This is
PC visual evidence, not physical play/audio/timing verification.

Across all runs through this checkpoint, actual provider-reported requests
have an estimated list-price cost of USD0.663989390. No physical AI-app
installation or RUN command was created. Weather remains rejected with its
source preserved; no additional weather request is authorized in this batch.

The three retained Luna-ready apps were then updated in their existing
projects, with the same app IDs and new0.1.2 versions. Temporary Luna/Luna
requests kept the 4,000/2,000 output caps, full USD0.25 per-case admission
and the global USD1 guard. Original packages were not overwritten.

| RGB/settings update | Generations / reviews | Seconds | Estimated USD | Pipeline/standard result |
| --- | ---: | ---: | ---: | --- |
| Stopwatch | 2 / 2 | 75.854 | 0.008215695 | Ready / pass |
| Calculator | 1 / 1 | 60.598 | 0.005054525 | Ready / pass |
| Sensor dashboard | 2 / 2 | 87.892 | 0.008812760 | Ready / pass; sensor-status caveat below |

All ten requests reported provider usage:169,047 input tokens (11,983
cached),12,116 output tokens,224.344 summed seconds and USD0.022082980.
Total estimated experimental spend through this checkpoint is USD0.686072370.
Source-bound on/off tests exercised nonzero output on every LED and finished
with all ten zero, for each app. The coordinator inspected the main images:
the calculator preserves its keyboard and adds a navigable RGB choice; the
stopwatch retains its core controls via a small options menu; the dashboard
keeps its panels and replaces unsupported separators with ASCII.

Static follow-up found a real dashboard fault-path issue: the Lua expression
`index < 5 and accel_ok or temp_ok` can report a good left status when
acceleration is invalid but temperature is valid. The measured ready/standard
result remains historical and is not an exhaustive sensor-error approval.
That precise source is retained for targeted correction. No physical app
operation is established by the PC toggle tests or screenshots.

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
label refinement. After the standards gate, one complete run passed 881 tests
and exposed one old dependency-fixture assumption: its fixed melody omitted
RGB while its preview profile now advertised SDK and RGB. Only the fixture's
scope was corrected to cover legacy and a legitimate SDK profile without
advertised RGB. All 48 affected dependency/standards/Resume tests then passed,
as did 65 context/standards checks and the earlier 103 integration checks.
No production gate was relaxed. This is not described as a second full run.
The later language/glyph checkpoint passed a complete 913-test run in
306.23 seconds, plus 88 focused checks. Its compact font facts come from the
actual shipped glyph masks, and its negation handling preserves the
difference between requesting no new audio and disabling existing game audio.
The native CI
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

## Second physical SDK probe

The next private image used the exact `4c89ce5` source with coalesced filled
panel rows and indexed glyph lookup. CI run 45594710399 passed 19 tests and
three builds. The private source was separately checked for UTF-8 preservation
against that snapshot; it retained the existing production strings.

The first gallery update still exceeded the unchanged 12 ms guard. Its
unfinished callback took 162,039 microseconds: 16,416 in instrumented native
display calls, including 15,975 in their Host implementations. Clear alone
took 10,846 microseconds. The remaining 145,623 microseconds includes VM,
helpers, scheduling and unprofiled work; it is not a measurement of pure Lua
CPU time. Nested text/asset measurements must not be added to the enclosing
native/Host times. No complete scene, later phase or device canvas was
obtained. These results do not approve either the private or clean SDK image.

API registration used 5,807 VM bytes; UI/gallery loading used 60,409 bytes,
with a 60,484-byte loading peak and 67,612-microsecond source load. No panic
or watchdog was observed. The retained RC9 was restored through ordinary
health approval and read back as A/app0, sequence 23, VALID with valid CRC.
The 45.038-second return observation recorded an 86,010-microsecond loop gap;
a subsequent ordinary restart was observed and COM3 closed. The consumed
private image remains in inactive B until a separately verified replacement;
this is an intermediate test state, not the final firmware handoff.

## Third physical SDK probe: isolated baselines

SDKQA3 retained the exact same production base and guards, adding bounded
timing checkpoints and small baseline fixtures. Actual callback measurements
confirmed 240 MHz on core1 and the existing 320×240, 16-bit PSRAM canvas.
Legacy arithmetic took 735 microseconds on its first update and at most
3,066; SDK arithmetic took 712 and at most 908. An empty SDK update took
59 and at most 158 microseconds. Those observations do not support treating
the earlier 145 ms residual as ordinary VM execution time.

The first black-clear callback took 11,044 microseconds. A later clear reached
12,341, including 12,100 in the native wrapper and 12,050 in the Host, and
failed the unchanged final time check after a normal `lua_pcall` return.
There was no throw/catch event to time in this run. The four prior baseline
phases completed; the rest, including theme-color clearing and all gallery
pages, did not run. Full-screen canvas filling is therefore a measured
bottleneck, while the cost of the earlier exception path remains unmeasured.

The retained RC9 returned through ordinary health approval to A/app0,
sequence25 VALID/CRC. The coordinator independently checked both metadata
CRCs and all three raw observation-log hashes. The return observation lasted
45.090 seconds with a 96,004-microsecond maximum loop gap, followed by a
20.148-second ordinary reboot observation. Neither showed panic/watchdog;
COM3 was closed. Inactive B contains the consumed private SDKQA3 image until
later cleanup. No clean SDK installation or physical visual approval is
claimed. A bounded fill optimization using the existing canvas is the next
code change; no VM allocation policy or resource quota is increased.

## Fourth physical probe: parity passed, fill speed did not improve

The `a2fb5d2` snapshot passed 20 native/release tests and all three firmware
builds in CI run 45607776172. Its exact normal image is 2,653,824 bytes,
SHA256 `ec4496891f1250b159f589a7f80227b7e115285af3cf677b124b95be146cc669`.
Static RAM remained 63,796 bytes and the aligned linked IRAM margin 1,128.
The coordinator checked the artifact ZIP digest and extracted files.

SDKQA4 compared original and raw16 full-canvas filling in 12 physical samples,
outside Lua callbacks. Whole-buffer SHA, every decoded pixel, drawing color
and layout agreed. For black, original fills took 10,042..11,294 microseconds
and raw16 took 11,398..11,411. For color 2113, original took 9,891..10,803 and
raw16 took 11,410..11,521. The new loop did not improve full-screen filling;
pixel parity alone did not establish a performance fix.

Four Lua baseline phases completed. The first clear(0) callback then reached
12,656 microseconds, including 12,377 in the Host, and the unchanged guard
stopped the run. No gallery, later app phase or canvas capture was obtained.
The retained RC9 returned as A/app0 sequence 27 VALID/CRC, independently
checked with the raw log hashes. Its 45.092-second return observation had
a 126,945-microsecond loop gap; a 20.063-second ordinary reboot followed.
No panic/watchdog was observed and COM3 closed. Inactive B26 contains the
consumed private probe; no clean SDK firmware is installed yet.

Code inspection then identified two OS background fills before the app's
own clear. The coordinated next design is one SDK OS-prefill with an explicit
per-app background preference. Only an initial matching clear on a privately
acknowledged, untouched frame may reuse those pixels. All logical I/O charges
and actual 12 ms callback guards remain. Later/different clears retain real
erase behavior; no app drawing is queued or moved outside its callback.

The unreleased SDK contract was revised from experimental `e6972ef5...`
to `83310c217698dd968f3773842f7f3fa05bc73b487a7c7f1cffefa33acec40667`,
adding `display.set_background`. The version remains fire-app-sdk-1.0, while
its explicit contract gate changes. Historical draft packages/images above
remain immutable evidence and are not silently accepted by the live current
Manifest. Legacy 0.1/0.2, the hardware hash and existing user apps are preserved.
The coordinated implementation now includes the native one-shot prefill
acknowledgement, next-frame configuration, all paint invalidators and the
matching simulator/capture/raster behavior. The existing 12 ms, 200,000
instructions, 128 KiB app memory and I/O quotas are unchanged. Instruction
accounting now resets at each callback; a reconstructed old-counter unit
case verifies the previous carry-over separately in native CI.

Backend verification passed 182 affected checks and 68 final focused tests.
The single final full run reported 957 passes and one derived-schema sync
failure in 312.72 seconds. Only the two JSON schema exports were regenerated
from the unchanged models; the contract test subsequently passed 1/1.
This is not represented as a fresh all-green full-suite run. Six canonical
gallery pages and four representative historical app sources have exact
decoded PNG pixel parity. The gallery has zero actual app-clear fills with
its explicitly prepared backgrounds. Historical sources/packages remain
immutable and are not accepted by the live current Manifest.

Native CI and a new guarded physical matrix are still required before
approval. Scope is limited to this core integration and acceptance: no new
paid generation cohorts, general historical importer, or sample-app repairs.

The coordinated snapshot `2e079b3bc1f8162c0f6029959e810438f9f43006`
subsequently passed 21 native/release tests and all three builds in run
45618043257, job 139218470052. The reconstructed old instruction-counter
case reproduced the carry-over; the current per-callback reset passed.
The independently downloaded artifact is 27,216,750 bytes, SHA256
`19fe56627471d66d40fc7d970273a4bbfba714654457a3a1a5039e6d0d335f10`.
Its exact normal image is 2,654,624 bytes, SHA256
`2da71ae5e57579514e6a20a6155b91ab1690307269ada267a915ff572705e9f5`.
Static RAM is 63,796 bytes; aligned IRAM end remains 0x4009fb98, leaving
1,128 bytes. These are compile-time facts, not free-heap or timing claims.

The existing Windows backend was activated once with the current 83310c
contract/V4 policy after repeated idle checks. Its raw settings and combined
credential fingerprints are unchanged. One listener remains; health/UI and
preview script return 200, unauthenticated preview 401. Current SDK schema
validation reached credential-scope denial before creating records; the old
experimental hash was rejected. No AI, install or RUN was invoked.
The first launcher shell attempt was blocked before process creation; the
subsequent existing launcher started the one effective new process. No
execution-policy, model-profile or saved setting was changed.

The private SDKQA5 image (2,678,304 bytes, SHA256
`18a3e71806e1abe0f8f9410fc82454b7fd89a1fd56b79339103da8868853c123`)
adds fixed diagnostic probes only. Its 11 private files and 149 remaining
device files were independently checked against that snapshot, and the
catalog was signed/verified locally. It is not a public release or the clean
normal image.

SDKQA5 completed ten positive baseline phases. Each SDK frame had one
completed OS prefill and no generic OS background fill. All initial matching
clears reused the prepared pixels; no actual app-clear fill occurred in
those phases. Gallery1 still failed its first update at a guard checkpoint
17,115 microseconds after callback start. Native calls used 12,324
microseconds, including 7,907 Host microseconds for four rounded panels and
2,686 for ten styled texts. Subsequent throw/catch took 142,662 microseconds;
the final 161,070-microsecond callback report is not pure drawing or VM time.
No canvas was captured, and later phases did not run.

The device returned to retained RC9 A/app0 sequence29 VALID/CRC, then rebooted
normally. The coordinator independently verified both metadata CRCs and all
three raw-log hashes. Return observation was 45.206 seconds, maximum loop
gap 89,996 microseconds; ordinary reboot observation was 20.116 seconds.
No panic/watchdog was recorded; COM3 closed. Inactive B28 contains the
consumed private image, not a clean SDK delivery.

The next bounded candidate delegates multi-row spans to the existing pinned
M5GFX fillRect implementation, retaining raw single-row glyph/asset spans.
M5GFX already uses a bounded internal source row for this PSRAM storage type.
No new framebuffer/cache, layout, API, allocator or quota change is planned;
the speedup remains unverified until the native tests and physical matrix run.

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

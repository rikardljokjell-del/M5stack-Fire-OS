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
No improved success rate has yet been established.

## Verification boundaries

The integration has a green 719-test backend regression run and subsequent
focused checks covering SDK resource accounting and Studio. The native CI
snapshot `8547e46ea26b3c4c9db9a71b0b6d1a4757d9047d` passed 19 tests and three
firmware builds. These results do not establish physical callback time,
display output, memory headroom, package installation or recovery behavior.
Physical SDK measurements and an actual device canvas image are pending.

Exact production CI linker maps provide this compile-time comparison:

| Measure | RC9 (`b77c579`) | SDK RC1 (`8547e46`) |
| --- | ---: | ---: |
| Firmware binary bytes | 2,427,328 | 2,652,912 |
| Static data + BSS bytes | 63,796 | 63,796 |
| IRAM space remaining in linked segment | 1,128 | 1,128 |
| Flash text section bytes | 1,541,183 | 1,551,891 |
| Flash read-only data section bytes | 723,368 | 938,240 |

The new bitmap/UI data chiefly occupies flash. Static RAM and linked IRAM
usage did not grow. The existing small IRAM margin still limits future
interrupt-resident additions; it does not measure runtime free SRAM or PSRAM.

The user's reported firmware download-to-SD write failure remains open and
is outside this SDK task. Earlier isolated SD tests do not close that issue.

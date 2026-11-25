# Device delivery status — 2026-11-25

## Current candidate: fire-os-1.2.0-rc9

Source `b77c579bec4b4986680f9f3be82a4afbe76f59e8`; CI 45575157747 passed 16 tests and all three builds.
Exact normal: 2,427,328 B, SHA256 `17edd52caa166558118c30ddead2d49ccc1d24360f68b326e2297eceab4fd6bd`.

Physical proof: two real signed RC8 downloads/saves with replacement/backups
using the frozen memory candidate; then one exact CI-RC9 GitHub download,
PSRAM/hash/TLS-stop barrier, SD binary and both signed catalogs readback,
unchanged complete OTA slots/8KiB metadata from save, retained older RC8 binary
and sidecar, separate native UI SD installation, actual Aseq19 VALID2/CRC and
CI flash readback, and ordinary reboot. Both slots are clean production RC9;
B is a USB/readback copy with unchanged seq18 metadata, not separately booted.
COM3 closed; no paid AI/RUN, new app installation or user-data reset.
Backend confirmed final-boot complete/storage-ready inventory: all7 IDs,
versions, checksums and normalized package IDs equal the durable complete
pre-production-RC9/SD-install reference. This was not the original RC2 baseline.
Report age176s; health/UI HTTP200, eight-version catalog, four ready transport
channels without errors. No AI/RUN acceptance is implied.

Pure production boot loop/gap 87625/92998us;
ordinary45s restart 80460/85996us.
Private fixture maxima and low-memory measurements are separately retained;
full-slot hashing/private overhead is not attributed to normal UI without proof.
See [canonical SD evidence](PHYSICAL_SD_2026-11-25.md). The earlier private
TLS failures and combined memory measures do not establish isolated causes or
prove unmodified RC8 production defective. Old EIO/FatFS cause remains unresolved.

Direct OTA remains the default, with historical RC7 physical proof; RC9 direct
OTA was not repeated. Root preserves all older published binaries/catalogs and
owns git/releases. Bundle `../M5Stack-backend/workspace/migration/fire-os-1.2.0-rc9/`
retains exact physically verified RC2 bootloader/table/recovery, separately sourced
from7efbae9/CI45431615060; normal comes from the above RC9 CI.
Home/HA, public backend WSS, visual/buttons, recovery hold, audio/AI acceptance
remain outside this physical SD gate. Historical reports remain unchanged.

## Historical RC2 candidate and first physical finding

RC2 is signed and independently verified. Source commit:
`7efbae95fa0a54aeb3e1d6a615390810b69279b4`.
CI 45431615060 passed all 12 tests and all three builds. Only those CI artifacts
were used. Package: `../M5Stack-backend/workspace/migration/fire-os-1.2.0-rc2/`.
The PC migration consumer passed signature/hash/image/layout checks without
opening a serial port at that stage. On 2026-11-24 the actual signed RC2 was
USB-migrated with verified full double backup and image readbacks. Factory
boot, controlled SDK rollback (ABORTED=4), 125 s normal boot, stored VALID=2
and a further 45 s normal restart passed the observed crash/reset checks.
See [physical USB evidence](PHYSICAL_USB_2026-11-24.md).
At that RC2 stage responsiveness did not pass: a repeatable early 1.38–1.39 s
UI-loop pause was found. The later bounded RC5 result is in the historical USB report.
This was not physical completion of Home/AI/audio/OTA.

RC2 removes the periodic teardown of healthy remote Home Auto connections.
Changed configuration resets route selection/backoff; layout/favorite changes
leave the network generation alone. No parallel probe or command retry added.
See DELIVERY_REPORT.md for exact RC2 artifacts and remaining physical tests.
At RC2 publication the root catalog was signed with RC2 first and historical
RC1 second. The later RC5 catalog contained RC5, historical RC2 and RC1;
its RC2 note recommended RC5 because of the measured inventory UI pause.
The RC7-era catalog later included RC7, RC6, RC5, RC2 and RC1.
The current signed feed starts with RC9, followed by RC8 and retained older releases.
Both versioned bins and all RC1 immutable files/RC2 USB inputs were verified
unchanged during catalog generation. Master handles publication; no more code
changes were pending at publication. The later physical response finding
led to RC5 above; immutable RC2 bytes remain unchanged.
RC1 remains immutable history.

## RC1 audit history

Source changes are frozen. Final source commit is
`34ade23bc2872dbc3561a09d859aba865d05f470`.
Linux CI passed all 12 tests and normal/recovery/bootloader builds. The exact
CI artifacts have been signed and independently verified by the PC migration
tool. Package: `../M5Stack-backend/workspace/migration/fire-os-1.2.0-rc1/`.
Authoritative delivered artifact hashes and remaining physical checks are in
[DELIVERY_REPORT.md](DELIVERY_REPORT.md); local build snapshots below are audit
history, not the distributed binary bytes. Master handles publication.
At the RC1 audit stage: no COM device, no flashing, no physical integration
claim. Later RC2 USB evidence is linked above. Master owns git.

## Final local builds

- Normal m5stack-fire-ble PASSED: flash 2,393,521 B, static RAM 63,796 B.
  Image 2,399,952 B. IRAM end 0x4009fb98: 1,128 B margin. BLE and audio enabled.
  Snapshot: test-results/normal-build/firmware.{bin,elf,map}, partitions.bin.
- Independent fire-recovery PASSED: flash 1,571,949 B, static RAM 50,684 B.
  Image 1,578,240 B. Snapshot: test-results/recovery-build/.
- Custom IDF 4.4.6 bootloader PASSED: 27,760 B (<28,672 B limit).
  GPIO39 low/3 seconds, rollback enabled, only OTA selection erased.
  Snapshot: test-results/bootloader-build/ (includes generated sdkconfig).
- Exact sizes/hashes: test-results/build-evidence.json. These local bytes have
  not been published, signed as a release or represented as physically tested.
- PC migration validator image_info accepted all three actual images; generated
  partition table matched its exact eight-row allowlist including checksum.
- Bootloader built from a normal short-path source copy at
  C:/Users/Rikard/.codex/device-build/bootloader because IDF rejects spaces.
  No Windows security policy was modified.

## Local test audit (final Linux gate passed)

- Five real ECDSA release tests PASSED; four migration-packaging tests PASSED.
- Original native_core executable PASSED locally earlier. Master reports both
  portable guard programs passed in Linux CI. Latest local unittest attempt
  compiled them, but Windows Application Control blocked execution (WinError
  4551). This is NOT a passing local suite and has not been hidden/skipped.
- New actual WebSocket header/nonce validator has positive/negative C++ tests.
  Linux firmware-checks.yml ran the complete 12-test suite successfully.
- The exact master-supplied source SHA and its Linux CI images were used by
  tools/package_migration.py. Both signed catalog and migration checks passed.

## Delivery included

Native Home/Camper; direct MQTT TLS/WSS; profile import; strict atomic catalogs,
state/ACK validation and freshness; no retained/replayed commands; bounded
HELLO-only retry; generations reject previous connections; private dedicated
configuration stores with checked writes/readbacks; measured UTF-8 clipping.

Verified TLS socket workers for backend control/audio/packages/GitHub; immutable
audio endpoint/token snapshots; connect cancellation; whole-frame capacity and
complete HTTP writes; nonce-derived WebSocket upgrade proof. Reverse sockets
have atomic ownership, cancellation and credential generations.

Package unpack/hash and GitHub SD work are on workers; only UI receives final
callbacks. Mobile HTTP setup is on its own worker with a persistent phase/CAS
mailbox; UI applies settings without waiting for browser input. Station connect
uses a timer instead of the old 75 ms UI sleep. Raw backend firmware-store and
native-app OTA bypasses are disabled; signed OS OTA is the only OS update path.

RMT holds the complete 241-word LED frame in four hardware blocks, without a
refill ISR. No linker enlargement, feature removal or unsafe PSRAM flags.
OS loop/gap/callback/heap/largest-block/stack metrics are emitted without secrets.

Signed exact-byte catalogs; inactive-slot OTA with written-byte hash; delayed
SDK rollback approval. Independent factory recovery has separate Wi-Fi/store,
online installation without SD/backend, signed SD selection and explicit A/B
old-slot choice with runtime health unknown. Raw PlatformIO Upload is blocked.

Version fire-os-1.2.0-rc1 is explicitly a physically unverified candidate.
Docs: README.md, recovery/README.md, recovery/MIGRATION-v1.md,
SIGNED_FIRMWARE-v2.md. PC tool belongs to backend agent. Physical/HA/public
endpoint matrix remains a final user step; compilation never proves it.

Final requested WDT correction included: enableLoopWDT() after successful normal/
recovery setup. Pinned SDK config is 5 s with panic/reset. Both rebuilt PASSED.
No further source changes pending; ready for master source commit.

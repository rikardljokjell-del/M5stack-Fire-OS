# Device delivery status — 2026-11-24

## Current candidate: fire-os-1.2.0-rc5

Source `958415d20029939a0e105f4ee23aa6008a7ab567`, CI 45477480676:
13 tests and all three builds passed. Exact tested normal image: 2,408,576 B,
SHA256 `6499092470f40287776fcac49fa73abc225c1f420b41ebb8c4ea76bce1d004e7`.
Static RAM 63,796 B; IRAM end 0x4009fb98, 1,128 B margin.

Physical RC5 normal boot ran 125.221 s, with max loop/gap 83,048/87,988 us;
ordinary restart ran 45.009 s, max 80,684/86,013 us. No extra reset, known
panic/watchdog marker or RGB timeout. Actual seq4 VALID=2 and correct CRC
were read from flash; RC4 app0/seq3 sector remained unchanged. COM3 released.
Fresh complete inventory retained all seven app/version/checksum/package
identities. No backend callback >=10 ms was logged. No Lua app was run.
The <100 ms gap target passed for this startup/inventory fixture only.

RC5 retains the cooperative inventory/cache and frame budget, and replaces
bytewise WebSocket payload reads with bounded bulk reads and a cooperative
10 ms I/O budget. Native callbacks remain synchronous and are measured;
this is not a universal 10 ms callback guarantee. Lifetime maxima stay intact.

Signed bundle: `../M5Stack-backend/workspace/migration/fire-os-1.2.0-rc5/`.
Its normal is the exact physically tested CI image. Bootloader/table/recovery
are byteidentical retained RC2 components from source 7efbae9 / CI 45431615060,
explicitly recorded in component-provenance.json. This is not a homogeneous
RC5 component build. Master owns root packaging/publication and all git.

Canonical scope, intermediate failures and private-evidence handling:
[PHYSICAL_USB_2026-11-24.md](PHYSICAL_USB_2026-11-24.md).
Button-hold recovery, screen/buttons/LED appearance, Home/HA, public TLS,
GitHub/SD OTA, audio/microphone and AI BUILD/RUN remain physically unverified.
The working production route in this fixture was private Reverse TCP.

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
UI-loop pause was found. The later bounded RC5 result is recorded above.
This was not physical completion of Home/AI/audio/OTA.

RC2 removes the periodic teardown of healthy remote Home Auto connections.
Changed configuration resets route selection/backoff; layout/favorite changes
leave the network generation alone. No parallel probe or command retry added.
See DELIVERY_REPORT.md for exact RC2 artifacts and remaining physical tests.
At RC2 publication the root catalog was signed with RC2 first and historical
RC1 second. The current catalog is RC5, historical RC2, historical RC1;
its RC2 note recommends RC5 because of the measured inventory UI pause.
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

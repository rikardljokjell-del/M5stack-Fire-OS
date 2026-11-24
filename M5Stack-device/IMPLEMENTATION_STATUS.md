# Device delivery status — 2026-11-24

## Current candidate: fire-os-1.2.0-rc7

Source `7eb40b7e0effca647d101031c777832aa672a010`; CI 45496282327 passed
15 tests and all three builds. Exact production image: 2,422,464 B,
SHA256 `55228972417300566da9c96a7c888b685cb7ec6d17a3b176b33cbc2d1df0c372`.

Actual GitHub catalog/download, direct inactive-slot OTA, accepted cancellation
with unchanged 8 KiB boot metadata, explicit retry, production app1 boot,
flash readback/CI identity, SDK seq10 VALID2/CRC and ordinary restart passed.
The private driver's premature failure marker is retained and explained in
the [canonical physical report](PHYSICAL_USB_2026-11-24.md); no repeat OTA was
used to hide it. Passive production capture 125.015s measured
loop/gap 79895/85014us; full reset capture
45.043s measured 80312/86013us.
No extra reset, known panic/watchdog or RGB timeout in these captures.
Backend confirmed a newer complete inventory tied to the final RC7 boot/epoch:
7/7 IDs, versions, checksums and normalized package IDs matched RC2. Storage
was ready, health UI HTTP200, four Reverse TCP channels ready without error.
The inventory was191s old at inspection, from this final boot, not the earlier
RC7 snapshot. This does not establish AI/RUN acceptance.
Update-time gap reached176143us and internal heap minimum2516B in the private
fixture; the update itself is not claimed below100ms.

Both slots now hold exact CI RC7 production; app1 is selected, and app0 is a
USB/readback-verified fallback copy, not separately booted in this final pass.
All private automatic test images were removed from device. COM3 released.
Bootloader/table/factory remain the physically verified RC2 components from
7efbae9 / CI45431615060, with separate component provenance. Root owns git
and publication. Signed bundle: `../M5Stack-backend/workspace/migration/fire-os-1.2.0-rc7/`.

GitHub SD saving is removed/rejected: physical EIO and a later FatFS null-pointer
panic remain unresolved. Direct OTA uses no SD staging. Offline signed-SD
installation, removed-card operation, GPIO39/button-hold recovery, visual
acceptance, Home/HA, public backend WSS, audio/AI/Lua RUN remain unverified.
No user data was erased and no paid AI/RUN or new app installation was done.
Historical RC5 and intermediate RC2/3/4 measurements remain in the physical report.

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
RC1 second. The later RC5 catalog contained RC5, historical RC2 and RC1;
its RC2 note recommended RC5 because of the measured inventory UI pause.
The published catalog now starts with RC7, RC6, RC5, RC2 and RC1.
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

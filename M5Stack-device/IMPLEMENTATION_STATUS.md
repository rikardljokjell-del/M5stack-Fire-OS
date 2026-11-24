# Device source freeze — 2026-11-24

READY FOR MASTER SOURCE COMMIT AND LINUX CI. Source changes are frozen.
No COM device, no flashing, no physical integration claim. Master owns git.

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

## Tests and remaining release gate

- Five real ECDSA release tests PASSED; four migration-packaging tests PASSED.
- Original native_core executable PASSED locally earlier. Master reports both
  portable guard programs passed in Linux CI. Latest local unittest attempt
  compiled them, but Windows Application Control blocked execution (WinError
  4551). This is NOT a passing local suite and has not been hidden/skipped.
- New actual WebSocket header/nonce validator has positive/negative C++ tests.
  Linux firmware-checks.yml must run the complete 12-test suite on this source.
- No source commit was guessed. tools/package_migration.py must receive the
  exact SHA supplied by master after committing the frozen sources. Prefer
  source-matched Linux CI images if master selects those as release artifacts.

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

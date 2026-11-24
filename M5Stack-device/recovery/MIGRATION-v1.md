# Migration artifact contract v1

Backend agent owns the PC tool; device agent produces the artifact directory.
Before the USB session on 2026-11-24 no device had been flashed in this work.
RC2 migration and controlled rollback have now been physically observed; see
[USB evidence and limits](../PHYSICAL_USB_2026-11-24.md). This contract remains
unchanged. Button-hold recovery and network OTA are not established by USB.

Directory `migration/` contains `migration.json`, `migration.sig`, `bootloader.bin`,
`partitions.bin`, `recovery.bin`, `normal.bin`, `catalog-v2.json`,
`release-public.pem`. Private signing keys are never included.

`migration.json` is UTF-8 JSON with these exact fields:

```json
{"schema":1,"target":"m5stack-fire","chip":"esp32","flash_size":16777216,
 "layout":"fire-ab-recovery-v1","recovery_version":1,
 "source_commit":"40 lowercase hex",
 "files":[
  {"role":"bootloader","name":"bootloader.bin","offset":4096,"max_size":28672,"size":1,"sha256":"64 lowercase hex"},
  {"role":"partitions","name":"partitions.bin","offset":32768,"max_size":4096,"size":3072,"sha256":"64 lowercase hex"},
  {"role":"normal","name":"normal.bin","offset":65536,"max_size":6553600,"size":1,"sha256":"64 lowercase hex"},
  {"role":"recovery","name":"recovery.bin","offset":13172736,"max_size":3145728,"size":1,"sha256":"64 lowercase hex"}
 ]}
```

`migration.json` uses canonical UTF-8 (sorted object keys, compact separators,
NFC, no BOM and no trailing newline). `migration.sig` is a single base64 line
containing a DER ECDSA-P256/SHA256 signature over the EXACT `migration.json`
bytes. The pinned `fire-release-2026` public key verifies it before any hashes,
offsets or roles are trusted. No parsing/reserialization before verification.
This binds bootloader, table, recovery and normal images, not just the OS.

Sizes above are shape examples, never usable release metadata. The producer
fills exact sizes and hashes only after successful builds. `normal.bin` must
match a verified entry in `catalog-v2.json` by size/hash; source commit matches
that entry and the migration manifest. Public key must match the pinned key in
the PC tool/source. Structural partition-table validation must check all rows
against `partitions.csv`, including MD5 entry, bounds and no overlaps.

`source_commit` identifies the normal firmware source. If an unchanged,
previously verified bootloader/table/recovery is deliberately reused, the
delivery report must record its own source commit, CI run and hashes separately.
The signed migration manifest still binds every component's exact bytes.
For the RC5 candidate, the retained base is the physically verified
RC2 base, with all three input hashes matching RC2. RC3 adds write-drain
introspection to the shared async client used by normal and recovery builds.
Therefore the latest recovery source is not identical to RC2: the retained
recovery must explicitly be attributed to RC2, rather than represented as the
new RC5 CI recovery image. Its original interface/layout remains the retained
baseline; compatibility and the deliberate component choice are documented
in the delivery report and component-provenance.json.
The packager requires explicit `--version` and release-specific `--notes`;
it no longer silently inserts RC2 notes into later releases.

Migration preserves NVS `0x9000..0xdfff`, coredump and all other unlisted
regions. On first boot the apps initialize dedicated `homecfg`/`rescuecfg`
NVS. Incompatible/full initialization formats ONLY those exactly located
partitions (they previously held SPIFFS bytes); it never formats default NVS.
Saved Home/recovery profiles therefore start empty after the first migration.
The PC backup remains the source for recovering old SPIFFS contents.
It must explicitly erase OTA selection `0xe000..0xffff` after writing
and verifying the images (erased selection chooses factory recovery), and it
must not erase either dedicated configuration partition. New factory recovery
then offers a physically confirmed choice of normal app0 or app1. Each image's
metadata/integrity is displayed with runtime health explicitly unknown. App1 is left intact
as a potential previous image, but is not claimed to be a valid rollback until
verified. Bootloader GPIO39 low for three seconds clears only OTA selection
and selects factory recovery; normal/configuration NVS are preserved.

Before any write: explicit COM port; verify ESP32 (not S2/S3/C3), 16 MiB flash,
secure-boot/flash-encryption disabled; reject incompatible eFuses; full 16 MiB
backup, read-back comparison and SHA256 persisted outside source control.
No erase-flash command. Read back each written range. Bootloader/table are
written last, on stable power. Interrupted migration can require USB restore;
the factory app is independent after successful migration, not before it.

Default command must validate/dry-run without writing. The physical migration
requires deliberate execute mode, a connected device and backup destination.
Restoration is a separately explicit action using that exact verified backup.

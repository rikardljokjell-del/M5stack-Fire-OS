# Signed firmware catalog v2 — frozen interface

Public path remains `firmware/index.json` in the repository. Legacy schema 1
may be displayed by the PC but MUST NOT authorize a device download/install.
Stable binaries have immutable versioned filenames; never replace a released
file. Backend is a read-only catalog consumer, never a firmware transport.

Envelope (exact keys):

```json
{"schema":2,"algorithm":"ecdsa-p256-sha256","key_id":"fire-release-2026","payload":"BASE64","signature":"BASE64_DER_ECDSA_SIGNATURE"}
```

Signature is ECDSA NIST P-256 over SHA256 of the exact base64-decoded payload
bytes, standard ASN.1 DER signature encoding. Device verifies those bytes
before parsing; it never reserializes untrusted JSON. Publisher produces
UTF-8 JSON with sorted keys, compact separators, ensure_ascii=false, NFC
strings, no BOM or trailing newline. Both base64 fields use standard RFC4648
alphabet with padding. Envelope <=32768 bytes, decoded payload <=16384.

Payload:

```json
{"channel":"stable","files":[{"name":"fire-os-1.2.0.bin","notes":"Kort norsk endringsbeskrivelse","path":"firmware/fire-os-1.2.0.bin","published_at":"2026-11-24T15:00:00Z","sha256":"64-lowercase-hex","size_bytes":2000000,"source_commit":"40-lowercase-hex","version":"1.2.0"}],"layout":"fire-ab-recovery-v1","min_recovery":1,"repository":"rikardljokjell-del/M5stack-Fire-OS","schema":2,"target":"m5stack-fire"}
```

At most 8 files. name: `fire-` prefix, only ASCII alphanumeric/dot/hyphen/
underscore, `.bin` suffix, <=64 bytes. path MUST equal `firmware/` + name.
version <=40 ASCII bytes. notes <=240 UTF-8 bytes. size_bytes positive and
<=4194304. source_commit is the actual source base. target/repository/layout
are exact strings above. min_recovery integer 1. No arbitrary download URL,
redirect host, bootloader image, partition table or downgrade policy fields.
Download uses fixed raw.githubusercontent.com repository prefix plus path.

Release public key is shared as `firmware/release-public.pem` and embedded
from `M5Stack-device/certs/release-public.pem` in normal/recovery images. A
missing/unknown key ID or invalid signature fails closed. Release private key
lives only in ignored `M5Stack-device/.secrets/`; never publish/log/package it.
The signing CLI accepts an explicit private-key path and verifies every file
size/hash against the exact binary before producing the envelope.

`fire-ab-recovery-v1` preserves OTA slot offsets/sizes from default_16MB,
adds a factory recovery partition, and is installed by the verified one-time
USB migration. It is not a remotely patched partition table. Installation
requires the expected physical partition layout and a recovery image.

No release binary or signed index is published until its build and artifact
checks pass. Signatures establish publisher integrity, not physical quality.

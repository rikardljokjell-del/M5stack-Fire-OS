"""Package exact built FIRE artifacts and sign the complete migration manifest.

No device I/O. Never copies the private signing key into the output directory.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sign_release import canonical, sign, verify

ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    "bootloader": ("bootloader.bin", 0x1000, 0x7000),
    "partitions": ("partitions.bin", 0x8000, 0x1000),
    "normal": ("normal.bin", 0x10000, 0x640000),
    "recovery": ("recovery.bin", 0xc90000, 0x300000),
}
PARTITIONS = [
    (1, 2, 0x9000, 0x5000, "nvs"), (1, 0, 0xe000, 0x2000, "otadata"),
    (0, 16, 0x10000, 0x640000, "app0"), (0, 17, 0x650000, 0x640000, "app1"),
    (0, 0, 0xc90000, 0x300000, "recovery"), (1, 2, 0xf90000, 0x20000, "homecfg"),
    (1, 2, 0xfb0000, 0x10000, "rescuecfg"), (1, 3, 0xff0000, 0x10000, "coredump"),
]

def validate_partitions(data: bytes):
    import struct
    if len(data) != 3072:
        raise ValueError("Expected one ESP-IDF partition-table sector payload")
    for at, expected in enumerate(PARTITIONS):
        magic, kind, subtype, offset, size, name, flags = struct.unpack_from("<HBBII16sI", data, at * 32)
        actual = (kind, subtype, offset, size, name.rstrip(b"\0").decode("ascii"))
        if magic != 0x50aa or actual != expected or flags:
            raise ValueError("Unexpected partition layout")
    at = len(PARTITIONS) * 32
    if data[at:at+16] != b"\xeb\xeb" + b"\xff" * 14 or data[at+16:at+32] != hashlib.md5(data[:at]).digest() or any(v != 255 for v in data[at+32:]):
        raise ValueError("Invalid partition table MD5/end marker")

def package(paths: dict[str, Path], commit: str, version: str, key_path: Path, output: Path):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected exact committed source SHA")
    if not re.fullmatch(r"fire-os-[A-Za-z0-9_.-]+", version) or len(version) > 40:
        raise ValueError("Unsafe immutable version")
    if output.exists():
        raise ValueError("Refusing to overwrite a migration artifact directory")
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    pinned = serialization.load_pem_public_key((ROOT / "certs/release-public.pem").read_bytes())
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1) or key.public_key().public_numbers() != pinned.public_numbers():
        raise ValueError("Signing key does not match the pinned release key")
    # Validate everything before creating or copying into a deliverable.
    entries = []
    for role, (name, offset, limit) in ROLES.items():
        data = paths[role].read_bytes()
        if not 1 <= len(data) <= limit:
            raise ValueError(f"{role} does not fit its allowlisted region")
        if role == "partitions":
            validate_partitions(data)
        elif len(data) < 24 or data[0] != 0xe9 or data[12:14] != b"\0\0":
            raise ValueError(f"{role} is not an ESP32 image")
        entries.append({"role": role, "name": name, "offset": offset, "max_size": limit,
                        "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"schema": 1, "target": "m5stack-fire", "chip": "esp32", "flash_size": 16777216,
                "layout": "fire-ab-recovery-v1", "recovery_version": 1, "source_commit": commit, "files": entries}
    output.mkdir(parents=True)
    for role, (name, _, _) in ROLES.items():
        shutil.copyfile(paths[role], output / name)
        entry = next(item for item in entries if item["role"] == role)
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Artifact changed during packaging")
    artifact = version + ".bin"
    shutil.copyfile(paths["normal"], output / artifact)
    normal = next(item for item in entries if item["role"] == "normal")
    payload = {"schema": 2, "repository": "rikardljokjell-del/M5stack-Fire-OS", "target": "m5stack-fire",
        "layout": "fire-ab-recovery-v1", "min_recovery": 1, "channel": "stable", "files": [{
        "name": artifact, "path": "firmware/" + artifact, "version": version,
        "notes": "RC2: Auto beholder fungerende MQTT-forbindelse. Direkte Home/TLS, signert OTA og separat recovery. Fysisk sluttkontroll gjenstår.",
        "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source_commit": commit,
        "sha256": normal["sha256"], "size_bytes": normal["size"]}]}
    envelope = sign(payload, key, output); verify(envelope, pinned)
    (output / "catalog-v2.json").write_bytes(canonical(envelope) + b"\n")
    raw = canonical(manifest)
    (output / "migration.json").write_bytes(raw)
    signature = key.sign(raw, ec.ECDSA(hashes.SHA256()))
    pinned.verify(signature, raw, ec.ECDSA(hashes.SHA256()))
    (output / "migration.sig").write_bytes(base64.b64encode(signature) + b"\n")
    shutil.copyfile(ROOT / "certs/release-public.pem", output / "release-public.pem")
    print("Packaged and verified signed migration artifacts; physical tests remain pending")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ROLES:
        parser.add_argument("--" + role, type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--version", default="fire-os-1.2.0-rc2")
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package({role: getattr(args, role) for role in ROLES}, args.source_commit, args.version, args.private_key, args.output)

if __name__ == "__main__":
    main()

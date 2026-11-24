"""Create/verify FIRE catalog envelopes. Private keys stay outside releases."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from datetime import datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

KEY_ID = "fire-release-2026"
REPO = "rikardljokjell-del/M5stack-Fire-OS"

def canonical(value: object) -> bytes:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if unicodedata.normalize("NFC", data) != data:
        raise ValueError("Release text must use NFC")
    return data.encode("utf-8")

def validate(payload: dict, directory: Path | None = None) -> None:
    if set(payload) != {"schema", "repository", "target", "layout", "min_recovery", "channel", "files"}:
        raise ValueError("Unexpected manifest fields")
    if (payload["schema"], payload["repository"], payload["target"], payload["layout"], payload["min_recovery"], payload["channel"]) != (
            2, REPO, "m5stack-fire", "fire-ab-recovery-v1", 1, "stable"):
        raise ValueError("Incompatible release profile")
    if type(payload["schema"]) is not int or type(payload["min_recovery"]) is not int:
        raise ValueError("Expected integer profile versions")
    if not isinstance(payload["files"], list) or not 1 <= len(payload["files"]) <= 8:
        raise ValueError("Invalid release count")
    names = set()
    for item in payload["files"]:
        if set(item) != {"name", "version", "notes", "path", "published_at", "sha256", "size_bytes", "source_commit"}:
            raise ValueError("Unexpected release fields")
        name = item["name"]
        if not re.fullmatch(r"fire-[A-Za-z0-9_.-]+\.bin", name) or len(name) > 64 or ".." in name or name in names:
            raise ValueError("Invalid/duplicate binary name")
        names.add(name)
        if item["path"] != "firmware/" + name or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Unsafe path/hash")
        if not re.fullmatch(r"[0-9a-f]{40}", item["source_commit"]):
            raise ValueError("Invalid source commit")
        if not isinstance(item["size_bytes"], int) or isinstance(item["size_bytes"], bool) or not 1 <= item["size_bytes"] <= 4194304:
            raise ValueError("Invalid binary size")
        if not isinstance(item["version"], str) or not 1 <= len(item["version"].encode("ascii")) <= 40 or len(item["notes"].encode()) > 240:
            raise ValueError("Invalid version/notes")
        if any(ord(c) < 32 or ord(c) > 126 for c in item["version"]):
            raise ValueError("Invalid version text")
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", item["published_at"]):
            raise ValueError("Invalid release timestamp")
        datetime.strptime(item["published_at"], "%Y-%m-%dT%H:%M:%SZ")
        if directory is not None:
            binary = (directory / name).read_bytes()
            if len(binary) != item["size_bytes"] or hashlib.sha256(binary).hexdigest() != item["sha256"] or binary[:1] != b"\xe9":
                raise ValueError("Release file does not match the exact ESP32 artifact")
    if len(canonical(payload)) > 16384:
        raise ValueError("Payload is too large")

def sign(payload: dict, key: ec.EllipticCurvePrivateKey, directory: Path) -> dict:
    if not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("Expected P-256 key")
    validate(payload, directory)
    raw = canonical(payload)
    signature = key.sign(raw, ec.ECDSA(hashes.SHA256()))
    return {"schema": 2, "algorithm": "ecdsa-p256-sha256", "key_id": KEY_ID,
            "payload": base64.b64encode(raw).decode(), "signature": base64.b64encode(signature).decode()}

def verify(envelope: dict, public: ec.EllipticCurvePublicKey) -> dict:
    if set(envelope) != {"schema", "algorithm", "key_id", "payload", "signature"} or (
            envelope["schema"], envelope["algorithm"], envelope["key_id"]) != (2, "ecdsa-p256-sha256", KEY_ID):
        raise ValueError("Untrusted envelope")
    if len(canonical(envelope)) > 32768 or not isinstance(public.curve, ec.SECP256R1):
        raise ValueError("Invalid envelope/key")
    raw = base64.b64decode(envelope["payload"], validate=True)
    if len(raw) > 16384:
        raise ValueError("Payload is too large")
    public.verify(base64.b64decode(envelope["signature"], validate=True), raw, ec.ECDSA(hashes.SHA256()))
    payload = json.loads(raw)
    validate(payload)
    if canonical(payload) != raw:
        raise ValueError("Noncanonical release payload")
    return payload

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    keygen = sub.add_parser("keygen"); keygen.add_argument("private", type=Path); keygen.add_argument("public", type=Path)
    signing = sub.add_parser("sign"); signing.add_argument("payload", type=Path); signing.add_argument("private", type=Path); signing.add_argument("directory", type=Path); signing.add_argument("output", type=Path)
    checking = sub.add_parser("verify"); checking.add_argument("envelope", type=Path); checking.add_argument("public", type=Path)
    args = parser.parse_args()
    if args.command == "keygen":
        if args.private.exists() or args.public.exists():
            raise ValueError("Refusing to overwrite a release trust key")
        args.private.parent.mkdir(parents=True, exist_ok=True); args.public.parent.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        args.private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        args.public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        print("Release key generated locally; private key is not a release artifact")
    elif args.command == "sign":
        key = serialization.load_pem_private_key(args.private.read_bytes(), password=None)
        result = sign(json.loads(args.payload.read_text(encoding="utf-8")), key, args.directory)
        verify(result, key.public_key())
        args.output.write_bytes(canonical(result) + b"\n")
        print("Catalog signed and independently verified")
    else:
        public = serialization.load_pem_public_key(args.public.read_bytes())
        result = verify(json.loads(args.envelope.read_text(encoding="utf-8")), public)
        print(f"Verified {len(result['files'])} signed release entries")

if __name__ == "__main__":
    main()

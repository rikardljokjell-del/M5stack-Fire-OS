"""Build ESP-IDF's compact, sorted subject/public-key CA bundle from certifi.

Public trust data only. Run deliberately when updating firmware trust; ordinary
builds use the committed bundle and do not fetch certificates from the network.
Format: https://github.com/espressif/esp-idf/blob/v4.4.6/components/mbedtls/esp_crt_bundle/gen_crt_bundle.py
"""
from pathlib import Path
import hashlib
import json
import struct

import certifi
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

root = Path(__file__).resolve().parents[1] / "certs"
root.mkdir(exist_ok=True)
pem = Path(certifi.where()).read_bytes()
certs = sorted(x509.load_pem_x509_certificates(pem), key=lambda c: c.subject.public_bytes())
data = struct.pack(">H", len(certs))
for cert in certs:
    name = cert.subject.public_bytes()
    key = cert.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    data += struct.pack(">HH", len(name), len(key)) + name + key
(root / "roots.bundle").write_bytes(data)
(root / "roots.json").write_text(json.dumps({"source": "Mozilla via certifi", "certifi": certifi.__version__,
    "count": len(certs), "sha256": hashlib.sha256(data).hexdigest()}, indent=2) + "\n", encoding="utf-8")
print(f"Public CA bundle: {len(certs)} roots, {len(data)} bytes")

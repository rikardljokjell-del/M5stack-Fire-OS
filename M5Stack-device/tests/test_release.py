import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec

spec = importlib.util.spec_from_file_location("sign_release", Path(__file__).parents[1] / "tools/sign_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name); self.key = ec.generate_private_key(ec.SECP256R1())
        binary = b"\xe9" + b"exact-artifact" * 100
        (self.directory / "fire-test.bin").write_bytes(binary)
        self.payload = {"schema": 2, "repository": release.REPO, "target": "m5stack-fire",
            "layout": "fire-ab-recovery-v1", "min_recovery": 1, "channel": "stable", "files": [{
            "name": "fire-test.bin", "version": "1.2.0", "notes": "Ærlig test", "path": "firmware/fire-test.bin",
            "published_at": "2026-11-24T15:00:00Z", "source_commit": "a" * 40,
            "size_bytes": len(binary), "sha256": hashlib.sha256(binary).hexdigest()}]}
    def test_real_signature_roundtrip(self):
        envelope = release.sign(self.payload, self.key, self.directory)
        self.assertEqual(release.verify(envelope, self.key.public_key()), self.payload)
    def test_wrong_key(self):
        envelope = release.sign(self.payload, self.key, self.directory)
        with self.assertRaises(InvalidSignature):
            release.verify(envelope, ec.generate_private_key(ec.SECP256R1()).public_key())
    def test_tampered_signed_bytes(self):
        envelope = release.sign(self.payload, self.key, self.directory)
        envelope["payload"] = envelope["payload"][:20] + "AAAA" + envelope["payload"][24:]
        with self.assertRaises((InvalidSignature, ValueError)):
            release.verify(envelope, self.key.public_key())
    def test_exact_artifact_and_no_path_escape(self):
        for change in ({"size_bytes": 10}, {"sha256": "0" * 64}, {"name": "fire-../escape.bin"},
                       {"path": "https://example.com/firmware.bin"}, {"unexpected": True}, {"version": "ø"}):
            with self.subTest(change=change):
                payload = copy.deepcopy(self.payload); payload["files"][0].update(change)
                with self.assertRaises((ValueError, UnicodeError, FileNotFoundError)):
                    release.sign(payload, self.key, self.directory)
    def test_layout_target_keyid_and_envelope_fields(self):
        for field, value in (("target", "other-board"), ("layout", "default"), ("min_recovery", 0)):
            payload = copy.deepcopy(self.payload); payload[field] = value
            with self.assertRaises(ValueError): release.sign(payload, self.key, self.directory)
        envelope = release.sign(self.payload, self.key, self.directory); envelope["key_id"] = "unknown"
        with self.assertRaises(ValueError): release.verify(envelope, self.key.public_key())

if __name__ == "__main__": unittest.main()

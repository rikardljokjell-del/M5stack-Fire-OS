import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import package_migration as package
import sign_release


class MigrationPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old_root = package.ROOT; package.ROOT = self.root
        self.addCleanup(setattr, package, "ROOT", old_root)
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.private = self.root / "private.pem"
        self.private.write_bytes(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (self.root / "certs").mkdir()
        (self.root / "certs/release-public.pem").write_bytes(self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        data = b"".join(struct.pack("<HBBII16sI", 0x50aa, kind, subtype, offset, size, name.encode(), 0)
                        for kind, subtype, offset, size, name in package.PARTITIONS)
        data += b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(data).digest()
        self.table = data.ljust(3072, b"\xff")
        self.paths = {}
        for role in package.ROLES:
            path = self.root / (role + ".input")
            # Small synthetic headers test packaging and signing, not ESP boot.
            path.write_bytes(self.table if role == "partitions" else b"\xe9" + b"\0" * 31)
            self.paths[role] = path
        self.output = self.root / "output"

    def build(self):
        package.package(self.paths, "a" * 40, "fire-os-test-rc1", self.private, self.output)

    def test_signed_manifest_binds_every_artifact_and_catalog(self):
        self.build()
        raw = (self.output / "migration.json").read_bytes()
        signature = base64.b64decode((self.output / "migration.sig").read_bytes(), validate=False)
        self.key.public_key().verify(signature, raw, ec.ECDSA(hashes.SHA256()))
        manifest = json.loads(raw)
        self.assertEqual({item["role"] for item in manifest["files"]}, set(package.ROLES))
        for item in manifest["files"]:
            self.assertEqual(hashlib.sha256((self.output / item["name"]).read_bytes()).hexdigest(), item["sha256"])
        payload = sign_release.verify(json.loads((self.output / "catalog-v2.json").read_bytes()), self.key.public_key())
        normal = next(item for item in manifest["files"] if item["role"] == "normal")
        self.assertEqual(payload["files"][0]["sha256"], normal["sha256"])
        self.assertFalse((self.output / "private.pem").exists())
        with self.assertRaises(InvalidSignature):
            self.key.public_key().verify(signature, raw + b" ", ec.ECDSA(hashes.SHA256()))

    def test_partition_layout_md5_end_and_overlap_rejected(self):
        for position in (0, 4, 9, 32 * 8 + 16, 32 * 9 + 1):
            data = bytearray(self.table); data[position] ^= 1
            with self.subTest(position=position), self.assertRaises(ValueError): package.validate_partitions(data)

    def test_release_notes_are_exact_signed_and_validated_before_output(self):
        for notes in ("", "ø" * 121, "e\u0301"):
            with self.subTest(notes=notes), self.assertRaises(ValueError):
                package.package(self.paths, "a" * 40, "fire-os-test-rc3",
                                self.private, self.output, notes=notes)
            self.assertFalse(self.output.exists())
        notes = "RC3: Trinnvis appoversikt. Fysisk sluttkontroll gjenstår."
        package.package(self.paths, "a" * 40, "fire-os-test-rc3",
                        self.private, self.output, notes=notes)
        payload = sign_release.verify(json.loads((self.output / "catalog-v2.json").read_bytes()), self.key.public_key())
        self.assertEqual(payload["files"][0]["notes"], notes)

    def test_wrong_key_and_wrong_chip_fail_before_output(self):
        other = ec.generate_private_key(ec.SECP256R1())
        self.private.write_bytes(other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.output.exists())
        self.private.write_bytes(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        data = bytearray(self.paths["normal"].read_bytes()); data[12] = 9
        self.paths["normal"].write_bytes(data)
        with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.output.exists())

    def test_existing_output_and_oversize_bootloader_rejected(self):
        self.paths["bootloader"].write_bytes(b"\xe9" + b"\0" * 0x7000)
        with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        with self.assertRaises(ValueError): self.build()

if __name__ == "__main__": unittest.main()

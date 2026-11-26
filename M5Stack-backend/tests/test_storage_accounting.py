import os
import subprocess

import pytest

from fire_backend.security import Redactor
from fire_backend.storage import Store


def test_fresh_accounting_matches_tree_and_external_changes(tmp_path):
    store = Store(tmp_path / "workspace", Redactor(), 1_000_000)
    nested = store.root / "builds" / "build-one" / ".temporary"
    nested.mkdir(parents=True)
    (nested / "source.lua").write_bytes(b"x" * 123)
    (store.root / "packages" / "package-one.zip.tmp").write_bytes(b"y" * 456)
    store.put("projects", "app-one", {"name": "Vater"})

    def original_size():
        return sum(p.stat().st_size for p in store.root.rglob("*") if p.is_file())

    assert store.size() == original_size()
    external = nested / "external.data"
    external.write_bytes(b"z" * 2048)
    assert store.size() == original_size()
    external.write_bytes(b"z")
    assert store.size() == original_size()
    external.unlink()
    assert store.size() == original_size()


def test_external_growth_cannot_bypass_quota_or_failure_reserve(tmp_path):
    store = Store(tmp_path / "workspace", Redactor(), 1000)
    external = store.root / "external.data"
    external.write_bytes(b"x" * 800)
    store.reserve(75)
    with pytest.raises(ValueError, match="Workspace disk limit"):
        store.reserve(76)
    store.reserve(200, critical=True)
    with pytest.raises(ValueError, match="Workspace disk limit"):
        store.reserve(201, critical=True)
    external.write_bytes(b"x" * 900)
    with pytest.raises(ValueError, match="Workspace disk limit"):
        store.reserve(1)
    external.unlink()
    store.reserve(875)


def test_symlink_files_count_but_directory_links_are_not_followed(tmp_path):
    store = Store(tmp_path / "workspace", Redactor(), 1_000_000)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "data"
    target.write_bytes(b"x" * 73)
    try:
        (store.root / "linked-file").symlink_to(target)
        (store.root / "linked-directory").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    assert store.size() == 73
    assert store.size() == sum(p.stat().st_size for p in store.root.rglob("*") if p.is_file())


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction semantics")
def test_windows_junction_accounting_preserves_current_tree_semantics(tmp_path):
    store = Store(tmp_path / "workspace", Redactor(), 1_000_000)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data").write_bytes(b"x" * 73)
    link = store.root / "junction"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
    if result.returncode:
        pytest.skip("Creating directory junctions is unavailable on this host")
    try:
        assert store.size() == 73
        assert store.size() == sum(p.stat().st_size for p in store.root.rglob("*") if p.is_file())
    finally:
        link.rmdir()

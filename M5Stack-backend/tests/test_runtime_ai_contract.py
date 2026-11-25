"""The optional extension is shared verbatim by backend and native runtime."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_ai_generated_contract_matches_packaged_and_native_data():
    path = ROOT / "scripts/build_runtime_ai_contract.py"
    spec = importlib.util.spec_from_file_location("runtime_contract_generator", path)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    canonical = (ROOT / "contracts/RUNTIME_AI-v1.json").read_bytes()
    assert (ROOT / "fire_backend/data/RUNTIME_AI-v1.json").read_bytes() == canonical
    assert (ROOT.parent / "M5Stack-device/src/fire_runtime_ai_contract.h").read_bytes() == generator.generated_header(json.loads(canonical))

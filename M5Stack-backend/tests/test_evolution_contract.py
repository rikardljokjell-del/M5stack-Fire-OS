import hashlib
import json
import subprocess
import sys
from pathlib import Path
from fire_backend.evolution_contract import CONTRACT, EXTENSION, REGISTRY, available


def test_canonical_packaged_header_and_budget_defaults_match():
    root = Path(__file__).resolve().parents[1]
    source = root / 'contracts/EVOLUTION-v1.json'
    assert source.read_bytes() == (root / 'fire_backend/data/EVOLUTION-v1.json').read_bytes()
    assert hashlib.sha256(json.dumps(REGISTRY, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == CONTRACT
    subprocess.run([sys.executable, str(root / 'scripts/build_evolution_contract.py'), '--check'], check=True)
    assert available({'evolution': EXTENSION})
    assert not available({}) and not available({'evolution': {**EXTENSION, 'contract': '0'*64}})
    assert REGISTRY['defaults']['budget_usd'] == .5
    assert REGISTRY['defaults']['max_builds'] == 2
    assert REGISTRY['defaults']['daily_app_budget_usd'] == 2
    assert not REGISTRY['defaults']['enabled'] and not REGISTRY['defaults']['telemetry_consent']
    assert REGISTRY['lua_access'] is False

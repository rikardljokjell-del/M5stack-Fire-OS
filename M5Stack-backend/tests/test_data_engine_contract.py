import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def generator():
    spec = importlib.util.spec_from_file_location('data_contract_generator', ROOT/'scripts/build_data_engine_contract.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_packaged_and_native_are_identical():
    raw = (ROOT/'contracts/DATA_ENGINE-v1.json').read_bytes()
    assert (ROOT/'fire_backend/data/DATA_ENGINE-v1.json').read_bytes() == raw
    assert (ROOT.parent/'M5Stack-device/src/fire_data_engine_contract.h').read_bytes() == generator().generated_header(json.loads(raw))


def test_stale_contract_hash_is_rejected():
    doc = json.loads((ROOT/'contracts/DATA_ENGINE-v1.json').read_bytes())
    doc['registry']['limits']['append_bytes'] += 1
    with pytest.raises(ValueError, match='hash is stale'):
        generator().generated_header(doc)


def test_worst_case_read_result_fits_unchanged_job_limit():
    registry = json.loads((ROOT/'contracts/DATA_ENGINE-v1.json').read_bytes())['registry']
    limits = registry['limits']
    result = {'ok': True, 'bytes': [255]*limits['read_bytes'], 'offset': limits['dataset_bytes'], 'eof': False}
    assert len(generator().canonical(result)) <= limits['result_bytes'] == 512

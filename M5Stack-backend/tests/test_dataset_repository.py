import hashlib

import pytest

from fire_backend.data_engine import DataError, DatasetRepository
from fire_backend.security import Redactor
from fire_backend.storage import Store


@pytest.fixture
def repo(tmp_path):
    store = Store(tmp_path, Redactor(), 10_000_000)
    store.put('projects', 'project-one', {'id': 'project-one', 'owner_device_id': 'fire-one', 'app_id': 'signal-tool'})
    for package, checksum in [('build-old', 'a' * 64), ('build-new', 'b' * 64)]:
        store.put('packages', package, {'id': package, 'project_id': 'project-one',
            'manifest': {'id': 'signal-tool', 'checksum': checksum}})
    return DatasetRepository(store, {'identifier_bytes': 40, 'label_bytes': 48, 'metadata_bytes': 512,
        'dataset_bytes': 16_777_216, 'datasets_per_app': 128, 'app_bytes': 134_217_728, 'http_chunk_bytes': 8192})


def descriptor(raw=b'\x00\xff\x80signal\n', **changes):
    result = {'dataset_id': 'capture-one', 'kind': 'binary', 'label': 'Signal', 'size': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(), 'metadata_json': '{}', 'origin_package_id': 'build-old',
        'origin_source_sha256': 'a' * 64, 'origin_run_id': 'run-original', 'created_ms': 1200}
    result['components'] = {'data': {'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}, **{k:{'size':0,'sha256':hashlib.sha256(b'').hexdigest()} for k in ['index','events']}}
    result.update(changes)
    return result


def put(repo, body, offset=0):
    result = repo.upload('fire-one', 'project-one', 'capture-one', offset, body, hashlib.sha256(body).hexdigest())
    if result['complete']:
        for part in ['index','events']:
            repo.upload('fire-one','project-one','capture-one',0,b'',hashlib.sha256(b'').hexdigest(),part)
    return result


def test_binary_preservation_resume_and_exact_duplicate_are_idempotent(repo):
    raw = b'\x00\xff\x80signal\n'
    record = repo.register('fire-one', 'project-one', descriptor(raw))
    assert put(repo, raw[:4]) == {'offset': 4, 'complete': False}
    assert put(repo, raw[:4]) == {'offset': 4, 'complete': False}
    recreated = DatasetRepository(repo.store, repo.limits)
    assert recreated.offset(record) == 4
    assert put(recreated, raw[4:], 4) == {'offset': len(raw), 'complete': True}
    assert put(recreated, raw[:4]) == {'offset': len(raw), 'complete': True}
    verified, path = recreated.verified('fire-one', 'project-one', 'capture-one')
    assert verified['state'] == 'sealed' and path.read_bytes() == raw
    assert verified['origin_package_id'] == 'build-old'  # Later app version keeps old capture provenance.
    assert not verified['physical_interpretation_verified']


def test_scope_paths_revision_and_corruption_are_rejected(repo):
    with pytest.raises(DataError, match='permission_denied'):
        repo.register('fire-other', 'project-one', descriptor())
    with pytest.raises(DataError, match='invalid_argument'):
        repo.register('fire-one', 'project-one', descriptor(dataset_id='../firmware'))
    with pytest.raises(DataError, match='permission_denied'):
        repo.register('fire-one', 'project-one', descriptor(origin_source_sha256='b' * 64))
    repo.register('fire-one', 'project-one', descriptor())
    with pytest.raises(DataError, match='checksum_mismatch'):
        repo.register('fire-one', 'project-one', descriptor(label='Different snapshot'))
    with pytest.raises(DataError, match='checksum_mismatch'):
        repo.upload('fire-one', 'project-one', 'capture-one', 0, b'bad', '0' * 64)
    with pytest.raises(DataError, match='offset_mismatch'):
        put(repo, b'x', 9)
    with pytest.raises(DataError, match='checksum_mismatch'):
        put(repo, b'wrong data')
    assert repo.get('fire-one', 'project-one', 'capture-one')['state'] == 'uploading'


def test_sealed_hash_is_checked_before_processing_and_raw_is_not_replaced(repo):
    raw = b'\x00\xff\x80signal\n'
    repo.register('fire-one', 'project-one', descriptor(raw))
    put(repo, raw)
    record, path = repo.verified('fire-one', 'project-one', 'capture-one')
    path.write_bytes(b'x' * len(raw))  # Deliberate external corruption in isolated test workspace.
    with pytest.raises(DataError, match='checksum_mismatch'):
        repo.verified('fire-one', 'project-one', 'capture-one')
    assert repo.get('fire-one', 'project-one', 'capture-one')['sha256'] == record['sha256']


def test_invalid_metadata_and_app_quota_fail_before_creating_payload(repo):
    with pytest.raises(DataError, match='invalid_json'):
        repo.register('fire-one', 'project-one', descriptor(metadata_json='{"x":1,"x":2}'))
    repo.limits['app_bytes'] = 1
    with pytest.raises(DataError, match='quota_exceeded'):
        repo.register('fire-one', 'project-one', descriptor())
    assert not repo.store.list('datasets')

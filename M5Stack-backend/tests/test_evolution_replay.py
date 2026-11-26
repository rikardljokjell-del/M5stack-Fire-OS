import copy
import json
from types import SimpleNamespace
import pytest
from fire_backend.storage import Store
from fire_backend.security import Redactor
from fire_backend.evolution_replay import prepare_evaluation, validate_evaluation, _imu_window
from fire_backend.evolution_compare import fingerprint


def test_new_app_has_no_invented_baseline_and_context_is_immutable(tmp_path):
    store = Store(tmp_path, Redactor(), 16*1024*1024)
    store.put('projects', 'project-one', {'id': 'project-one', 'owner_device_id': 'fire-one'})
    service = SimpleNamespace(store=store)
    evaluation = prepare_evaluation(service, 'fire-one', 'project-one', None,
        goal={'kind': 'functional', 'instruction': 'Create a clock with start and reset.'})
    assert evaluation['baseline_source_sha256'] is None
    assert evaluation['base_package_id'] is None
    validate_evaluation(service, 'fire-one', evaluation)
    changed = copy.deepcopy(evaluation)
    changed['policy']['required_checks'] = ['weaker']
    with pytest.raises(ValueError): validate_evaluation(service, 'fire-one', changed)
    with pytest.raises(PermissionError): validate_evaluation(service, 'fire-other', evaluation)
    with pytest.raises(ValueError):
        prepare_evaluation(service, 'fire-one', 'project-one', None, goal={'kind':'metric'})


def test_changed_target_capabilities_invalidate_the_same_frozen_comparison(tmp_path):
    store = Store(tmp_path, Redactor(), 16*1024*1024)
    store.put('projects', 'project-one', {'id':'project-one', 'owner_device_id':'fire-one'})
    service = SimpleNamespace(store=store)
    value = prepare_evaluation(service, 'fire-one', 'project-one', None,
        goal={'instruction': 'Make a counter'})
    store.put('devices', 'fire-one', {'capabilities': {'services': ['display']}})
    with pytest.raises(ValueError, match='capability'): validate_evaluation(service, 'fire-one', value)


def test_changed_canonical_assets_or_validator_policy_invalidate_cached_evaluation(tmp_path, monkeypatch):
    import fire_backend.app_sdk as sdk
    import fire_backend.sdk_context as policy
    store = Store(tmp_path, Redactor(), 16*1024*1024)
    store.put('projects', 'project-one', {'id':'project-one', 'owner_device_id':'fire-one'})
    service = SimpleNamespace(store=store)
    value = prepare_evaluation(service, 'fire-one', 'project-one', None,
                               goal={'instruction': 'Make a counter'})
    old = sdk.data_fingerprint
    monkeypatch.setattr(sdk, 'data_fingerprint', lambda: 'f'*64)
    with pytest.raises(ValueError, match='policy changed'):
        validate_evaluation(service, 'fire-one', value)
    monkeypatch.setattr(sdk, 'data_fingerprint', old)
    monkeypatch.setattr(policy, 'VERSION', 'future-policy')
    with pytest.raises(ValueError, match='policy changed'):
        validate_evaluation(service, 'fire-one', value)


def test_real_csv_window_is_bounded_and_preserves_values_and_provenance(tmp_path):
    path = tmp_path / 'measurement.csv'
    path.write_text('sample_index,ax,ay,az,received_us\n' + ''.join(
        f'{i},0.25,-0.5,1.75,{i*10000}\n' for i in range(6000)), encoding='utf-8')
    record = {'kind':'csv','metadata':{'columns':['sample_index','ax','ay','az','received_us'],
        'sample_rate_hz':100}, 'dataset_id':'ds-one','sha256':'a'*64,'components':{},'acquisition':'native_imu_fifo'}
    result = _imu_window(path, record)
    assert len(result['imu_samples']) == 256
    assert result['imu_samples'][1] == {'at_ms':10,'x':.25,'y':-.5,'z':1.75}
    assert result['coverage'] == 'bounded_prefix' and not result['physical_verified']
    path.write_text('sample_index,ax,ay,az,received_us\n0,0,0,1,0\n2,0,0,1,10000\n', encoding='utf-8')
    with pytest.raises(ValueError, match='gap'): _imu_window(path, record)


def test_replay_accepts_actual_repository_register_upload_and_seal_metadata(tmp_path):
    import hashlib
    from fire_backend.data_engine import DatasetRepository
    from fire_backend.data_contract import LIMITS
    store = Store(tmp_path, Redactor(), 16*1024*1024)
    store.put('projects', 'project-one', {'id':'project-one','owner_device_id':'fire-one','app_id':'measurement'})
    store.put('packages', 'build-one', {'id':'build-one','project_id':'project-one',
        'manifest':{'id':'measurement','checksum':'b'*64}})
    for group in ('datasets',): (store.root/group).mkdir(exist_ok=True)
    repo = DatasetRepository(store, LIMITS)
    raw = b'sample_index,ax,ay,az,received_us\n0,0.25,-0.5,1.75,100\n1,0.5,0,2,10100\n'
    sha = hashlib.sha256(raw).hexdigest()
    empty = hashlib.sha256(b'').hexdigest()
    descriptor = {'dataset_id':'ds-real','kind':'csv','label':'Real repository fixture',
        'size':len(raw),'sha256':sha,'metadata_json':json.dumps({'columns':['sample_index','ax','ay','az','received_us'],
        'sample_rate_hz':100}), 'origin_package_id':'build-one','origin_source_sha256':'b'*64,
        'origin_run_id':'run-one','created_ms':10,'acquisition':'native_imu_fifo',
        'components':{'data':{'size':len(raw),'sha256':sha},'index':{'size':0,'sha256':empty},'events':{'size':0,'sha256':empty}}}
    record = repo.register('fire-one','project-one',descriptor)
    for part, data in (('data',raw),('index',b''),('events',b'')):
        repo.upload('fire-one','project-one','ds-real',0,data,hashlib.sha256(data).hexdigest(),part=part)
    record, _ = repo.verified('fire-one','project-one','ds-real')
    assert 'metadata_json' not in record and isinstance(record['metadata'],dict)
    result = _imu_window(repo.path(record,sealed=True),record)
    assert result['imu_samples'][1]['x'] == .5 and result['dataset_sha256'] == sha


def test_worker_replays_actual_values_without_python_bridge_or_physical_claim():
    from fire_backend.lua_worker import simulate
    from fire_backend.api_registry import HARDWARE_API, API_CONTRACT
    replay = {'evidence':'recorded_data_replayed_in_simulator','physical_verified':False,
        'imu_samples':[{'at_ms':0,'x':.25,'y':-.5,'z':1.75},
                       {'at_ms':16,'x':.25,'y':-.5,'z':1.75},
                       {'at_ms':32,'x':.25,'y':-.5,'z':1.75}]}
    replay['snapshot_sha256'] = fingerprint(replay)
    request = {'main_lua': 'function init() end function update(dt) local v=fire.imu.accel(); if v.x~=0.25 or v.y~=-0.5 or v.z~=1.75 then error("changed measurement") end end',
        'required_services':['imu'], 'api_version':HARDWARE_API, 'api_contract':API_CONTRACT,
        'max_memory':131072,'max_runtime_ms':32,'profile':'idle','evolution_replay':replay}
    result = simulate(request)
    assert result['ok'] and result['evolution_replay_sha256'] == replay['snapshot_sha256']
    assert not result['native_timing_measured']
    replay['imu_samples'][0]['x'] = 99
    with pytest.raises(ValueError, match='snapshot'): simulate(request)

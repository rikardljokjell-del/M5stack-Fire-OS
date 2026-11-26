"""Freeze existing evidence and create bounded, data-derived PC replay inputs."""
import copy
import csv
import hashlib
import math

from .storage import canonical, new_id
from .evolution_compare import fingerprint

MAX_REPLAY_SAMPLES = 256
MAX_REPLAY_BYTES = 65536
CHECKS = ['release-v4', 'sdk-standard-gate', 'independent-app-review']


def evaluation_versions():
    """Invalidate persisted measurements when their canonical evaluator changes."""
    from .app_sdk import data_fingerprint, SDK_CONTRACT
    from .sdk_context import VERSION as sdk_policy
    from .sdk_standards import VERSION as standard_policy
    from .build_strategy import VERSION as build_policy
    from .app_quality import UX_POLICY_VERSION
    return {'sdk_data_sha256': data_fingerprint(), 'sdk_contract': SDK_CONTRACT,
            'sdk_policy': sdk_policy, 'standard_policy': standard_policy,
            'build_policy': build_policy, 'experience_policy': UX_POLICY_VERSION,
            'release_suite': 'release-v4', 'evolution_evaluator': 1}


def _owned(service, owner, project_id, package_id=None):
    project = service.store.get('projects', project_id)
    if project.get('owner_device_id') != owner:
        raise PermissionError('Evolution project belongs to another owner')
    package = service.store.get('packages', package_id) if package_id else None
    if package and package['project_id'] != project_id:
        raise PermissionError('Evolution base belongs to another project')
    if package:
        from .builds import verify_archive
        verify_archive(service.store.path('packages', package_id, '.zip'),
                       package['manifest'], package['archive_sha256'])
    return project, package


def prepare_evaluation(service, owner_device_id, project_id, base_package_id,
                       development_context_id=None, goal=None):
    goal = copy.deepcopy(goal or {'kind': 'functional'})
    project, package = _owned(service, owner_device_id, project_id, base_package_id)
    if not package and goal.get('kind', 'functional') != 'functional':
        raise ValueError('Numeric optimization requires a measured baseline package')
    context = service.data_engine.context(owner_device_id, development_context_id) if development_context_id else None
    if context and context['parent_project_id'] != project_id:
        grant = project.get('parent_context_grant') or {}
        if (not grant.get('readonly') or grant.get('context_id') != development_context_id or
                grant.get('snapshot_sha256') != context['snapshot_sha256']):
            raise PermissionError('No readonly parent context grant')
    try:
        device = service.store.get('devices', owner_device_id)
        caps = device.get('capabilities') or {}
    except FileNotFoundError:
        caps = {}
    requirements = goal.get('requirements') or goal.get('instruction')
    if package:
        build = service.store.get('builds', package['build_id'])
        requirements = requirements or build.get('effective_summary') or build.get('summary')
    if not isinstance(requirements, str) or not requirements.strip():
        raise ValueError('Accepted app requirements are required for an independent evaluation')
    sequences = []
    if package:
        import json
        folder = service.store.path('builds', package['build_id'], '')
        plans = sorted(folder.glob('test-plan-*.json'), key=lambda p: int(p.stem.split('-')[-1])) if folder.exists() else []
        if plans:
            sequences = json.loads(plans[-1].read_text(encoding='utf-8'))
    sequences += goal.get('regression_sequences', [])
    from .models import AppTestSequence
    if len(sequences) > 16:
        raise ValueError('Frozen regression set exceeds bound')
    sequences = [AppTestSequence.model_validate(s).model_dump() for s in sequences]
    policy = {'schema': 1, 'owner_device_id': owner_device_id, 'project_id': project_id,
        'goal': goal, 'requirements_sha256': fingerprint(requirements),
        'capabilities_sha256': fingerprint(caps), 'required_checks': CHECKS,
        'test_sequences': sequences,
        'evaluator_versions': evaluation_versions(),
        'development_context_id': development_context_id,
        'development_context_sha256': context['snapshot_sha256'] if context else None,
        'dataset_refs': copy.deepcopy(context.get('dataset_refs', [])) if context else [],
        'max_replay_samples': MAX_REPLAY_SAMPLES, 'max_replay_bytes': MAX_REPLAY_BYTES}
    result = {'id': new_id('evaluation'), 'schema': 1, 'owner_device_id': owner_device_id,
        'project_id': project_id, 'base_package_id': base_package_id,
        'baseline_source_sha256': package['manifest']['checksum'] if package else None,
        'baseline_archive_sha256': package['archive_sha256'] if package else None,
        'policy': policy, 'context_sha256': fingerprint(policy)}
    result['snapshot_sha256'] = fingerprint(result)
    return result


def validate_evaluation(service, owner, evaluation):
    if evaluation.get('owner_device_id') != owner:
        raise PermissionError('Evaluation belongs to another owner')
    if fingerprint({k: v for k, v in evaluation.items() if k != 'snapshot_sha256'}) != evaluation.get('snapshot_sha256'):
        raise ValueError('Evolution evaluation snapshot was changed')
    policy = evaluation['policy']
    if fingerprint(policy) != evaluation['context_sha256'] or policy['required_checks'] != CHECKS:
        raise ValueError('Independent evaluation policy changed')
    if policy.get('evaluator_versions') != evaluation_versions():
        raise ValueError('SDK/evaluator policy changed; freeze a new evaluation')
    try:
        caps = service.store.get('devices', owner).get('capabilities') or {}
    except FileNotFoundError:
        caps = {}
    if fingerprint(caps) != policy['capabilities_sha256']:
        raise ValueError('Actual target capability profile changed')
    _, package = _owned(service, owner, evaluation['project_id'], evaluation['base_package_id'])
    if package and (package['manifest']['checksum'] != evaluation['baseline_source_sha256'] or
                    package['archive_sha256'] != evaluation['baseline_archive_sha256']):
        raise ValueError('Baseline archive/source changed')
    if policy['development_context_id']:
        context = service.data_engine.context(owner, policy['development_context_id'])
        if (context['snapshot_sha256'] != policy['development_context_sha256'] or
                context.get('dataset_refs', []) != policy['dataset_refs']):
            raise ValueError('Dataset/context revision changed')
    return evaluation


def _imu_window(path, dataset):
    if dataset['kind'] != 'csv':
        return None
    metadata = dataset.get('metadata')
    if not isinstance(metadata, dict):
        raise ValueError('Stored dataset is missing validated metadata')
    columns = metadata.get('columns', [])
    names = [v['name'] if isinstance(v, dict) else v for v in columns]
    if not {'ax', 'ay', 'az', 'sample_index'} <= set(names):
        return None
    rate = metadata.get('sample_rate_hz')
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 1 <= rate <= 10000:
        return None
    rows = []
    with path.open('r', encoding='utf-8', newline='') as handle:
        def lines():
            for _ in range(MAX_REPLAY_SAMPLES + 1):
                line = handle.readline(4097)
                if not line:
                    return
                if len(line.encode('utf-8')) > 4096:
                    raise ValueError('Replay CSV row exceeds bound')
                yield line
        reader = csv.reader(lines(), strict=True)
        if next(reader, None) != names:
            raise ValueError('Replay header does not match dataset metadata')
        first = previous = None
        for row in reader:
            if len(row) != len(names):
                raise ValueError('Invalid replay row')
            record = dict(zip(names, row))
            index = int(record['sample_index'])
            if index < 0 or previous is not None and index != previous + 1:
                raise ValueError('Replay sample index gap')
            if first is None:
                first = index
            previous = index
            values = [float(record[name]) for name in ('ax', 'ay', 'az')]
            if any(not math.isfinite(v) or abs(v) > 1000000 for v in values):
                raise ValueError('Invalid measured replay value')
            at_ms = round((index - first) * 1000 / rate)
            if rows and at_ms <= rows[-1]['at_ms']:
                raise ValueError('Replay timing cannot be represented without duplicates')
            rows.append({'at_ms': at_ms, 'x': values[0], 'y': values[1], 'z': values[2]})
    return {'imu_samples': rows, 'dataset_id': dataset['dataset_id'],
        'dataset_sha256': dataset['sha256'], 'components': dataset['components'],
        'acquisition': dataset.get('acquisition', 'app_recorded'),
        'evidence': 'recorded_data_replayed_in_simulator',
        'timing': 'nominal_sample_index_replay_not_calibrated_physical_time',
        'coverage': 'bounded_prefix', 'physical_verified': False}


async def materialize_replay(service, owner, evaluation):
    validate_evaluation(service, owner, evaluation)
    for ref in evaluation['policy']['dataset_refs']:
        dataset = service.data_engine.dataset(owner, evaluation['project_id'], ref['dataset_id'], sealed=True)
        if any(dataset[k] != ref[k] for k in ('sha256', 'revision', 'components')):
            raise ValueError('Replay component/source changed')
        def read():
            path = service.data_engine.verified_file(dataset)
            return _imu_window(path, dataset)
        replay = await service.data_engine.thread_work(read)
        validate_evaluation(service, owner, evaluation)
        if replay and replay['imu_samples']:
            replay['evaluation_context_sha256'] = evaluation['context_sha256']
            replay['snapshot_sha256'] = fingerprint(replay)
            if len(canonical(replay)) > MAX_REPLAY_BYTES:
                raise ValueError('Replay input exceeds worker bound')
            return replay
    return None

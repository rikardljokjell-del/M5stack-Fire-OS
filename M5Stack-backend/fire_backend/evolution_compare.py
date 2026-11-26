"""Objective comparisons over a frozen evaluation context, never AI verdicts."""
import hashlib
import math
import re

from .storage import canonical


METRICS = {
    'app_memory_peak': ('lower', 'simulation'),
    'max_io_calls': ('lower', 'simulation'),
    'max_io_bytes': ('lower', 'simulation'),
    'max_callback_operations': ('lower', 'simulation'),
    'max_callback_display_work': ('lower', 'simulation_proxy'),
    'max_callback_text_bytes': ('lower', 'simulation'),
    'callback_p95_us': ('lower', 'physical'),
    'callback_max_us': ('lower', 'physical'),
    'callback_mean_us': ('lower', 'physical'),
    'runtime_memory_peak': ('lower', 'physical'),
    'energy_mwh': ('lower', 'physical'),
    'measurement_error': ('lower', 'reference_measurement'),
    'generation_cost_usd': ('lower', 'provider_usage'),
    'generation_seconds': ('lower', 'provider_usage'),
}
RESOURCE_METRICS = tuple(k for k, (_, evidence) in METRICS.items()
                         if evidence in {'simulation', 'simulation_proxy'})


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validation_metrics(validation):
    profiles = validation.get('profiles') or [validation]
    result = {}
    for name in RESOURCE_METRICS:
        values = [profile[name] for profile in profiles if finite(profile.get(name))]
        if values:
            result[name] = {'value': max(values), 'evidence': METRICS[name][1]}
    return result


def compare(baseline, candidate, goal):
    """Inputs are source-bound records created by the trusted evaluator.

    A caller must verify archives and release eligibility before setting gates.
    The context hash includes test/replay/criteria/hardware/SDK versions and
    excludes the candidate's necessarily different source checksum.
    """
    metric = goal.get('metric')
    if metric not in METRICS:
        raise ValueError('Unknown or non-numeric optimization target')
    threshold = goal.get('minimum_improvement_percent', 5)
    if not finite(threshold) or not 0 < threshold <= 100:
        raise ValueError('Invalid optimization threshold')
    result = {'status': 'not_comparable', 'metric': metric,
              'baseline_source_sha256': baseline.get('source_sha256'),
              'candidate_source_sha256': candidate.get('source_sha256'),
              'evaluation_context_sha256': baseline.get('context_sha256'),
              'minimum_improvement_percent': threshold, 'physical_verified': False,
              'reasons': [], 'deltas': {}}
    for item in (baseline, candidate):
        if not isinstance(item.get('source_sha256'), str) or not re.fullmatch('[a-f0-9]{64}', item['source_sha256']):
            result['reasons'].append('missing_source_identity')
    context = baseline.get('context_sha256')
    if not isinstance(context, str) or not re.fullmatch('[a-f0-9]{64}', context) or context != candidate.get('context_sha256'):
        result['reasons'].append('evaluation_context_changed')
    if result['reasons']:
        return result
    if baseline['source_sha256'] == candidate['source_sha256'] and METRICS[metric][1] != 'provider_usage':
        result.update(status='not_improved', reasons=['unchanged_source'])
        return result
    if not baseline.get('gates_passed') or not candidate.get('gates_passed'):
        result.update(status='blocked', reasons=['independent_quality_gate_failed'])
        return result
    if baseline.get('required_checks') != candidate.get('required_checks') or not baseline.get('required_checks'):
        result['reasons'].append('acceptance_checks_changed_or_missing')
        return result
    old, new = baseline.get('metrics', {}), candidate.get('metrics', {})
    a, b = old.get(metric, {}), new.get(metric, {})
    expected = METRICS[metric][1]
    if (not finite(a.get('value')) or not finite(b.get('value')) or
            a.get('evidence') != expected or b.get('evidence') != expected):
        result['reasons'].append('target_not_measured_with_required_evidence')
        return result
    if expected in {'physical', 'reference_measurement'}:
        for item, value in ((baseline, a), (candidate, b)):
            if (not value.get('run_id') or value.get('source_sha256') != item['source_sha256'] or
                    not isinstance(value.get('samples'), int) or value['samples'] < 30 or
                    not value.get('measurement_protocol_sha256')):
                result['reasons'].append('insufficient_source_bound_measurements')
        if a.get('measurement_protocol_sha256') != b.get('measurement_protocol_sha256'):
            result['reasons'].append('measurement_protocol_changed')
        if expected == 'reference_measurement' and (not a.get('reference_sha256') or
                a.get('reference_sha256') != b.get('reference_sha256')):
            result['reasons'].append('reference_missing_or_changed')
        if result['reasons']:
            return result
    # A saving cannot be bought by silently worsening another resource budget.
    for name in RESOURCE_METRICS:
        before, after = old.get(name, {}), new.get(name, {})
        if name != metric and finite(before.get('value')):
            if not finite(after.get('value')) or before.get('evidence') != after.get('evidence'):
                result['reasons'].append('resource_measurement_missing:' + name)
            elif after['value'] > before['value']:
                result['reasons'].append('resource_regression:' + name)
    improvement = ((a['value'] - b['value']) / a['value'] * 100) if a['value'] else 0
    result['deltas'][metric] = {'before': a['value'], 'after': b['value'],
                                'improvement_percent': improvement, 'evidence': expected}
    result['physical_verified'] = expected in {'physical', 'reference_measurement'}
    result['status'] = ('regressed' if result['reasons'] or b['value'] > a['value'] else
                        'improved' if improvement >= threshold else 'not_improved')
    return result


async def evaluate_package(service, owner, package_id, evaluation):
    """Fresh ordinary release checks, cached only by immutable evaluation/source."""
    import json
    import zipfile
    from .evolution_replay import validate_evaluation, materialize_replay
    from .quality import require_deliverable
    from .builds import verify_archive, validate_release, simulate
    from .app_quality import UX_POLICY_VERSION
    validate_evaluation(service, owner, evaluation)
    package = service.store.get('packages', package_id)
    if package['project_id'] != evaluation['project_id']:
        raise PermissionError('Comparison package belongs to another project')
    path = service.store.path('packages', package_id, '.zip')
    verify_archive(path, package['manifest'], package['archive_sha256'])
    try:
        require_deliverable(package)
        eligible_now = True
    except ValueError:
        eligible_now = False
    cache_id = 'evaluation-' + fingerprint([package_id, package['manifest']['checksum'],
        package['archive_sha256'], evaluation['snapshot_sha256']])[:32]
    group = service.store.root / 'evolution_evaluations'
    group.mkdir(exist_ok=True)
    try:
        saved = service.store.get('evolution_evaluations', cache_id)
        if (saved.get('record_sha256') == fingerprint({k: v for k, v in saved.items() if k != 'record_sha256'})
                and saved.get('context_sha256') == evaluation['context_sha256'] and
                saved.get('source_sha256') == package['manifest']['checksum']):
            if not eligible_now:
                saved = {**saved, 'gates_passed': False, 'release_eligibility_changed': True}
                saved['record_sha256'] = fingerprint({k:v for k,v in saved.items() if k!='record_sha256'})
                service.store.put('evolution_evaluations',cache_id,saved)
            return saved
    except FileNotFoundError:
        pass
    with zipfile.ZipFile(path) as archive:
        source = archive.read('apps/' + package['manifest']['id'] + '/main.lua').decode('utf-8')
    caps = {}
    try: caps = service.store.get('devices', owner).get('capabilities') or {}
    except FileNotFoundError: pass
    app = {**package['manifest'], 'main_lua': source,
        'hardware': caps.get('hardware') or {}, 'service_methods': caps.get('service_methods'),
        'service_modes': caps.get('service_modes'), 'data_capture': caps.get('data_engine') or {},
        'experience_policy_version': UX_POLICY_VERSION,
        'test_sequences': evaluation['policy']['test_sequences']}
    # The same frozen regression inputs run on baseline and candidate; the
    # candidate's generated plan cannot replace this independent test set.
    record = {'id': cache_id, 'package_id': package_id, 'source_sha256': package['manifest']['checksum'],
        'project_id': package['project_id'], 'owner_device_id': owner,
        'archive_sha256': package['archive_sha256'], 'context_sha256': evaluation['context_sha256'],
        'required_checks': evaluation['policy']['required_checks'], 'physical_verified': False}
    build = service.store.get('builds', package['build_id'])
    record['strategy_components_sha256'] = build.get('evolution_strategy_components_sha256')
    try:
        validation = await validate_release(app, service.store, cache_id)
        replay = await materialize_replay(service, owner, evaluation)
        if replay and 'imu' in app['required_services']:
            observed = await simulate({**app, 'profile': 'idle', 'evolution_replay': replay,
                'test_horizon_ms': max(100, replay['imu_samples'][-1]['at_ms']),
                'capture_at_ms': []}, service.store, cache_id)
            validation['profiles'].append(observed)
            record['replay_sha256'] = replay['snapshot_sha256']
        record.update(core_passed=True, metrics=validation_metrics(validation))
        # A historical build with different requirements/prompt conditions is
        # not a controlled API-cost baseline. Unknown usage stays unmeasured.
        if build.get('evolution_generation_protocol_sha256') == evaluation['context_sha256']:
            rows = [r for r in service.usage.cost_records(service.usage.records())
                    if r.get('build_id') == package['build_id'] and r.get('operation') in {'generate','review'}]
            if rows and all(r.get('tokens_measured') and r.get('price_kind') in {'provider','duration'} and
                            r.get('status') in {'completed','failed'} for r in rows):
                record['metrics']['generation_cost_usd'] = {
                    'value':sum(r['provider_calculated_usd'] for r in rows),'evidence':'provider_usage',
                    'pricing':'calculated_from_provider_usage_not_invoice',
                    'generation_protocol_sha256':evaluation['context_sha256']}
                record['metrics']['generation_seconds'] = {
                    'value':sum(r['latency_ms'] for r in rows)/1000,'evidence':'provider_usage',
                    'generation_protocol_sha256':evaluation['context_sha256']}
        try:
            require_deliverable(package)
            record['gates_passed'] = True
        except ValueError:
            record['gates_passed'] = False
    except ValueError as error:
        record.update(core_passed=False, gates_passed=False, metrics={},
                      error=service.redactor.text(str(error))[:1200])
    validate_evaluation(service, owner, evaluation)
    record['record_sha256'] = fingerprint(record)
    service.store.put('evolution_evaluations', cache_id, record)
    return record


async def assess_packages(service, owner_device_id, base_package_id,
                          candidate_package_id, evaluation, goal=None):
    from .evolution_replay import validate_evaluation
    validate_evaluation(service, owner_device_id, evaluation)
    frozen_goal = evaluation['policy']['goal']
    if goal is not None and goal != frozen_goal:
        raise ValueError('Comparison goal differs from approved frozen criteria')
    if base_package_id != evaluation['base_package_id']:
        raise ValueError('Comparison baseline changed')
    candidate = await evaluate_package(service, owner_device_id, candidate_package_id, evaluation)
    baseline = await evaluate_package(service, owner_device_id, base_package_id, evaluation) if base_package_id else None
    if frozen_goal.get('kind', 'functional') == 'metric':
        if baseline is None:
            raise ValueError('Numeric optimization has no measured baseline')
        return compare(baseline, candidate, frozen_goal)
    package = service.store.get('packages', candidate_package_id)
    result = {'status': 'validated_candidate' if candidate['gates_passed'] else 'blocked',
        'context_sha256': evaluation['context_sha256'], 'candidate_source_sha256': candidate['source_sha256'],
        'baseline_source_sha256': baseline['source_sha256'] if baseline else None,
        'candidate_package_id': candidate_package_id, 'physical_verified': False,
        'physical_resolution_verified': False, 'reasons': [],
        'baseline_core_passed': baseline['core_passed'] if baseline else None,
        'candidate_core_passed': candidate['core_passed'],
        'independent_regression_reproduced': bool(baseline and not baseline['core_passed'] and candidate['core_passed'])}
    if baseline:
        old = service.store.get('packages', base_package_id)
        if set(old['manifest']['required_services']) - set(package['manifest']['required_services']):
            result.update(status='blocked', reasons=['declared_existing_functionality_removed'])
        if candidate['source_sha256'] == baseline['source_sha256']:
            result.update(status='not_improved', reasons=['unchanged_source'])
    return result

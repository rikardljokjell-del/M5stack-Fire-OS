import copy
import pytest
from fire_backend.evolution_compare import compare, validation_metrics


def pair():
    old = {'source_sha256': 'a'*64, 'context_sha256': 'c'*64,
           'gates_passed': True, 'required_checks': ['release-v4', 'app-regression'],
           'metrics': {'app_memory_peak': {'value': 10000, 'evidence': 'simulation'},
                       'max_io_calls': {'value': 20, 'evidence': 'simulation'}}}
    new = copy.deepcopy(old)
    new['source_sha256'] = 'b'*64
    new['metrics']['app_memory_peak']['value'] = 9000
    return old, new


def test_actual_improvement_requires_same_independent_suite_and_no_regressions():
    old, new = pair()
    result = compare(old, new, {'metric': 'app_memory_peak'})
    assert result['status'] == 'improved' and not result['physical_verified']
    new['metrics']['max_io_calls']['value'] = 21
    assert compare(old, new, {'metric': 'app_memory_peak'})['status'] == 'regressed'


@pytest.mark.parametrize('change', ['context', 'checks', 'gate', 'evidence', 'source'])
def test_source_context_acceptance_and_evidence_cannot_be_substituted(change):
    old, new = pair()
    if change == 'context': new['context_sha256'] = 'd'*64
    if change == 'checks': new['required_checks'] = ['weaker']
    if change == 'gate': new['gates_passed'] = False
    if change == 'evidence': new['metrics']['app_memory_peak']['evidence'] = 'ai_estimate'
    if change == 'source': new['source_sha256'] = None
    assert compare(old, new, {'metric': 'app_memory_peak'})['status'] in {'blocked', 'not_comparable'}


def test_healthy_receipt_or_pc_time_does_not_establish_physical_performance():
    old, new = pair()
    for item, value in ((old, 20000), (new, 15000)):
        item['metrics']['callback_p95_us'] = {'value': value, 'evidence': 'physical',
            'source_sha256': item['source_sha256'], 'run_id': 'run-one', 'samples': 1,
            'measurement_protocol_sha256': 'e'*64}
    assert compare(old, new, {'metric': 'callback_p95_us'})['status'] == 'not_comparable'
    old['metrics']['callback_p95_us']['samples'] = new['metrics']['callback_p95_us']['samples'] = 40
    assert compare(old, new, {'metric': 'callback_p95_us'})['status'] == 'improved'


def test_missing_battery_and_reference_are_not_estimated_or_zero_filled():
    old, new = pair()
    assert compare(old, new, {'metric': 'energy_mwh'})['status'] == 'not_comparable'
    assert validation_metrics({'profiles': [{'app_memory_peak': 10}, {'app_memory_peak': 14}]}) == {
        'app_memory_peak': {'value': 14, 'evidence': 'simulation'}}


def test_unchanged_and_small_changes_do_not_pass_and_nonfinite_is_rejected():
    old, new = pair()
    new['metrics']['app_memory_peak']['value'] = 9800
    assert compare(old, new, {'metric': 'app_memory_peak'})['status'] == 'not_improved'
    new['source_sha256'] = old['source_sha256']
    assert compare(old, new, {'metric': 'app_memory_peak'})['status'] == 'not_improved'
    with pytest.raises(ValueError): compare(old, new, {'metric': 'app_memory_peak', 'minimum_improvement_percent': float('nan')})


async def test_real_normal_builder_archive_evaluates_without_ai_or_physical_commands(tmp_path):
    from fire_backend.service import Backend
    from fire_backend.evolution_replay import prepare_evaluation
    from fire_backend.evolution_compare import assess_packages, evaluate_package
    from test_device_protocol import configured
    from test_pre_delivery import build
    service = Backend(configured(tmp_path))
    try:
        session = await build(service)
        package = service.store.get('packages',session.package_id)
        evaluation = prepare_evaluation(service,'fire-01',session.project_id,None,
            goal={'kind':'functional','requirements':session.summary})
        result = await assess_packages(service,'fire-01',None,package['id'],evaluation)
        assert result['status'] == 'validated_candidate' and not result['physical_verified']
        assert not service.store.list('commands') and not service.usage.records()
        checked = await evaluate_package(service,'fire-01',package['id'],evaluation)
        assert checked['core_passed'] and checked['gates_passed']
        # A later real failure must supersede a cached local success.
        service.quality.record(project_id=session.project_id,package_id=package['id'],
            message='Lua update nil value',provenance='device_receipt',error_code='runtime_error')
        blocked = await evaluate_package(service,'fire-01',package['id'],evaluation)
        assert not blocked['gates_passed'] and blocked['release_eligibility_changed']
    finally:
        await service.close()

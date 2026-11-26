import copy
import pytest
from fire_backend.storage import Store
from fire_backend.security import Redactor
from fire_backend.evolution_compare import fingerprint
from fire_backend.evolution_strategies import Strategies


def setup(tmp_path):
    store = Store(tmp_path, Redactor(), 16*1024*1024)
    store.put('projects','project-one',{'id':'project-one','owner_device_id':'fire-one'})
    manager = Strategies(store)
    evaluation = {'id':'evaluation-one','owner_device_id':'fire-one','project_id':'project-one',
        'context_sha256':'a'*64}
    evaluation['snapshot_sha256'] = fingerprint(evaluation)
    comparison = {'status':'improved','independent_checks_passed':True,'context_sha256':'a'*64,
        'training_ids':['train'],'holdout_ids':['holdout']}
    return store, manager, evaluation, comparison


def test_strategy_archive_does_not_mutate_policy_or_adopt_without_approval(tmp_path):
    store, manager, evaluation, comparison = setup(tmp_path)
    base = manager.active('fire-one','project-one')
    record = manager.archive_candidate('fire-one','project-one',components={'guidance':'Cache unchanged labels'},
        evaluation=evaluation,comparison=comparison)
    assert manager.active('fire-one','project-one') == base
    with pytest.raises(PermissionError):
        manager.promote_app('fire-one','project-one',record['id'],record['snapshot_sha256'],{})
    manager.promote_app('fire-one','project-one',record['id'],record['snapshot_sha256'],
        {'kind':'manual','proposal_id':'proposal-one','event_id':'event-one'})
    assert manager.active('fire-one','project-one')['id'] == record['id']
    assert store.list('feedback')[0]['physical_solution_verified'] is False


def test_missing_or_leaked_holdout_stays_unverified_and_cross_owner_is_rejected(tmp_path):
    store, manager, evaluation, comparison = setup(tmp_path)
    comparison['holdout_ids'] = ['train']
    record = manager.archive_candidate('fire-one','project-one',components={'guidance':'Cache labels'},
        evaluation=evaluation,comparison=comparison)
    assert not record['eligible_for_adoption']
    with pytest.raises(ValueError):
        manager.promote_app('fire-one','project-one',record['id'],record['snapshot_sha256'],
            {'kind':'manual','proposal_id':'proposal','event_id':'event'})
    with pytest.raises(PermissionError): manager.active('other','project-one')


def test_owner_default_needs_separate_manual_and_real_multi_app_evaluation_refs(tmp_path):
    _, manager, evaluation, comparison = setup(tmp_path)
    comparison['verified_projects'] = ['fake-one','fake-two','fake-three']
    record = manager.archive_candidate('fire-one','project-one',components={'guidance':'Cache labels'},
        evaluation=evaluation,comparison=comparison,scope='owner')
    with pytest.raises(PermissionError):
        manager.promote_owner('fire-one','project-one',record['id'],record['snapshot_sha256'],
            {'kind':'evolution_mandate','proposal_id':'proposal','event_id':'event'})
    with pytest.raises(ValueError,match='multi-app'):
        manager.promote_owner('fire-one','project-one',record['id'],record['snapshot_sha256'],
            {'kind':'manual','proposal_id':'proposal','event_id':'event'})


def test_changed_archived_strategy_or_protected_component_is_not_read(tmp_path):
    store, manager, evaluation, comparison = setup(tmp_path)
    with pytest.raises(ValueError):
        manager.archive_candidate('fire-one','project-one',components={'validator':'weaken'},
            evaluation=evaluation,comparison=comparison)
    record = manager.archive_candidate('fire-one','project-one',components={'guidance':'Cache labels'},
        evaluation=evaluation,comparison=comparison)
    project = store.get('projects','project-one');project['evolution_strategy_id']=record['id']
    store.put('projects',project['id'],project)
    record['components']['guidance']='tampered'
    store.put('evolution_strategies',record['id'],record)
    with pytest.raises(ValueError,match='changed'): manager.active('fire-one','project-one')


async def test_owner_trial_uses_three_normal_builder_apps_and_real_comparison_proofs(tmp_path):
    from fire_backend.ai import MockProvider
    from fire_backend.models import GeneratedApp
    from fire_backend.service import Backend
    from fire_backend.evolution_replay import prepare_evaluation
    from fire_backend.evolution_strategies import (prepare_owner_evaluation,
        validate_owner_evaluation, assess_owner_evaluation)
    from test_device_protocol import configured
    from test_pre_delivery import build

    class Provider(MockProvider):
        baseline = True
        async def generate(self, summary, context, error=None, previous=None):
            return GeneratedApp(name='Trial counter', required_services=['display','buttons'], main_lua=
                "function init() end function update(dt) " +
                ("fire.display.text(10,40,'Ready',65535) " if self.baseline else '') +
                "fire.display.text(10,40,'Ready',65535) end function on_button(b) end")

    provider = Provider()
    service = Backend(configured(tmp_path), provider)
    try:
        sessions = [await build(service) for _ in range(3)]
        projects = [s.project_id for s in sessions]
        assert len(set(projects)) == 3
        origin = projects[0]
        manager = Strategies(service.store)
        evaluation = prepare_evaluation(service, 'fire-01', origin, sessions[0].package_id,
            goal={'kind':'metric','metric':'max_callback_operations'})
        strategy = manager.archive_candidate('fire-01', origin, components={'guidance':'Avoid unused buffers'},
            evaluation=evaluation, comparison={'status':'improved','independent_checks_passed':True,
            'context_sha256':evaluation['context_sha256'],'training_ids':['train'],'holdout_ids':['holdout']})
        cohort = prepare_owner_evaluation(service, 'fire-01', origin, strategy['id'], projects,
                                          goal={'kind':'metric','metric':'max_callback_operations'})
        with pytest.raises(PermissionError): validate_owner_evaluation(service, 'fire-02', cohort)
        tampered = copy.deepcopy(cohort); tampered['entries'].pop()
        with pytest.raises(ValueError): validate_owner_evaluation(service, 'fire-01', tampered)
        with pytest.raises(ValueError):
            prepare_owner_evaluation(service, 'fire-01', origin, strategy['id'], projects[:2])
        provider.baseline = False
        candidates = {}
        for entry in cohort['entries']:
            session = await service.desktop_conversation('fire-01', entry['project_id'], entry['base_package_id'])
            await service.text(session, 'Lag en sirkel og fjern ubrukt buffer')
            await service.confirm_build(session, session.proposal_id); await session.task
            assert session.package_id
            candidate = service.store.get('packages', session.package_id)
            record = service.store.get('builds', candidate['build_id'])
            record['evolution_strategy_components_sha256'] = cohort['strategy_components_sha256']
            service.store.put('builds', record['id'], record)
            candidates[entry['project_id']] = candidate['id']
        result = await assess_owner_evaluation(service, 'fire-01', cohort, candidates)
        assert result['status'] == 'improved', result
        assert len(result['multi_app_evaluations']) == 3
        comparison = {**strategy['comparison'], 'multi_app_evaluations':result['multi_app_evaluations']}
        owner_record = manager.archive_candidate('fire-01', origin, strategy['id'], strategy['components'],
            evaluation, comparison, scope='owner')
        approval = {'kind':'manual','proposal_id':'proposal-owner','event_id':'actual-confirm'}
        manager.promote_owner('fire-01', origin, owner_record['id'], owner_record['snapshot_sha256'], approval)
        assert manager.active('fire-01', projects[1])['id'] == owner_record['id']
        # A later actual source failure prevents adopting an old successful trial.
        service.quality.record(project_id=projects[1], package_id=candidates[projects[1]],
            message='Lua update nil value',provenance='device_receipt',error_code='runtime_error')
        with pytest.raises(ValueError):
            manager.promote_owner('fire-01', origin, owner_record['id'], owner_record['snapshot_sha256'], approval)
        assert not service.store.list('commands') and not service.usage.records()
    finally:
        await service.close()

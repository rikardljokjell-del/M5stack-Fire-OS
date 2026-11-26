import pytest
from fire_backend.evolution_gepa import (available, optimize_strategy,
    validate_candidate, FireGEPAAdapter)


@pytest.mark.skipif(not available(), reason='Install the optional Evolution extra for actual GEPA tests')
def test_real_gepa_core_uses_injected_evaluator_and_proposer_without_network(tmp_path, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('Unexpected network'))
    assert available()
    reflected = []
    def evaluate(candidate, case):
        return {'score': 1.0 if candidate['guidance'] == 'cache_labels' else 0.0,
                'output': case['id'], 'feedback': 'Repeated unchanged labels cost work.'}
    def propose(candidate, data, components):
        reflected.extend(trace['case_id'] for traces in data.values() for trace in traces)
        assert set(reflected) <= {'training'}
        return {'guidance': 'cache_labels'}
    result = optimize_strategy({'guidance': 'seed'}, [{'id': 'training'}],
        [{'id': 'held-out'}], evaluate, propose, max_evaluations=8)
    assert result['candidate']['guidance'] == 'cache_labels'
    assert result['evaluation_calls'] >= 3 and reflected
    assert not result['global_adoption_authorized'] and not result['physical_verified']
    assert not list(tmp_path.iterdir())


def test_holdout_cannot_be_reflected_even_if_wrong_batch_is_supplied():
    pytest.importorskip('gepa')
    from gepa.core.adapter import EvaluationBatch
    adapter = FireGEPAAdapter(lambda *_: None, ['training'])
    with pytest.raises(ValueError, match='Held-out'):
        adapter.make_reflective_dataset({'guidance': 'x'}, EvaluationBatch(
            outputs=[], scores=[], trajectories=[{'case_id': 'held-out'}]), ['guidance'])


@pytest.mark.parametrize('candidate', [
    {'security_policy': 'weaken'}, {'guidance': 'x'*4097},
    {'example_ids': '["unavailable"]'}, {'context_selection': '["sandbox"]'},
    {'repair_method': 'ignore_tests'}, {'guidance': 123},
])
def test_protected_components_and_unavailable_examples_are_rejected(candidate):
    with pytest.raises(ValueError): validate_candidate(candidate)


@pytest.mark.skipif(not available(), reason='Install the optional Evolution extra for actual GEPA tests')
def test_stop_prevents_evaluation_and_sets_are_independent():
    with pytest.raises(InterruptedError):
        optimize_strategy({'guidance': 'seed'}, [{'id': 'train'}], [{'id': 'test'}],
            lambda *_: pytest.fail('Evaluated after stop'), lambda *_: {}, stop=lambda: True)
    with pytest.raises(ValueError, match='overlap'):
        optimize_strategy({'guidance': 'seed'}, [{'id': 'same'}], [{'id': 'same'}], lambda *_: {}, lambda *_: {})


@pytest.mark.skipif(not available(), reason='Install the optional Evolution extra for actual GEPA tests')
def test_provider_budget_or_unknown_failure_is_not_silently_retried_by_gepa():
    calls = []
    def propose(*_):
        calls.append(1)
        raise RuntimeError('budget admission denied')
    with pytest.raises(RuntimeError, match='budget admission denied'):
        optimize_strategy({'guidance':'seed'}, [{'id':'training'}], [{'id':'held-out'}],
            lambda *_: {'score':0,'output':None}, propose)
    assert len(calls) == 1


def test_optional_optimizer_absence_does_not_remove_the_plain_strategy_validator(monkeypatch):
    import fire_backend.evolution_gepa as adapter
    from importlib.metadata import PackageNotFoundError
    def absent(_): raise PackageNotFoundError('gepa')
    monkeypatch.setattr(adapter, 'version', absent)
    assert not adapter.available()
    assert adapter.validate_candidate({'guidance':'Keep existing controls'})
    with pytest.raises(ValueError, match='not installed'):
        adapter.optimize_strategy({'guidance':'seed'},[{'id':'train'}],[{'id':'test'}],
            lambda *_:pytest.fail('No evaluator without optional optimizer'),lambda *_:{})

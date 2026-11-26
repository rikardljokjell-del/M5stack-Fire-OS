"""Small GEPA bridge: no provider/client, shell tools, pickle or external logging."""
import copy
import json
import math
import re
from importlib.metadata import PackageNotFoundError, version

from .storage import canonical


COMPONENTS = {'guidance', 'context_selection', 'example_ids', 'repair_method'}
CONTEXT_KEYS = {'history', 'feedback', 'data', 'hardware', 'examples'}
REPAIR_METHODS = {'targeted', 'reproduce_first', 'preserve_baseline'}


def available():
    try:
        return version('gepa') == '0.1.4'
    except PackageNotFoundError:
        return False


def validate_candidate(candidate, allowed_examples=()):
    if not isinstance(candidate, dict) or not candidate or set(candidate) - COMPONENTS:
        raise ValueError('Strategy contains unapproved components')
    if any(not isinstance(value, str) for value in candidate.values()) or len(canonical(candidate)) > 8192:
        raise ValueError('Strategy text exceeds bound')
    if len(candidate.get('guidance', '').encode('utf-8')) > 4096:
        raise ValueError('Guidance exceeds bound')
    for key in ('context_selection', 'example_ids'):
        if key not in candidate:
            continue
        value = json.loads(candidate[key])
        allowed = CONTEXT_KEYS if key == 'context_selection' else set(allowed_examples)
        if (not isinstance(value, list) or len(value) > 8 or
                any(not isinstance(v, str) or v not in allowed for v in value) or len(set(value)) != len(value)):
            raise ValueError('Strategy references an unavailable optional context/example')
    if candidate.get('repair_method', 'targeted') not in REPAIR_METHODS:
        raise ValueError('Unapproved repair method')
    # These fields are optional app-development hints. The caller always keeps
    # canonical API, sandbox and acceptance policies outside this mapping.
    return copy.deepcopy(candidate)


class FireGEPAAdapter:
    propose_new_texts = None

    def __init__(self, evaluate, training_ids, allowed_examples=(), stop=None):
        self.evaluate_one = evaluate
        self.training_ids = set(training_ids)
        self.allowed_examples = tuple(allowed_examples)
        self.stop = stop or (lambda: False)
        self.calls = 0

    def evaluate(self, batch, candidate, capture_traces=False):
        from gepa.core.adapter import EvaluationBatch
        candidate = validate_candidate(candidate, self.allowed_examples)
        outputs, scores, traces = [], [], []
        for example in batch:
            if self.stop():
                raise InterruptedError('Evolution paused or stopped')
            result = self.evaluate_one(copy.deepcopy(candidate), copy.deepcopy(example))
            self.calls += 1
            score = result.get('score')
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError('Evaluator returned an invalid score')
            if len(canonical(result)) > 16384:
                raise ValueError('Evaluation trace exceeds bound')
            outputs.append(result.get('output'))
            scores.append(float(score))
            traces.append({'case_id': example['id'], 'score': float(score),
                           'feedback': result.get('feedback', ''), 'evidence': result.get('evidence', 'simulation')})
        return EvaluationBatch(outputs=outputs, scores=scores, trajectories=traces if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        validate_candidate(candidate, self.allowed_examples)
        if set(components_to_update) - COMPONENTS:
            raise ValueError('Attempt to modify a protected strategy component')
        traces = eval_batch.trajectories or []
        if any(trace.get('case_id') not in self.training_ids for trace in traces):
            raise ValueError('Held-out evaluation cannot enter reflection')
        return {component: copy.deepcopy(traces) for component in components_to_update}


def optimize_strategy(seed, trainset, holdout, evaluate, propose, *, stop=None,
                      max_evaluations=32, max_proposals=2, allowed_examples=()):
    """Run in a worker; injected callbacks marshal paid work to the owner loop.

    `propose(candidate, reflective_dataset, components)` must use the normal
    budgeted OpenAI provider. It never receives held-out cases or their traces.
    The caller journals each action/evaluation in its existing JSON workspace.
    GEPA's pickle-based run_dir/resume and optional cloud integrations stay off.
    """
    if not available():
        raise ValueError('GEPA 0.1.4 is not installed for this backend')
    seed = validate_candidate(seed, allowed_examples)
    if type(max_evaluations) is not int or not 1 <= max_evaluations <= 256:
        raise ValueError('Invalid evaluation budget')
    if type(max_proposals) is not int or not 1 <= max_proposals <= 8:
        raise ValueError('Invalid strategy proposal budget')
    if not trainset or not holdout or len(trainset) + len(holdout) > 64:
        raise ValueError('Independent bounded training and holdout sets are required')
    ids = [case.get('id') for case in [*trainset, *holdout]]
    if any(not isinstance(i, str) or not re.fullmatch(r'[a-z0-9_-]{1,64}', i) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Evaluation cases overlap or lack immutable identifiers')
    errors, proposals = [], [0]
    def stopped():
        return bool(errors) or bool(stop and stop())
    def guarded_evaluate(candidate, case):
        try:
            return evaluate(candidate, case)
        except Exception as error:
            errors.append(error)
            raise
    adapter = FireGEPAAdapter(guarded_evaluate, [case['id'] for case in trainset], allowed_examples, stopped)
    def proposal(candidate, reflective_dataset, components_to_update, **_):
        if adapter.stop():
            raise InterruptedError('Evolution paused or stopped')
        if proposals[0] >= max_proposals:
            raise ValueError('Strategy proposal limit reached')
        proposals[0] += 1
        try:
            return validate_candidate(propose(copy.deepcopy(candidate), copy.deepcopy(reflective_dataset),
                                               list(components_to_update)), allowed_examples)
        except Exception as error:
            errors.append(error)
            raise
    import gepa
    class QuietLogger:
        # GEPA diagnostics may contain reflected user data. The owner journals
        # bounded, redacted actions; never print arbitrary reflection traces.
        def log(self, message):
            pass
    result = gepa.optimize(seed_candidate=seed, trainset=copy.deepcopy(trainset),
        valset=copy.deepcopy(holdout), adapter=adapter, custom_candidate_proposer=proposal,
        task_lm=None, reflection_lm=None, max_metric_calls=max_evaluations,
        candidate_selection_strategy='current_best', acceptance_criterion='strict_improvement',
        use_merge=False, run_dir=None, use_cloudpickle=False, use_wandb=False,
        use_mlflow=False, seed=0, display_progress_bar=False, raise_on_exception=True,
        logger=QuietLogger(), stop_callbacks=[lambda state: stopped() or proposals[0] >= max_proposals])
    if errors:
        raise errors[0]
    if stop and stop():
        raise InterruptedError('Evolution paused or stopped')
    return {'optimizer': 'gepa-0.1.4', 'candidate': validate_candidate(result.best_candidate, allowed_examples),
            'evaluation_calls': adapter.calls, 'training_ids': [case['id'] for case in trainset],
            'holdout_ids': [case['id'] for case in holdout],
            'validation_scores': list(result.val_aggregate_scores),
            'physical_verified': False, 'global_adoption_authorized': False}

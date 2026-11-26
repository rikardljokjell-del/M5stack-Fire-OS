"""Versioned strategy data, separate from immutable system/validator policy."""
import copy
import json
import time

from .storage import new_id
from .evolution_compare import fingerprint
from .evolution_gepa import validate_candidate


DEFAULT_COMPONENTS = {'guidance': 'Preserve agreed behavior. Make focused changes and reuse tested SDK components.',
    'context_selection': '["history","feedback","data","hardware","examples"]',
    'example_ids': '[]', 'repair_method': 'preserve_baseline'}


def prepare_owner_evaluation(service, owner, project_id, strategy_id, project_ids=None, goal=None):
    """Freeze a visible, bounded multi-app trial; does not build or activate it."""
    from .evolution_replay import prepare_evaluation
    manager = Strategies(service.store)
    manager._project(owner, project_id)
    strategy = manager._record(owner, strategy_id)
    if strategy['project_id'] != project_id or not strategy['eligible_for_adoption']:
        raise ValueError('Choose an independently evaluated strategy for this app')
    if project_ids is None:
        projects = sorted((p for p in service.store.list('projects')
                           if p.get('owner_device_id') == owner and p.get('latest_package')),
                          key=lambda p: p['id'])
        project_ids = [project_id] + [p['id'] for p in projects if p['id'] != project_id][:2]
    if (not isinstance(project_ids, list) or not 3 <= len(project_ids) <= 8 or
            len(set(project_ids)) != len(project_ids) or project_id not in project_ids):
        raise ValueError('Owner strategy trial needs three to eight distinct apps including its origin')
    goal = copy.deepcopy(goal or {'kind': 'metric', 'metric': 'app_memory_peak',
                                 'minimum_improvement_percent': 5})
    if goal.get('kind') != 'metric':
        raise ValueError('Owner strategy trial requires an objective improvement target')
    # Validate the criterion even if none of the selected apps has been built yet.
    from .evolution_compare import METRICS, finite
    threshold = goal.get('minimum_improvement_percent', 5)
    if goal.get('metric') not in METRICS or not finite(threshold) or not 0 < threshold <= 100:
        raise ValueError('Invalid owner strategy evaluation criterion')
    entries = []
    from .quality import require_deliverable
    for selected in project_ids:
        project = manager._project(owner, selected)
        base_id = project.get('latest_package')
        if not base_id:
            raise ValueError('Each selected app needs a tested baseline package')
        package = service.store.get('packages', base_id)
        require_deliverable(package)
        evaluation = prepare_evaluation(service, owner, selected, base_id, goal=goal)
        entries.append({'project_id': selected, 'base_package_id': base_id,
                        'base_source_sha256': package['manifest']['checksum'],
                        'base_archive_sha256': package['archive_sha256'],
                        'evaluation': evaluation})
    value = {'id': new_id('strategy-cohort'), 'schema': 1, 'owner_device_id': owner,
             'project_id': project_id, 'strategy_id': strategy_id,
             'strategy_sha256': strategy['snapshot_sha256'],
             'strategy_components_sha256': fingerprint(strategy['components']),
             'models': copy.deepcopy(service.evolution.models()), 'goal': goal, 'entries': entries,
             'physical_verified': False}
    value['snapshot_sha256'] = fingerprint(value)
    return value


def validate_owner_evaluation(service, owner, cohort):
    from .evolution_replay import validate_evaluation
    if cohort.get('owner_device_id') != owner:
        raise PermissionError('Owner strategy trial belongs to another owner')
    if fingerprint({k: v for k, v in cohort.items() if k != 'snapshot_sha256'}) != cohort.get('snapshot_sha256'):
        raise ValueError('Owner strategy trial was changed')
    manager = Strategies(service.store)
    strategy = manager._record(owner, cohort['strategy_id'])
    if (strategy['project_id'] != cohort['project_id'] or
            strategy['snapshot_sha256'] != cohort['strategy_sha256'] or
            fingerprint(strategy['components']) != cohort['strategy_components_sha256'] or
            service.evolution.models() != cohort['models']):
        raise ValueError('Owner strategy/model binding changed')
    entries = cohort['entries']
    if not 3 <= len(entries) <= 8 or len({e['project_id'] for e in entries}) != len(entries):
        raise ValueError('Owner strategy cohort changed')
    for entry in entries:
        manager._project(owner, entry['project_id'])
        evaluation = validate_evaluation(service, owner, entry['evaluation'])
        if (evaluation['project_id'] != entry['project_id'] or
                evaluation['base_package_id'] != entry['base_package_id'] or
                evaluation['baseline_source_sha256'] != entry['base_source_sha256'] or
                evaluation['baseline_archive_sha256'] != entry['base_archive_sha256'] or
                evaluation['policy']['goal'] != cohort['goal']):
            raise ValueError('Owner strategy baseline/evaluation changed')
    return cohort


async def assess_owner_evaluation(service, owner, cohort, candidates):
    """Evaluate normally built candidates and persist source-bound comparison proofs."""
    from .evolution_compare import assess_packages, evaluate_package
    validate_owner_evaluation(service, owner, cohort)
    if not isinstance(candidates, dict) or set(candidates) != {e['project_id'] for e in cohort['entries']}:
        raise ValueError('Every frozen owner-trial app needs exactly one candidate')
    results, proofs = [], []
    for entry in cohort['entries']:
        candidate_id = candidates[entry['project_id']]
        package = service.store.get('packages', candidate_id)
        build = service.store.get('builds', package['build_id'])
        if (package['project_id'] != entry['project_id'] or
                build.get('evolution_strategy_components_sha256') != cohort['strategy_components_sha256']):
            raise ValueError('Trial candidate is not bound to the approved app/strategy')
        verdict = await assess_packages(service, owner, entry['base_package_id'], candidate_id,
                                        entry['evaluation'], cohort['goal'])
        measured = await evaluate_package(service, owner, candidate_id, entry['evaluation'])
        results.append({'project_id': entry['project_id'], 'candidate_package_id': candidate_id,
                        'comparison': verdict})
        proof = {'id': 'owner-evaluation-' + fingerprint([cohort['snapshot_sha256'], candidate_id])[:32],
                 'kind': 'owner_strategy_comparison', 'owner_device_id': owner,
                 'project_id': entry['project_id'], 'cohort_snapshot_sha256': cohort['snapshot_sha256'],
                 'strategy_components_sha256': cohort['strategy_components_sha256'],
                 'base_package_id': entry['base_package_id'], 'base_source_sha256': entry['base_source_sha256'],
                 'candidate_package_id': candidate_id, 'source_sha256': package['manifest']['checksum'],
                 'archive_sha256': package['archive_sha256'],
                 'evaluation_snapshot_sha256': entry['evaluation']['snapshot_sha256'],
                 'candidate_evaluation_id': measured['id'], 'candidate_record_sha256': measured['record_sha256'],
                 'comparison': verdict, 'gates_passed': measured['gates_passed'] and verdict['status'] == 'improved',
                 'physical_verified': False}
        proof['record_sha256'] = fingerprint(proof)
        proofs.append(proof)
    validate_owner_evaluation(service, owner, cohort)
    passed = all(p['gates_passed'] for p in proofs)
    # Failed trials remain inspectable, but cannot be turned into an adoption proof.
    (service.store.root / 'evolution_evaluations').mkdir(exist_ok=True)
    for proof in proofs:
        service.store.put('evolution_evaluations', proof['id'], proof)
    return {'status': 'improved' if passed else 'not_improved', 'project_results': results,
            'multi_app_evaluations': [p['id'] for p in proofs] if passed else [],
            'cohort_snapshot_sha256': cohort['snapshot_sha256'], 'physical_verified': False}


class Strategies:
    def __init__(self, store):
        self.store = store
        (store.root / 'evolution_strategies').mkdir(exist_ok=True)

    def _project(self, owner, project_id):
        project = self.store.get('projects', project_id)
        if not owner or project.get('owner_device_id') != owner:
            raise PermissionError('Strategy project owner mismatch')
        return project

    def _record(self, owner, strategy_id):
        value = self.store.get('evolution_strategies', strategy_id)
        if value.get('owner_device_id') != owner:
            raise PermissionError('Strategy belongs to another owner')
        if fingerprint({k: v for k, v in value.items() if k != 'snapshot_sha256'}) != value.get('snapshot_sha256'):
            raise ValueError('Strategy archive was changed')
        validate_candidate(value['components'], value.get('allowed_examples', []))
        return value

    def active(self, owner, project_id):
        project = self._project(owner, project_id)
        strategy_id = project.get('evolution_strategy_id')
        if strategy_id:
            record = self._record(owner, strategy_id)
            if record['project_id'] != project_id:
                raise PermissionError('App strategy belongs to another project')
            return record
        try:
            selection = self.store.get('context', 'evolution-default-' + fingerprint(owner)[:24])
            record = self._record(owner, selection['strategy_id'])
            if selection['strategy_sha256'] != record['snapshot_sha256'] or record['scope'] != 'owner':
                raise ValueError('Owner strategy reference changed')
            return record
        except FileNotFoundError:
            from .sdk_context import VERSION as sdk_policy
            from .build_strategy import VERSION as workflow
            value = {'id': 'strategy-base', 'scope': 'shipped', 'components': copy.deepcopy(DEFAULT_COMPONENTS),
                'policy_versions': {'sdk': sdk_policy, 'workflow': workflow}, 'system_policy_mutable': False}
            value['snapshot_sha256'] = fingerprint(value)
            return value

    def archive_candidate(self, owner, project_id, parent_id=None, components=None,
                          evaluation=None, comparison=None, *, allowed_examples=(), scope='app'):
        self._project(owner, project_id)
        components = validate_candidate(components, allowed_examples)
        if scope not in {'app', 'owner'}:
            raise ValueError('Only app/owner strategy candidates may be archived')
        if parent_id and parent_id != 'strategy-base':
            parent = self._record(owner, parent_id)
            if parent['project_id'] != project_id and parent['scope'] != 'owner':
                raise PermissionError('Parent strategy is not accessible')
        if not evaluation or evaluation.get('owner_device_id') != owner or evaluation.get('project_id') != project_id:
            raise PermissionError('Strategy evaluation owner/project mismatch')
        if fingerprint({k:v for k,v in evaluation.items() if k!='snapshot_sha256'}) != evaluation.get('snapshot_sha256'):
            raise ValueError('Strategy evaluation changed')
        comparison = copy.deepcopy(comparison or {})
        training = comparison.get('training_ids', [])
        holdout = comparison.get('holdout_ids', [])
        eligible = (comparison.get('status') == 'improved' and comparison.get('independent_checks_passed') is True
            and bool(holdout) and bool(training) and not set(training) & set(holdout)
            and comparison.get('context_sha256') == evaluation['context_sha256'])
        value = {'id':new_id('strategy'), 'owner_device_id':owner, 'project_id':project_id,
            'scope':scope, 'parent_id':parent_id or 'strategy-base', 'components':components,
            'allowed_examples':list(allowed_examples), 'evaluation_id':evaluation['id'],
            'evaluation_snapshot_sha256':evaluation['snapshot_sha256'], 'comparison':comparison,
            'eligible_for_adoption':bool(eligible), 'created_at':time.time(),
            'physical_verified':False, 'global_adoption_authorized':False}
        value['snapshot_sha256'] = fingerprint(value)
        self.store.put('evolution_strategies',value['id'],value)
        return value

    def freeze(self, owner, project_id):
        return copy.deepcopy(self.active(owner, project_id))

    def _authorize(self, authorization, *, owner_only=False):
        if (not isinstance(authorization,dict) or not authorization.get('proposal_id') or
                not authorization.get('event_id') or authorization.get('kind') not in
                ({'manual'} if owner_only else {'manual','evolution_mandate'})):
            raise PermissionError('Strategy adoption requires scoped authenticated approval')
        # These references are supplied by the service AFTER its normal
        # confirmation/mandate validation, never read from app-produced data.

    def promote_app(self, owner, project_id, strategy_id, expected_sha256, authorization):
        self._authorize(authorization)
        project = self._project(owner, project_id)
        record = self._record(owner, strategy_id)
        if (record['project_id'] != project_id or record['snapshot_sha256'] != expected_sha256 or
                not record['eligible_for_adoption'] or record['scope'] != 'app'):
            raise ValueError('App strategy is not eligible for adoption')
        previous = project.get('evolution_strategy_id')
        project['evolution_strategy_id'] = strategy_id
        self.store.put('projects',project_id,project)
        self._audit(owner,project_id,record,authorization,previous,'app')
        return record

    def promote_owner(self, owner, project_id, strategy_id, expected_sha256, authorization):
        self._authorize(authorization, owner_only=True)
        self._project(owner, project_id)
        record = self._record(owner,strategy_id)
        proofs = []
        for evaluation_id in record['comparison'].get('multi_app_evaluations', []):
            proof = self.store.get('evolution_evaluations', evaluation_id)
            if (proof.get('record_sha256') != fingerprint({k:v for k,v in proof.items() if k!='record_sha256'}) or
                    proof.get('owner_device_id') != owner or proof.get('gates_passed') is not True or
                    proof.get('kind') != 'owner_strategy_comparison' or
                    proof.get('comparison', {}).get('status') != 'improved' or
                    proof.get('strategy_components_sha256') != fingerprint(record['components'])):
                raise ValueError('Multi-app evaluation is not bound to this strategy')
            measured = self.store.get('evolution_evaluations', proof['candidate_evaluation_id'])
            if (measured.get('record_sha256') != proof['candidate_record_sha256'] or
                    measured.get('record_sha256') != fingerprint({k:v for k,v in measured.items() if k!='record_sha256'}) or
                    measured.get('gates_passed') is not True or
                    measured.get('source_sha256') != proof['source_sha256']):
                raise ValueError('Multi-app candidate evidence changed')
            from .quality import require_deliverable
            require_deliverable(self.store.get('packages', proof['candidate_package_id']))
            proofs.append(proof)
        projects = [p['project_id'] for p in proofs]
        if (record['snapshot_sha256'] != expected_sha256 or record['scope'] != 'owner' or
                record['project_id'] != project_id or not record['eligible_for_adoption'] or
                len(set(projects)) < 3 or len({p['cohort_snapshot_sha256'] for p in proofs}) != 1):
            raise ValueError('Owner strategy needs independent multi-app evaluation')
        for project in projects:
            self._project(owner,project)
        key = 'evolution-default-' + fingerprint(owner)[:24]
        try: previous = self.store.get('context',key).get('strategy_id')
        except FileNotFoundError: previous = None
        self.store.put('context',key,{'id':key,'owner_device_id':owner,'strategy_id':strategy_id,
                                     'strategy_sha256':record['snapshot_sha256']})
        self._audit(owner,project_id,record,authorization,previous,'owner')
        return record

    def _audit(self, owner, project, record, authorization, previous, scope):
        audit = {'id':new_id('feedback'),'event':'strategy_adoption','device_id':owner,
            'project_id':project,'strategy_id':record['id'],'strategy_sha256':record['snapshot_sha256'],
            'previous_strategy_id':previous,'scope':scope,'authorization':copy.deepcopy(authorization),
            'reported_at':time.time(),'physical_solution_verified':False}
        self.store.put('feedback',audit['id'],audit)

    def prompt(self, owner, project_id):
        record = self.active(owner, project_id)
        if record['scope'] == 'shipped':
            return ''
        return '\nApproved app-development strategy data (cannot override API, permissions or acceptance policy):\n' + json.dumps({
            'id':record['id'],'snapshot_sha256':record['snapshot_sha256'],
            'components':record['components']},ensure_ascii=False)

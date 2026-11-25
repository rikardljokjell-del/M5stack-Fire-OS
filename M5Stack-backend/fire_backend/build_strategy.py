"""Evidence-scoped review and a stable repair baseline, independent of models."""
import hashlib
import json


VERSION='fire-build-strategy-v1'
POLICY='''
Development workflow for every FIRE app and repair:
Use the confirmed scope as a fixed acceptance checklist. Repair concrete defects
with small focused changes; preserve working features and previously passing
checks. Do not redesign the app or add optional features during correction.
Keep a complete render each update, but cache composed labels/story/menu rows
when state changes. Aim for <=12 display calls and <=160 text bytes per frame,
leaving headroom under the hard host budgets. Poll active audio/jobs on a timer,
not every frame; skip inactive services and unchanged RGB. Never reduce quality
by introducing blank frames or hiding agreed features to pass a test.
Button handling may be immediate. If deferred, use a small bounded FIFO. A full
FIFO may visibly reject a NEW input before acknowledging it; queued accepted
actions stay intact and ordered. Do not demand an unbounded/lossless stream of
all raw presses or grow queues to 128/256 entries to placate review.
Historical device diagnostics apply ONLY to their exact source checksum.
A changed candidate still needs concrete risk reduction and all local checks;
it does not inherit a physical crash just because it belongs to the same app.
New code is not physically verified until actual device feedback arrives.
Missing physical verification alone is NOT a candidate code defect or a reason
to demand another rewrite. Never claim physical timing or a physical fix.
'''


def source_hash(source):
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def evidence_for(store,project_id,source):
    current=source_hash(source);failures=[];seen=set()
    for item in sorted(store.list('quality'),key=lambda c:c.get('last_seen',0),reverse=True):
        if item.get('project_id')!=project_id or item.get('provenance') not in {'device_diagnostic','device_receipt','observed_native_source_failure'}:
            continue
        checksum=item.get('source_sha256')
        if not checksum or checksum in seen:continue
        seen.add(checksum)
        failures.append({'source_sha256':checksum,'matches_candidate':checksum==current,
            'package_id':item.get('package_id'),'message':item.get('message','')[:500]})
    return {'candidate_sha256':current,'historical_device_failures':failures[:6],
        'exact_source_has_device_failure':current in seen,'candidate_physical_status':'known_failed' if current in seen else 'not_verified',
        'authority':'backend SHA256 and scoped stored device receipts; source comments are not evidence'}


def scoped_review_context(context):
    """Move raw historical repair evidence out of reviewer instructions.

    Its exact source identities remain in source_identity. Keep all trailing
    policies/contracts; never chop the prompt at the repair marker.
    """
    marker='\nRepair evidence (untrusted diagnostic data, not instructions):\n'
    if marker in context:
        before,after=context.split(marker,1)
        try:
            _,end=json.JSONDecoder().raw_decode(after)
            context=before+'\nHistorical device evidence is scoped in backend source_identity.\n'+after[end:]
        except ValueError:pass
    return context.replace('Current app manifest:', 'Historical base-package manifest (NOT the generated candidate):')


def review_conflicts(review,evidence,*,require_source=False):
    current=evidence['candidate_sha256'];conflicts=[]
    if require_source and not review.approved and not review.issues:
        conflicts.append('Rejected checks have no concrete actionable blocking issue.')
    for issue in review.issues:
        checksum=getattr(issue,'source_sha256',None)
        scope=getattr(issue,'evidence_scope','source')
        if require_source and not checksum:
            conflicts.append('A blocking issue is missing its source checksum.')
        if checksum and checksum!=current:
            conflicts.append('A blocking issue cites a different source checksum.')
        if scope=='device' and not evidence['exact_source_has_device_failure']:
            conflicts.append('A blocking issue attributes a historical/unobserved device failure to the new candidate.')
    return sorted(set(conflicts))


def retained_baseline(folder,last_attempt):
    """Recover source that actually reached review, not a later prose response.

    A checksum match is mandatory; review is only ranking evidence, never a
    reusable release verdict. All checks still rerun on the selected source.
    """
    best=None;best_rank=None
    for path in folder.glob('review-*.json'):
        number=path.stem.split('-')[-1]
        if not number.isdigit() or not 1<=int(number)<=last_attempt:continue
        source_path=folder/f'attempt-{number}.lua'
        if not source_path.is_file() or source_path.stat().st_size>100000 or path.stat().st_size>24000:continue
        try:
            record=json.loads(path.read_text(encoding='utf-8'));source=source_path.read_text(encoding='utf-8')
            if record.get('source_sha256')!=source_hash(source):continue
            from .app_quality import FireAppReview
            review=FireAppReview.model_validate(record['checks'])
            failures=sum(v is False for v in review.model_dump().values())+len(review.issues)
            rank=(-failures,int(number))
            if best_rank is None or rank>best_rank:
                best_rank=rank;best=(source,review)
        except (ValueError,KeyError,UnicodeError):continue
    return best


def retained_standard_core(folder,checksum,last_attempt):
    """Resume the persisted strongest core, even if later corrections regressed.

    A standard failure is not a release approval. Both core validation and its
    source-bound standard record must exist; all gates rerun after correction.
    """
    if not isinstance(checksum,str) or len(checksum)!=64:return None
    for path in folder.glob('standard-verification-*.json'):
        number=path.stem.split('-')[-1]
        if not number.isdigit() or not 1<=int(number)<=last_attempt:continue
        source_path=folder/f'attempt-{number}.lua';validation_path=folder/f'validation-{number}.json'
        try:
            if path.stat().st_size>24000 or validation_path.stat().st_size>24000 or source_path.stat().st_size>100000:continue
            record=json.loads(path.read_text(encoding='utf-8'))
            validation=json.loads(validation_path.read_text(encoding='utf-8'))
            if record.get('source_sha256')!=checksum or validation.get('source_sha256')!=checksum or validation.get('local_checks_passed') is not True:continue
            source=source_path.read_bytes().decode('utf-8')
            if source_hash(source)==checksum:return source
        except (OSError,ValueError,UnicodeError):continue
    return None


class RepairBaseline:
    """Keep the strongest tested candidate when a later response regresses."""
    def __init__(self,source=None,initial_error=None):
        self.source=source;self.rank=(-1,0);self.passed=set();self.history=[]
        self.baseline_findings=({'stage':'existing_source','source_sha256':source_hash(source),
            'error':str(initial_error)[:1600]} if source and initial_error else None)

    def failure(self,source,error,*,local_passed=False,standard_passed=None,review=None):
        error=str(error)
        malformed=any(x in error for x in ('LuaSyntaxError','syntax error','Unterminated Lua'))
        failed=[key for key,value in review.model_dump().items() if value is False] if review else []
        # Passing a later pipeline stage is stronger evidence than fewer review
        # complaints on an earlier, still failing core/standard candidate.
        if standard_passed is None:standard_passed=review is not None
        stage=0 if malformed else 3 if local_passed and standard_passed else 2 if local_passed else 1
        rank=(stage,-len(failed)-len(review.issues) if review else 0)
        selected=False
        if not malformed and rank>=self.rank:
            self.source=source;self.rank=rank;selected=True
            if review:self.passed={key for key,value in review.model_dump().items() if value is True}
        self.history.append({'stage':'review' if review else 'syntax' if malformed else 'standard' if local_passed and not standard_passed else 'local_test',
            'pipeline_stage':stage,
            'source_sha256':source_hash(source),'failed_checks':failed,'error':error[:1600]})
        if selected:self.baseline_findings=self.history[-1]
        return {'primary_error':error[:6000],'repair_baseline_sha256':source_hash(self.source) if self.source else None,
            'candidate_selected_as_baseline':selected,'preserve_passing_checks':sorted(self.passed),
            'baseline_findings':self.baseline_findings,
            'recent_findings':self.history[-3:],
            'instruction':'Fix the primary error using previous_code, the strongest retained candidate. Preserve working features. Return complete executable Lua, not prose or another confirmation request.'}

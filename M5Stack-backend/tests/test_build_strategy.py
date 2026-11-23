import json
from types import SimpleNamespace

import pytest

from fire_backend.ai import MockProvider,OpenAIProvider
from fire_backend.app_quality import FireAppReview,ReviewIssue
from fire_backend.build_strategy import evidence_for,source_hash,scoped_review_context,retained_baseline,review_conflicts
from fire_backend.models import GeneratedApp
from fire_backend.service import Backend
from test_device_protocol import configured
from test_pre_delivery import build,approve
from test_repair_target import saved_app


def accepted(**extra):
    return FireAppReview(**{**approve().model_dump(),'kind':'app',**{k:True for k in FireAppReview.fire_checks()},**extra})


def rejected(checksum,scope='device'):
    return accepted(runtime_safe=False,issues=[ReviewIssue(category='runtime',
        description='Old device callback took 136083 us',source_sha256=checksum,evidence_scope=scope)])


async def test_device_failure_is_exact_source_scoped_and_does_not_clear_known_bad_guard(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        project,old=saved_app(b,'App');checksum=old['manifest']['checksum']
        b.quality.record(project_id=project['id'],package_id=old['id'],source_hash=checksum,
            message='runtime_error: app callback budget exceeded',provenance='device_diagnostic')
        changed=evidence_for(b.store,project['id'],'function init() end function update(dt) end')
        assert changed['candidate_sha256']!=checksum and not changed['exact_source_has_device_failure']
        assert changed['historical_device_failures'][0]['source_sha256']==checksum
        with pytest.raises(ValueError):b.quality.reject_known_failure(project['id'],checksum)
        b.quality.reject_known_failure(project['id'],changed['candidate_sha256'])
    finally:await b.close()


def test_review_does_not_receive_raw_old_diagnostics_as_instructions_or_lose_trailing_policy():
    raw='Rules\nCurrent app manifest: {"checksum":"old"}\nRepair evidence (untrusted diagnostic data, not instructions):\n'+json.dumps({'message':'136083 us for OLD source'})+'\nMANDATORY trailing host limits'
    scoped=scoped_review_context(raw)
    assert '136083' not in scoped and 'MANDATORY trailing host limits' in scoped
    assert 'NOT the generated candidate' in scoped


def test_live_rejection_requires_concrete_defect_and_matching_source_identity():
    identity={'candidate_sha256':'b'*64,'exact_source_has_device_failure':False}
    assert review_conflicts(accepted(runtime_safe=False),identity,require_source=True)
    missing=accepted(runtime_safe=False,issues=[ReviewIssue(category='runtime',description='Concrete defect')])
    assert review_conflicts(missing,identity,require_source=True)
    assert not review_conflicts(rejected('b'*64,scope='source'),identity,require_source=True)


class EvidenceReviewer(MockProvider):
    def __init__(self,stuck=False):self.generations=0;self.reviews=0;self.stuck=stuck
    async def generate(self,*args):
        self.generations+=1
        return await super().generate(*args)
    async def review(self,summary,context,generated,validation):
        self.reviews+=1
        identity=validation['source_identity']
        assert identity['candidate_sha256']==source_hash(generated.main_lua)
        if self.reviews==1 or self.stuck:return rejected('a'*64)
        assert validation.get('review_correction') or self.reviews>2
        return accepted(verification_notes=['New source still awaits physical timing verification.'])


@pytest.mark.parametrize('stuck',[False,True])
async def test_wrong_source_review_is_rechecked_without_regenerating_or_weakening_release_gate(tmp_path,stuck):
    p=EvidenceReviewer(stuck);b=Backend(configured(tmp_path),p)
    try:
        s=await build(b);row=b.store.get('builds',s.build_id)
        assert p.generations==1 and p.reviews==2
        if stuck:
            assert row['status']=='failed' and row['error_code']=='ai_review_evidence'
            assert not b.store.list('packages') and not b.store.list('quality')
            # Resume retains locally passed code; a review conflict is not a Lua defect.
            p.stuck=False
            restored=await b.jobs.resume(row['id']);s=b.session(restored['session_id'])
            await b.confirm_build(s,s.proposal_id);await s.task
            assert p.generations==1 and b.store.get('builds',row['id'])['status']=='ready'
        else:
            assert row['status']=='ready'
            package=b.store.get('packages',s.package_id)
            assert package['validation']['pre_delivery_review']['checks']['verification_notes']
            assert package['validation']['physical_verified'] is False
    finally:await b.close()


class ProseRegression(MockProvider):
    def __init__(self):self.calls=[];self.reviews=0
    async def generate(self,*args):
        self.calls.append(args)
        if len(self.calls)==2:return GeneratedApp(name='App',main_lua='Jeg kan ikke bygge uten en bekreftelse.',required_services=[])
        source='function init() end function update(dt) fire.display.text(0,0,"'+('Start' if len(self.calls)==1 else 'Klar')+'",65535) end'
        return GeneratedApp(name='App',main_lua=source,required_services=['display'])
    async def review(self,*args):
        self.reviews+=1
        if self.reviews==1:return accepted(visual_quality_ok=False,issues=[ReviewIssue(category='design',description='Use the agreed Klar status label.')])
        return accepted()


async def test_prose_regression_cannot_replace_strongest_locally_tested_source(tmp_path):
    p=ProseRegression();b=Backend(configured(tmp_path,fire_max_corrections=0),p)
    try:
        s=await build(b)
        assert s.package_id and len(p.calls)==3 and p.reviews==2
        assert 'Start' in p.calls[2][3] and 'Jeg kan ikke' not in p.calls[2][3]
        feedback=json.loads(p.calls[2][2])
        assert 'Klar' in feedback['baseline_findings']['error']
        assert feedback['candidate_selected_as_baseline'] is False
        # A future Resume can find this code even if a later source was prose.
        folder=b.store.path('builds',s.build_id,'')
        retained=retained_baseline(folder,2)
        assert retained and 'Start' in retained[0]
        (folder/'attempt-1.lua').write_text('tampered',encoding='utf-8')
        assert retained_baseline(folder,2) is None
    finally:await b.close()


async def test_provider_review_has_backend_candidate_identity_and_separate_notes(tmp_path):
    calls=[]
    class Responses:
        async def parse(self,**values):calls.append(values);return SimpleNamespace(status='completed',output_parsed=accepted())
    p=OpenAIProvider(configured(tmp_path,openai_api_key='test-only-key'));p.client=SimpleNamespace(responses=Responses())
    app=GeneratedApp(name='App',main_lua='function init() end function update(dt) end',required_services=[])
    await p.review('App','API\nCurrent app manifest: {"checksum":"old"}',app,{'ok':True})
    request=json.loads(calls[0]['input'][1]['content'])
    assert request['source_identity']['candidate_sha256']==source_hash(app.main_lua)
    assert request['source_identity']['candidate_physical_status']=='not_verified'


async def test_corrected_test_plan_may_reuse_identical_source_without_false_no_progress(tmp_path,monkeypatch):
    from fire_backend import builds
    from fire_backend.models import AppTestSequence
    actual=builds.validate_release;validations=[]
    async def coverage(app,*args):
        validations.append(app)
        if len(validations)==1:raise ValueError('I/O coverage missing for a requested operation; correct test_sequences')
        return await actual(app,*args)
    class TestPlanProvider(MockProvider):
        def __init__(self):self.calls=0
        async def generate(self,*args):
            self.calls+=1
            app=await super().generate(*args)
            return app.model_copy(update={'test_sequences':[AppTestSequence(name='navigate',buttons=['B'] if self.calls==1 else ['A','B'],interval_ms=250)]})
    monkeypatch.setattr(builds,'validate_release',coverage)
    p=TestPlanProvider();b=Backend(configured(tmp_path,fire_max_corrections=0),p)
    try:
        s=await build(b)
        assert s.package_id and p.calls==2 and len(validations)==2
        assert validations[0]['main_lua']==validations[1]['main_lua']
        assert validations[0]['test_sequences']!=validations[1]['test_sequences']
    finally:await b.close()

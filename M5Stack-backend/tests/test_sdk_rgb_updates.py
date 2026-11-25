"""Same-app update authorization, immutable base packages and shared cost admission."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fire_backend.app_quality import FireAppReview
from fire_backend.models import GeneratedApp
from fire_backend.service import Backend
from scripts import benchmark_app_sdk as benchmark
from scripts import repair_sdk_rgb as rgb
from test_pre_delivery import approve


async def test_update_retains_verified_base_app_identity_and_creates_new_version(tmp_path,monkeypatch):
    source='function init() end function update(dt) fire.ui.screen("CORE") end'
    class Seed(benchmark.BenchmarkProvider):
        async def generate(self,*args):return GeneratedApp(name='Klokke',main_lua=source,required_services=['display'])
        async def review(self,*args):return FireAppReview(**approve().model_dump(),kind='app',**{n:True for n in FireAppReview.fire_checks()})
        async def close(self):pass
    config=SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna',evaluation_output_cap=True)
    cohort=tmp_path/'source';workspace=cohort/'seed-sdk'
    settings=benchmark.case_settings(workspace,config,'fake-key-only').model_copy(update={'fire_ai_mode':'mock'})
    seed=Backend(settings,Seed(settings))
    try:
        session=await seed.desktop_conversation('benchmark-fire',hardware_preview=True)
        await seed.text(session,'Lag en stoppeklokke.')
        await seed.confirm_build(session,session.proposal_id);await session.task
        base=seed.store.get('packages',session.package_id)
        original={'case':'stopwatch','profile':'sdk','status':'ready','workspace':str(workspace.resolve()),
            'build_id':base['build_id'],'request':'Lag en stoppeklokke.'}
    finally:await seed.close()
    (cohort/'results.json').write_text(json.dumps({'results':[original]}),encoding='utf-8')
    before={str(p.relative_to(cohort)):hashlib.sha256(p.read_bytes()).hexdigest() for p in cohort.rglob('*') if p.is_file()}
    generation_errors=[]
    class Updated(rgb.RepairProvider):
        async def generate(self,summary,context,error=None,previous=None):
            self.verify_previous(previous);generation_errors.append(error)
            if len(generation_errors)==1:assert previous==source
            assert 'ALLE ti' in summary and 'kompakt' in summary
            code=source+'\nlocal old_update=update;local led=0;local on=true;function on_button(b,e) if b=="B" and e=="pressed" then on=not on;led=0 end end;function update(dt) old_update(dt);if led<10 then fire.rgb.set(led,0,on and 40 or 0,on and 100 or 0);led=led+1 end end'
            return GeneratedApp(name='Klokke',main_lua=code,required_services=['display','buttons','rgb'],
                test_sequences=[{'name':'rgb_av','buttons':['B'],'interval_ms':250}])
        async def review(self,*args):return FireAppReview(**approve().model_dump(),kind='app',**{n:True for n in FireAppReview.fire_checks()})
        async def close(self):pass
    monkeypatch.setattr(rgb,'RepairProvider',Updated)
    output=tmp_path/'update';output.mkdir()
    row=await rgb.update_case(output,config,'fake-key-only',cohort,'stopwatch','sdk')
    assert row['status']=='ready',row['error']+' '+repr(generation_errors)
    assert row['same_project'] and row['same_app'] and row['build_id']!=base['build_id']
    assert row['new_version']=='0.1.2' and row['standard_verification']['passed']
    assert row['previous_code_sha256'][0]==base['manifest']['checksum']
    assert row['calls']==0 and row['commands_created']==0
    after={str(p.relative_to(cohort)):hashlib.sha256(p.read_bytes()).hexdigest() for p in cohort.rglob('*') if p.is_file()}
    assert before==after


async def test_shared_point25_reservation_can_admit_three_cheap_updates_but_never_overspend(tmp_path,monkeypatch):
    calls=[]
    async def fake(root,config,key,cohort,label,variant):
        calls.append(label)
        return {'case':label,'status':'ready','generation_attempts':1,'calls':2,'elapsed_seconds':1,
                'estimated_usd':.004,'evaluation_failure_types':[]}
    monkeypatch.setattr(rgb,'update_case',fake)
    config=SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna')
    report=await rgb.execute(tmp_path/'evaluation',config,'fake-key-only',tmp_path/'source',.66398939)
    assert calls==['stopwatch','calculator','dashboard'] and 'evaluation_stopped' not in report
    calls.clear()
    report=await rgb.execute(tmp_path/'tight',config,'fake-key-only',tmp_path/'source',.749)
    assert calls==['stopwatch'] and report['evaluation_stopped']=='insufficient_reserved_room_for_next_case'

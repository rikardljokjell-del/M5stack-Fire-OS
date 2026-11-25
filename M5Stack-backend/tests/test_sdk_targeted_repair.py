"""Targeted experiment uses immutable originals and the real same-build Resume gate."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from fire_backend.app_quality import FireAppReview
from fire_backend.models import GeneratedApp
from scripts import benchmark_app_sdk as benchmark
from scripts import repair_sdk_benchmark as repair
from test_pre_delivery import approve


async def test_targeted_repair_copies_original_and_resumes_same_build_with_previous_code(tmp_path,monkeypatch):
    code='local font="ui16b";function init() end function update(dt) fire.ui.label(10,10,"CORE",{font=font}) end'
    class Seed(benchmark.BenchmarkProvider):
        async def generate(self,*args):return GeneratedApp(name='Test',required_services=['display'],main_lua=code)
        async def close(self):pass
    monkeypatch.setattr(benchmark,'BenchmarkProvider',Seed)
    original=tmp_path/'original';original.mkdir()
    config=SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna')
    row=await benchmark.run_case(original,config,'fake-key-only','weather','Lag en værapp.','sdk')
    assert row['status']=='failed'
    (original/'results.json').write_text(json.dumps({'results':[row]}),encoding='utf-8')
    before={str(p.relative_to(original)):hashlib.sha256(p.read_bytes()).hexdigest() for p in original.rglob('*') if p.is_file()}
    class Fixed(repair.RepairProvider):
        async def generate(self,summary,context,error=None,previous=None):
            self.verify_previous(previous)
            assert previous==code and 'ui16b' in error
            fixed=previous.replace('ui16b','ui16')+'\nlocal original_update=update;local led=0;function update(dt) original_update(dt);if led<10 then fire.rgb.set(led,0,40,100);led=led+1 end end'
            return GeneratedApp(name='Test',required_services=['display','rgb'],main_lua=fixed)
        async def review(self,*args):return FireAppReview(**approve().model_dump(),kind='app',**{n:True for n in FireAppReview.fire_checks()})
        async def close(self):pass
    monkeypatch.setattr(repair,'RepairProvider',Fixed)
    target=tmp_path/'repair';target.mkdir()
    result=await repair.repair_case(target,SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',evaluation_output_cap=True),
        'fake-key-only',original,'weather')
    assert result['status']=='ready',result['error']
    assert result['same_build'] and result['same_project'] and result['build_id']==row['build_id']
    assert result['generation_attempts']==1 and result['initial_attempts']==2
    assert result['standard_verification']['passed'] and result['commands_created']==0
    assert result['previous_code_sha256']==[hashlib.sha256(code.encode()).hexdigest()]
    after={str(p.relative_to(original)):hashlib.sha256(p.read_bytes()).hexdigest() for p in original.rglob('*') if p.is_file()}
    assert before==after and result['calls']==0


async def test_targeted_batch_reserves_full_next_case_from_shared_historical_budget(tmp_path,monkeypatch):
    calls=[]
    async def fake(root,config,key,cohort,label):
        calls.append(label)
        return {'case':label,'status':'ready','generation_attempts':1,'calls':2,'elapsed_seconds':1,
                'estimated_usd':.05,'api_failure_types':[]}
    monkeypatch.setattr(repair,'repair_case',fake)
    result=await repair.execute(tmp_path/'evaluation',SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra'),
        'fake-key-only',tmp_path/'original',.74)
    assert calls==['weather'] and result['evaluation_stopped']=='insufficient_reserved_room_for_next_case'


async def test_continuation_caps_actual_requests_and_prevents_expansion_and_extra_generation(tmp_path):
    from scripts.benchmark_app_sdk import case_settings
    from fire_backend.generation_errors import GenerationResponseError
    code='function init() end function update(dt) end';digest=hashlib.sha256(code.encode()).hexdigest()
    provider=repair.RepairProvider(case_settings(tmp_path,SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',evaluation_output_cap=True),'fake-key-only'),
        digest,generate_cap=4000,review_cap=2000,max_generations=1,request_limit=3)
    requests=[]
    class Responses:
        async def parse(self,**values):
            requests.append(values)
            return SimpleNamespace(status='completed',output_parsed=GeneratedApp(name='Test',main_lua=code,required_services=[]))
    provider.client=SimpleNamespace(responses=Responses())
    await provider.parsed('generate','gpt-6.2-sol','SDK',{},GeneratedApp,8000,'low')
    await provider.parsed('review','gpt-6.1-terra','SDK',{},GeneratedApp,6000,'low')
    assert [r['max_output_tokens'] for r in requests]==[4000,2000]
    with pytest.raises(GenerationResponseError):
        with provider.metered('review','gpt-6.1-terra',{},4000):pass
    provider.verify_previous(code)
    with pytest.raises(GenerationResponseError):provider.verify_previous(code)
    assert len(requests)==2


async def test_continuation_reserves_point35_including_historical_cost(tmp_path,monkeypatch):
    calls=[]
    async def fake(root,config,key,cohort,label):
        calls.append(label)
        return {'case':label,'status':'ready','generation_attempts':1,'calls':2,'elapsed_seconds':1,
                'estimated_usd':.02,'api_failure_types':[]}
    monkeypatch.setattr(repair,'repair_case',fake)
    config=SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',case_budget=.35,generate_cap=4000,review_cap=2000)
    result=await repair.execute(tmp_path/'evaluation',config,'fake-key-only',tmp_path/'source',.64)
    assert calls==['weather'] and result['evaluation_stopped']=='insufficient_reserved_room_for_next_case'
    assert result['plan']['per_case_usd']==.35


async def test_expected_case_generation_end_does_not_skip_independent_platform(tmp_path,monkeypatch):
    calls=[]
    async def fake(root,config,key,cohort,label):
        calls.append(label)
        return {'case':label,'status':'failed','generation_attempts':1,'calls':2,'elapsed_seconds':1,
            'estimated_usd':.02,'api_failure_types':[],'evaluation_failure_types':['GenerationResponseError'],
            'failure_code':'benchmark_generation_limit'}
    monkeypatch.setattr(repair,'repair_case',fake)
    config=SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',case_budget=.35)
    result=await repair.execute(tmp_path/'evaluation',config,'fake-key-only',tmp_path/'source',.4563)
    assert calls==['weather','platform'] and 'evaluation_stopped' not in result

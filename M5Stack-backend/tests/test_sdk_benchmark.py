"""Benchmark wiring tested without any paid request or actual device."""
from types import SimpleNamespace
import pytest

from fire_backend.app_quality import FireAppReview
from fire_backend.app_sdk import DATA,SDK_VERSION
from fire_backend.models import GeneratedApp
from scripts import benchmark_app_sdk as benchmark
from test_pre_delivery import approve


def test_benchmark_plan_is_bounded_whitelisted_and_has_matched_controls():
    config=SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna')
    plan=benchmark.plan(config,True)
    assert plan['builds']==14 and len(plan['cases'])==11
    assert sum(c['profiles']==['legacy','sdk'] for c in plan['cases'])==3
    assert not plan['execute'] and not plan['voices'] and not plan['install'] and not plan['run']
    assert 'credential' not in str(plan) and plan['max_generations_per_build']==2


async def test_benchmark_exercises_real_confirm_build_and_screenshot_review_without_run(tmp_path,monkeypatch):
    seen=[]
    class OfflineProvider(benchmark.BenchmarkProvider):
        async def generate(self,*args):
            assert self.settings.fire_cost_limits_enabled and self.settings.fire_build_budget_usd==.25
            return GeneratedApp(name='Stoppeklokke',required_services=['display','buttons'],
                                main_lua=(DATA/'stopwatch.lua').read_text(encoding='utf-8'))
        async def review(self,summary,context,generated,validation):
            assert SDK_VERSION in context and validation['_visual_review_images']
            seen.extend(validation['_visual_review_images'])
            return FireAppReview(**approve().model_dump(),kind='app',**{n:True for n in FireAppReview.fire_checks()})
        async def close(self):pass
    monkeypatch.setattr(benchmark,'BenchmarkProvider',OfflineProvider)
    config=SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna')
    result=await benchmark.run_case(tmp_path,config,'fake-key-only','stopwatch','Lag en stoppeklokke.','sdk')
    assert result['status']=='ready',result['error']
    assert result['generation_attempts']==1 and result['commands_created']==0
    assert result['local_profiles']>=14 and result['screenshots'] and seen
    assert result['physical_verified'] is False and result['native_timing_measured'] is False
    assert result['calls']==0 and result['usage_all_provider_reported'] is False


async def test_benchmark_reserves_whole_next_case_before_admission(tmp_path,monkeypatch):
    calls=[]
    async def fake(root,config,key,label,request,variant):
        calls.append(label)
        return dict(case=label,profile=variant,status='ready',generation_attempts=1,calls=2,
                    elapsed_seconds=1,estimated_usd=.24)
    monkeypatch.setattr(benchmark,'run_case',fake)
    config=SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna')
    result=await benchmark.execute(tmp_path/'evaluation',config,'fake-key-only')
    assert len(calls)==4 and result['evaluation_stopped']=='insufficient_reserved_room_for_next_case'


def test_stronger_pilot_plan_and_ledger_reservations_fit_without_profile_change(tmp_path):
    from fire_backend.storage import Store
    from fire_backend.security import Redactor
    from fire_backend.usage import UsageLedger
    config=SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',evaluation_output_cap=True)
    plan=benchmark.plan(config,True,pilot=True)
    assert plan['builds']==4 and plan['temporary_output_cap']==8000
    assert plan['initial_control']['generate']=='gpt-6-luna'
    assert all(c['profiles']==['sdk'] for c in plan['cases'])
    settings=benchmark.case_settings(tmp_path/'case',config,'fake-key-only')
    assert settings.fire_cost_limits_enabled and settings.fire_build_budget_usd==.25
    assert settings.fire_output_limits_enabled
    store=Store(settings.fire_workspace,Redactor('fake-key-only'),16*1024*1024)
    ledger=UsageLedger(store,settings)
    key=ledger.begin('generate','gpt-6.2-sol',25000,8000,build_id='build-pilot')
    assert ledger.store.get('usage',key)['reserved_usd']<.25
    ledger.finish(key,{'input_tokens':6000,'output_tokens':2000})
    review=ledger.begin('review','gpt-6.1-terra',35000,6000,build_id='build-pilot')
    assert ledger.store.get('usage',review)['reserved_usd']<.25
    assert config.code_model=='gpt-6.2-sol'  # no saved config/vault is involved


async def test_pilot_caps_actual_request_and_vetoes_output_expansion_before_request(tmp_path):
    config=SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',evaluation_output_cap=True)
    settings=benchmark.case_settings(tmp_path,config,'fake-key-only')
    app=GeneratedApp(name='Test',required_services=[],main_lua='function init() end function update(dt) end')
    requests=[]
    class Responses:
        async def parse(self,**values):
            requests.append(values)
            return SimpleNamespace(status='completed',output_parsed=app)
    provider=benchmark.BenchmarkProvider(settings)
    provider.client=SimpleNamespace(responses=Responses())
    await provider.parsed('generate',settings.openai_code_model,'SDK',{},GeneratedApp,12000,'low')
    assert len(requests)==1 and requests[0]['max_output_tokens']==8000
    assert requests[0]['reasoning']=={'effort':'low'}
    with pytest.raises(benchmark.GenerationResponseError,match='8000-token'):
        with provider.metered('generate',settings.openai_code_model,{},16000):pass
    assert len(requests)==1

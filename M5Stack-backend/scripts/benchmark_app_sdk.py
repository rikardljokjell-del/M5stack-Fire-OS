"""Opt-in offline-device AI benchmark. Default is a secret-free execution plan.

Uses normal build_confirm, Builder, sandbox, screenshots, source-bound review
and usage accounting, with no listener, device commands or run_confirm.
The isolated evaluation's two-generation limit never changes the saved profile.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fire_backend.ai import OpenAIProvider
from fire_backend.app_sdk import SDK_CONTRACT, data_fingerprint
from fire_backend.sdk_context import VERSION as SDK_POLICY_VERSION
from fire_backend.config import Settings
from fire_backend.desktop_config import DesktopConfig, WindowsVault, data_directory
from fire_backend.model_catalog import CODE_MODELS, PRICES, PRICING_DATE, SOURCE
from fire_backend.models import DialogReply
from fire_backend.generation_errors import GenerationResponseError
from fire_backend.service import Backend
from fire_backend.storage import new_id
from fire_backend.visual_preview import preview_folder


CASES=(('stopwatch','Lag en stoppeklokke.'),('weather','Lag en værapp.'),
       ('calculator','Lag en kalkulator.'),('dashboard','Lag et sensordashboard.'),
       ('instrument','Lag et teknisk måleinstrument.'),('snake','Lag Snake.'),
       ('tetris','Lag Tetris.'),('racing','Lag et bilspill.'),
       ('space','Lag et space shooter-spill.'),('platform','Lag et plattformspill.'),
       ('adventure','Lag et eventyrspill.'))
CONTROLS={'stopwatch','calculator','racing'}
# Same literal cases and models, with tool/sensor/game sentinels first.
ORDER=('stopwatch','dashboard','racing','weather','calculator','instrument','snake','tetris','space','platform','adventure')


def profile():
    path=data_directory()/'settings.json'
    if not path.is_file():raise ValueError('Existing Windows profile required; no profile will be created')
    config=DesktopConfig.model_validate_json(path.read_text(encoding='utf-8'))
    if config.code_model not in CODE_MODELS or config.review_model not in CODE_MODELS:
        raise ValueError('Selected models are outside the reviewed benchmark allowlist')
    # Read only the OpenAI credential. Do not load device/admin tokens or write
    # the Credential Manager/configuration, including when this is a dry run.
    key=WindowsVault().get(f'FIREBackend/{config.credential_namespace}/openai')
    return config,key


def plan(config,key_present):
    models={role:{'name':model,'usd_per_million_text_in':PRICES[model].text_in,
                        'usd_per_million_text_out':PRICES[model].text_out,
                        'usd_per_million_cached_in':PRICES[model].text_cache}
            for role,model in [('generate',config.code_model),('review',config.review_model)]}
    return dict(execute=False,key_present=key_present,models=models,pricing_date=PRICING_DATE,
        pricing_source=SOURCE,pricing_basis='existing reviewed local catalog; estimated list-price USD, not invoice',
        sdk_contract=SDK_CONTRACT,sdk_data_sha256=data_fingerprint(),sdk_policy_version=SDK_POLICY_VERSION,
        cases=[{'case':key,'request':text,'profiles':['legacy','sdk'] if key in CONTROLS else ['sdk']} for key,text in CASES],
        case_order=list(ORDER),early_stop='two or more failures in first three SDK cases',
        builds=14,max_generations_per_build=2,paid_operations=['generate','review'],
        max_response_format_retries=1,max_transport_retries=4,max_actual_api_requests_per_build=8,
        evaluation_total_budget_usd=1.0,evaluation_build_budget_usd=.25,
        reserve_next_case_usd=.25,
        voices=False,dialogue='literal request confirmed without paid planning',
        control_scope='Three matched single-run controls; not a statistical performance guarantee',
        physical_verified=False,install=False,run=False,server=False,saved_settings_changed=False)


class BenchmarkProvider(OpenAIProvider):
    def __init__(self,settings):
        super().__init__(settings)
        self.evaluation_requests=0
        self.evaluation_api_failures=[]

    @contextmanager
    def metered(self,*args,**kwargs):
        # Evaluation-only envelope, including response and transport retries.
        # Never applies to the saved Windows profile or production jobs.
        if self.evaluation_requests>=8:
            raise GenerationResponseError('benchmark_call_limit','Evaluation request envelope reached')
        self.evaluation_requests+=1
        try:
            with super().metered(*args,**kwargs) as state:yield state
        except Exception as error:
            self.evaluation_api_failures.append(type(error).__name__)
            raise

    async def connect_dialog(self,context):return None,None

    async def dialog(self,history,context,connection):
        # The experiment measures code+review, not voice or dialogue quality.
        return DialogReply(message='Bestillingen er klar for testbygging.',
                           build_summary=history[-1]['content'],clarification_needed=False)


async def run_case(root,config,key,label,request,variant):
    folder=root/(label+'-'+variant)
    settings=Settings(_env_file=None,openai_api_key=key,openai_code_model=config.code_model,
        openai_review_model=config.review_model,fire_ai_mode='openai',fire_workspace=folder,
        fire_device_tokens=json.dumps({'benchmark-fire':'benchmark-device-credential-only-123456'}),
        fire_audio_enabled=False,fire_speech_enabled=False,fire_max_corrections=1,
        fire_max_build_kb=2048,fire_max_workspace_mb=128,fire_ai_timeout_seconds=90,
        fire_cost_limits_enabled=True,fire_build_budget_usd=.25,fire_output_limits_enabled=False)
    backend=Backend(settings,BenchmarkProvider(settings))
    started=time.monotonic();build=None
    try:
        session=await backend.desktop_conversation('benchmark-fire',hardware_preview=True)
        if variant=='legacy':session.capabilities.pop('app_sdk',None)
        await backend.text(session,request)
        if not session.proposal_id:raise ValueError('Benchmark request did not yield a proposal')
        # Exercise the real current-proposal authorization gate. No run_confirm.
        build=await backend.confirm_build(session,session.proposal_id)
        await session.task
        saved=backend.store.get('builds',build['id'])
        package=backend.store.get('packages',saved['package_id']) if saved.get('package_id') else {}
        validation=package.get('validation',{})
        profiles=validation.get('profiles',[])
        candidates=list(backend.store.path('builds',build['id'],'').glob('attempt-*.lua'))
        source_bytes=len((backend.store.path('builds',build['id'],'')/'main.lua').read_bytes()) if package else max((p.stat().st_size for p in candidates),default=0)
        rows=backend.usage.records()
        evidence=validation.get('visual_evidence',{});screenshots=[]
        if evidence:
            base=preview_folder(backend.store,build['id'],evidence['source_sha256'])
            screenshots=[str(base/(f['png_sha256'][:24]+'.png')) for f in evidence.get('frames',[])]
        return dict(case=label,request=request,profile=variant,status=saved['status'],
            elapsed_seconds=round(time.monotonic()-started,3),generation_attempts=saved.get('attempts',0),
            calls=len(rows),generate_calls=sum(r['operation']=='generate' for r in rows),
            review_calls=sum(r['operation']=='review' for r in rows),
            input_tokens=sum(r.get('input_tokens',0) for r in rows),
            output_tokens=sum(r.get('output_tokens',0) for r in rows),
            cached_tokens=sum(r.get('cached_tokens',0) for r in rows),
            estimated_usd=sum(r.get('estimated_usd',0) for r in rows),
            usage_all_provider_reported=bool(rows) and all(r.get('usage_source')=='provider' for r in rows),
            api_failure_types=sorted(set(backend.provider.evaluation_api_failures)),
            source_bytes=source_bytes,source_sha256=package.get('manifest',{}).get('checksum'),
            failure_code=saved.get('error_code'),error=backend.store.redactor.text(saved.get('error',''))[:300],
            local_profiles=len(profiles),peak_app_memory=max((p.get('app_memory_peak',0) for p in profiles),default=0),
            peak_io_calls=max((p.get('max_io_calls',0) for p in profiles),default=0),
            screenshots=screenshots,sdk_data_sha256=evidence.get('sdk_data_sha256'),
            physical_verified=False,native_timing_measured=False,
            commands_created=len(backend.store.list('commands')),
            build_id=build['id'],workspace=str(folder.resolve()))
    finally:await backend.close()


async def execute(root,config,key,*,prior_estimated_usd=0):
    root.mkdir(parents=True,exist_ok=False)
    report={'plan':plan(config,True),'prior_estimated_usd':prior_estimated_usd,'results':[]}
    report['plan']['execute']=True
    def save():
        (root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for label in ORDER:
        request=dict(CASES)[label]
        for variant in (['legacy','sdk'] if label in CONTROLS else ['sdk']):
            if prior_estimated_usd+sum(r['estimated_usd'] for r in report['results'])+.25>1.0+1e-12:
                report['evaluation_stopped']='insufficient_reserved_room_for_next_case'
                save();return report
            result=await run_case(root,config,key,label,request,variant)
            report['results'].append(result)
            # Incremental private results survive an interruption. No source,
            # credentials, raw provider responses or private settings printed.
            save()
            print(json.dumps({k:result[k] for k in ('case','profile','status','generation_attempts','calls','elapsed_seconds','estimated_usd')},ensure_ascii=False),flush=True)
            sdk_results=[r for r in report['results'] if r['profile']=='sdk']
            if len(sdk_results)==3 and sum(r['status']!='ready' for r in sdk_results)>=2:
                report['evaluation_stopped']='broad_failure_in_first_three_sdk_cases'
                save();return report
            if result['status']!='ready' and result.get('api_failure_types'):
                report['evaluation_stopped']='unexpected_api_error'
                save();return report
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Make real paid code/review calls; requires coordinated authorization')
    options=parser.parse_args()
    config,key=profile()
    if not options.execute:
        print(json.dumps(plan(config,bool(key)),ensure_ascii=False,indent=2));return
    if not key:raise ValueError('No saved OpenAI credential')
    base=Path(__file__).resolve().parents[1]/'workspace'/'sdk-benchmark'
    prior=sum(sum(r['estimated_usd'] for r in json.loads(p.read_text(encoding='utf-8')).get('results',[])) for p in base.glob('evaluation-*/results.json'))
    root=base/new_id('evaluation')
    asyncio.run(execute(root,config,key,prior_estimated_usd=prior))


if __name__=='__main__':main()

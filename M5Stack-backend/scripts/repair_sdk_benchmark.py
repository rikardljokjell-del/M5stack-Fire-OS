"""Bounded, opt-in repairs of the two retained weather/platform candidates.

Copies private benchmark workspaces, resumes the SAME build/project through
current build_confirm, then uses normal validation/review. No listener or RUN.
Saved Windows settings and original measurements are never changed.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.benchmark_app_sdk import BenchmarkProvider,case_settings,profile
from fire_backend.build_strategy import retained_baseline
from fire_backend.service import Backend
from fire_backend.storage import new_id
from fire_backend.visual_preview import preview_folder
from fire_backend.generation_errors import GenerationResponseError


class RepairProvider(BenchmarkProvider):
    def __init__(self,settings,expected_baseline,*,generate_cap=8000,review_cap=6000,max_generations=2,request_limit=8):
        super().__init__(settings);self.expected_baseline=expected_baseline;self.baselines=[]
        self.generate_cap=generate_cap;self.review_cap=review_cap
        self.max_generations=max_generations;self.request_limit=request_limit

    def verify_previous(self,previous):
        if len(self.baselines)>=self.max_generations:
            self.evaluation_api_failures.append('GenerationResponseError')
            raise GenerationResponseError('benchmark_generation_limit','Targeted evaluation generation allowance reached; retained source preserved')
        if previous is None:raise ValueError('Targeted repair requires retained previous_code')
        digest=hashlib.sha256(previous.encode('utf-8')).hexdigest()
        if not self.baselines and digest!=self.expected_baseline:
            raise ValueError('Targeted repair baseline differs from retained strongest candidate')
        self.baselines.append(digest)

    async def generate(self,summary,context,error=None,previous=None):
        self.verify_previous(previous)
        return await super().generate(summary,context,error,previous)

    async def parsed(self,operation,model,instructions,payload,schema,max_output_tokens,effort,*,images=()):
        cap=self.generate_cap if operation=='generate' else self.review_cap
        return await super().parsed(operation,model,instructions,payload,schema,min(max_output_tokens,cap),effort,images=images)

    from contextlib import contextmanager
    @contextmanager
    def metered(self,*args,**kwargs):
        cap=self.generate_cap if args[0]=='generate' else self.review_cap
        if args[3]>cap or self.evaluation_requests>=self.request_limit:
            self.evaluation_api_failures.append('GenerationResponseError')
            raise GenerationResponseError('benchmark_request_limit','Temporary targeted evaluation envelope prevents output expansion or excess requests')
        with super().metered(*args,**kwargs) as state:yield state


def artifact_row(cohort,label):
    cohort=Path(cohort).resolve()
    rows=json.loads((cohort/'results.json').read_text(encoding='utf-8'))['results']
    row=next(r for r in rows if r['case']==label and r['profile'] in {'sdk','targeted-sdk'})
    if row['status']!='failed':raise ValueError('This repair phase requires a failed retained candidate')
    original=Path(row['workspace']).resolve();original.relative_to(cohort)
    return row,original


async def repair_case(root,config,key,cohort,label):
    row,original=artifact_row(cohort,label)
    if any(p.is_symlink() for p in original.rglob('*')):raise ValueError('Symlink in original benchmark')
    folder=Path(root)/(label+'-targeted-sdk')
    shutil.copytree(original,folder)
    settings=case_settings(folder,config,key)
    settings=settings.model_copy(update={'fire_build_budget_usd':getattr(config,'case_budget',.25)})
    old_build=json.loads((folder/'builds'/(row['build_id']+'.json')).read_text(encoding='utf-8'))
    old_attempts=old_build['attempts'];build_folder=folder/'builds'/old_build['id']
    retained=retained_baseline(build_folder,old_attempts)
    source=retained[0] if retained else (build_folder/f'attempt-{old_attempts}.lua').read_bytes().decode('utf-8')
    baseline_sha=hashlib.sha256(source.encode('utf-8')).hexdigest()
    prior_records=[json.loads(p.read_text(encoding='utf-8')) for p in (folder/'usage').glob('usage-*.json')]
    provider=RepairProvider(settings,baseline_sha,generate_cap=getattr(config,'generate_cap',8000),
        review_cap=getattr(config,'review_cap',6000),max_generations=1 if label=='weather' and getattr(config,'continuation',False) else 2,
        request_limit=max(0,8-len(prior_records)))
    backend=Backend(settings,provider)
    prior_usage={r['id'] for r in backend.usage.records()}
    commands_before=len(backend.store.list('commands'));started=time.monotonic()
    try:
        session=await backend.desktop_conversation('benchmark-fire',project_id=old_build['project_id'],hardware_preview=True)
        await backend.restore_failed_build(session,backend.store.get('builds',old_build['id']))
        if not session.proposal_id:raise ValueError('Resume did not produce a current proposal')
        confirmed=await backend.confirm_build(session,session.proposal_id)
        if confirmed['id']!=old_build['id']:raise ValueError('Resume created a different build')
        await session.task
        saved=backend.store.get('builds',old_build['id'])
        package=backend.store.get('packages',saved['package_id']) if saved.get('package_id') else {}
        if saved['project_id']!=old_build['project_id']:raise ValueError('Repair changed project identity')
        usage=[r for r in backend.usage.records() if r['id'] not in prior_usage]
        validation=package.get('validation',{});evidence=validation.get('visual_evidence',{})
        screenshots=[]
        if evidence:
            base=preview_folder(backend.store,saved['id'],evidence['source_sha256'])
            screenshots=[str(base/(f['png_sha256'][:24]+'.png')) for f in evidence['frames']]
        return dict(case=label,profile='targeted-sdk',status=saved['status'],
            original_cohort=Path(cohort).name,original_build_id=old_build['id'],build_id=saved['id'],
            same_project=True,same_build=True,initial_attempts=old_attempts,
            generation_attempts=saved.get('attempts',0)-old_attempts,
            baseline_sha256=baseline_sha,previous_code_sha256=provider.baselines,
            generate_model=settings.openai_code_model,review_model=settings.openai_review_model,
            temporary_output_cap=provider.generate_cap,temporary_review_output_cap=provider.review_cap,
            per_case_budget_usd=settings.fire_build_budget_usd,
            elapsed_seconds=round(time.monotonic()-started,3),
            calls=len(usage),generate_calls=sum(r['operation']=='generate' for r in usage),
            review_calls=sum(r['operation']=='review' for r in usage),
            input_tokens=sum(r.get('input_tokens',0) for r in usage),
            output_tokens=sum(r.get('output_tokens',0) for r in usage),
            cached_tokens=sum(r.get('cached_tokens',0) for r in usage),
            estimated_usd=sum(r.get('estimated_usd',0) for r in usage),
            usage_all_provider_reported=bool(usage) and all(r.get('usage_source')=='provider' for r in usage),
            standard_verification=validation.get('standard_verification'),
            source_sha256=package.get('manifest',{}).get('checksum'),screenshots=screenshots,
            required_services=package.get('manifest',{}).get('required_services'),
            api_failure_types=sorted(set(provider.evaluation_api_failures)-{'UsageBudgetError','GenerationResponseError'}),
            evaluation_failure_types=sorted(set(provider.evaluation_api_failures)),
            failure_code=saved.get('error_code'),error=backend.store.redactor.text(saved.get('error',''))[:1000],
            commands_created=len(backend.store.list('commands'))-commands_before,
            physical_verified=False,native_timing_measured=False,workspace=str(folder.resolve()))
    finally:await backend.close()


async def execute(root,config,key,cohort,prior_estimated_usd):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    cases=getattr(config,'cases',('weather','platform'))
    report={'kind':'targeted-sdk-repairs','prior_estimated_usd':prior_estimated_usd,
            'plan':{'cases':list(cases),'generate':config.code_model,'review':config.review_model,
                    'per_case_usd':getattr(config,'case_budget',.25),'aggregate_usd':1,
                    'temporary_output_cap':getattr(config,'generate_cap',8000),
                    'temporary_review_output_cap':getattr(config,'review_cap',6000)},'results':[]}
    def save():(root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for label in cases:
        if prior_estimated_usd+sum(r['estimated_usd'] for r in report['results'])+getattr(config,'case_budget',.25)>1+1e-12:
            report['evaluation_stopped']='insufficient_reserved_room_for_next_case';save();break
        source_cohort=getattr(config,'weather_cohort',None) if label=='weather' else None
        result=await repair_case(root,config,key,source_cohort or cohort,label)
        report['results'].append(result);save()
        print(json.dumps({k:result[k] for k in ('case','status','generation_attempts','calls','elapsed_seconds','estimated_usd')},ensure_ascii=False),flush=True)
        expected_case_end=result.get('failure_code') in {'benchmark_generation_limit','benchmark_request_limit','benchmark_output_limit'}
        if result['api_failure_types'] or result.get('evaluation_failure_types') and not expected_case_end:
            report['evaluation_stopped']='internal_evaluation_guard' if not result['api_failure_types'] else 'unexpected_api_error'
            save();break
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--continuation',action='store_true',help='Authorized 4000/2000-token, .35-budget continuation only')
    parser.add_argument('--platform-only',action='store_true',help='Finish the already authorized separate platform case; no new weather call')
    args=parser.parse_args();_,key=profile()
    config=SimpleNamespace(code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',evaluation_output_cap=True)
    base=Path(__file__).resolve().parents[1]/'workspace'/'sdk-benchmark'
    if args.continuation:
        config.generate_cap=4000;config.review_cap=2000;config.case_budget=.35;config.continuation=True
        config.weather_cohort=base/'evaluation-e711081caa934c2c8d18'
    if args.platform_only:config.cases=('platform',)
    prior=sum(sum(r['estimated_usd'] for r in json.loads(p.read_text(encoding='utf-8')).get('results',[])) for p in base.glob('evaluation-*/results.json'))
    if not args.execute:
        print(json.dumps({'execute':False,'key_present':bool(key),'generate':config.code_model,'review':config.review_model,
            'prior_estimated_usd':prior,'remaining_aggregate_usd':1-prior,'cases':list(getattr(config,'cases',('weather','platform'))),
            'per_case_usd':getattr(config,'case_budget',.25),'output_cap':getattr(config,'generate_cap',8000),
            'review_output_cap':getattr(config,'review_cap',6000),
            'resume_same_build':True,'install':False,'run':False}));sys.exit(0)
    if not key:raise ValueError('No saved OpenAI credential')
    asyncio.run(execute(base/new_id('evaluation'),config,key,base/'evaluation-19b622a7514f4a50b838',prior))

"""Opt-in, same-app updates of three retained Luna benchmark cores.

Uses verified base packages and normal text/proposal/build_confirm, not a new
app or a fabricated device crash. Originals and Windows profile stay untouched.
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
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.benchmark_app_sdk import case_settings,profile
from scripts.repair_sdk_benchmark import RepairProvider
from fire_backend.builds import verify_archive
from fire_backend.service import Backend
from fire_backend.storage import new_id
from fire_backend.visual_preview import preview_folder


CASES=(('stopwatch','evaluation-31b55b41a0c1432489b5','sdk-luna-v3-control'),
       ('calculator','evaluation-19b622a7514f4a50b838','sdk'),
       ('dashboard','evaluation-19b622a7514f4a50b838','sdk'))
COMMON='''Målrettet oppdatering av den valgte eksisterende appen: behold navn,
utseende og alle fungerende kjernefunksjoner. Legg til meningsfull RGB-status på
BEGGE fem-LED-sider og et fungerende korttrykksbasert RGB av/på-valg. Ett endret
rgb.set per callback; sammenlign faktiske fargeverdier, ikke tabellidentitet.
Av skal nullstille ALLE ti LED-er over avgrensede updates. Følg OS-reserverte
knapper og globale innstillinger. Bruk eksisterende UI-kit og faktiske signaturer. Inkluder testsekvenser
som både viser aktivt RGB og slår det av, med tid til at alle ti blir svarte.
Ingen ombygging fra bunnen eller nye funksjonsområder utover denne oppdateringen.'''
DETAILS={
 'stopwatch':'Behold A nullstill, B start/pause og kompakt/normal visning. C brukes allerede til Visning: gi en liten faktisk A/B/C-valgmeny for visning/RGB/tilbake, ikke fjern visningsfunksjonen eller bruk lange trykk.',
 'calculator':'Behold alle 16 taster, A forrige/B velg/C neste, fire regnearter, nullstilling og deling-på-null-feil. Legg RGB-valg til som et eget navigerbart menypunkt uten å fortrenge tall eller bruke knappekombinasjoner.',
 'dashboard':'Behold akselerometer, temperatur og oppetid samt panelene. Ingen appkorttrykk finnes nå, så B kan betjene tydelig RGB av/på. Bytt unsupported separatorer og initialplaceholder til ASCII - eller /, behold æøå og gradstegn. Ikke presenter foreldede/ugyldige målinger som ferske.',
}


async def update_case(root,config,key,source_cohort,label,variant):
    source_cohort=Path(source_cohort).resolve()
    rows=json.loads((source_cohort/'results.json').read_text(encoding='utf-8'))['results']
    original_row=next(r for r in rows if r['case']==label and r['profile']==variant)
    if original_row['status']!='ready':raise ValueError('RGB update requires retained pipeline-ready core')
    original=Path(original_row['workspace']).resolve();original.relative_to(source_cohort)
    if any(p.is_symlink() for p in original.rglob('*')):raise ValueError('Symlink in original benchmark')
    folder=Path(root)/(label+'-rgb-update');shutil.copytree(original,folder)
    old_build=json.loads((folder/'builds'/(original_row['build_id']+'.json')).read_text(encoding='utf-8'))
    base=json.loads((folder/'packages'/(old_build['package_id']+'.json')).read_text(encoding='utf-8'))
    archive_path=folder/'packages'/(base['id']+'.zip')
    verify_archive(archive_path,base['manifest'],base['archive_sha256'])
    with zipfile.ZipFile(archive_path) as archive:
        previous=archive.read(f"apps/{base['manifest']['id']}/main.lua").decode('utf-8')
    baseline=hashlib.sha256(previous.encode('utf-8')).hexdigest()
    settings=case_settings(folder,config,key)
    provider=RepairProvider(settings,baseline,generate_cap=4000,review_cap=2000,max_generations=2,request_limit=8)
    backend=Backend(settings,provider);initial_usage={r['id'] for r in backend.usage.records()}
    commands_before=len(backend.store.list('commands'));started=time.monotonic()
    try:
        session=await backend.desktop_conversation('benchmark-fire',project_id=base['project_id'],base_package_id=base['id'],hardware_preview=True)
        request=original_row['request']+'\n'+COMMON+'\n'+DETAILS[label]
        await backend.text(session,request)
        if not session.proposal_id:raise ValueError('Update did not produce a current proposal')
        build=await backend.confirm_build(session,session.proposal_id);await session.task
        saved=backend.store.get('builds',build['id'])
        package=backend.store.get('packages',saved['package_id']) if saved.get('package_id') else {}
        if saved['project_id']!=base['project_id']:raise ValueError('RGB update changed project identity')
        if package and package['manifest']['id']!=base['manifest']['id']:raise ValueError('RGB update changed app identity')
        usage=[r for r in backend.usage.records() if r['id'] not in initial_usage]
        validation=package.get('validation',{});evidence=validation.get('visual_evidence',{})
        images=[]
        if evidence:
            path=preview_folder(backend.store,saved['id'],evidence['source_sha256'])
            images=[str(path/(f['png_sha256'][:24]+'.png')) for f in evidence['frames']]
        return dict(case=label,profile='rgb-update-sdk',status=saved['status'],request=request,
            source_cohort=source_cohort.name,base_package_id=base['id'],base_source_sha256=baseline,
            build_id=saved['id'],same_project=True,same_app=True,new_version=package.get('manifest',{}).get('version'),
            previous_code_sha256=provider.baselines,generation_attempts=saved.get('attempts',0),
            generate_model=settings.openai_code_model,review_model=settings.openai_review_model,
            calls=len(usage),generate_calls=sum(r['operation']=='generate' for r in usage),review_calls=sum(r['operation']=='review' for r in usage),
            input_tokens=sum(r.get('input_tokens',0) for r in usage),cached_tokens=sum(r.get('cached_tokens',0) for r in usage),
            output_tokens=sum(r.get('output_tokens',0) for r in usage),estimated_usd=sum(r.get('estimated_usd',0) for r in usage),
            usage_all_provider_reported=bool(usage) and all(r.get('usage_source')=='provider' for r in usage),
            elapsed_seconds=round(time.monotonic()-started,3),temporary_output_cap=4000,temporary_review_output_cap=2000,
            standard_verification=validation.get('standard_verification'),source_sha256=package.get('manifest',{}).get('checksum'),
            required_services=package.get('manifest',{}).get('required_services'),screenshots=images,
            failure_code=saved.get('error_code'),error=backend.store.redactor.text(saved.get('error',''))[:1000],
            evaluation_failure_types=sorted(set(provider.evaluation_api_failures)),
            commands_created=len(backend.store.list('commands'))-commands_before,
            physical_verified=False,native_timing_measured=False,workspace=str(folder.resolve()))
    finally:await backend.close()


async def execute(root,config,key,source_root,prior_estimated_usd):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    report={'kind':'retained-luna-rgb-updates','prior_estimated_usd':prior_estimated_usd,
        'plan':{'cases':[c[0] for c in CASES],'models':{'generate':config.code_model,'review':config.review_model},
            'per_case_usd':.25,'aggregate_usd':1,'output_caps':[4000,2000]},'results':[]}
    def save():(root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for label,cohort,variant in CASES:
        if prior_estimated_usd+sum(r['estimated_usd'] for r in report['results'])+.25>1+1e-12:
            report['evaluation_stopped']='insufficient_reserved_room_for_next_case';save();break
        result=await update_case(root,config,key,Path(source_root)/cohort,label,variant)
        report['results'].append(result);save()
        print(json.dumps({k:result[k] for k in ('case','status','generation_attempts','calls','elapsed_seconds','estimated_usd')},ensure_ascii=False),flush=True)
        if result['evaluation_failure_types'] and result.get('failure_code') not in {'benchmark_generation_limit','benchmark_request_limit','benchmark_output_limit'}:
            report['evaluation_stopped']='unexpected_provider_or_admission_error';save();break
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    _,key=profile();base=Path(__file__).resolve().parents[1]/'workspace'/'sdk-benchmark'
    config=SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna',evaluation_output_cap=True)
    prior=sum(sum(r['estimated_usd'] for r in json.loads(p.read_text(encoding='utf-8')).get('results',[])) for p in base.glob('evaluation-*/results.json'))
    if not args.execute:
        print(json.dumps({'execute':False,'key_present':bool(key),'generate':config.code_model,'review':config.review_model,
            'prior_estimated_usd':prior,'remaining_usd':1-prior,'reserve_before_each':.25,'output_caps':[4000,2000],
            'cases':[c[0] for c in CASES],'same_app_update':True,'install':False,'run':False}));sys.exit(0)
    if not key:raise ValueError('No saved OpenAI credential')
    asyncio.run(execute(base/new_id('evaluation'),config,key,base,prior))

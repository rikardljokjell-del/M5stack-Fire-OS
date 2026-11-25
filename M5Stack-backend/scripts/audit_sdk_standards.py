"""Offline standard revalidation of immutable benchmark READY candidates.

No server, vault, AI call, original artifact writes, device command or RUN.
Fresh telemetry and pictures are stored only in a new isolated audit folder.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fire_backend.app_quality import UX_POLICY_VERSION
from fire_backend.app_sdk import data_fingerprint
from fire_backend.builds import validate_release,verify_archive
from fire_backend.revalidation import sdk_revalidation_input
from fire_backend.sdk_standards import verify,VERSION
from fire_backend.security import Redactor
from fire_backend.storage import Store,identifier


async def audit(cohorts,output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    report={'kind':'offline-sdk-standard-audit','version':VERSION,'physical_verified':False,
            'sdk_data_sha256':data_fingerprint(),'ai_calls':0,'device_commands':0,'results':[]}
    for cohort in cohorts:
        cohort=Path(cohort).resolve()
        rows=json.loads((cohort/'results.json').read_text(encoding='utf-8'))['results']
        for row in rows:
            if row['status']!='ready' or row['profile']=='legacy':continue
            original=Path(row['workspace']).resolve();original.relative_to(cohort)
            # Read-only adapter: no Store constructor/directory creation in originals.
            original_store=SimpleNamespace(path=lambda group,key,suffix='.json':original/group/(identifier(key)+suffix))
            package=json.loads(original_store.path('packages',row['build_id']).read_text(encoding='utf-8'))
            build=json.loads(original_store.path('builds',row['build_id']).read_text(encoding='utf-8'))
            manifest=package['manifest'];archive_path=original_store.path('packages',package['id'],'.zip')
            verify_archive(archive_path,manifest,package['archive_sha256'])
            with zipfile.ZipFile(archive_path) as archive:
                source=archive.read(f"apps/{manifest['id']}/main.lua").decode('utf-8')
            expected,extra=sdk_revalidation_input(original_store,package,build,source)
            target=output/(row['case']+'-'+row['profile']+'-'+cohort.name[-6:])
            target.mkdir(exist_ok=False)
            store=Store(target,Redactor(''),128*1024*1024)
            record={'cohort':cohort.name,'case':row['case'],'profile':row['profile'],
                    'original_build_id':row['build_id'],'original_workspace':str(original),
                    'source_sha256':manifest['checksum'],'required_services':manifest['required_services'],
                    'standard_contract':expected,'pipeline_ready_historically':True,'physical_verified':False}
            try:
                validation=await validate_release(dict(main_lua=source,required_services=manifest['required_services'],
                    api_version=manifest['api_version'],api_contract=manifest['api_contract'],
                    max_memory=manifest['max_memory'],max_runtime_ms=manifest['max_runtime_ms'],
                    experience_policy_version=UX_POLICY_VERSION,**extra),store,package['id'])
                proof=verify(expected,manifest['required_services'],validation,manifest['checksum'])
                record.update(core_passed=True,standard_verification=proof,
                    profiles=len(validation['profiles']),screenshots=validation['visual_evidence'],
                    io_coverage_missing=validation['io_coverage_missing'])
                store.write(target/'fresh-validation.json',validation)
            except (ValueError,OSError,KeyError) as error:
                record.update(core_passed=False,standard_verification=None,error=str(error)[:1200])
            verify_archive(archive_path,manifest,package['archive_sha256'])
            store.write(target/'standard-audit.json',record)
            report['results'].append(record)
            (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'case':row['case'],'profile':row['profile'],'core_passed':record['core_passed'],
                'standard_passed':bool(record['standard_verification'] and record['standard_verification']['passed'])}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cohorts',nargs='+',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();asyncio.run(audit(args.cohorts,args.output))

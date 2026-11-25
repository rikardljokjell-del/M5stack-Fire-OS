"""Offline, hash-checked candidate/evidence summary; never calls AI or a device."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def analyze(root):
    root=Path(root).resolve();report=read(root/'results.json');cases=[]
    for row in report['results']:
        workspace=Path(row['workspace']).resolve();workspace.relative_to(root)
        if not re.fullmatch(r'build-[a-z0-9]{20}',row['build_id']):raise ValueError('Invalid build identity')
        folder=workspace/'builds'/row['build_id'];attempts=[]
        package_path=workspace/'packages'/(row['build_id']+'.json')
        package=read(package_path) if package_path.exists() else {}
        original=read(folder/'request.json');caps=original.get('capabilities') or {}
        for path in sorted(folder.glob('candidate-*.json')):
            n=int(path.stem.split('-')[-1]);meta=read(path);source=folder/f'attempt-{n}.lua'
            data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
            if digest!=meta['source_sha256']:raise ValueError('Candidate source checksum mismatch')
            review_path=folder/f'review-{n}.json';review=read(review_path) if review_path.exists() else {}
            screenshots=[];index=folder/'previews'/digest[:16]/'index.json'
            if index.exists():
                evidence=read(index)
                if evidence['source_sha256']!=digest:raise ValueError('Evidence source mismatch')
                for frame in evidence['frames']:
                    png=index.parent/(frame['png_sha256'][:24]+'.png')
                    if hashlib.sha256(png.read_bytes()).hexdigest()!=frame['png_sha256']:
                        raise ValueError('Screenshot checksum mismatch')
                    screenshots.append({'path':str(png),'source_sha256':digest,
                        'sdk_data_sha256':evidence['sdk_data_sha256'],'png_sha256':frame['png_sha256']})
            attempts.append({'attempt':n,'source_sha256':digest,'source_bytes':len(data),
                'required_services':meta['required_services'],
                'local_core_passed':(folder/f'validation-{n}.json').exists(),
                'review_approved':review.get('approved'),
                'issues':review.get('checks',{}).get('issues',[]),'screenshots':screenshots})
        validation=package.get('validation',{});manifest=package.get('manifest',{})
        rgb_calls=sum(v for k,v in validation.get('io_calls',{}).items() if k in {'rgb.set','display.rgb'})
        cases.append({'case':row['case'],'profile':row['profile'],'pipeline_ready':row['status']=='ready',
            'standard_status':'not_deterministically_verified' if not validation.get('standard_verification') else validation['standard_verification'],
            'actual_announced_rgb':'rgb' in caps.get('services',[]),
            'declares_rgb':'rgb' in manifest.get('required_services',[]),
            'rgb_calls_reported':rgb_calls,'final_required_services':manifest.get('required_services'),
            'physical_compatibility':'not_checked_against_fresh_device',
            'physical_verified':False,'attempts':attempts})
    sums={key:sum(r.get(key,0) for r in report['results']) for key in
          ('calls','input_tokens','output_tokens','cached_tokens','elapsed_seconds','estimated_usd')}
    output={'kind':'offline-hash-checked-sdk-artifacts','plan':report['plan'],
            'completed':len(cases),'pipeline_ready':sum(c['pipeline_ready'] for c in cases),
            'candidate_count':sum(len(c['attempts']) for c in cases),'totals':sums,
            'evaluation_stopped':report.get('evaluation_stopped'),'cases':cases}
    (root/'artifact-summary.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('cohort',type=Path)
    result=analyze(parser.parse_args().cohort)
    print(json.dumps({k:result[k] for k in ('completed','pipeline_ready','candidate_count','totals')}))

"""Smaller model inputs without relaxing the release contract or losing evidence.

Full original diagnostics and release results stay in local storage. These
deterministic views remove duplicated history and repeated simulation output.
"""
import copy
import json

from .api_registry import ALL_SERVICES
from .capabilities import policy


def dumps(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def dialogue_policy(settings,session):
    effective=policy(settings,'device' if session.desktop_device_id else session.target,session.capabilities)
    # Planning needs availability and ownership, not every Lua method signature.
    return ('\nAuthoritative capability policy for THIS session:\n'+dumps(effective)+
        '\nOnly lua_services are available. Unavailable: '+','.join(sorted(ALL_SERVICES-set(effective['lua_services'])))+
        '. Conversation audio never grants Lua mic/speaker. Zero lifetime means until user exit. '
        'Keep unavailable hardware goals; explain the missing firmware prerequisite without unrelated replacements. '
        'GPS is external and requires an announced UART. Never claim physical success from PC tests.\n')


def _fields(value,keys,limit=800):
    if not isinstance(value,dict):return {}
    return {k:(v[:limit] if isinstance(v,str) else copy.deepcopy(v)) for k in keys if (v:=value.get(k)) is not None}


def compact_repair_evidence(evidence):
    """Retain current identity/fault and recent distinct failure evidence once."""
    if not isinstance(evidence,dict):return str(evidence)[:2400] if evidence else evidence
    result=_fields(evidence,(
        'package_id','reported_package_id','target_resolution','identity_warnings',
        'reported_version','reported_source_sha256','boot_id','run_id','last_button',
        'last_button_action','error_code','message','diagnostics','latest_version_used_as_base',
        'physical_root_cause_verified','blocked_device_runtime','repair_job_id',
        'source_sha256','reproduced_on_pc','validator_error','case_id',
    ),1200)
    cases=evidence.get('cases') or []
    ordered=sorted((c for c in cases if isinstance(c,dict)),key=lambda c:c.get('last_seen',0),reverse=True)
    selected=[];seen=set()
    for case in ordered:
        identity=(case.get('source_sha256'),case.get('category'),case.get('message'))
        if identity in seen:continue
        seen.add(identity)
        row=_fields(case,('id','category','count','message','package_id','source_sha256','status','provenance','last_seen'))
        row['regression']=_fields(case.get('regression'),('rule_id','required_check','root_cause_status'))
        failure=case.get('failure_evidence') or {}
        row['failure_evidence']=_fields(failure,('physical_failure_observed','root_cause_verified','source_sha256','provenance'))
        row['failure_evidence']['latest_feedback']=_fields(failure.get('latest_feedback'),
            ('event','error_code','message','boot_id','run_id','diagnostics'))
        row['fix']=_fields(case.get('fix'),('status','summary','source_changed','candidate_package_id',
            'candidate_source_sha256','physical_resolution_verified','required_regression_check'))
        selected.append(row)
        if len(selected)==6:break
    result['cases']=selected
    if len(selected)<len(cases):result['older_case_count']=len(cases)-len(selected)
    return result


def compact_validation(validation):
    """Lossless grouping of successful profile metrics and IMU scene contents.

    Raw drawing traces repeat source behavior and are not a rendered screenshot.
    All profile metrics, scenario identities, coverage, faults, and actual IMU
    checkpoint content are retained, with identical records referenced once.
    """
    if not isinstance(validation,dict):return validation
    result={k:copy.deepcopy(v) for k,v in validation.items() if k not in {'trace','profiles','imu_scenes','_visual_review_images'}}
    scenes=[];scene_ids={};groups=[];group_ids={}
    for profile in validation.get('profiles',[]):
        metrics={k:copy.deepcopy(v) for k,v in profile.items() if k not in {'profile','scenario','trace','imu_scenes'}}
        refs=[]
        for scene in profile.get('imu_scenes') or []:
            key=dumps(scene)
            if key not in scene_ids:
                scene_ids[key]=len(scenes);scenes.append(copy.deepcopy(scene))
            refs.append(scene_ids[key])
        if refs:metrics['imu_scene_refs']=refs
        key=dumps(metrics)
        label={k:profile[k] for k in ('profile','scenario') if k in profile}
        if key in group_ids:groups[group_ids[key]]['cases'].append(label)
        else:
            group_ids[key]=len(groups);groups.append({'cases':[label],'metrics':metrics})
    if groups:
        common={k:v for k,v in groups[0]['metrics'].items()
                if all(k in group['metrics'] and group['metrics'][k]==v for group in groups[1:])}
        if common:
            result['profile_defaults']=common
            for group in groups:
                for key in common:group['metrics'].pop(key)
    result['profile_groups']=groups
    if scenes:result['imu_scene_table']=scenes
    # Direct callers may provide only one result rather than a full release suite.
    if not validation.get('profiles') and validation.get('imu_scenes'):
        result['imu_scenes']=copy.deepcopy(validation['imu_scenes'])
    result['review_view']='deduplicated-release-v1; each case = profile_defaults + group.metrics; scene refs index imu_scene_table; raw drawing trace omitted'
    return result

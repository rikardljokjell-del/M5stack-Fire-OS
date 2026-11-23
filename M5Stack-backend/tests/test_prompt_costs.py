import copy
import json

import pytest

from fire_backend.api_registry import API_CONTRACT,preview_capabilities
from fire_backend.app_quality import APP_QUALITY_POLICY
from fire_backend.models import SessionStart
from fire_backend.prompt_context import compact_repair_evidence,compact_validation,dumps
from fire_backend.service import Backend
from test_device_protocol import configured


def test_compact_repair_keeps_identity_and_current_failure_without_nested_history():
    case={'id':'case-one','category':'budget','message':'Lua update main.lua:88 budget exceeded',
        'source_sha256':'a'*64,'last_seen':5,'regression':{'rule_id':'budget','required_check':'Measure native callback'},
        'failure_evidence':{'source_sha256':'a'*64,'physical_failure_observed':True,
            'latest_feedback':{'boot_id':'boot-current','diagnostics':{'callback_us':132000}}},
        'fix_history':[{'huge_old_history':'x'*20000}],
        'fix':{'status':'failed_on_device','physical_resolution_verified':False,'summary':'Changed render path',
            'previous_metrics':{'huge_unneeded_payload':'y'*20000}}}
    evidence={'package_id':'build-current','source_sha256':'b'*64,'case_id':'case-current',
        'validator_error':'PC did not reproduce native timing','reproduced_on_pc':False,
        'blocked_device_runtime':True,'reported_package_id':'build-stale','reported_source_sha256':'b'*64,
        'diagnostics':{'callback_us':132000},'cases':[copy.deepcopy(case) for _ in range(12)]}
    compact=compact_repair_evidence(evidence)
    assert compact['package_id']=='build-current' and compact['reported_package_id']=='build-stale'
    assert compact['reported_source_sha256']=='b'*64 and compact['source_sha256']=='b'*64
    assert compact['validator_error']==evidence['validator_error'] and compact['reproduced_on_pc'] is False
    assert compact['blocked_device_runtime'] is True
    assert compact['cases'][0]['failure_evidence']['latest_feedback']['diagnostics']['callback_us']==132000
    assert compact['cases'][0]['fix']['physical_resolution_verified'] is False
    assert len(dumps(compact))<len(dumps(evidence))*.05
    assert 'huge_old_history' not in dumps(compact)
    assert 'fix_history' in evidence['cases'][0]  # No mutation of retained evidence.


def test_review_view_preserves_all_profiles_metrics_and_actual_imu_scenes_with_deduplication():
    scene={'time_ms':400,'text':['Pitch -30.0'],'leds':[1]*10,'grids':[{'cells':'1234'}]}
    base={'ok':True,'frames':3750,'elapsed_ms':60000,'max_callback_operations':20,
        'io_calls':{'uart.read':12},'jobs_started':{'speaker.tone':2},'imu_reads':200,
        'imu_scenes':[scene],'trace':[['text',4,4,'Repeated']]*240}
    raw={**copy.deepcopy(base),'suite':'release-v4','physical_verified':False,
        'profiles':[{**copy.deepcopy(base),'profile':name} for name in ('idle','cycle','imu_motion','imu_recovery')]}
    compact=compact_validation(raw)
    assert 'trace' not in compact and 'trace' not in compact['profile_groups'][0]['metrics']
    assert len(compact['profile_groups'])==1
    group=compact['profile_groups'][0]
    assert [c['profile'] for c in group['cases']]==['idle','cycle','imu_motion','imu_recovery']
    metrics={**compact.get('profile_defaults',{}),**group['metrics']}
    assert metrics['max_callback_operations']==20
    assert metrics['jobs_started']['speaker.tone']==2
    assert compact['imu_scene_table'][metrics['imu_scene_refs'][0]]==scene
    assert compact['physical_verified'] is False and len(dumps(compact))<len(dumps(raw))*.1
    assert raw['trace'] and raw['profiles'][0]['imu_scenes']==[scene]


async def test_dialogue_planning_omits_codegen_registry_while_generation_keeps_authoritative_contract(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        s=await b.start(SessionStart())
        s.capabilities=preview_capabilities();s.desktop_device_id='fire-01'
        b.quality.record(project_id=s.project_id,message='visual_quality_ok failure',provenance='user_report')
        dialog=b.context_for(s,dialogue=True);generation=b.context_for(s)
        assert 'Authoritative capability policy' in dialog and API_CONTRACT in dialog
        assert 'hardware_resources' in dialog and 'gpio_read' in dialog
        assert 'Exact negotiated host contract' not in dialog
        assert 'Exact negotiated host contract' in generation and 'frequency_hz' in generation
        assert generation.count(APP_QUALITY_POLICY)==1
        assert 'A previous/up, B select/confirm, C next/down' in dialog
        assert len(dialog)<len(generation)*.30
    finally:await b.close()


async def test_review_cost_limit_does_not_trigger_another_paid_generation(tmp_path):
    from fire_backend.ai import MockProvider
    from fire_backend.usage import UsageBudgetError
    class Provider(MockProvider):
        generated=0
        async def generate(self,*args,**kwargs):
            self.generated+=1
            return await super().generate(*args,**kwargs)
        async def review(self,*args,**kwargs):raise UsageBudgetError()
    p=Provider();b=Backend(configured(tmp_path),p)
    try:
        s=await b.start(SessionStart());await b.text(s,'Lag en sirkel')
        build=await b.confirm_build(s,s.proposal_id);await s.task
        assert p.generated==1
        assert b.store.get('builds',build['id'])['status']=='failed'
        assert not b.store.list('packages')
    finally:await b.close()

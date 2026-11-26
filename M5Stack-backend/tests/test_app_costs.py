import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.metering import session_usage,usage_session,usage_scope
from fire_backend.service import Backend
from test_device_protocol import configured,headers,ADMIN
from test_device_app_manager import version
from test_repair_target import saved_app


def charge(b,project,operation,model='gpt-6-luna',build=None,seconds=None):
    item=b.usage.begin(operation,model,1000,1000,project_id=project,build_id=build,audio_seconds=seconds)
    return b.usage.finish(item,{'input_tokens':1000,'output_tokens':1000},duration_seconds=seconds)


def test_library_cost_sums_all_versions_failed_fixes_and_audio_without_double_counting_or_reset(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as client:
        b=client.app.state.backend;p,first=saved_app(b,'Spill');new=version(b,first,2)
        other,other_package=saved_app(b,'Annen',slug='annen')
        b.store.put('builds','build-failed-fix',{'id':'build-failed-fix','project_id':p['id'],'status':'failed'})
        costs=[charge(b,p['id'],'generate',build=first['build_id']),charge(b,p['id'],'review',build=new['build_id']),
            charge(b,p['id'],'generate',build='build-failed-fix'),
            charge(b,p['id'],'dialog','gpt-realtime-2.1-mini'),
            charge(b,p['id'],'speech','gpt-realtime-2.1-mini'),
            charge(b,p['id'],'transcribe','gpt-transcribe',seconds=30)]
        charge(b,other['id'],'generate')
        expected=sum(x['estimated_usd'] for x in costs)
        library=client.get('/desktop/status',headers=headers(ADMIN)).json()['apps']
        rows=[a for a in library if a['project_id']==p['id']]
        assert len(rows)==2 and all(a['cost']==pytest.approx(expected) for a in rows)
        assert all(a['cost_detail']['requests']==6 for a in rows)
        assert {r['operation'] for r in rows[0]['cost_detail']['by_operation']}=={'generate','review','dialog','speech','transcribe'}
        assert rows[0]['cost_detail']['scope']=='all_versions_lifetime'
        client.post('/desktop/usage/reset',headers=headers(ADMIN),json={})
        assert b.usage.snapshot()['since_reset']['requests']==0
        assert all(a['cost']==pytest.approx(expected) for a in b.app_library() if a['project_id']==p['id'])
        # Removing a historical version/build cannot remove its already billed use.
        b.store.path('packages',new['id']).unlink();b.store.path('builds',new['build_id']).unlink()
        assert next(a for a in b.app_library() if a['project_id']==p['id'])['cost']==pytest.approx(expected)


async def test_build_attribution_is_backfilled_before_build_metadata_can_be_deleted(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        p,package=saved_app(b,'App')
        result=charge(b,None,'generate',build=package['build_id'])
        assert result['project_id']==p['id']
        b.store.path('builds',package['build_id']).unlink()
        assert b.usage.project_costs()[p['id']]['estimated_usd']==result['estimated_usd']
    finally:await b.close()


async def test_resolved_repair_turn_reassigns_asr_cost_without_changing_amounts_or_build_costs(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        old,first=saved_app(b,'Gammel');chosen,second=saved_app(b,'Valgt',slug='valgt')
        s=SimpleNamespace(id='session-attribution',project_id=old['id'],turn_id='turn-attribution')
        class Turn:
            service=b
            @session_usage
            async def run(self,session):
                active=usage_session.get()
                item=b.usage.begin('transcribe','gpt-transcribe',0,0,audio_seconds=10,
                    project_id=active.project_id,session_id=active.id,turn_id=active.turn_id)
                record=b.usage.finish(item,None,duration_seconds=10)
                session.project_id=chosen['id']  # App resolved from speech.
                return record['id'],record['estimated_usd']
        build_cost=charge(b,old['id'],'generate',build=first['id'])
        identifier,amount=await Turn().run(s)
        moved=b.store.get('usage',identifier)
        assert moved['project_id']==chosen['id'] and moved['original_project_id']==old['id']
        assert moved['estimated_usd']==amount and b.store.get('usage',build_cost['id'])['project_id']==old['id']
        assert usage_session.get() is None and usage_scope.get()=={}
    finally:await b.close()


async def test_attribution_storage_failure_always_releases_project_context():
    def unavailable(*args):raise OSError('Disk unavailable')
    class Turn:
        usage=SimpleNamespace(attribute_turn=unavailable)
        @session_usage
        async def run(self,session):return None
    with pytest.raises(OSError):
        await Turn().run(SimpleNamespace(id='session-failed',turn_id='turn-failed',project_id='app-failed'))
    assert usage_scope.get()=={} and usage_session.get() is None


@pytest.mark.parametrize('explicit_target',[True,False])
async def test_turn_attribution_isolates_frozen_job_target_from_dynamic_app_choice(tmp_path,explicit_target):
    b=Backend(configured(tmp_path))
    try:
        initial,_=saved_app(b,'Første',slug='initial')
        target,_=saved_app(b,'Jobbmål',slug='target')
        final,_=saved_app(b,'Valgt til slutt',slug='final')
        binding={'project_id':target['id']} if explicit_target else None
        s=SimpleNamespace(id='session-isolation',project_id=initial['id'],turn_id='turn-isolation',job_context_target=binding)
        class Turn:
            service=b
            @session_usage
            async def run(self,session):
                assert usage_scope.get()['project_id']==(target['id'] if explicit_target else initial['id'])
                item=b.usage.begin('transcribe','gpt-transcribe',0,0,audio_seconds=10,
                    project_id=usage_scope.get()['project_id'],session_id=session.id,turn_id=session.turn_id)
                row=b.usage.finish(item,None,duration_seconds=10)
                session.project_id=final['id']
                if session.job_context_target is not None:session.job_context_target.clear()
                session.job_context_target=None
                return item,row['estimated_usd']
        identifier,amount=await Turn().run(s)
        row=b.store.get('usage',identifier)
        assert row['project_id']==(target['id'] if explicit_target else final['id'])
        assert row['estimated_usd']==amount and row['usage_source']=='duration'
        assert usage_scope.get()=={} and usage_session.get() is None
    finally:await b.close()

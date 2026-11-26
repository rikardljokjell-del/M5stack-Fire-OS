import json
import asyncio
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from fire_backend.app import create_app
from fire_backend.models import SessionStart,DeviceEvent
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from fire_backend.evolution_contract import EXTENSION
from fire_backend.evolution_models import EvolutionConfig
from fire_backend.storage import new_id
from test_device_protocol import configured,CAPS,ADMIN,TOKEN
from test_repair_target import Peer,saved_app


def event(session,name,**values):
    return DeviceEvent(device_id=session.device_id,event=name,session_id=session.id,event_id=new_id('evt'),
        protocol_version='0.2',boot_id=session.boot_id,**values)


async def test_native_exact_scope_config_replay_and_unbound_telemetry_never_claims_physical(tmp_path):
    b=Backend(configured(tmp_path));peer=Peer()
    try:
        s=await b.start(SessionStart(device_id='fire-01',target='device',protocol_version='0.2',boot_id='boot-new',
            capabilities={**CAPS,'evolution':EXTENSION}),peer,'fire-01')
        project,package=saved_app(b,'Kontroll',slug='kontroll')
        config=EvolutionConfig(telemetry_consent=True).model_dump()
        prepare=event(s,'evolution_prepare',app_id='kontroll',request_id='req-config',operation='configure',expected_revision=0,evolution_json=json.dumps(config))
        p=await dispatch(b,s,prepare)
        confirm=event(s,'evolution_confirm',app_id='kontroll',request_id='req-confirm',proposal_id=p['proposal_id'],expected_revision=0)
        await dispatch(b,s,confirm)
        assert (await dispatch(b,s,confirm))['status']=='duplicate'
        state=b.evolution.state('fire-01',project['id'])
        assert state['revision']==1 and state['approval']['event_id']==confirm.event_id
        value={'schema':1,'batch_id':'batch-one','captured_boot_id':'boot-older','run_id':'run-unknown',
            'start_ms':0,'end_ms':60000,'callbacks':{'update':{'count':100,'total_us':100000,'max_us':1000}},
            'buttons':{'A':1},'job_errors':[],'dropped_batches':0}
        packet=event(s,'evolution_telemetry',app_id='kontroll',request_id='req-telemetry',package_id=package['id'],
            source_sha256=package['manifest']['checksum'],telemetry_json=json.dumps(value))
        result=await dispatch(b,s,packet)
        assert result['status']=='accepted'
        saved=b.store.list('evolution_telemetry')[0]
        assert not saved['run_bound'] and not saved['physical_verified']
        assert saved['transport_boot_id']=='boot-new' and saved['telemetry']['captured_boot_id']=='boot-older'
        duplicate=event(s,'evolution_telemetry',app_id='kontroll',request_id='req-other',package_id=package['id'],
            source_sha256=package['manifest']['checksum'],telemetry_json=json.dumps(value))
        assert (await dispatch(b,s,duplicate))['status']=='duplicate'
        bad=duplicate.model_copy(update={'event_id':new_id('evt'),'telemetry_json':json.dumps({**value,'callbacks':[{}]})})
        with pytest.raises(ValueError):await dispatch(b,s,bad)
        assert not b.store.list('commands') and not b.usage.records()
    finally:await b.close()


def test_http_uses_existing_auth_and_manual_current_proposal(tmp_path):
    app=create_app(configured(tmp_path,fire_desktop_enabled=True))
    with TestClient(app) as client:
        b=app.state.backend;project=b.new_project('fire-01','device')
        b.store.put('devices','fire-01',{'id':'fire-01','capabilities':CAPS})
        path='/desktop/apps/'+project['id']+'/evolution'
        assert client.get(path).status_code==401
        assert client.get(path,headers={'Authorization':'Bearer '+TOKEN}).status_code==403
        headers={'Authorization':'Bearer '+ADMIN}
        assert client.get(path,headers=headers).json()['config']['enabled'] is False
        config=EvolutionConfig(enabled=True,flags={'generate':True},autonomy='manual').model_dump()
        p=client.post(path+'/prepare',headers=headers,json={'operation':'configure','expected_revision':0,'value':config}).json()
        assert client.post(path+'/confirm',headers=headers,json={'proposal_id':p['id'],'expected_revision':0}).status_code==200
        p=client.post(path+'/prepare',headers=headers,json={'operation':'generate','expected_revision':1,'value':{'goal':'Lag en sirkel'}}).json()
        result=client.post(path+'/confirm',headers=headers,json={'proposal_id':p['id'],'expected_revision':1})
        assert result.status_code==200
        current=client.get(path+'/proposal',headers=headers)
        assert current.status_code==200 and current.json()['proposal_id']
        assert not b.store.list('builds') and not b.store.list('commands')
        assert client.post('/build/confirm',headers=headers,json={'session_id':current.json()['session_id'],'proposal_id':'proposal-wrong'}).status_code==409


async def test_native_manual_proposal_keeps_project_context_and_normal_current_build_gate(tmp_path):
    from test_evolution_engine import Provider
    provider=Provider();b=Backend(configured(tmp_path),provider);peer=Peer()
    try:
        s=await b.start(SessionStart(device_id='fire-01',target='device',protocol_version='0.2',boot_id='boot-manual',
            capabilities={**CAPS,'evolution':EXTENSION}),peer,'fire-01')
        project_id=s.project_id
        config=EvolutionConfig(enabled=True,flags={'generate':True},autonomy='manual').model_dump()
        p=await dispatch(b,s,event(s,'evolution_prepare',app_id=project_id,request_id='config-prepare',
            operation='configure',expected_revision=0,evolution_json=json.dumps(config)))
        await dispatch(b,s,event(s,'evolution_confirm',app_id=project_id,request_id='config-confirm',
            proposal_id=p['proposal_id'],expected_revision=0))
        p=await dispatch(b,s,event(s,'evolution_prepare',app_id=project_id,request_id='manual-prepare',
            operation='generate',expected_revision=1,evolution_json=json.dumps({'goal':'Tell med knapp'})))
        await dispatch(b,s,event(s,'evolution_confirm',app_id=project_id,request_id='manual-confirm',
            proposal_id=p['proposal_id'],expected_revision=1))
        proposal=next(e for e in reversed(peer.events) if e['type']=='build_proposal')
        assert proposal['project_id']==project_id==s.project_id
        assert proposal['app_name']==b.store.get('projects',project_id)['name']
        assert 'context_id' in proposal and proposal['context_id']==s.development_context_id
        assert proposal['evolution_job_id']==s.evolution_job_id
        assert proposal['proposal_id']==s.proposal_id
        assert not provider.calls and not b.store.list('builds') and not b.store.list('commands')
        with pytest.raises(ValueError):await dispatch(b,s,event(s,'build_confirm',proposal_id='proposal-stale'))
        assert not provider.calls and not b.store.list('builds')
        confirmed=await dispatch(b,s,event(s,'build_confirm',proposal_id=proposal['proposal_id']))
        await asyncio.wait_for(asyncio.shield(s.task),30)
        pending=b.evolution.tasks.get(proposal['evolution_job_id'])
        if pending:await asyncio.wait_for(asyncio.shield(pending),30)
        build=b.store.get('builds',confirmed['build_id'])
        assert build['authorization']['kind']=='explicit_build_confirm'
        assert build['evolution_job_id']==proposal['evolution_job_id']
        assert build['resume_context']['base_package_id'] is None
        assert build['status']=='ready' and len(provider.calls)==1
        assert b.store.get('evolution_jobs',proposal['evolution_job_id'])['state']=='awaiting_install'
        assert not b.store.list('commands')  # Opening/confirming the build cannot install or RUN.
    finally:await b.close()


@pytest.mark.parametrize('name', ['evolution_prepare','backend_settings_prepare'])
def test_wire_controls_enforce_utf8_and_revision_zero(name):
    values={'app_id':'clock','operation':'configure','evolution_json':'{}'} if name=='evolution_prepare' else {'settings_json':'{}'}
    packet={'device_id':'fire-01','event':name,'event_id':'event-one','request_id':'request-one','session_id':'session-one',
        'protocol_version':'0.2','expected_revision':0,**values}
    assert DeviceEvent.model_validate(packet).expected_revision==0
    key='evolution_json' if name=='evolution_prepare' else 'settings_json'
    with pytest.raises(ValidationError):DeviceEvent.model_validate({**packet,key:'æ'*1500})


async def native_manual_proposal(b):
    request=SessionStart(device_id='fire-01',target='device',protocol_version='0.2',boot_id='boot-durable',
        capabilities={**CAPS,'evolution':EXTENSION})
    s=await b.start(request,Peer(),'fire-01')
    for operation,revision,value in (
        ('configure',0,EvolutionConfig(enabled=True,flags={'generate':True},autonomy='manual').model_dump()),
        ('generate',1,{'goal':'Tell med knapp'})):
        p=await dispatch(b,s,event(s,'evolution_prepare',app_id=s.project_id,request_id=new_id('req'),
            operation=operation,expected_revision=revision,evolution_json=json.dumps(value)))
        await dispatch(b,s,event(s,'evolution_confirm',app_id=s.project_id,request_id=new_id('req'),
            proposal_id=p['proposal_id'],expected_revision=revision))
    return request,s


async def test_native_persisted_evolution_proposal_restores_binding_and_requires_resume(tmp_path):
    import time
    from test_evolution_engine import Provider
    provider=Provider();b=Backend(configured(tmp_path),provider)
    request,s=await native_manual_proposal(b)
    job_id=s.evolution_job_id;old_proposal=s.proposal_id;project_id=s.project_id
    b.persist(s)
    assert b.store.get('sessions',s.id)['evolution_job_id']==job_id
    # Preserve the last durable native snapshot as a crash would; no stop rewrite.
    b.sessions.pop(s.id)
    await b.close()
    replacement=Provider();b=Backend(configured(tmp_path),replacement)
    try:
        restored=await b.start(request.model_copy(update={'resume_session_id':s.id}),Peer(),'fire-01')
        assert restored.evolution_job_id==job_id and restored.proposal_id==old_proposal
        assert b.evolution.snapshot('fire-01',project_id)['job']['state']=='paused'
        with pytest.raises(ValueError):await dispatch(b,restored,event(restored,'build_confirm',proposal_id=old_proposal))
        assert not b.store.list('builds') and not replacement.calls
        job=b.store.get('evolution_jobs',job_id);mandate=b.store.get('evolution_mandates',job['mandate_id'])
        expires=mandate['expires_at'];mandate['expires_at']=time.time()-1
        b.store.put('evolution_mandates',mandate['id'],mandate)
        with pytest.raises(ValueError):await b.evolution.control('fire-01',project_id,'resume',1,job_id=job_id)
        mandate['expires_at']=expires;b.store.put('evolution_mandates',mandate['id'],mandate)
        await b.evolution.control('fire-01',project_id,'resume',1,job_id=job_id)
        pending=b.evolution.tasks.get(job_id)
        if pending:await asyncio.wait_for(asyncio.shield(pending),10)
        assert restored.proposal_id!=old_proposal and restored.evolution_job_id==job_id
        with pytest.raises(ValueError):await dispatch(b,restored,event(restored,'build_confirm',proposal_id=old_proposal))
        authorization=b.build_authorization(restored,restored.proposal_id)
        assert authorization['job_id']==job_id and authorization['mandate_id']==mandate['id']
        assert not b.store.list('builds') and not replacement.calls and not b.usage.records()
    finally:await b.close()


@pytest.mark.parametrize('transition',['app_select','new_text'])
async def test_explicit_foreground_goal_pauses_and_releases_evolution_session(tmp_path,transition):
    from test_evolution_engine import Provider
    provider=Provider();b=Backend(configured(tmp_path),provider)
    try:
        _,s=await native_manual_proposal(b)
        job_id=s.evolution_job_id;proposal=s.proposal_id;origin=s.project_id
        if transition=='app_select':
            await dispatch(b,s,event(s,'app_select',app_mode='new'))
            assert s.project_id!=origin
        else:
            await b.text(s,'Lag en sirkel')
        assert s.evolution_job_id is None
        assert b.store.get('sessions',s.id)['evolution_job_id'] is None
        assert b.store.get('evolution_jobs',job_id)['state']=='paused'
        mandate=b.store.get('evolution_mandates',b.store.get('evolution_jobs',job_id)['mandate_id'])
        assert mandate['state']=='paused'
        with pytest.raises(ValueError):b.build_authorization(s,proposal)
        if transition=='app_select':await b.text(s,'Lag en sirkel')
        assert b.build_authorization(s,s.proposal_id)=={'kind':'explicit_build_confirm','proposal_id':s.proposal_id}
        assert not provider.calls and not b.store.list('builds') and not b.usage.records()
    finally:await b.close()

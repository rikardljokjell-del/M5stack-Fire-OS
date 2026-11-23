import asyncio
import copy

import pytest
from fastapi.testclient import TestClient

from fire_backend.ai import MockProvider
from fire_backend.app import create_app
from fire_backend.generation_errors import GenerationResponseError
from fire_backend.models import State, DialogReply
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from test_build_resume import action, start
from test_device_protocol import configured, headers, ADMIN
from test_repair_target import session


class FailsOnce(MockProvider):
    def __init__(self):self.calls=0;self.entered=asyncio.Event();self.release=asyncio.Event()
    async def dialog(self,history,context,connection=None):
        return DialogReply(message='Jeg lager et RPG-spill.',clarification_needed=False,build_summary='Lag et RPG-spill')
    async def generate(self,*args):
        self.calls+=1
        if self.calls==1:
            self.entered.set();await self.release.wait()
            raise GenerationResponseError('ai_output_limit','AI-svaret nådde svargrensen. Planen er bevart.')
        return await super().generate(*args)


async def failed_job(b,p):
    s,peer=await session(b);await b.text(s,'Lag et RPG-spill')
    history=copy.deepcopy(s.history);build=await b.confirm_build(s,s.proposal_id);task=s.task
    await p.entered.wait();b.jobs.context(build['id'],'Bruk større tekst i spillet')
    p.release.set();await task
    return s,peer,b.store.get('builds',build['id']),history


async def test_device_failed_job_resumes_after_reboot_without_paid_call_and_needs_fresh_confirmation(tmp_path):
    p=FailsOnce();b=Backend(configured(tmp_path),p)
    try:
        old,peer,build,history=await failed_job(b,p)
        view=b.build_view(build)
        assert view['can_open'] and view['can_resume'] and view['error_code']=='ai_output_limit'
        assert view['message']=='AI-svaret ble avkuttet'
        assert any(e['type']=='error' and e['message']=='AI-svaret ble avkuttet' for e in peer.events)
        assert any(e['type']=='build_progress' and e.get('error_code')=='ai_output_limit' for e in peer.events)
        await b.stop(old)
        fresh,new_peer=await start(b)
        result=await dispatch(b,fresh,action(fresh,'build_resume',build_id=build['id']))
        assert result['can_retry'] and result['proposal_id'] and result['history_restored']
        assert fresh.state==State.awaiting_build_confirmation and fresh.history==history
        assert fresh.project_id==build['project_id'] and fresh.base_package_id is None
        assert 'større tekst' in fresh.summary and p.calls==1
        proposal=fresh.proposal_id
        await dispatch(b,fresh,action(fresh,'build_resume',build_id=build['id']))
        assert fresh.proposal_id==proposal and p.calls==1
        confirm=action(fresh,'build_confirm',proposal_id=proposal)
        await dispatch(b,fresh,confirm);task=fresh.task
        await dispatch(b,fresh,confirm)  # Exact event replay cannot start another job.
        await asyncio.wait_for(task,10)
        new=b.store.get('builds',fresh.build_id)
        assert new['id']==build['id'] and new['status']=='ready'
        assert new['run_history'][0]['status']=='failed' and new['resume_count']==1
        assert new['project_id']==build['project_id'] and p.calls==2
        assert not any(c['kind']=='run' for c in b.store.list('commands'))
    finally:await b.close()


async def test_failed_build_discovery_persists_across_backend_restart_and_is_owner_scoped(tmp_path):
    p=FailsOnce();b=Backend(configured(tmp_path),p)
    old,_,build,_=await failed_job(b,p)
    build['background']=True;b.store.put('builds',build['id'],build)
    await b.close();b=Backend(configured(tmp_path))
    try:
        s,peer=await start(b)
        assert any(e['type']=='build_job_status' and e['status']=='failed' and e['can_resume'] for e in peer.events)
        await dispatch(b,s,action(s,'build_jobs'))
        catalog=next(e for e in reversed(peer.events) if e['type']=='build_jobs')
        assert any(j['build_id']==build['id'] and j['can_open'] for j in catalog['jobs'])
        other,_=await start(b,device='fire-02')
        with pytest.raises(PermissionError):await dispatch(b,other,action(other,'build_resume',build_id=build['id']))
        result=await dispatch(b,s,action(s,'build_resume',build_id=build['id']))
        assert result['state']=='awaiting_build_confirmation'
    finally:await b.close()


def test_pc_can_resume_failed_new_app_without_package_admin_only_and_no_generation(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as c:
        b=c.app.state.backend;p=b.new_project('fire-01','device')
        job={'id':'build-rpg','project_id':p['id'],'owner_device_id':'fire-01','status':'failed','phase':'failed',
             'error':'OpenAI code response incomplete or refused','summary':'Lag et RPG-spill',
             'resume_context':{'history':[{'role':'user','content':'Lag et RPG-spill'}],'base_package_id':None}}
        b.store.put('builds',job['id'],job)
        b.store.put('usage','usage-old',{'id':'usage-old','build_id':job['id'],'operation':'generate','model':'gpt-6-luna',
             'output_tokens':8000,'reasoning_tokens':8000,'started_at':1,'status':'completed','estimated_usd':.0057,'usage_source':'provider'})
        endpoint='/desktop/jobs/build-rpg/resume'
        assert c.post(endpoint,headers=headers(),json={}).status_code==403
        response=c.post(endpoint,headers=headers(ADMIN),json={});assert response.status_code==200
        data=response.json()
        assert data['state']=='awaiting_build_confirmation' and data['project_id']==p['id']
        assert '8000' in data['last_error'] and data['history']==job['resume_context']['history']
        assert data['last_error_status']=='AI-svaret ble avkuttet'
        second=c.post(endpoint,headers=headers(ADMIN),json={}).json()
        assert second['session_id']==data['session_id'] and second['proposal_id']==data['proposal_id']
        row=c.get('/desktop/jobs',headers=headers(ADMIN)).json()['jobs'][0]
        assert row['can_resume'] and row['error_code']=='ai_output_limit' and 'ingen appkode' in row['error']
        assert len(b.store.list('projects'))==1 and len(b.store.list('builds'))==1
        assert not b.store.list('packages') and len(b.store.list('usage'))==2  # Old usage + metadata only.


async def test_resume_keeps_large_context_and_repair_base_without_oversized_device_message(tmp_path):
    import json
    from test_repair_target import saved_app
    b=Backend(configured(tmp_path))
    try:
        project,base=saved_app(b,'Spill');s,peer=await session(b)
        job={'id':'build-failed-repair','project_id':project['id'],'owner_device_id':s.device_id,'status':'failed',
             'phase':'failed','error':'AI-svaret nådde svargrensen.','summary':'Lag et spill',
             'repair_context':json.dumps({'package_id':base['id'],'message':'Appen krasjet'}),
             'resume_context':{'history':[],'base_package_id':base['id']}}
        b.store.put('builds',job['id'],job)
        notes=[{'text':'ø'*2000,'revision':n+1} for n in range(8)]
        b.store.put('job_context',job['id'],{'id':job['id'],'revision':8,'applied_revision':0,'notes':notes})
        await dispatch(b,s,action(s,'build_resume',build_id=job['id']))
        assert len(s.summary)>16000 and s.base_package_id==base['id']
        assert s.repair_context['package_id']==base['id'] and s.app_mode=='update'
        assert all(len(json.dumps(e,ensure_ascii=False).encode('utf-8'))<=8192 for e in peer.events)
        await dispatch(b,s,action(s,'app_select',app_mode='new'))
        assert s.resumed_from_build_id is None and s.project_id!=project['id']
    finally:await b.close()


async def test_old_failed_notice_cannot_replace_an_active_job_after_reconnect(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        s,peer=await session(b)
        for identifier,status in [('build-old','failed'),('build-current','building')]:
            b.store.put('builds',identifier,{'id':identifier,'project_id':s.project_id,'owner_device_id':s.device_id,
                'status':status,'phase':'failed' if status=='failed' else 'generating','summary':'Lag en app',
                'error':'AI-svaret nådde svargrensen.' if status=='failed' else '', 'background':True})
        peer.events.clear();await b.build_notices(s)
        notices=[e for e in peer.events if e['type']=='build_job_status']
        assert [e['build_id'] for e in notices]==['build-current']
    finally:await b.close()


async def test_concurrently_completed_resume_still_requires_matching_confirmation(tmp_path):
    from fire_backend.service import Conflict
    p=FailsOnce();b=Backend(configured(tmp_path),p)
    try:
        s,_,build,_=await failed_job(b,p)
        await b.restore_failed_build(s,build)
        completed={**build,'status':'ready'}
        b.store.put('builds',build['id'],completed)
        with pytest.raises(Conflict):await b.confirm_build(s,'proposal-wrong')
        s.stopped=True
        with pytest.raises(Conflict):await b.confirm_build(s,s.proposal_id)
        assert p.calls==1 and len(b.store.list('builds'))==1
    finally:await b.close()

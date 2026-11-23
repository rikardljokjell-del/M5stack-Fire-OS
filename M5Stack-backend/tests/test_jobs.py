import asyncio
import pytest
from fastapi.testclient import TestClient
from fire_backend.app import create_app
from fire_backend.service import Backend
from fire_backend.models import SessionStart
from test_device_protocol import configured,headers,ADMIN
from test_background_repairs import RepairProvider

async def start(b):
    s=await b.start(SessionStart());await b.text(s,'Lag en sirkel')
    build=await b.confirm_build(s,s.proposal_id)
    return s,build

async def test_live_context_is_applied_to_next_candidate_and_does_not_ship_stale_code(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,build=await start(b);await p.entered.wait()
        b.jobs.context(build['id'],'Gjør sirkelen blå og behold knappene.')
        view=b.jobs.snapshot()['jobs'][0]
        assert view['context_pending'] and view['can_add_context'] and view['phase']=='generating'
        p.release.set();await s.task
        assert len(p.calls)==2 and 'Gjør sirkelen blå' in p.calls[1][0]
        view=b.jobs.snapshot()['jobs'][0]
        assert view['status']=='ready' and not view['context_pending']
        assert view['context']['applied_attempt']==2
        assert 'Gjør sirkelen blå' in b.store.get('projects',s.project_id)['last_confirmed_summary']
        assert not b.store.list('commands')
    finally:await b.close()

async def test_no_extra_paid_attempt_after_context_arrives_at_last_allowed_attempt(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path,fire_max_corrections=0),p)
    try:
        s,build=await start(b);await p.entered.wait();b.jobs.context(build['id'],'Bruk større tekst')
        p.release.set();await s.task
        row=b.jobs.snapshot()['jobs'][0]
        assert row['status']=='failed' and row['context_pending']
        assert len(p.calls)==1 and not b.store.list('packages')
        assert 'rettingsgrensen' in row['error']
    finally:await b.close()

async def test_new_context_during_source_review_requires_regeneration(tmp_path):
    class Provider(RepairProvider):
        def __init__(self):super().__init__();self.review_entered=asyncio.Event();self.review_release=asyncio.Event();self.reviews=0
        async def review(self,*args):
            self.reviews+=1
            if self.reviews==1:self.review_entered.set();await self.review_release.wait()
            return await super().review(*args)
    p=Provider();b=Backend(configured(tmp_path),p)
    try:
        s,build=await start(b);await p.review_entered.wait()
        b.jobs.context(build['id'],'Legg til tydelig poengvisning')
        p.review_release.set();await s.task
        assert len(p.calls)==2 and p.reviews==2 and s.package_id
        assert 'poengvisning' in p.calls[1][0]
        assert not b.store.list('quality')
    finally:await b.close()

async def test_job_errors_and_cost_remain_visible_after_restart_and_cannot_be_steered(tmp_path):
    b=Backend(configured(tmp_path));project=b.new_project("fire-01","device")
    b.store.put('builds','build-failed',{'id':'build-failed','project_id':project['id'],'status':'failed','phase':'failed',
        'error':'OpenAI HTTP429; billing/quota limit','summary':'Lag en app','last_validation_error':'Kontrollfunn'})
    row=b.jobs.snapshot()['jobs'][0]
    assert row['error_status']=='Kontroller API-kontoen' and row['last_validation_error']=='Kontrollfunn'
    with pytest.raises(ValueError):b.jobs.context('build-failed','Mer kontekst')
    await b.close()
    b=Backend(configured(tmp_path))
    try:assert b.jobs.snapshot()['jobs'][0]['error']==row['error']
    finally:await b.close()

def test_job_api_is_admin_only_and_context_is_validated_and_redacted(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as c:
        b=c.app.state.backend;p=b.new_project("fire-01","device")
        b.store.put('builds','build-test',{'id':'build-test','project_id':p['id'],'status':'queued','phase':'queued','summary':'Test'})
        assert c.get('/desktop/jobs',headers=headers()).status_code==403
        assert c.post('/desktop/jobs/build-test/context',headers=headers(),json={'text':'test'}).status_code==403
        url='/desktop/jobs/build-test/context'
        for text in ['', 'x'*2001,None]:assert c.post(url,headers=headers(ADMIN),json={'text':text}).status_code==400
        assert c.post(url,headers=headers(ADMIN),json={'text':'Ønsker større tekst '+ADMIN}).status_code==200
        row=c.get('/desktop/jobs',headers=headers(ADMIN)).json()['jobs'][0]
        assert ADMIN not in str(row) and row['context_pending']
        b.store.put('builds','build-test',{'id':'build-test','project_id':p['id'],'status':'building','phase':'packaging'})
        assert c.post(url,headers=headers(ADMIN),json={'text':'Sen endring'}).status_code==400

async def test_cost_failure_does_not_claim_pending_context_was_used(tmp_path):
    from fire_backend.usage import UsageBudgetError
    class Provider(RepairProvider):
        async def generate(self,*args):raise UsageBudgetError()
    b=Backend(configured(tmp_path),Provider())
    try:
        s,build=await start(b)
        b.jobs.context(build['id'],'Bruk bedre kontrast')
        await s.task
        row=b.jobs.snapshot()['jobs'][0]
        assert row['context_pending'] and row['context']['applied_revision']==0
        assert row['error_status']=='Kostnadsgrensen er nådd'
    finally:await b.close()


def test_job_ui_shows_errors_and_context_without_losing_draft(tmp_path,monkeypatch):
    import tkinter as tk
    from fire_backend.desktop_ui import DesktopUI
    from fire_backend.desktop_config import DesktopStore
    from test_desktop_costs import MemoryVault
    monkeypatch.setattr('fire_backend.desktop_ui.threading.Thread.start',lambda _:None)
    monkeypatch.setattr('fire_backend.desktop_ui.lan_addresses',lambda:['127.0.0.1'])
    root=tk.Tk();root.withdraw()
    try:
        ui=DesktopUI(root,DesktopStore(tmp_path,MemoryVault()))
        ui.job_snapshot={'active_count':0,'jobs':[{'id':'build-one','name':'Prøve','status':'failed','message':'Kontroller API-kontoen',
          'progress':0,'error':'billing/quota limit','error_status':'Kontroller API-kontoen','context_pending':True,
          'context':{'notes':[{'text':'Større tekst'}]},'can_add_context':False,'can_resume':True,'build_id':'build-one'}]}
        ui.job_prompt.insert('1.0','Behold dette utkastet');ui.render_jobs()
        assert 'STOPPÅRSAK' in ui.job_detail.get('1.0','end') and 'Større tekst' in ui.job_detail.get('1.0','end')
        assert ui.job_prompt.get('1.0','end').strip()=='Behold dette utkastet'
        assert str(ui.job_send.cget('state'))=='disabled'
        assert str(ui.job_resume.cget('state'))=='normal'
        second={**ui.job_snapshot['jobs'][0],'id':'build-two','name':'Annen app'}
        ui.job_snapshot['jobs'].append(second);ui.render_jobs()
        ui.job_table.selection_set('build-two');ui.render_job_detail()
        assert not ui.job_prompt.get('1.0','end').strip()
        ui.job_table.selection_set('build-one');ui.render_job_detail()
        assert ui.job_prompt.get('1.0','end').strip()=='Behold dette utkastet'
        result={'session_id':'session-restored','desktop_device_id':'fire-01','resumed_from_build_id':'build-one'}
        monkeypatch.setattr(ui,'show',lambda _:None)
        monkeypatch.setattr(ui,'refresh_now',lambda:None)
        ui.choose_pc_session(result)
        assert ui.prompt.get('1.0','end').strip()=='Behold dette utkastet'
        assert 'sirkel som beveger seg' not in ui.prompt.get('1.0','end')

    finally:root.destroy()

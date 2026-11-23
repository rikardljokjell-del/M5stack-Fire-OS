import asyncio
import json

import pytest

from fire_backend.ai import MockProvider
from fire_backend.models import GeneratedApp,State
from fire_backend.service import Backend
from fire_backend.protocol import dispatch
from fire_backend.historical_costs import backfill
from test_device_protocol import configured
from test_repair_target import session
from test_build_resume import action,start
from test_usage import ledger
from test_historical_costs import artifact


class RepairAfterResume(MockProvider):
    def __init__(self):self.calls=[];self.wait=asyncio.Event();self.entered=asyncio.Event()
    async def generate(self,*args):
        self.calls.append(args)
        if len(self.calls)<=2:
            return GeneratedApp(name='Test',main_lua=f"function init() end function update(dt) error('fault {len(self.calls)}') end",required_services=[])
        self.entered.set();await self.wait.wait()
        return await super().generate(*args)


async def test_continue_same_job_appends_attempts_keeps_source_error_cost_and_clears_stale_ui(tmp_path):
    p=RepairAfterResume();b=Backend(configured(tmp_path,fire_max_corrections=1),p)
    try:
        s,peer=await session(b);await b.text(s,'Lag en sirkel')
        job=await b.confirm_build(s,s.proposal_id);await s.task
        failed=b.store.get('builds',job['id']);assert failed['attempts']==2 and failed['status']=='failed'
        prior=(b.store.path('builds',job['id'],'')/'attempt-2.lua').read_text(encoding='utf-8')
        await dispatch(b,s,action(s,'build_resume',build_id=job['id']))
        proposal=s.proposal_id
        resumed=await b.confirm_build(s,proposal)
        assert resumed['id']==job['id'] and s.last_error=='' and s.progress['phase']=='queued'
        assert b.build_entry(job['id'])['worker'].last_error==''
        await p.entered.wait()
        # Different event IDs with the same consumed proposal reattach, never enqueue.
        again=await b.confirm_build(s,proposal)
        assert again['id']==job['id'] and len(b.store.list('builds'))==1 and len(p.calls)==3
        assert p.calls[2][3]==prior and p.calls[2][2]==failed['last_validation_error']
        await dispatch(b,s,action(s,'build_background',build_id=job['id']))
        await b.stop(s)
        newer,new_peer=await start(b)
        assert any(e['type']=='build_job_status' and e['build_id']==job['id'] for e in new_peer.events)
        p.wait.set();task=b.build_entry(job['id'])['task'];await asyncio.wait_for(task,10)
        ready=b.store.get('builds',job['id'])
        assert ready['status']=='ready' and ready['attempts']==3 and ready['run_history'][0]['attempts']==2
        folder=b.store.path('builds',job['id'],'')
        assert all((folder/f'attempt-{n}.lua').is_file() for n in (1,2,3))
        assert (folder/'request-before-resume-1.json').is_file()
        assert any(e['type']=='build_ready_notice' and e['build_id']==job['id'] for e in new_peer.events)
    finally:p.wait.set();await b.close()


async def test_boot_discovers_foreground_build_and_foreground_completion_has_persistent_notice(tmp_path):
    from test_background_repairs import RepairProvider
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,peer=await session(b);await b.text(s,'Lag en sirkel')
        job=await b.confirm_build(s,s.proposal_id);task=s.task;await p.entered.wait()
        # Re-discovery must work even without a successful Background event.
        assert job['background'] is False
        peer.events.clear();await b.build_notices(s)
        assert any(e['type']=='build_job_status' and e['build_id']==job['id'] for e in peer.events)
        p.release.set();await asyncio.wait_for(task,10)
        assert any(e['type']=='build_ready_notice' for e in peer.events)
        peer.events.clear();await b.build_notices(s)
        assert any(e['type']=='build_ready_notice' for e in peer.events)
        await dispatch(b,s,action(s,'build_notice_ack',build_id=job['id'],notification_action='dismiss'))
        peer.events.clear();await b.build_notices(s)
        assert not any(e['type']=='build_ready_notice' for e in peer.events)
        assert b.store.get('packages',job['id'])
    finally:p.release.set();await b.close()


def test_job_cost_includes_legacy_and_new_continuation_without_erasing_pre_metering_cost(tmp_path):
    m=ledger(tmp_path,clock=lambda:100,fire_cost_limits_enabled=False)
    artifact(m);backfill(m.store,100)
    old=m.build_costs()['build-old']['estimated_usd']
    ticket=m.begin('generate','gpt-6-luna',10,10,build_id='build-old')
    actual=m.finish(ticket,{'input_tokens':10,'output_tokens':10})['estimated_usd']
    assert m.build_costs()['build-old']['estimated_usd']==pytest.approx(old+actual)
    assert m.project_costs()['app-old']['estimated_usd']==pytest.approx(old+actual)
    m.reset()
    assert m.build_costs()['build-old']['estimated_usd']==pytest.approx(old+actual)


async def test_job_list_exposes_historical_cost_even_without_a_successful_app(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        artifact(b.usage);backfill(b.store,b.usage.meta['tracking_started_at'])
        row=next(r for r in b.jobs.snapshot()['jobs'] if r['id']=='build-old')
        assert row['estimated_usd']>0
        assert row['cost_detail']['historical_estimate']['models']==['gpt-6.2-astra']
    finally:await b.close()

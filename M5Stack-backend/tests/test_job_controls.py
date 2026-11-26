import asyncio
import json
import time

import pytest
from pydantic import ValidationError

from fire_backend.audio import AudioManager
from fire_backend.models import DeviceEvent,GeneratedApp
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from fire_backend.storage import new_id
from test_background_repairs import RepairProvider,event,prepare
from test_device_protocol import configured
from test_repair_target import saved_app,session


async def running_build(b,provider):
    s,peer=await session(b)
    await b.text(s,'Lag en sirkel')
    build=await b.confirm_build(s,s.proposal_id)
    await asyncio.wait_for(provider.entered.wait(),3)
    return s,peer,build


async def test_pause_drains_generation_and_resume_requires_current_build_without_repaying_source(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,peer,build=await running_build(b,p);task=s.task
        with pytest.raises(ValueError):await dispatch(b,s,event(s,'job_control',build_id=build['id'],job_action='delete'))
        result=await dispatch(b,s,event(s,'job_control',build_id=build['id'],job_action='pause'))
        assert result['status']=='pause_requested' and not task.done()
        assert b.jobs.snapshot()['active_count']==1
        p.release.set();await asyncio.wait_for(task,15)
        stopped=b.store.get('builds',build['id'])
        assert stopped['error_code']=='build_paused' and stopped['status']=='failed'
        assert len(p.calls)==1 and not b.store.list('packages')
        meta=json.loads((b.store.path('builds',build['id'],'')/'candidate-1.json').read_text())
        assert meta['local_validated']
        resumed=await dispatch(b,s,event(s,'job_control',build_id=build['id'],job_action='resume'))
        assert resumed['proposal_id']==s.proposal_id and len(p.calls)==1
        with pytest.raises(ValueError):await dispatch(b,s,event(s,'build_confirm',proposal_id='proposal-stale'))
        await dispatch(b,s,event(s,'build_confirm',proposal_id=s.proposal_id));await s.task
        assert len(p.calls)==1 and b.store.get('builds',build['id'])['status']=='ready'
        assert b.store.get('builds',build['id'])['reused_candidate_from']==build['id']
        from fire_backend.app_icons import valid_icon
        package=b.store.get('packages',build['id'])
        assert valid_icon(package['manifest']['icon'])
    finally:await b.close()


async def test_context_voice_uses_existing_transcribe_without_dialog_or_new_build(tmp_path):
    from test_audio import wav_data
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    original=p.dialog;dialog_calls=[];transcribes=[]
    async def dialog(*args):dialog_calls.append(1);return await original(*args)
    async def transcribe(data):transcribes.append(data);return 'Behold knappene, bruk blå farge.'
    p.dialog=dialog;p.transcribe=transcribe
    try:
        s,peer,build=await running_build(b,p)
        await dispatch(b,s,event(s,'job_control',build_id=build['id'],job_action='context'))
        assert s.job_context_target['build_id']==build['id']
        b.audio=AudioManager(b);s.turn_id=new_id('turn')
        item={'id':new_id('audio'),'turn_id':s.turn_id,'session_id':s.id,'status':'processing','expires_at':time.time()+60}
        path=b.store.path('audio',item['id'],'.wav');path.write_bytes(wav_data())
        await b.audio.transcribe(s,item,path)
        assert item['status']=='completed' and s.job_context_target is None
        assert len(dialog_calls)==len(transcribes)==1 and len(p.calls)==1
        assert b.store.get('job_context',build['id'])['notes'][0]['text']=='Behold knappene, bruk blå farge.'
        assert len(b.store.list('builds'))==1
    finally:await b.close()


async def test_cancel_retains_unknown_usage_reservation_without_auto_retry(tmp_path):
    from fire_backend.metering import usage_scope
    class Metered(RepairProvider):
        async def generate(self,*args):
            scope=usage_scope.get()
            item=b.usage.begin('generate','gpt-6.2-sol',10000,2000,build_id=scope['build_id'],project_id=scope['project_id'])
            try:return await super().generate(*args)
            except asyncio.CancelledError:
                b.usage.finish(item,None,status='cancelled')
                raise
    p=Metered();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,_,build=await running_build(b,p)
        await dispatch(b,s,event(s,'job_control',build_id=build['id'],job_action='context'))
        await dispatch(b,s,event(s,'job_control',build_id=build['id'],job_action='cancel'))
        assert s.job_context_target is None
        records=b.usage.records()
        assert len(p.calls)==len(records)==1 and records[0]['status']=='cancelled'
        assert records[0]['usage_source']=='reservation' and records[0]['estimated_usd']>0
        price=b.usage.build_costs()[build['id']]
        assert price['unknown_usage_requests']==1 and price['provider_calculated_usd']==0
        assert price['budget_reserved_usd']>0 and not b.store.list('packages')
    finally:await b.close()


async def test_cancel_evolution_child_stops_parent_revokes_mandate_and_keeps_unknown_usage(tmp_path):
    from fire_backend.metering import usage_scope
    from fire_backend.evolution_models import EvolutionConfig
    from fire_backend.models import SessionStart
    from test_device_protocol import CAPS
    from test_repair_target import Peer
    class Metered(RepairProvider):
        async def generate(self,*args):
            scope=usage_scope.get()
            identifier=b.usage.begin('generate',b.settings.openai_code_model,1000,1000,**scope)
            try:return await super().generate(*args)
            except asyncio.CancelledError:
                b.usage.finish(identifier,None,status='cancelled')
                raise
    p=Metered();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,peer=await session(b)
        config=EvolutionConfig(enabled=True,flags={'generate':True},autonomy='auto_build').model_dump()
        proposal=await b.evolution.prepare(s.device_id,s.project_id,'configure',config,0)
        await b.evolution.confirm(s.device_id,s.project_id,proposal['id'],0)
        proposal=await b.evolution.prepare(s.device_id,s.project_id,'generate',{'goal':'Tell med knapp'},1)
        result=await b.evolution.confirm(s.device_id,s.project_id,proposal['id'],1)
        await asyncio.wait_for(p.entered.wait(),3)
        job=b.store.get('evolution_jobs',result['job_id']);build_id=job['build_ids'][0]
        other=await b.start(SessionStart(device_id='fire-02',target='device',protocol_version='0.2',boot_id='boot-other',capabilities=CAPS),Peer(),'fire-02')
        with pytest.raises(PermissionError):
            await dispatch(b,other,event(other,'job_control',build_id=build_id,job_action='cancel'))
        assert b.store.get('evolution_mandates',result['mandate_id'])['state']=='active'
        response=await dispatch(b,s,event(s,'job_control',build_id=build_id,job_action='cancel'))
        assert response['type']=='build_cancelled' and response['build_id']==build_id
        assert b.store.get('evolution_jobs',job['id'])['state']=='stopped'
        assert b.store.get('evolution_mandates',result['mandate_id'])['state']=='revoked'
        assert not b.evolution.active_project(s.project_id) and not b.evolution.in_flight(job['id'])
        rows=b.usage.records()
        assert len(rows)==len(p.calls)==1 and rows[0]['status']=='cancelled'
        assert rows[0]['usage_source']=='reservation' and rows[0]['estimated_usd']>0
        assert b.evolution.cost(job['id'])['unknown_usage_requests']==1
        assert not b.store.list('packages') and not b.store.list('commands')
        with pytest.raises(ValueError):b.evolution.validate_mandate(result['mandate_id'])
    finally:await b.close()


async def test_queued_repair_pause_resume_and_single_child_row(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        project,old=saved_app(b,'Måler',slug='maaler');s,peer=await session(b)
        await b.build_lock.acquire()
        repair=await prepare(b,s,old)
        await dispatch(b,s,event(s,'build_confirm',repair_id=repair['repair_id'],proposal_id=repair['proposal_id']))
        task=b.repairs.tasks[repair['repair_id']]
        await dispatch(b,s,event(s,'job_control',repair_id=repair['repair_id'],job_action='pause'))
        await asyncio.wait_for(task,3)
        assert b.store.get('repairs',repair['repair_id'])['status']=='paused' and not p.calls
        assert b.repairs.public(b.store.get('repairs',repair['repair_id']))['message']=='På pause'
        b.build_lock.release()
        await dispatch(b,s,event(s,'job_control',repair_id=repair['repair_id'],job_action='resume'))
        await asyncio.wait_for(p.entered.wait(),3)
        await dispatch(b,s,event(s,'build_jobs'))
        page=next(e for e in reversed(peer.events) if e['type']=='build_jobs')
        rows=[r for r in page['jobs'] if r.get('repair_id')==repair['repair_id']]
        assert len(rows)==1 and rows[0]['build_id'] and rows[0]['name']==project['name']
        assert [r['created_at'] for r in page['jobs']]==sorted((r['created_at'] for r in page['jobs']),reverse=True)
        await dispatch(b,s,event(s,'job_control',repair_id=repair['repair_id'],job_action='cancel'))
        assert b.store.get('repairs',repair['repair_id'])['status']=='cancelled' and len(p.calls)==1
    finally:
        if b.build_lock.locked():b.build_lock.release()
        await b.close()


async def test_resume_catalog_deduplicates_repairs_is_newest_first_and_delete_preserves_records(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        project,old=saved_app(b,'Måler',slug='maaler');s,peer=await session(b)
        repair=await prepare(b,s,old)
        await dispatch(b,s,event(s,'build_jobs'))
        page=next(e for e in reversed(peer.events) if e['type']=='build_jobs')
        assert page['jobs'][0]['repair_id']==repair['repair_id'] and page['jobs'][0]['job_kind']=='repair'
        await dispatch(b,s,event(s,'job_control',repair_id=repair['repair_id'],job_action='cancel'))
        before=len(b.store.list('builds'));package_bytes=b.store.path('packages',old['id'],'.zip').read_bytes()
        await dispatch(b,s,event(s,'job_control',repair_id=repair['repair_id'],job_action='delete'))
        await dispatch(b,s,event(s,'build_jobs'))
        page=next(e for e in reversed(peer.events) if e['type']=='build_jobs')
        assert all(row.get('repair_id')!=repair['repair_id'] for row in page['jobs'])
        assert len(b.store.list('builds'))==before and b.store.get('repairs',repair['repair_id'])['status']=='cancelled'
        assert b.store.path('packages',old['id'],'.zip').read_bytes()==package_bytes
        assert not b.usage.records()
    finally:await b.close()


async def test_job_context_and_control_reject_another_device(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        project,pkg=saved_app(b,'Klokke',owner='fire-02',slug='clock');s,_=await session(b)
        with pytest.raises(PermissionError):
            await dispatch(b,s,event(s,'job_control',build_id=pkg['build_id'],job_action='context',text='Endre'))
        assert not b.store.list('job_context')
    finally:await b.close()


@pytest.mark.parametrize('values',[{}, {'build_id':'build-one','repair_id':'repair-one'},
    {'build_id':'build-one','job_action':'pause','text':'ikke kontekst'},
    {'build_id':'build-one','job_action':'context','text':'æ'*1001}])
def test_job_control_envelope_rejects_ambiguous_or_unbounded_context(values):
    with pytest.raises(ValidationError):
        DeviceEvent(event='job_control',device_id='fire-01',protocol_version='0.2',session_id='session-one',
                    event_id='event-one',boot_id='boot-one',**values)


async def test_generated_icon_schema_is_curated_and_legacy_manifest_omits_none(tmp_path):
    from fire_backend.app_icons import ALLOWED_ICONS
    from fire_backend.models import Manifest
    enums=GeneratedApp.model_json_schema()['properties']['icon']['anyOf']
    assert next(x for x in enums if x['type']=='string')['enum']==list(ALLOWED_ICONS)
    b=Backend(configured(tmp_path))
    try:
        project,pkg=saved_app(b,'Klokke',slug='clock')
        assert 'icon' not in pkg['manifest']
        assert 'icon' not in Manifest.model_validate(pkg['manifest']).model_dump()
        with pytest.raises(ValidationError):GeneratedApp(name='Clock',main_lua='x',required_services=[],icon='invented')
    finally:await b.close()

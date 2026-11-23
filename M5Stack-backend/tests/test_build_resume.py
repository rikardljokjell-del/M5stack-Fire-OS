import asyncio
import copy

import pytest

from fire_backend.models import DeviceEvent,SessionStart,State
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from fire_backend.storage import new_id
from test_device_protocol import configured,CAPS
from test_repair_target import session,Peer
from test_background_repairs import RepairProvider


def action(s,name,**fields):
    return DeviceEvent(event=name,device_id=s.device_id,protocol_version='0.2',event_id=new_id('evt'),
                       session_id=s.id,boot_id=s.boot_id,**fields)


async def start(b,device='fire-01',boot='boot-next'):
    peer=Peer()
    s=await b.start(SessionStart(device_id=device,protocol_version='0.2',target='device',boot_id=boot,capabilities=CAPS),peer,device)
    return s,peer


async def test_build_survives_disconnect_reboot_and_restores_exact_project_and_dialog(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,old_peer=await session(b);await b.text(s,'Lag en sirkel')
        project=s.project_id;history=copy.deepcopy(s.history);summary=s.summary
        build=await b.confirm_build(s,s.proposal_id);task=s.task;await p.entered.wait()
        await dispatch(b,s,action(s,'build_background',build_id=build['id']))
        assert s.state==State.idle and not task.done()
        await b.detach(s,old_peer);await b.stop(s)
        newer,peer=await start(b)
        p.release.set();await asyncio.wait_for(task,10)
        notices=[m for m in peer.events if m['type']=='build_ready_notice']
        assert len(notices)==1 and notices[0]['build_id']==build['id']
        assert notices[0]['message']=='Appen er klar'
        assert not b.store.list('commands')
        open_notice=action(newer,'build_notice_ack',build_id=build['id'],notification_action='open')
        await dispatch(b,newer,open_notice)
        assert newer.project_id==project and newer.base_package_id==build['id']
        assert newer.history==history and newer.summary==summary
        assert newer.package_id==build['id'] and newer.state==State.awaiting_install
        assert any(m['type']=='install_request' and m['package_id']==build['id'] for m in peer.events)
        assert not any(c['kind']=='run' for c in b.store.list('commands'))
        assert len(p.calls)==1  # Reopening does not regenerate.
        await dispatch(b,newer,open_notice)
        before=len([m for m in peer.events if m['type']=='build_ready_notice'])
        await b.build_notices(newer)
        assert len([m for m in peer.events if m['type']=='build_ready_notice'])==before
    finally:await b.close()


async def test_cancel_background_build_stops_only_selected_job_and_frees_builder(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,peer=await session(b);await b.text(s,'Lag en sirkel')
        first=await b.confirm_build(s,s.proposal_id);task=s.task;await p.entered.wait()
        await dispatch(b,s,action(s,'build_background',build_id=first['id']))
        assert any(m['type']=='build_backgrounded' for m in peer.events)
        await b.text(s,'Lag en ny sirkel');second=await b.confirm_build(s,s.proposal_id);next_task=s.task
        await dispatch(b,s,action(s,'build_cancel',build_id=first['id']))
        assert task.done() and b.store.get('builds',first['id'])['status']=='failed'
        assert not b.store.path('packages',first['id']).exists()
        p.release.set();await asyncio.wait_for(next_task,10)
        assert b.store.get('builds',second['id'])['status']=='ready'
        assert not b.build_lock.locked()
        # Repeating cancel cannot remove a completed immutable package.
        answer=await dispatch(b,s,action(s,'build_cancel',build_id=second['id']))
        assert answer['status']=='ready' and answer['message']=='Appen er klar'
        assert b.store.get('packages',second['id'])
    finally:await b.close()


async def test_cancel_queued_build_never_calls_provider_or_leaks_queue(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,_=await session(b);await b.text(s,'Lag en sirkel')
        first=await b.confirm_build(s,s.proposal_id);first_task=s.task;await p.entered.wait()
        b.detach_device_build(s);await b.text(s,'Lag en sirkel')
        queued=await b.confirm_build(s,s.proposal_id)
        await dispatch(b,s,action(s,'build_cancel',build_id=queued['id']))
        assert queued['id'] not in b.device_builds and len(p.calls)==1
        assert b.store.get('builds',queued['id'])['status']=='failed'
        p.release.set();await asyncio.wait_for(first_task,10)
        assert b.store.get('builds',first['id'])['status']=='ready' and not b.build_lock.locked()
    finally:await b.close()


async def test_active_repair_can_resume_then_leave_without_cancelling_it(tmp_path):
    from test_repair_target import saved_app
    from test_background_repairs import prepare,event,finished
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        _,old=saved_app(b,'Vater');s,peer=await session(b)
        job=await prepare(b,s,old)
        await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
        await p.entered.wait();job=b.store.get('repairs',job['repair_id']);build_id=job['build_id']
        await dispatch(b,s,action(s,'build_resume',build_id=build_id))
        assert s.state==State.building and s.project_id==old['project_id']
        await b.stop(s);p.release.set()
        done=await finished(b,job['id'])
        assert done['status']=='ready' and b.store.get('packages',done['package_id'])
    finally:await b.close()


async def test_backend_app_deleted_on_device_remains_selectable_without_installing(tmp_path):
    from test_repair_target import saved_app
    b=Backend(configured(tmp_path))
    try:
        project,old=saved_app(b,'Verktøy');s,peer=await session(b)
        await b.absent_app(s,old['manifest']['id'],'deleted')
        await dispatch(b,s,action(s,'app_list'))
        catalog=next(m for m in reversed(peer.events) if m['type']=='app_catalog')
        assert any(a['project_id']==project['id'] for a in catalog['apps'])
        await dispatch(b,s,action(s,'app_select',app_mode='update',project_id=project['id'],base_package_id=old['id']))
        assert s.project_id==project['id'] and s.base_package_id==old['id'] and s.install_permitted
        assert not b.store.list('commands')
    finally:await b.close()


async def test_pending_notice_survives_backend_restart_and_dismiss_does_not_delete_app(tmp_path):
    p=RepairProvider();b=Backend(configured(tmp_path),p)
    s,_=await session(b);await b.text(s,'Lag en sirkel')
    build=await b.confirm_build(s,s.proposal_id);task=s.task;b.detach_device_build(s)
    await asyncio.wait_for(task,10);project=build['project_id'];await b.close()
    b2=Backend(configured(tmp_path))
    try:
        s2,peer=await start(b2)
        assert any(m['type']=='build_ready_notice' and m['build_id']==build['id'] for m in peer.events)
        await dispatch(b2,s2,action(s2,'build_notice_ack',build_id=build['id'],notification_action='dismiss'))
        assert b2.store.get('packages',build['id'])
        assert b2.store.get('projects',project)['latest_package']==build['id']
        peer.events.clear();await b2.build_notices(s2)
        assert not peer.events
        await dispatch(b2,s2,action(s2,'build_resume',build_id=build['id']))
        assert s2.project_id==project and s2.base_package_id==build['id']
    finally:await b2.close()


async def test_resume_running_build_on_new_boot_uses_new_session_for_install(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        s,peer=await session(b);await b.text(s,'Lag en sirkel')
        build=await b.confirm_build(s,s.proposal_id);task=s.task;await p.entered.wait()
        await b.detach(s,peer);await b.stop(s)
        s2,peer2=await start(b)
        await dispatch(b,s2,action(s2,'build_jobs'))
        assert any(m['type']=='build_jobs' and m['jobs'][0]['build_id']==build['id'] for m in peer2.events)
        await dispatch(b,s2,action(s2,'build_resume',build_id=build['id']))
        assert s2.state==State.building
        p.release.set();await asyncio.wait_for(task,10)
        install=next(m for m in peer2.events if m['type']=='install_request')
        assert install['boot_id']==s2.boot_id and install['session_id']==s2.id
        assert not any(c['kind']=='run' for c in b.store.list('commands'))
    finally:await b.close()


async def test_another_device_cannot_open_or_dismiss_build_notice(tmp_path):
    b=Backend(configured(tmp_path),RepairProvider())
    try:
        s,_=await session(b);await b.text(s,'Lag en sirkel')
        build=await b.confirm_build(s,s.proposal_id);task=s.task;b.detach_device_build(s);await task
        other,peer=await start(b,device='fire-02')
        for name,fields in [('build_resume',{}),('build_notice_ack',{'notification_action':'dismiss'})]:
            with pytest.raises(PermissionError):await dispatch(b,other,action(other,name,build_id=build['id'],**fields))
        await dispatch(b,other,action(other,'build_jobs'))
        assert peer.events[-2]['type']=='build_jobs' and peer.events[-2]['jobs']==[]
    finally:await b.close()

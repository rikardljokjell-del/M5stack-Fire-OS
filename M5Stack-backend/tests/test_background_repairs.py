import asyncio
import copy
import time

import pytest
from pydantic import ValidationError

from fire_backend.ai import MockProvider
from fire_backend.models import DeviceEvent,GeneratedApp
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from fire_backend.storage import new_id
from test_device_protocol import configured
from test_repair_target import saved_app,session
from test_device_app_manager import version


class RepairProvider(MockProvider):
    def __init__(self):self.calls=[];self.entered=asyncio.Event();self.release=asyncio.Event();self.release.set()
    async def generate(self,summary,context,error=None,previous=None):
        self.calls.append((summary,context,previous));self.entered.set();await self.release.wait()
        return GeneratedApp(name='Reparert app',main_lua='function init() end function update(dt) fire.display.text(0,0,"Reparert",65535) end',required_services=['display'])


def event(s,name,**values):
    return DeviceEvent(device_id=s.device_id,event=name,protocol_version='0.2',session_id=s.id,
                       boot_id=s.boot_id,event_id=new_id('evt'),**values)


async def prepare(b,s,package,**values):
    return await dispatch(b,s,event(s,'app_repair_prepare',app_id=package['manifest']['id'],**values))


async def finished(b,repair_id):
    task=b.repairs.tasks.get(repair_id)
    if task:await asyncio.wait_for(asyncio.shield(task),10)
    return b.store.get('repairs',repair_id)


async def test_fix_without_logs_uses_saved_source_and_finishes_after_device_page_closes(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        project,old=saved_app(b,'Vater',slug='vater');s,peer=await session(b)
        original=(s.project_id,s.state,list(s.history))
        job=await prepare(b,s,old)  # App is known; log/version are optional.
        assert job['status']=='awaiting_confirmation' and not p.calls
        confirm=event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id'])
        await dispatch(b,s,confirm);await p.entered.wait()
        assert (s.project_id,s.state,s.history)==original
        assert not b.backend_delete_check(b.store.get('projects',project['id']))[0]
        await b.stop(s)  # Closing the originating page/session must not cancel it.
        p.release.set();done=await finished(b,job['repair_id'])
        assert done['status']=='ready' and done['version']=='0.1.2'
        assert len(p.calls)==1 and 'Ikke be brukeren' in p.calls[0][0]
        assert 'function init()' in p.calls[0][2]
        assert b.store.get('projects',project['id'])['latest_package']==done['package_id']
        assert not b.store.list('commands')
        assert not b.store.get('projects',project['id']).get('current')
        s2,peer2=await session(b)
        status=await dispatch(b,s2,event(s2,'app_repair_status',repair_id=job['repair_id']))
        assert status['package_id']==done['package_id']
        assert any(e['type']=='app_repair_status' and e['status']=='ready' for e in peer2.events)
        package=b.store.get('packages',done['package_id']);package['quality']={'blocked':True};b.store.put('packages',package['id'],package)
        blocked=await dispatch(b,s2,event(s2,'app_repair_status',repair_id=job['repair_id']))
        assert blocked['status']=='unavailable'
    finally:await b.close()


async def test_checksum_corrects_stale_package_mapping_and_latest_is_base(tmp_path):
    p=RepairProvider();b=Backend(configured(tmp_path),p)
    try:
        project,old=saved_app(b,'Vater',slug='vater');new=version(b,old,2)
        # Supply a different immutable source for the new version.
        from fire_backend.builds import sha256,write_archive
        code=b'function init() end function update(dt) fire.display.text(0,0,"Ny",65535) end'
        new['manifest']['checksum']=sha256(code);path=b.store.path('packages',new['id'],'.zip')
        write_archive(path,new['manifest'],code);new['archive_sha256']=sha256(path.read_bytes());b.store.put('packages',new['id'],new)
        s,_=await session(b)
        job=await prepare(b,s,old,package_id=old['id'],sha256=new['manifest']['checksum'])
        assert job['failed_package_id']==new['id'] and job['base_version']=='0.1.2'
        assert 'reported_package_mapping_mismatch' in job['identity_warnings']
        await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
        done=await finished(b,job['repair_id']);assert done['version']=='0.1.3'
        assert p.calls[0][2]==code.decode()
    finally:await b.close()


async def test_repeated_clicks_and_replayed_confirmation_create_only_one_build(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    try:
        _,old=saved_app(b,'Vater',slug='vater');s,_=await session(b)
        job=await prepare(b,s,old,package_id=old['id'])
        assert (await prepare(b,s,old,package_id=old['id']))['repair_id']==job['repair_id']
        confirm=event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id'])
        await dispatch(b,s,confirm);await dispatch(b,s,confirm)
        await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
        await p.entered.wait();assert len(p.calls)==1
        p.release.set();await finished(b,job['repair_id'])
        assert (await prepare(b,s,old,package_id=old['id']))['status']=='ready'
    finally:await b.close()


async def test_missing_app_wrong_owner_checksum_and_expired_proposal_are_rejected(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        _,old=saved_app(b,'Vater',slug='vater');_,other=saved_app(b,'Annen',owner='fire-02',slug='other')
        s,_=await session(b)
        with pytest.raises(ValidationError):event(s,'app_repair_prepare')
        with pytest.raises((ValueError,PermissionError)):await prepare(b,s,other)
        with pytest.raises(PermissionError):await prepare(b,s,old,package_id=other['id'])
        with pytest.raises(ValueError,match='source_identity_mismatch'):await prepare(b,s,old,sha256='0'*64)
        job=await prepare(b,s,old);saved=b.store.get('repairs',job['repair_id']);saved['expires_at']=time.time()-1;b.repairs.save(saved)
        with pytest.raises(ValueError,match='utløpt'):
            await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
        assert len(b.store.list('builds'))==2 and not b.repairs.tasks
    finally:await b.close()


async def test_misattributed_diagnostic_is_retained_without_poisoning_wrong_source(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        _,old=saved_app(b,'Vater',slug='vater');s,_=await session(b)
        result=await dispatch(b,s,event(s,'app_diagnostic',app_id='vater',package_id=old['id'],error_code='runtime_error',
            message='Lua update: main.lua:105: app callback budget exceeded',diagnostics={'source_bytes':999,'callback_us':135053}))
        assert result['status']=='identity_conflict'
        assert not b.store.get('packages',old['id']).get('quality')
        assert not b.store.list('quality') and not b.store.list('feedback')
        assert len(b.store.list('diagnostics'))==1
    finally:await b.close()


async def test_backend_shutdown_preserves_interrupted_job_and_never_replays_paid_work(tmp_path):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    _,old=saved_app(b,'Vater',slug='vater');s,_=await session(b)
    job=await prepare(b,s,old);await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
    await p.entered.wait();await b.close()
    assert b.store.get('repairs',job['repair_id'])['status']=='interrupted'
    b2=Backend(configured(tmp_path),p)
    try:
        assert b2.store.get('repairs',job['repair_id'])['status']=='interrupted'
        assert len(p.calls)==1 and not b2.repairs.tasks
    finally:await b2.close()


def test_websocket_fix_progress_download_and_explicit_run_use_new_package(tmp_path):
    from fastapi.testclient import TestClient
    from fire_backend.app import create_app
    from test_device_protocol import Device,headers
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect('/ws/device',headers=headers()) as socket:
            d=Device(socket);d.start();offer,_=d.build();d.install(offer)
            b=client.app.state.backend;old=b.store.get('packages',offer['package_id'])
            sent=d.send('app_repair_prepare',app_id=old['manifest']['id'],package_id=old['id'],
                        app_version=old['manifest']['version'],sha256=old['manifest']['checksum'],message='App error')
            job=d.until('app_repair_status');d.ack(sent)
            assert job['status']=='awaiting_confirmation'
            sent=d.send('build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id'])
            d.ack(sent)
            ready=d.until('app_repair_status',lambda e:e['status']=='ready')
            assert ready['package_id']!=old['id'] and ready['version']=='0.1.2'
            assert not any(c['kind']=='run' for c in b.store.list('commands'))
            sent=d.send('app_download',package_id=ready['package_id'])
            install=d.until('install_request');d.ack(sent)
            assert install['package_id']==ready['package_id'];d.install(install)
            run,_=d.run(ready['package_id']);d.healthy(run)
            assert b.store.get('devices','fire-01')['running_package_id']==ready['package_id']


async def test_failed_repair_retains_error_and_releases_global_builder(tmp_path):
    class Bad(RepairProvider):
        async def generate(self,*args):
            return GeneratedApp(name='Vater',required_services=['display'],main_lua='function init() end function update(dt) while true do end end')
    b=Backend(configured(tmp_path),Bad())
    try:
        _,old=saved_app(b,'Vater',slug='vater');s,_=await session(b)
        job=await prepare(b,s,old)
        await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
        done=await finished(b,job['repair_id'])
        assert done['status']=='failed' and done['message'] and not done.get('package_id')
        assert not b.build_lock.locked() and not b.store.list('commands')
        assert len(b.store.list('packages'))==1  # Only the original source.
    finally:await b.close()

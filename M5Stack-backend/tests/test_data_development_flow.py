import asyncio
import hashlib
import json
import pytest

from fire_backend.api_registry import preview_capabilities, REGISTRY
from fire_backend.models import Capabilities, DeviceEvent, SessionStart, State
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from fire_backend.storage import new_id
from test_data_engine import Socket
from test_device_protocol import configured


def action(s, name, **fields):
    return DeviceEvent(event=name,device_id=s.device_id,protocol_version='0.2',event_id=new_id('event'),
        session_id=s.id,boot_id=s.boot_id,**fields)


async def legacy_running(tmp_path):
    backend=Backend(configured(tmp_path))
    pc=await backend.desktop_conversation('fire-01',hardware_preview=True)
    caps=preview_capabilities()
    for key in ('app_sdk','runtime_ai','data_engine'):caps.pop(key)
    caps['services']=list(REGISTRY['services'])
    pc.capabilities=caps
    await backend.text(pc,'Lag en sirkel')
    await backend.confirm_build(pc,pc.proposal_id);await pc.task
    built=backend.store.get('builds',pc.build_id)
    assert built['status']=='ready',built.get('error')
    package=backend.store.get('packages',built['package_id'])
    assert package['manifest']['api_version']=='fire-lua-0.2' and 'data_engine' not in package['manifest']
    peer=Socket()
    session=await backend.start(SessionStart(device_id='fire-01',protocol_version='0.2',target='device',
        boot_id='boot-develop',project_id=pc.project_id,base_package_id=package['id'],
        capabilities=Capabilities(**preview_capabilities())),peer,'fire-01')
    session.package_id=package['id']
    await backend.offer_install(session,package)
    offer=next(e for e in reversed(peer.events) if e['type']=='install_request')
    await dispatch(backend,session,action(session,'device_install_result',package_id=package['id'],
        install_id=offer['install_id'],archive_sha256=package['archive_sha256'],status='ok'))
    run=await backend.confirm_run(session,package['id'])
    await dispatch(backend,session,action(session,'app_started',package_id=package['id'],run_id=run['run_id'],
        source_sha256=package['manifest']['checksum']))
    return backend,session,peer,package,run


@pytest.mark.parametrize('mode',['update','fork'])
async def test_legacy_os_improve_creates_normal_proposal_and_tested_update_without_granting_data(tmp_path,mode):
    backend,s,peer,package,run=await legacy_running(tmp_path)
    try:
        project=s.project_id;old_zip=backend.store.path('packages',package['id'],'.zip').read_bytes()
        request=action(s,'app_develop_request',request_id=new_id('data'),app_id=package['manifest']['id'],
            package_id=package['id'],source_sha256=package['manifest']['checksum'],run_id=run['run_id'],mode=mode)
        await dispatch(backend,s,request)
        await backend.data_engine.tasks[request.request_id]['task']
        context=next(e['context_id'] for e in peer.events if e['type']=='app_develop_ready')
        # The explicit normal user exit occurs AFTER context has been prepared.
        await dispatch(backend,s,action(s,'app_stopped',package_id=package['id'],run_id=run['run_id'],reason='user_exit'))
        before=len(backend.store.list('builds'))
        reopened=await backend.start(SessionStart(device_id=s.device_id,protocol_version='0.2',target='device',
            boot_id=s.boot_id,capabilities=Capabilities(**preview_capabilities()),development_context_id=context),peer,s.device_id)
        if mode=='update':assert reopened.project_id==project and reopened.base_package_id==package['id']
        else:
            assert reopened.project_id!=project and reopened.base_package_id is None
            assert backend.store.get('projects',reopened.project_id)['parent_context_grant']['context_id']==context
        assert reopened.state==State.awaiting_build_confirmation and reopened.proposal_id
        assert len(backend.store.list('builds'))==before
        assert not backend.store.get('packages',package['id'])['manifest'].get('data_engine')
        proposal=reopened.proposal_id
        await backend.confirm_build(reopened,proposal);await reopened.task
        candidate=backend.store.get('builds',reopened.build_id)
        assert candidate['status']=='ready',candidate.get('error')
        new_package=backend.store.get('packages',candidate['package_id'])
        if mode=='update':
            assert new_package['project_id']==project and new_package['manifest']['id']==package['manifest']['id']
            assert new_package['manifest']['version']!=package['manifest']['version']
        else:
            assert new_package['project_id']!=project and new_package['manifest']['id']!=package['manifest']['id']
        assert candidate['resume_context']['development_context_id']==context
        assert backend.store.path('packages',package['id'],'.zip').read_bytes()==old_zip
        assert not any(c['package_id']==new_package['id'] and c['kind']=='run' for c in backend.store.list('commands'))
    finally:await backend.close()

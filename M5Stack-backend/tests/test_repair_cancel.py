import pytest

from fire_backend.models import DeviceEvent
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from test_device_protocol import configured
from test_background_repairs import RepairProvider,prepare,event,finished
from test_repair_target import saved_app,session
from test_build_resume import start


@pytest.mark.parametrize('phase',['prepared','queued','building','ready'])
async def test_scoped_idempotent_repair_cancel_at_each_phase_preserves_ready_package(tmp_path,phase):
    p=RepairProvider();p.release.clear();b=Backend(configured(tmp_path),p)
    held=False
    try:
        _,base=saved_app(b,'Spill');s,_=await session(b)
        job=await prepare(b,s,base)
        if phase=='queued':await b.build_lock.acquire();held=True
        if phase!='prepared':
            await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
        if phase in {'building','ready'}:await p.entered.wait()
        if phase=='ready':p.release.set();await finished(b,job['repair_id'])
        other,_=await start(b,device='fire-02')
        with pytest.raises(PermissionError):
            await dispatch(b,other,event(other,'app_repair_cancel',repair_id=job['repair_id']))
        result=await dispatch(b,s,event(s,'app_repair_cancel',repair_id=job['repair_id']))
        assert result['status']==('ready' if phase=='ready' else 'cancelled')
        assert result['message']==('Ny versjon klar' if phase=='ready' else 'Byggingen ble avbrutt')
        again=await dispatch(b,s,event(s,'app_repair_cancel',repair_id=job['repair_id']))
        assert again['status']==result['status']
        assert job['repair_id'] not in b.repairs.tasks
        assert len(p.calls)==(1 if phase in {'building','ready'} else 0)
        assert len(b.store.list('packages'))==(2 if phase=='ready' else 1)
        if not held:assert not b.build_lock.locked()
    finally:
        if held:b.build_lock.release()
        p.release.set();await b.close()


def test_cancel_requires_explicit_repair_identity():
    with pytest.raises(ValueError):
        DeviceEvent(event='app_repair_cancel',device_id='fire-01',protocol_version='0.2',
            session_id='session-test',boot_id='boot-test',event_id='evt-test')


async def test_cancel_same_build_repair_continuation_while_queued_cleans_worker_and_session(tmp_path):
    from fire_backend.generation_errors import GenerationResponseError
    class Unavailable(RepairProvider):
        async def generate(self,*args):raise GenerationResponseError('ai_incomplete','AI-svaret ble avbrutt')
    b=Backend(configured(tmp_path),Unavailable());held=False
    try:
        _,base=saved_app(b,'Spill');s,_=await session(b)
        job=await prepare(b,s,base)
        await dispatch(b,s,event(s,'build_confirm',repair_id=job['repair_id'],proposal_id=job['proposal_id']))
        failed=await finished(b,job['repair_id']);build_id=failed['build_id']
        await b.build_lock.acquire();held=True
        await dispatch(b,s,event(s,'build_resume',build_id=build_id))
        await dispatch(b,s,event(s,'build_confirm',proposal_id=s.proposal_id))
        assert b.store.get('repairs',job['repair_id'])['status']=='queued'
        result=await dispatch(b,s,event(s,'app_repair_cancel',repair_id=job['repair_id']))
        assert result['status']=='cancelled'
        assert build_id not in b.device_builds and b.store.get('builds',build_id)['status']=='failed'
        assert s.build_id is None and s.task is None
    finally:
        if held:b.build_lock.release()
        await b.close()

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from fire_backend.app import create_app
from fire_backend.models import Capabilities, SessionStart
from fire_backend.service import Backend, Conflict
from test_device_protocol import CAPS, Device, configured, headers


async def expire(service, session):
    await service.detach(session, next(iter(session.sockets), None))
    session.disconnected_at = time.time() - service.settings.fire_session_resume_seconds - 1
    service.persist(session)


def request(**extra):
    return SessionStart(device_id='fire-01', target='device', protocol_version='0.2',
                        boot_id='boot-01', capabilities=Capabilities(**CAPS), **extra)


def test_rejected_session_start_closes_before_pong_can_keep_unbound_socket_alive(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            first = Device(socket)
            started = first.start()
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            peer = Device(socket)
            peer.counter = 100
            event = peer.send('session_start', target='device', resume_session_id=started['session_id'],
                              capabilities={**CAPS, 'audio_input': False})
            error = peer.until('error')
            assert error['code'] == 'session_start_rejected'
            assert error['retryable'] is False
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 1008
            service = client.app.state.backend
            result = service.store.get('events', event['event_id'])['result']
            assert result == {'error': 'SessionStartRejected', 'reason_code': 'capabilities_mismatch'}
            assert service.store.list('builds') == []
            assert service.store.list('commands') == []
        # Failed start replay remains terminal, never an accepted unbound ACK.
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            socket.send_json(event)
            assert socket.receive_json()['code'] == 'session_start_rejected'
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            peer = Device(socket)
            peer.counter = 200
            assert peer.start(resume_session_id=started['session_id'])['session_id'] == started['session_id']


def test_stopped_session_fresh_socket_retains_plan_but_requires_new_confirmation(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            old = Device(socket)
            started = old.start()
            old.send('text', text='Lag en sirkel')
            proposal = old.until('build_proposal')
            stop = old.send('session_stop')
            old.until('session_stopped')
            old.ack(stop)
        service = client.app.state.backend
        retained = service.store.get('sessions', started['session_id'])
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            peer = Device(socket)
            peer.counter = 100
            fresh = peer.start(resume_session_id=started['session_id'])
            snapshot = peer.until('session_snapshot')
            assert fresh['session_id'] != started['session_id'] and fresh['seq'] == 1
            assert fresh['project_id'] == started['project_id']
            assert snapshot['summary'] == retained['summary'] and snapshot['proposal_id'] is None
            assert snapshot['pending_commands'] == []
            result = peer.until('event_ack')['result']
            assert result['recovery_reason_code'] == 'stopped'
            peer.send('build_confirm', proposal_id=proposal['proposal_id'])
            assert peer.until('error')['code'] == 'event_rejected'
            peer.send('ping')
            assert peer.until('pong')['session_id'] == fresh['session_id']
            assert service.store.list('builds') == service.store.list('commands') == []


@pytest.mark.parametrize('stale', ['expired', 'stopped'])
async def test_stale_identical_session_gets_fresh_session_same_plan_no_authority_or_work(tmp_path, stale):
    service = Backend(configured(tmp_path))
    try:
        old = await service.start(request(), principal='fire-01')
        old.summary = 'Behold den opprinnelige planen'
        old.history = [{'role': 'user', 'content': 'Lag en måleapp'}]
        old.proposal_id = 'proposal-old'
        old.evolution_job_id = 'evolution-old'
        # Unknown paid history is retained; connecting never replays its action.
        usage_id = service.usage.begin('generate', service.settings.openai_code_model, 100, 100,
                                       project_id=old.project_id, session_id=old.id)
        service.usage.finish(usage_id, None, status='cancelled')
        before_usage = service.usage.records()
        await service.detach(old, None)
        if stale == 'stopped':
            await service.stop(old)
        else:
            old.disconnected_at = time.time() - service.settings.fire_session_resume_seconds - 1
            service.persist(old)
        # Native can retain resume ID while its project selector is empty.
        fresh = await service.start(request(resume_session_id=old.id), principal='fire-01')
        assert fresh.id != old.id and fresh.project_id == old.project_id
        assert fresh.history == old.history and fresh.summary == old.summary
        assert fresh.base_package_id == old.base_package_id
        assert fresh.proposal_id is None and fresh.evolution_job_id is None
        assert fresh.build_id is None and fresh.package_id is None
        assert service.store.get('sessions', old.id)['stopped'] is True
        assert len(service.store.list('projects')) == 1
        assert service.store.list('builds') == service.store.list('commands') == []
        assert service.usage.records() == before_usage
        with pytest.raises(Conflict):
            await service.confirm_build(fresh, 'proposal-old')
    finally:
        await service.close()


@pytest.mark.parametrize('change,reason', [
    ({'device_id': 'fire-02'}, 'identity_mismatch'),
    ({'boot_id': 'boot-other'}, 'boot_mismatch'),
    ({'capabilities': Capabilities(**{**CAPS, 'audio_input': False})}, 'capabilities_mismatch'),
    ({'conversation_mode': 'chat'}, 'mode_mismatch'),
    ({'base_package_id': 'build-other'}, 'base_mismatch'),
])
async def test_stopped_session_mismatch_never_uses_fresh_recovery(tmp_path, change, reason):
    service = Backend(configured(tmp_path))
    try:
        old = await service.start(request(), principal='fire-01')
        await service.stop(old)
        incoming = request(resume_session_id=old.id).model_copy(update=change)
        with pytest.raises(Conflict) as error:
            await service.start(incoming, principal=incoming.device_id)
        assert error.value.reason_code == reason
        assert not service.sessions and len(service.store.list('projects')) == 1
        assert not service.store.list('builds') and not service.store.list('commands')
    finally:
        await service.close()


async def test_expired_in_flight_session_is_not_cancelled_or_replaced(tmp_path):
    service = Backend(configured(tmp_path))
    release = asyncio.Event()
    try:
        old = await service.start(request(), principal='fire-01')
        await service.detach(old, None)
        old.operation_task = asyncio.create_task(release.wait())
        old.disconnected_at = time.time() - service.settings.fire_session_resume_seconds - 1
        for change, reason in [({'device_id': 'fire-02'}, 'identity_mismatch'),
                ({'boot_id': 'boot-other'}, 'boot_mismatch'),
                ({'capabilities': Capabilities(**{**CAPS, 'audio_input': False})}, 'capabilities_mismatch')]:
            incoming = request(resume_session_id=old.id).model_copy(update=change)
            with pytest.raises(Conflict) as error:
                await service.start(incoming, principal=incoming.device_id)
            assert error.value.reason_code == reason
            assert not old.stopped and not old.operation_task.done()
        resumed = await service.start(request(resume_session_id=old.id), principal='fire-01')
        assert resumed is old
        assert not old.stopped and not old.operation_task.done()
        assert list(service.sessions) == [old.id]
    finally:
        release.set()
        if old.operation_task:
            await old.operation_task
        await service.close()


def test_expired_active_build_socket_replacement_retains_task_and_normal_job_controls(tmp_path):
    from fire_backend.metering import usage_scope
    from test_background_repairs import RepairProvider

    class Metered(RepairProvider):
        async def generate(self, *args):
            identifier = service.usage.begin('generate', service.settings.openai_code_model,
                                              1000, 1000, **usage_scope.get())
            try:
                return await super().generate(*args)
            finally:
                service.usage.finish(identifier, None, status='cancelled')

    provider = Metered()
    provider.release.clear()
    with TestClient(create_app(configured(tmp_path), provider)) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            first = Device(socket)
            started = first.start()
            first.send('text', text='Lag en sirkel')
            proposal = first.until('build_proposal')
            confirm = first.send('build_confirm', proposal_id=proposal['proposal_id'])
            build_id = first.ack(confirm)['result']['build_id']

            async def expire_while_blocked():
                await asyncio.wait_for(provider.entered.wait(), 3)
                old = service.session(started['session_id'])
                old.disconnected_at = time.time() - service.settings.fire_session_resume_seconds - 1
                service.persist(old)
                return old.task

            task = client.portal.call(expire_while_blocked)
            with client.websocket_connect('/ws/device', headers=headers()) as replacement:
                peer = Device(replacement)
                peer.counter = 100
                resumed = peer.start(resume_session_id=started['session_id'])
                snapshot = peer.until('session_snapshot')
                assert resumed['session_id'] == started['session_id']
                assert snapshot['build_id'] == build_id
                assert service.session(peer.session_id).task is task and not task.done()
                assert len(provider.calls) == len(service.usage.records()) == 1
                pause = peer.send('job_control', build_id=build_id, job_action='pause')
                assert peer.ack(pause)['result']['status'] == 'pause_requested'
                assert not task.done() and len(provider.calls) == 1
                cancel = peer.send('job_control', build_id=build_id, job_action='cancel')
                assert peer.until('error')['display_text'] == 'Byggingen ble avbrutt'
                peer.ack(cancel)
                assert task.done() and len(provider.calls) == len(service.usage.records()) == 1
                assert service.usage.records()[0]['status'] == 'cancelled'
                assert len(service.store.list('builds')) == 1 and not service.store.list('commands')


async def test_stopped_session_cannot_change_project_or_recover_across_owner(tmp_path):
    service = Backend(configured(tmp_path))
    try:
        old = await service.start(request(), principal='fire-01')
        own_other = service.new_project('fire-01', 'device')
        foreign = service.new_project('fire-02', 'device')
        await service.stop(old)
        with pytest.raises(Conflict) as error:
            await service.start(request(resume_session_id=old.id, project_id=own_other['id']), principal='fire-01')
        assert error.value.reason_code == 'project_mismatch'
        with pytest.raises(PermissionError):
            await service.start(request(resume_session_id=old.id, project_id=foreign['id']), principal='fire-01')
        assert not service.sessions and len(service.store.list('projects')) == 3
    finally:
        await service.close()


async def test_lost_recovery_response_reuses_exact_successor_through_six_expiries_and_restart(tmp_path):
    from test_repair_target import Peer
    service = Backend(configured(tmp_path))
    try:
        original = await service.start(request(), Peer(), 'fire-01')
        original.summary = 'Behold planen'
        original.proposal_id = 'proposal-old'
        original.history = [{'role': 'user', 'content': 'Lag en måleapp'}]
        await expire(service, original)
        incoming = request(resume_session_id=original.id)
        previous = original
        for cycle in range(6):
            lost = Peer()
            successor = await service.start(incoming, lost, 'fire-01')
            assert successor.id != previous.id
            assert lost.events[0]['type'] == 'session_started'
            assert lost.events[0]['session_id'] == successor.id
            # Simulate losing every response, not learning the new session ID.
            replacement = Peer()
            repeated = await service.start(incoming, replacement, 'fire-01')
            assert repeated is successor and not successor.stopped
            assert repeated.summary == original.summary and repeated.history == original.history
            assert repeated.proposal_id is None and repeated.evolution_job_id is None
            assert len(service.store.list('sessions')) == cycle + 2
            if cycle == 2:
                await service.close()
                service = Backend(configured(tmp_path))
                successor = await service.start(incoming, Peer(), 'fire-01')
                assert successor.id == repeated.id
            with pytest.raises(Conflict):await service.confirm_build(successor, 'proposal-old')
            with pytest.raises((ValueError, FileNotFoundError, KeyError)):
                await service.confirm_run(successor, 'build-untested')
            await expire(service, successor)
            previous = successor
        assert len(service.store.list('projects')) == 1
        assert service.store.list('builds') == service.store.list('commands') == service.usage.records() == []
        assert service.store.get('sessions', original.id)['stopped'] is True
    finally:
        await service.close()


async def test_recovery_reservation_is_durable_before_first_response_and_cold_materialization(tmp_path,monkeypatch):
    from test_repair_target import Peer
    service=Backend(configured(tmp_path))
    old=await service.start(request(),Peer(),'fire-01')
    await expire(service,old)
    put=service.store.put
    reserved=[]
    def crash(group,identifier,value,**kwargs):
        if group=='sessions' and identifier!=old.id:
            reserved.append(identifier)
            raise OSError('simulated cold crash before successor persist')
        return put(group,identifier,value,**kwargs)
    monkeypatch.setattr(service.store,'put',crash)
    with pytest.raises(OSError):await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
    assert len(reserved)==1
    monkeypatch.setattr(service.store,'put',put)
    service.sessions.clear()  # the crashed process cannot clean up its volatile state
    await service.close()
    service=Backend(configured(tmp_path))
    try:
        next_session=await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
        assert next_session.id==reserved[0] and len(service.store.list('sessions'))==2
        assert not service.store.list('builds') and not service.store.list('commands')
    finally:await service.close()


async def test_recovery_racing_retries_and_same_start_event_duplicate_use_one_successor(tmp_path):
    from test_repair_target import Peer
    service=Backend(configured(tmp_path))
    try:
        old=await service.start(request(),Peer(),'fire-01')
        await expire(service,old)
        a,b=await asyncio.gather(*(service.start(request(resume_session_id=old.id),Peer(),'fire-01') for _ in range(2)))
        assert a is b and len(service.store.list('sessions'))==2
        assert len(service.store.list('projects'))==1 and not service.usage.records()
    finally:await service.close()


@pytest.mark.parametrize('tamper',['successor','cycle','foreign','context_project','context_mode','context_base','explicit'])
async def test_recovery_link_tamper_and_changed_intent_cannot_take_over(tmp_path,tamper):
    from test_repair_target import Peer
    service=Backend(configured(tmp_path))
    try:
        old=await service.start(request(),Peer(),'fire-01')
        await expire(service,old)
        successor=await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
        incoming=request(resume_session_id=old.id)
        saved=service.store.get('sessions',old.id)
        if tamper in {'successor','cycle','foreign'}:
            saved['recovery']['successor']['session_id']={'successor':'session-missing','cycle':old.id,'foreign':successor.id}[tamper]
            if tamper=='foreign':saved['recovery']['successor']['root_id']='session-foreign'
            service.store.put('sessions',old.id,saved)
        elif tamper.startswith('context_'):
            if tamper=='context_project':successor.project_id=service.new_project('fire-01','device')['id']
            if tamper=='context_mode':successor.conversation_mode='chat'
            if tamper=='context_base':successor.base_package_id='build-other'
            service.persist(successor)
        else:incoming=incoming.model_copy(update={'project_id':old.project_id,'app_mode':'update'})
        with pytest.raises(Conflict):await service.start(incoming,Peer(),'fire-01')
        assert service.sessions[successor.id] is successor
        assert len(service.store.list('sessions'))==2 and not service.store.list('commands')
    finally:await service.close()


async def test_current_successor_text_and_proposal_do_not_invalidate_reconnect_or_revert_plan(tmp_path):
    from test_repair_target import Peer
    service=Backend(configured(tmp_path))
    try:
        old=await service.start(request(),Peer(),'fire-01')
        await expire(service,old)
        current=await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
        await service.text(current,'Lag en sirkel')
        assert current.proposal_id and current.history
        plan=current.summary;history=list(current.history)
        await expire(service,current)
        newer=await service.start(request(resume_session_id=current.id),Peer(),'fire-01')
        assert newer.id!=current.id and newer.summary==plan and newer.history==history
        assert newer.proposal_id is None
        assert (await service.start(request(resume_session_id=old.id),Peer(),'fire-01')).id==newer.id
        assert not service.store.list('builds') and not service.store.list('commands')
    finally:await service.close()


async def test_exact_current_successor_can_start_new_lineage_after_real_selection(tmp_path):
    from fire_backend.protocol import dispatch
    from test_background_repairs import event
    from test_repair_target import Peer
    service=Backend(configured(tmp_path))
    try:
        old=await service.start(request(),Peer(),'fire-01')
        await expire(service,old)
        current=await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
        await dispatch(service,current,event(current,'app_select',app_mode='new'))
        await dispatch(service,current,event(current,'mode_select',conversation_mode='chat'))
        with pytest.raises(Conflict):await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
        await expire(service,current)
        next_session=await service.start(request(resume_session_id=current.id),Peer(),'fire-01')
        assert next_session.project_id==current.project_id and next_session.conversation_mode=='chat'
        assert next_session.recovery['origin']['root_id']==current.id
        assert next_session.selection_ack==current.selection_ack
    finally:await service.close()


async def test_selection_receipts_survive_lost_ack_cold_restart_and_inert_recovery(tmp_path):
    from fire_backend.protocol import dispatch
    from test_background_repairs import event
    from test_repair_target import Peer
    service=Backend(configured(tmp_path))
    try:
        old=await service.start(request(),Peer(),'fire-01')
        app=event(old,'app_select',app_mode='new')
        await dispatch(service,old,app)
        mode=event(old,'mode_select',conversation_mode='chat')
        await dispatch(service,old,mode)
        assert service.store.get('sessions',old.id)['selection_ack']=={'app_select':app.event_id,'mode_select':mode.event_id}
        assert len(service.store.list('projects'))==2
        await expire(service,old)
        await service.close()
        service=Backend(configured(tmp_path))
        peer=Peer()
        resumed=await service.start(request(resume_session_id=old.id),peer,'fire-01')
        assert peer.events[0]['selection_ack']=={'app_select':app.event_id,'mode_select':mode.event_id}
        assert resumed.project_id==old.project_id and resumed.conversation_mode=='chat'
        assert len(service.store.list('projects'))==2  # native consumes refs instead of repeating New
        assert not service.store.list('builds') and not service.store.list('commands') and not service.usage.records()
        fake=service.store.get('events',app.event_id)
        fake['device_id']='fire-02'
        service.store.put('events',app.event_id,fake)
        assert 'app_select' not in service.snapshot(resumed)['selection_ack']
        resumed.conversation_mode='develop'
        assert 'selection_ack' not in service.snapshot(resumed)
    finally:await service.close()


def test_rejected_selection_has_exact_event_ref_and_no_effect_receipt(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect('/ws/device',headers=headers()) as socket:
            peer=Device(socket);peer.start()
            service=client.app.state.backend
            session=service.session(peer.session_id)
            from fire_backend.models import State
            session.state=State.building
            for kind,values in [('app_select',{'app_mode':'new'}),('mode_select',{'conversation_mode':'chat'})]:
                sent=peer.send(kind,**values)
                error=peer.until('error')
                assert error['event_id']==sent['event_id']
                assert 'selection_ack' not in service.snapshot(session)
            assert len(service.store.list('projects'))==1 and not service.store.list('commands')
            session.state=State.idle


def test_historical_start_duplicate_on_attached_successor_uses_verified_alias_without_rebinding(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        service=client.app.state.backend
        with client.websocket_connect('/ws/device',headers=headers()) as socket:
            first=Device(socket)
            original_start=first.send('session_start',target='device',capabilities=CAPS)
            old_id=first.until('session_started')['session_id']
        client.portal.call(expire,service,service.session(old_id))
        with client.websocket_connect('/ws/device',headers=headers()) as socket:
            peer=Device(socket);peer.counter=100
            current=peer.start(resume_session_id=old_id)
            peer.until('session_snapshot')
            epoch=service.device_record(service.session(peer.session_id))['connection_epoch']
            socket.send_json(original_start)
            assert peer.until('session_started')['session_id']==current['session_id']
            ack=peer.until('event_ack',lambda e:e['event_id']==original_start['event_id'])
            assert ack['status']=='duplicate' and ack['result']['session_id']==current['session_id']
            assert service.device_record(service.session(peer.session_id))['connection_epoch']==epoch
        with client.websocket_connect('/ws/device',headers=headers()) as socket:
            socket.send_json(original_start)
            peer=Device(socket)
            assert peer.until('session_started')['session_id']==current['session_id']
        assert len(service.store.list('sessions'))==2 and not service.store.list('commands')


@pytest.mark.parametrize('endpoint_stopped',[False,True])
async def test_exact_legacy_ce_fc_link_plan_preserves_both_records_and_failed_evidence(tmp_path,monkeypatch,endpoint_stopped):
    from test_repair_target import Peer
    from fire_backend.storage import new_id
    names=iter(['session-ce96097b3f2b45b98883','session-fc1654205ff74cea9716','session-recovered-legacy'])
    monkeypatch.setattr('fire_backend.service.new_id',lambda prefix:next(names) if prefix=='session' else new_id(prefix))
    service=Backend(configured(tmp_path))
    try:
        old=await service.start(request(),Peer(),'fire-01')
        await expire(service,old)
        current=await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
        await service.detach(current,next(iter(current.sockets)))
        if endpoint_stopped:await service.stop(current)
        before={}
        for identifier in (old.id,current.id):
            data=service.store.get('sessions',identifier)
            data.pop('recovery',None)  # exact pre-link legacy layout
            service.store.put('sessions',identifier,data)
            before[identifier]=data
        service.sessions.clear()
        failed={'id':'evt-legacy-failure','device_id':'fire-01','status':'completed','digest':'f'*64,
                'result':{'error':'Conflict','reason_code':'session_conflict'}}
        service.store.put('events',failed['id'],failed)
        predecessor=service.resume_record(old.id);successor=service.resume_record(current.id)
        link=service.recovery_link(predecessor.id,predecessor.id,successor.id,predecessor)
        # The approved one-pair rollout plan changes only these record fields;
        # it does not run ordinary persist() or refresh snapshot timestamps.
        service.store.put('sessions',old.id,{**before[old.id],'recovery':{'first_successor':link,'successor':link}})
        service.store.put('sessions',current.id,{**before[current.id],'recovery':{'origin':link}})
        for identifier in (old.id,current.id):
            after=service.store.get('sessions',identifier);after.pop('recovery')
            assert after==before[identifier]
        restored=await service.start(request(resume_session_id=old.id),Peer(),'fire-01')
        assert restored.id==(current.id if not endpoint_stopped else 'session-recovered-legacy')
        assert len(service.store.list('sessions'))==(2 if not endpoint_stopped else 3)
        assert restored.project_id==current.project_id and len(service.store.list('projects'))==1
        assert service.store.get('events',failed['id'])==failed
        assert not service.store.list('builds') and not service.store.list('commands') and not service.usage.records()
    finally:await service.close()

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from fire_backend.app import create_app
from fire_backend.models import Capabilities, SessionStart
from fire_backend.service import Backend, Conflict
from test_device_protocol import CAPS, Device, configured, headers


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

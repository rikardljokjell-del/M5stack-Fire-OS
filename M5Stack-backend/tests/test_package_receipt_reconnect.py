"""Real offline WebSocket lifecycle; fixture receipts are not physical evidence."""
import copy
import time

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from test_device_protocol import CAPS, OTHER, Device, configured, headers
from test_session_reconnect import bounded_receive


def attach(client, socket, *, counter=0, resume=None, device_id='fire-01'):
    bounded_receive(socket)
    device = Device(socket, device_id=device_id)
    device.counter = counter
    sent = device.send('session_start', target='device', capabilities=CAPS,
                       **({'resume_session_id': resume} if resume else {}))
    started = device.until('session_started')
    device.session_id = started['session_id']
    device.ack(sent)  # The start must be durably accepted before fixture detach.
    return device


def receipt(device, offer, **changes):
    result = {'type': 'device_event', 'protocol_version': '0.2',
              'event_id': 'install-receipt-stable', 'device_id': device.device_id,
              'session_id': device.session_id, 'boot_id': device.boot_id,
              'event': 'device_install_result', 'install_id': offer['install_id'],
              'package_id': offer['package_id'], 'archive_sha256': offer['archive_sha256'],
              'status': 'ok'}
    result.update(changes)
    return result


def accepted(device, sent):
    # build() already consumes the earlier build-confirm ACK while waiting for
    # the eventual install offer. Never wait twice for a single wire message.
    found = next((e for e in device.events if e['type'] == 'event_ack'
                  and e['event_id'] == sent['event_id']), None)
    assert (found or device.ack(sent))['status'] == 'accepted'


def assert_no_extra_work(service, before_usage, build_ids, command_ids):
    assert service.usage.records() == before_usage
    assert {b['id'] for b in service.store.list('builds')} == build_ids
    assert {c['id'] for c in service.store.list('commands')} == command_ids


def test_install_receipt_survives_same_session_reconnect_and_lost_ack_without_reexecution(tmp_path, monkeypatch):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            first = attach(client, socket)
            offer, confirmed = first.build()
            accepted(first, confirmed)
            original_id = first.session_id
            sent = receipt(first, offer)
            first.send('run_confirm', package_id=offer['package_id'])
            assert first.until('error')['code'] == 'event_rejected'
        assert not service.sessions[original_id].sockets
        usage = service.usage.records()
        build_ids = {b['id'] for b in service.store.list('builds')}
        command_ids = {offer['install_id']}
        original_archive = service.store.path('packages', offer['package_id'], '.zip').read_bytes()

        original_emit = service.emit
        dropped = []

        async def lose_first_receipt_ack(session, message):
            if message.get('type') == 'event_ack' and message.get('event_id') == sent['event_id'] and not dropped:
                dropped.append(copy.deepcopy(message))
                return
            return await original_emit(session, message)

        monkeypatch.setattr(service, 'emit', lose_first_receipt_ack)
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            second = attach(client, socket, counter=100, resume=original_id)
            assert second.session_id == original_id
            assert service.store.get('commands', offer['install_id'])['status'] == 'pending'
            socket.send_json(sent)
            second.send('ping')
            second.until('pong')  # Barrier after the deliberately lost receipt ACK.
            assert len(dropped) == 1
            assert not any(e.get('event_id') == sent['event_id'] for e in second.events)
            assert service.store.get('commands', offer['install_id'])['status'] == 'completed'
            assert dropped[0]['status'] == 'accepted'
            assert dropped[0]['result'] == {'status': 'recorded', 'package_id': offer['package_id']}
            assert_no_extra_work(service, usage, build_ids, command_ids)

        # The exact pending receipt is retained across another real disconnect.
        # It keeps its original event_id/session/boot/package/hash, never a new grant.
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            third = attach(client, socket, counter=200, resume=original_id)
            assert third.session_id == original_id
            socket.send_json(sent)
            replay = third.ack(sent)
            assert replay['status'] == 'duplicate' and replay['result'] == dropped[0]['result']
            socket.send_json(sent)
            assert third.ack(sent)['status'] == 'duplicate'
            assert_no_extra_work(service, usage, build_ids, command_ids)
            assert service.store.path('packages', offer['package_id'], '.zip').read_bytes() == original_archive
            changed = {**sent, 'archive_sha256': '0' * 64}
            socket.send_json(changed)
            assert third.until('error')['code'] == 'event_rejected'
            assert service.store.get('events', sent['event_id'])['result'] == replay['result']
            # Only now does the fixture issue a separate, explicit normal Run.
            run, run_confirmation = third.run(offer['package_id'])
            third.ack(run_confirmation)
            command = service.store.get('commands', run['run_id'])
            assert command['session_id'] == original_id and command['boot_id'] == first.boot_id
            assert command['package_id'] == offer['package_id']
            assert command['archive_sha256'] == offer['archive_sha256']
            assert service.usage.records() == usage
            assert len(service.store.list('commands')) == 2
            assert len(service.store.list('builds')) == 1


@pytest.mark.parametrize('invalid', ['session', 'boot', 'hash', 'package', 'expired_command', 'missing_session', 'foreign_owner'])
def test_install_receipt_reconnect_rejects_wrong_scope_or_expired_command(tmp_path, invalid):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            first = attach(client, socket)
            offer, confirmed = first.build()
            accepted(first, confirmed)
            session_id = first.session_id
        usage = service.usage.records()
        if invalid == 'expired_command':
            command = service.store.get('commands', offer['install_id'])
            command['expires_at'] = int(time.time()) - 1
            service.store.put('commands', command['id'], command)
        foreign = invalid == 'foreign_owner'
        with client.websocket_connect('/ws/device', headers=headers(OTHER) if foreign else headers()) as socket:
            device = attach(client, socket, counter=100, resume=None if foreign else session_id,
                            device_id='fire-02' if foreign else 'fire-01')
            sent = receipt(device, offer)
            if invalid == 'session': sent['session_id'] = 'session-wrong'
            if invalid == 'boot': sent['boot_id'] = 'boot-wrong'
            if invalid == 'hash': sent['archive_sha256'] = '0' * 64
            if invalid == 'package': sent['package_id'] = 'build-wrong'
            if invalid == 'missing_session': sent.pop('session_id')
            socket.send_json(sent)
            error = device.until('error')
            assert error['code'] in {'event_rejected', 'invalid_event'}
            command_status = service.store.get('commands', offer['install_id'])['status']
            # Normal maintenance may retire the deliberately expired command
            # during reconnect. Both states reject its receipt; neither installs.
            assert command_status in ({'pending', 'unknown'} if invalid == 'expired_command' else {'pending'})
            assert service.store.get('devices', 'fire-01').get('installed_package_id') is None
            assert_no_extra_work(service, usage, {offer['package_id']}, {offer['install_id']})


def test_expired_session_does_not_transfer_pending_install_authority_to_successor(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            first = attach(client, socket)
            offer, confirmed = first.build()
            accepted(first, confirmed)
            old_id = first.session_id
        usage = service.usage.records()

        async def expire():
            session = service.sessions[old_id]
            session.disconnected_at = time.time() - service.settings.fire_session_resume_seconds - 1
            service.persist(session)

        client.portal.call(expire)
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            fresh = attach(client, socket, counter=100, resume=old_id)
            assert fresh.session_id != old_id
            socket.send_json(receipt(fresh, offer))
            assert fresh.until('error')['code'] == 'event_rejected'
            assert service.store.get('commands', offer['install_id'])['status'] != 'completed'
            assert service.store.get('devices', 'fire-01').get('installed_package_id') is None
            assert_no_extra_work(service, usage, {offer['package_id']}, {offer['install_id']})


def test_missing_resume_session_never_admits_an_install_receipt(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            bounded_receive(socket)
            device = Device(socket)
            device.send('session_start', target='device', capabilities=CAPS, resume_session_id='session-missing')
            error = device.until('error')
            assert error['code'] == 'session_start_rejected' and error['retryable'] is False
            assert service.store.list('commands') == service.store.list('builds') == []
            assert service.usage.records() == []

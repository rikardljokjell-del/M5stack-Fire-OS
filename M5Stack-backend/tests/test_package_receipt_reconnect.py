"""Real offline WebSocket lifecycle; fixture receipts are not physical evidence."""
import copy
import json
import time

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from test_device_protocol import CAPS, OTHER, Device, configured, headers
from test_session_reconnect import bounded_receive


def attach(client, socket, *, counter=0, resume=None, device_id='fire-01', boot_id='boot-01'):
    bounded_receive(socket)
    device = Device(socket, device_id=device_id, boot_id=boot_id)
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


def test_failed_same_package_retry_preserves_verified_install_and_explicit_run(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket)
            first, confirmed = device.build()
            accepted(device, confirmed)
            device.install(first)
            package = service.store.get('packages', first['package_id'])
            inventory = device.send('app_inventory', storage_ready=True, complete=True,
                apps=[{'app_id': package['manifest']['id'], 'package_id': package['id'],
                       'version': package['manifest']['version'], 'checksum': package['manifest']['checksum']}])
            device.ack(inventory)
            download = device.send('app_download', project_id=package['project_id'], package_id=package['id'])
            retry = device.until('install_request')
            accepted(device, download)
            failed = device.send('device_install_result', install_id=retry['install_id'], package_id=package['id'],
                status='failed', error_code='install_failed', message='Package worker allocation failed')
            device.ack(failed)
            assert service.store.get('devices', 'fire-01')['installed_package_id'] == package['id']
            assert service.current_inventory_matches(service.sessions[device.session_id], package)
            assert service.store.get('commands', first['install_id'])['status'] == 'completed'
            assert service.store.get('commands', retry['install_id'])['status'] == 'failed'
            stored = service.store.get('commands', retry['install_id'])
            assert stored['error_code'] == 'install_failed' and stored['message'] == 'Package worker allocation failed'
            assert stored['receipt']['event_id'] == failed['event_id'] and stored['receipt']['status'] == 'failed'
            assert not any(c['kind'] == 'run' for c in service.store.list('commands'))
            # A failed retry cannot erase the separately checksum-confirmed,
            # current-inventory installation. Run still needs an explicit event.
            run, confirmation = device.run(package['id'])
            device.ack(confirmation)
            assert run['package_id'] == package['id'] and run['source_sha256'] == package['manifest']['checksum']


def report_inventory(device, package, **changes):
    data = {'app_id': package['manifest']['id'], 'package_id': package['id'],
            'version': package['manifest']['version'], 'checksum': package['manifest']['checksum']}
    data.update(changes)
    sent = device.send('app_inventory', storage_ready=True, complete=True, apps=[data])
    device.ack(sent)


def test_normal_lua_current_sd_inventory_after_new_boot_requires_explicit_source_bound_run(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            first = attach(client, socket)
            offer, confirmed = first.build(); accepted(first, confirmed)
            first.install(offer)
            package = service.store.get('packages', offer['package_id'])
            assert 'ai' not in package['manifest']['required_services']
        usage = service.usage.records()
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket, boot_id='boot-new')
            assert service.store.get('devices', 'fire-01')['installed_package_id'] is None
            report_inventory(device, package)
            assert len(service.store.list('commands')) == 1  # Inventory never runs/installs.
            run, confirmed = device.run(package['id']); device.ack(confirmed)
            command = service.store.get('commands', run['run_id'])
            assert command['sd_presence_verified'] is True and command['boot_id'] == 'boot-new'
            device.send('app_started', run_id=run['run_id'], package_id=package['id'])
            assert device.until('error')['code'] == 'event_rejected'
            device.send('app_started', run_id=run['run_id'], package_id=package['id'], source_sha256='0'*64)
            assert device.until('error')['code'] == 'event_rejected'
            assert service.store.get('commands', run['run_id'])['status'] == 'pending'
            sent = device.send('app_started', run_id=run['run_id'], package_id=package['id'],
                               source_sha256=package['manifest']['checksum'])
            device.ack(sent)
            healthy = device.send('app_healthy', run_id=run['run_id'], package_id=package['id'])
            device.ack(healthy)
            assert service.store.get('commands', run['run_id'])['status'] == 'healthy'
            assert service.usage.records() == usage


@pytest.mark.parametrize('invalid', ['foreign_owner', 'stale_epoch', 'stale_boot', 'incomplete', 'checksum',
                                   'removed', 'blocked_quality', 'active_other_run', 'active_pointer_mismatch',
                                   'app_permission', 'archive', 'caps'])
def test_normal_lua_inventory_run_never_bypasses_current_evidence_or_delivery_guards(tmp_path, invalid):
    from test_repair_target import saved_app
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        project, package = saved_app(service, 'Timer', slug='timer')
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket)
            report_inventory(device, package)
            record = service.store.get('devices', 'fire-01')
            current = service.sessions[device.session_id]
            if invalid == 'foreign_owner':
                project['owner_device_id'] = 'fire-02'; service.store.put('projects', project['id'], project)
            elif invalid in {'stale_epoch', 'stale_boot', 'checksum'}:
                presence = record['apps'][package['manifest']['id']]
                if invalid == 'stale_epoch': presence['connection_epoch'] -= 1
                elif invalid == 'stale_boot': presence['boot_id'] = 'boot-old'
                else: presence['checksum'] = '0'*64
                service.store.put('devices', 'fire-01', record)
            elif invalid in {'incomplete', 'removed'}:
                sent = device.send('app_inventory', storage_ready=True, complete=invalid=='removed', apps=[])
                device.ack(sent)
            elif invalid == 'blocked_quality':
                package['quality'] = {'blocked': True}; service.store.put('packages', package['id'], package)
            elif invalid == 'app_permission':
                current.install_permitted = False
            elif invalid == 'archive':
                archive = service.store.path('packages', package['id'], '.zip')
                archive.write_bytes(archive.read_bytes()+b'tampered')
            elif invalid == 'caps':
                current.capabilities = {**current.capabilities, 'max_memory': 1024}
            else:
                other = service.issue_command(current, 'run', 'build-other')
                record.update(active_run_id=other['id'], running_package_id=package['id'] if invalid=='active_pointer_mismatch' else 'build-other', runtime_status='unknown')
                service.store.put('devices', 'fire-01', record)
            before = service.store.list('commands')
            selection = (current.project_id, current.package_id, current.app_revision)
            device_before = service.store.get('devices', 'fire-01')
            device.send('run_confirm', package_id=package['id'])
            assert device.until('error')['code'] == 'event_rejected'
            assert service.store.list('commands') == before
            assert (current.project_id, current.package_id, current.app_revision) == selection
            assert service.store.get('devices', 'fire-01') == device_before
            assert service.store.get('devices', 'fire-01').get('pending_run_id') is None
            assert not service.usage.records()


def test_install_failure_command_retains_bounded_redacted_receipt_after_later_success(tmp_path):
    from test_device_protocol import TOKEN
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket)
            offer, confirmed = device.build(); accepted(device, confirmed)
            failed = device.send('device_install_result', install_id=offer['install_id'], package_id=offer['package_id'],
                status='failed', error_code='install_failed', message='Package worker allocation failed '+TOKEN)
            device.ack(failed)
            old = service.store.get('commands', offer['install_id'])
            assert old['receipt']['event_id'] == failed['event_id']
            assert old['receipt']['status'] == 'failed' and old['error_code'] == 'install_failed'
            assert old['receipt']['reported_at'] > 0
            assert old['receipt']['message'] == old['message'] and len(old['message']) <= 240
            assert TOKEN not in str(old)
            sent = device.send('app_download', package_id=offer['package_id'])
            retry = device.until('install_request'); accepted(device, sent)
            device.install(retry)
            assert service.store.get('commands', offer['install_id']) == old
            complete = service.store.get('commands', retry['install_id'])
            assert complete['status'] == 'completed'
            assert complete['receipt']['archive_sha256'] == retry['archive_sha256']
            assert complete['receipt']['status'] == 'ok'


def test_explicit_download_request_reference_survives_pending_reserialization_and_cold_restart(tmp_path):
    settings = configured(tmp_path)
    with TestClient(create_app(settings)) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket)
            first, confirmed = device.build(); accepted(device, confirmed)
            assert 'request_event_id' not in first  # Old Builder shape remains valid.
            device.install(first)
            download = device.send('app_download', package_id=first['package_id'])
            offer = device.until('install_request')
            assert offer['request_event_id'] == download['event_id']
            accepted(device, download)
            session_id = device.session_id
        usage = service.usage.records()
        commands = service.store.list('commands')
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            resumed = attach(client, socket, counter=100, resume=session_id)

            async def reserialize_pending():
                # Re-read the actual persisted bytes, not the earlier object.
                cold = json.loads(service.store.path('commands', offer['install_id']).read_text(encoding='utf-8'))
                assert cold['status'] == 'pending'
                await service.emit(service.sessions[resumed.session_id], service.command_message(cold))

            client.portal.call(reserialize_pending)
            repeated = resumed.until('install_request')
            assert repeated['request_event_id'] == download['event_id']
            assert repeated['install_id'] == offer['install_id']
            assert repeated['archive_sha256'] == offer['archive_sha256']
            socket.send_json(download)
            assert resumed.ack(download)['status'] == 'duplicate'
            assert service.store.list('commands') == commands and service.usage.records() == usage
    # A true backend restart keeps the correlation, but deliberately does not
    # replay an uncertain physical operation or manufacture new authority.
    with TestClient(create_app(settings)) as client:
        service = client.app.state.backend
        saved = service.store.get('commands', offer['install_id'])
        assert saved['status'] == 'unknown'
        assert service.command_message(saved)['request_event_id'] == download['event_id']
        assert len(service.store.list('commands')) == len(commands)
        assert service.usage.records() == usage


def test_normal_protocol02_matched_install_keeps_optional_started_source_compatibility(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket)
            offer, confirmed = device.build(); accepted(device, confirmed)
            device.install(offer)
            package = service.store.get('packages', offer['package_id'])
            report_inventory(device, package)
            run, confirmation = device.run(package['id']); device.ack(confirmation)
            assert service.store.get('commands', run['run_id'])['sd_presence_verified'] is False
            device.healthy(run)  # Ordinary old 0.2 clients may omit source_sha256.
            assert service.store.get('commands', run['run_id'])['status'] == 'healthy'

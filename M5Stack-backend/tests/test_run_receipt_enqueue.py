"""Offline real WebSocket dedup; MockBuilder never establishes physical execution."""
import copy

from fastapi.testclient import TestClient

from fire_backend.app import create_app
from test_device_protocol import configured, headers
from test_package_receipt_reconnect import accepted, attach


def run_receipt(device, run, kind):
    # Native retries freeze this exact body; optional diagnostics stay absent.
    stable = ('rs-' if kind == 'app_started' else 'rh-') + run['run_id']
    values = {'event_id': stable, 'run_id': run['run_id'], 'package_id': run['package_id']}
    if kind == 'app_started':
        values['source_sha256'] = run['source_sha256']
    return device.send(kind, **values)


def begin_run(device):
    install, confirmed = device.build()
    accepted(device, confirmed)
    device.install(install)
    run, confirmed = device.run(install['package_id'])
    accepted(device, confirmed)
    return run


def block_provider(service, monkeypatch):
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append('unexpected provider call')
        raise AssertionError('Receipt/reconnect must not invoke a provider')

    for name in ['dialog', 'generate', 'review', 'transcribe', 'speech', 'runtime_ai']:
        monkeypatch.setattr(service.provider, name, forbidden)
    return calls


def retained(service):
    return {name: copy.deepcopy(service.store.list(name))
            for name in ['builds', 'packages', 'commands', 'usage', 'quality', 'feedback']}


def assert_recorded(ack, event, status):
    assert ack['event_id'] == event['event_id'] and ack['status'] == status
    assert ack['result'] == {'status': 'recorded', 'package_id': event['package_id']}


def test_exact_stable_started_and_healthy_repeats_after_healthy_are_duplicate_without_side_effects(tmp_path, monkeypatch):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket)  # Existing bounded 3s receive helper.
            run = begin_run(device)
            provider_calls = block_provider(service, monkeypatch)
            started = run_receipt(device, run, 'app_started')
            assert_recorded(device.ack(started), started, 'accepted')
            healthy = run_receipt(device, run, 'app_healthy')
            assert_recorded(device.ack(healthy), healthy, 'accepted')
            assert 'diagnostics' not in started and 'diagnostics' not in healthy
            assert service.store.get('commands', run['run_id'])['status'] == 'healthy'
            before = retained(service)
            event_records = {e['event_id']: service.store.get('events', e['event_id']) for e in [started, healthy]}
            for event in [started, healthy, started, healthy]:
                socket.send_json(event)
                assert_recorded(device.ack(event), event, 'duplicate')
            assert retained(service) == before
            assert {key: service.store.get('events', key) for key in event_records} == event_records

            # Same ID cannot authorize a changed identity/source/body. The
            # optional diagnostics must also remain omitted on exact retries.
            for invalid in [{**started, 'session_id': 'session-wrong'},
                            {**started, 'boot_id': 'boot-wrong'},
                            {**started, 'source_sha256': '0'*64},
                            {**healthy, 'diagnostics': {'phase': 'update'}}]:
                socket.send_json(invalid)
                assert device.until('error')['code'] == 'event_rejected'
            assert retained(service) == before
            assert {key: service.store.get('events', key) for key in event_records} == event_records
            assert provider_calls == []
            assert len(before['builds']) == 1 and len(before['commands']) == 2


def test_lost_started_ack_after_commit_reconnect_replays_exact_stable_body_then_accepts_healthy(tmp_path, monkeypatch):
    with TestClient(create_app(configured(tmp_path))) as client:
        service = client.app.state.backend
        dropped = []
        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            device = attach(client, socket)
            run = begin_run(device)
            session_id, boot_id = device.session_id, device.boot_id
            original_deadline = service.store.get('commands', run['run_id'])['expires_at']
            provider_calls = block_provider(service, monkeypatch)
            original_emit = service.emit
            expected_id = 'rs-' + run['run_id']

            async def lose_started_ack(session, message):
                if message.get('type') == 'event_ack' and message.get('event_id') == expected_id and not dropped:
                    # dispatch finished the durable journal before attempting
                    # to deliver this ACK. This is not a processing/torn result.
                    record = service.store.get('events', expected_id)
                    assert record['status'] == 'completed'
                    dropped.append(copy.deepcopy(message))
                    return
                return await original_emit(session, message)

            monkeypatch.setattr(service, 'emit', lose_started_ack)
            started = run_receipt(device, run, 'app_started')
            ping = device.send('ping')
            device.until('pong')
            accepted(device, ping)
            assert len(dropped) == 1
            assert_recorded(dropped[0], started, 'accepted')
            assert not any(e.get('event_id') == expected_id for e in device.events)
            assert service.store.get('commands', run['run_id'])['status'] == 'started'
            committed = service.store.get('events', expected_id)
            before = retained(service)
        assert not service.sessions[session_id].sockets

        with client.websocket_connect('/ws/device', headers=headers()) as socket:
            resumed = attach(client, socket, counter=100, resume=session_id, boot_id=boot_id)
            assert resumed.session_id == session_id
            socket.send_json(started)
            assert_recorded(resumed.ack(started), started, 'duplicate')
            assert service.store.get('events', expected_id) == committed
            assert retained(service) == before
            assert service.store.get('commands', run['run_id'])['expires_at'] == original_deadline
            healthy = run_receipt(resumed, run, 'app_healthy')
            assert 'diagnostics' not in healthy
            assert_recorded(resumed.ack(healthy), healthy, 'accepted')
            assert service.store.get('commands', run['run_id'])['status'] == 'healthy'
            after = retained(service)
            for event in [started, healthy]:
                socket.send_json(event)
                assert_recorded(resumed.ack(event), event, 'duplicate')
            assert retained(service) == after
            assert provider_calls == []
            assert len(after['builds']) == 1 and len(after['commands']) == 2
            assert after['usage'] == before['usage']

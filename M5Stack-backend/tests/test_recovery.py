"""Connection recovery never re-executes actions or restores a fake capture."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.models import SessionStart, State
from fire_backend.service import Backend, Conflict
from test_device_protocol import CAPS, Device, configured, headers


def test_exact_start_retry_reattaches_new_socket_without_new_project(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as first_socket:
            first = Device(first_socket)
            sent = first.send("session_start", target="device", capabilities=CAPS)
            initial = first.until("session_started")
            with client.websocket_connect("/ws/device", headers=headers()) as next_socket:
                next_socket.send_json(sent)  # Original reply was lost on the wire.
                second = Device(next_socket)
                started = second.until("session_started")
                second.session_id, second.counter = started["session_id"], 10
                assert started["session_id"] == initial["session_id"]
                assert second.until("session_snapshot")["pending_commands"] == []
                ack = second.ack(sent)
                assert ack["status"] == "duplicate"
                second.send("text", text="Lag en sirkel")
                assert second.until("build_proposal")["project_id"] == initial["project_id"]
                assert len(client.app.state.backend.store.list("projects")) == 1
                assert len(client.app.state.backend.sessions) == 1


def test_new_start_event_replaces_old_live_socket_for_same_boot(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as first_socket:
            first = Device(first_socket)
            initial = first.start()
            with client.websocket_connect("/ws/device", headers=headers()) as next_socket:
                second = Device(next_socket)
                second.counter = 100
                started = second.start()
                assert started["session_id"] == initial["session_id"]
                assert second.until("session_snapshot")["boot_id"] == "boot-01"
                second.ack(second.send("ping"))
                assert client.app.state.backend.store.get("devices", "fire-01")["online"]


def test_start_retry_on_same_socket_resends_snapshot(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            sent = device.send("session_start", target="device", capabilities=CAPS)
            initial = device.until("session_started")
            device.ack(sent)
            socket.send_json(sent)
            assert device.until("session_started")["session_id"] == initial["session_id"]
            assert device.until("session_snapshot")["project_id"] == initial["project_id"]
            assert device.ack(sent)["status"] == "duplicate"
            assert len(client.app.state.backend.store.list("projects")) == 1


class Peer:
    def __init__(self):
        self.messages = []
        self.closed = False

    async def send_json(self, value):
        self.messages.append(value)

    async def close(self, code=1000):
        self.closed = True


def request(**values):
    return SessionStart(device_id="fire-01", target="device", protocol_version="0.2",
                        boot_id="boot-01", capabilities=CAPS, **values)


async def test_superseded_detach_cannot_disconnect_new_peer(tmp_path):
    backend = Backend(configured(tmp_path))
    old, new = Peer(), Peer()
    try:
        initial = await backend.start(request(conversation_mode="chat"), old, "fire-01")
        resumed = await backend.start(request(), new, "fire-01")
        assert resumed is initial and resumed.conversation_mode == "chat"
        await backend.detach(initial, old)
        assert old.closed and initial.sockets == {new}
        assert initial.disconnected_at is None and backend.device_record(initial)["online"]
        with pytest.raises(Conflict):
            await backend.start(request(resume_session_id=initial.id, conversation_mode="develop"), Peer(), "fire-01")
        assert initial.sockets == {new}
    finally:
        await backend.close()


async def test_backend_restart_does_not_restore_active_recording(tmp_path):
    settings = configured(tmp_path)
    original = Backend(settings)
    session = await original.start(request(conversation_mode="chat"), principal="fire-01")
    session.state, session.activity, session.turn_id = State.listening, "listening", "turn-cut"
    session.audio_status = {"phase": "recording", "turn_id": "turn-cut"}
    original.persist(session)
    # Simulate a crash: persisted capture exists but no corresponding sampler
    # or coroutine survives in the new process.
    replacement = Backend(settings)
    try:
        resumed = await replacement.start(request(resume_session_id=session.id), Peer(), "fire-01")
        assert resumed.state == State.idle and resumed.activity == "idle"
        assert resumed.turn_id is None and resumed.recording_started_at is None
        assert resumed.audio_status["phase"] == "interrupted"
        assert resumed.conversation_mode == "chat"
    finally:
        await replacement.close()
        await original.close()


async def test_detach_and_reconnect_are_serialized_while_dialogue_closes(tmp_path):
    backend = Backend(configured(tmp_path))
    old, new = Peer(), Peer()
    entered, release = asyncio.Event(), asyncio.Event()
    try:
        session = await backend.start(request(), old, "fire-01")
        close = backend.close_dialog
        async def slow_close(value):
            entered.set()
            await release.wait()
            await close(value)
        backend.close_dialog = slow_close
        detaching = asyncio.create_task(backend.detach(session, old))
        await entered.wait()
        reconnecting = asyncio.create_task(backend.start(request(), new, "fire-01"))
        await asyncio.sleep(0)
        assert not reconnecting.done()
        release.set()
        await detaching
        assert await reconnecting is session
        assert session.sockets == {new} and backend.device_record(session)["online"]
        assert session.disconnected_at is None
    finally:
        release.set()
        await backend.close()


async def test_failed_send_marks_offline_without_deadlocking_start(tmp_path):
    class BrokenPeer(Peer):
        async def send_json(self, value):
            raise ConnectionError("peer disconnected")
    backend = Backend(configured(tmp_path))
    broken = BrokenPeer()
    try:
        session = await asyncio.wait_for(backend.start(request(), broken, "fire-01"), timeout=3)
        await asyncio.gather(*tuple(backend.connection_cleanup))
        assert not session.sockets and session.disconnected_at
        assert not backend.device_record(session)["online"]
        assert broken.closed and not backend.detaching_sockets
        replacement = await backend.start(request(), Peer(), "fire-01")
        assert replacement is session and backend.device_record(session)["online"]
    finally:
        await backend.close()


async def test_command_timeout_releases_reservation_but_does_not_claim_stopped(tmp_path):
    backend = Backend(configured(tmp_path))
    try:
        session = await backend.start(request(), Peer(), "fire-01")
        run = backend.issue_command(session, "run", "package-unconfirmed")
        device = backend.device_record(session)
        device.update(pending_run_id=run["id"], runtime_status="starting")
        backend.store.put("devices", device["id"], device)
        backend.unknown_command(run)
        updated = backend.device_record(session)
        assert updated["pending_run_id"] is None and updated["runtime_status"] == "unknown"
        assert backend.store.get("commands", run["id"])["status"] == "unknown"
        assert updated.get("current") is None and updated.get("installed_package_id") is None
    finally:
        await backend.close()


async def test_immediate_reopen_waits_for_explicit_stop_cleanup(tmp_path):
    backend = Backend(configured(tmp_path))
    old, new = Peer(), Peer()
    entered, release = asyncio.Event(), asyncio.Event()
    try:
        first = await backend.start(request(), old, "fire-01")
        close = backend.close_dialog
        async def slow_close(value):
            if value is first:
                entered.set()
                await release.wait()
            await close(value)
        backend.close_dialog = slow_close
        stopping = asyncio.create_task(backend.stop(first))
        await entered.wait()
        assert first.stopped
        reopening = asyncio.create_task(backend.start(request(), new, "fire-01"))
        await asyncio.sleep(0)
        assert not reopening.done()
        release.set()
        await stopping
        reopened = await asyncio.wait_for(reopening, timeout=3)
        assert reopened.id != first.id and reopened.sockets == {new}
        assert len(backend.sessions) == 1 and backend.device_record(reopened)["online"]
        await backend.detach(first, old)
        assert backend.device_record(reopened)["online"]
    finally:
        release.set()
        await backend.close()


async def test_concurrent_starts_create_one_session_and_one_project(tmp_path):
    backend = Backend(configured(tmp_path))
    first, second = Peer(), Peer()
    try:
        a, b = await asyncio.gather(backend.start(request(), first, "fire-01"),
                                    backend.start(request(), second, "fire-01"))
        assert a is b and a.sockets == {second} and first.closed
        assert len(backend.sessions) == 1 and len(backend.store.list("projects")) == 1
        assert backend.device_record(a)["online"]
    finally:
        await backend.close()


async def test_interrupted_stop_can_finish_cleanup_on_retry(tmp_path):
    backend = Backend(configured(tmp_path))
    entered, release = asyncio.Event(), asyncio.Event()
    try:
        session = await backend.start(request(), Peer(), "fire-01")
        close = backend.close_dialog
        async def slow_close(value):
            entered.set()
            await release.wait()
            await close(value)
        backend.close_dialog = slow_close
        stopping = asyncio.create_task(backend.stop(session))
        await entered.wait()
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert session.stopped and session.id in backend.sessions
        release.set()
        await backend.stop(session)
        assert session.id not in backend.sessions
        assert not backend.device_record(session)["online"]
    finally:
        release.set()
        await backend.close()

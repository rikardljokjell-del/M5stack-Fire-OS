import asyncio
import json
from importlib.resources import files

import pytest
from fastapi.testclient import TestClient

from fire_backend.ai import MockProvider
from fire_backend.app import create_app
from fire_backend.builds import verify_archive
from fire_backend.config import Settings
from fire_backend.models import GeneratedApp, SessionStart, State
from fire_backend.service import Backend, Conflict


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, fire_workspace=tmp_path / "workspace", fire_ai_mode="mock")


async def proposed(service):
    session = await service.start(SessionStart())
    await service.text(session, "Lag en animasjon med en sirkel som beveger seg.")
    return session


def test_http_health_context_auth_and_limits(settings):
    settings.fire_backend_token = "x" * 32
    # Assignment doesn't validate by default; construct normally for production.
    settings = Settings(**settings.model_dump(), _env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/device/context").status_code == 401
        headers = {"Authorization": "Bearer " + "x" * 32}
        context = client.get("/device/context", headers=headers).json()
        assert "GPIO39" in context["context"]
        assert context["source_verified"] is True
        assert context["firmware_runtime_verified"] is False
        assert client.post("/session/start", json={}, headers=headers).status_code == 200
        assert client.post("/session/start", content="x" * 9000).status_code == 413
        assert client.get("/projects/invalid.id", headers=headers).status_code == 400


def test_lan_requires_token():
    with pytest.raises(ValueError):
        Settings(_env_file=None, fire_backend_host="0.0.0.0", fire_backend_token="")


async def test_confirmations_and_package_integrity(settings):
    service = Backend(settings)
    try:
        session = await proposed(service)
        assert not service.store.list("builds")
        with pytest.raises(Conflict):
            await service.confirm_build(session, "proposal-wrong")
        with pytest.raises(Conflict):
            await service.confirm_run(session, "build-wrong")
        proposal = session.proposal_id
        build = await service.confirm_build(session, proposal)
        with pytest.raises(Conflict):
            await service.confirm_build(session, proposal)
        await session.task
        assert session.state == State.ready_to_run
        package = service.store.get("packages", session.package_id)
        assert package["validation"]["frames"] == 180
        assert service.store.get("projects", session.project_id)["current"] is None
        archive = service.store.path("packages", session.package_id, ".zip")
        assert verify_archive(archive, package["manifest"], package["archive_sha256"])
        with pytest.raises(Conflict):
            await service.confirm_run(session, "build-wrong")
        result = await service.confirm_run(session, session.package_id)
        assert result["target"] == "pc_simulation"
        assert service.store.get("projects", session.project_id)["last_simulated_package_id"] == session.package_id
        assert service.store.get("projects", session.project_id)["current"] is None
        assert service.store.get("builds", build["id"])["status"] == "ready"
        assert (service.store.path("builds", build["id"], "") / "build-manifest.json").exists()
        archive.write_bytes(archive.read_bytes() + b"tamper")
        with pytest.raises(Conflict):
            await service.confirm_run(session, session.package_id)
        assert session.state == State.failed
    finally:
        await service.close()


async def test_new_text_invalidates_proposal(settings):
    service = Backend(settings)
    try:
        session = await proposed(service)
        old = session.proposal_id
        await service.text(session, "Hva mener du?")
        assert session.state == State.clarification_needed
        assert session.proposal_id is None
        with pytest.raises(Conflict):
            await service.confirm_build(session, old)
    finally:
        await service.close()


class BrokenProvider(MockProvider):
    def __init__(self):
        self.calls = []

    async def generate(self, summary, context, error=None, previous=None):
        self.calls.append((context, error, previous))
        return GeneratedApp(name="Broken", main_lua="function init( end", required_services=[])


async def test_three_corrections_and_no_failed_package(settings):
    provider = BrokenProvider()
    service = Backend(settings, provider)
    try:
        session = await proposed(service)
        build = await service.confirm_build(session, session.proposal_id)
        await session.task
        assert len(provider.calls) == 4
        assert all("GPIO39" in call[0] for call in provider.calls)
        assert all(call[1] for call in provider.calls[1:])
        assert session.state == State.failed
        assert service.store.get("builds", build["id"])["attempts"] == 4
        assert service.store.list("packages") == []
        assert "stdout:" in service.store.path("logs", build["id"], ".log").read_text()
    finally:
        await service.close()


async def test_version_rotation_rollback(settings):
    service = Backend(settings)
    try:
        session = await proposed(service)
        ids = []
        for i in range(3):
            if i:
                await service.text(session, "Lag en sirkel")
            await service.confirm_build(session, session.proposal_id)
            await session.task
            ids.append(session.package_id)
            await service.confirm_run(session, session.package_id)
        project = service.store.get("projects", session.project_id)
        assert [project[k] for k in ("simulated_backup", "simulated_previous", "last_simulated_package_id")] == ids
        assert [project[k] for k in ("backup", "previous", "current")] == [None, None, None]
        with pytest.raises(Conflict):
            await service.device_failed(session, ids[2])
    finally:
        await service.close()


class SlowProvider(MockProvider):
    async def generate(self, *args, **kwargs):
        await asyncio.sleep(60)


class Recorder:
    def __init__(self):
        self.messages = []

    async def send_json(self, event):
        self.messages.append(event)


async def test_heartbeat_stop_and_global_builder_lock(settings):
    settings.fire_progress_interval_seconds = 1
    service = Backend(settings, SlowProvider())
    try:
        session = await proposed(service)
        recorder = Recorder()
        session.sockets.add(recorder)
        await service.confirm_build(session, session.proposal_id)
        second = await service.start(SessionStart(device_id="second"))
        await service.text(second, "Lag en sirkel")
        with pytest.raises(Conflict):
            await service.confirm_build(second, second.proposal_id)
        await asyncio.sleep(2.2)
        pulses = [e for e in recorder.messages if e["type"] == "build_progress" and e["phase"] == "generating"]
        assert len(pulses) >= 3
        await service.stop(session)
        assert not service.build_lock.locked()
        assert service.store.get("builds", session.build_id)["status"] == "failed"
        assert not service.store.list("packages")
    finally:
        await service.close()


def receive_until(socket, kind):
    for _ in range(100):
        result = socket.receive_json()
        if result["type"] == "error":
            pytest.fail(str(result))
        if result["type"] == kind:
            return result
    pytest.fail("Expected event not received")


def test_websocket_full_flow_and_buttons_do_not_confirm(settings):
    with TestClient(create_app(settings)) as client:
        with client.websocket_connect("/ws/device") as socket:
            def send(event, **values):
                socket.send_json({"type": "device_event", "device_id": "pc-mock-01", "event": event, **values})
            send("session_start")
            start = receive_until(socket, "session_started")
            send("text", text="Lag en animasjon med en sirkel som beveger seg.")
            proposal = receive_until(socket, "build_proposal")
            send("button", button="B", action="pressed")
            send("ping")
            assert receive_until(socket, "pong")["state"] == "awaiting_build_confirmation"
            assert not client.app.state.backend.store.list("builds")
            send("build_confirm", proposal_id=proposal["proposal_id"])
            package = receive_until(socket, "package_ready")
            package_id = package["package_id"]
            assert client.get(f"/packages/{package_id}/download").status_code == 200
            send("run_confirm", package_id=package_id)
            assert receive_until(socket, "run_result")["status"] == "completed"
            send("session_stop")
            receive_until(socket, "session_stopped")
        assert client.delete(f"/projects/{start['project_id']}").status_code == 200
        assert client.get(f"/projects/{start['project_id']}").status_code == 404


async def test_disk_quota_and_recovery(settings):
    service = Backend(settings)
    session = await proposed(service)
    service.store.put("builds", "build-abandoned", {"id": "build-abandoned", "status": "building"})
    service.store.reserve(100)
    with pytest.raises(ValueError):
        service.store.reserve(service.store.max_bytes)
    await service.close()
    replacement = Backend(settings)
    try:
        assert replacement.store.get("builds", "build-abandoned")["status"] == "failed"
        assert replacement.sessions == {}
    finally:
        await replacement.close()


async def test_immediate_cancel_releases_builder(settings):
    service = Backend(settings)
    try:
        session = await proposed(service)
        await service.confirm_build(session, session.proposal_id)
        await service.stop(session)  # before the new task gets CPU time
        assert not service.build_lock.locked()
        assert service.store.get("builds", session.build_id)["status"] == "failed"
    finally:
        await service.close()


async def test_build_timeout_fails_without_package(settings):
    settings.fire_build_timeout_seconds = 1
    service = Backend(settings, SlowProvider())
    try:
        session = await proposed(service)
        await service.confirm_build(session, session.proposal_id)
        await session.task
        assert session.state == "failed"
        assert not service.build_lock.locked()
        assert not service.store.list("packages")
    finally:
        await service.close()


async def test_small_build_quota_still_records_failure(settings):
    settings.fire_max_build_kb = 8
    service = Backend(settings)
    try:
        session = await proposed(service)
        await service.confirm_build(session, session.proposal_id)
        await session.task
        assert session.state == "failed"
        assert "disk limit" in service.store.get("builds", session.build_id)["error"]
        assert not service.store.list("packages")
    finally:
        await service.close()


async def test_project_edits_reuse_saved_history_manifest_and_source(settings):
    class CaptureProvider(MockProvider):
        def __init__(self):
            self.previous = []

        async def generate(self, summary, context, error=None, previous=None):
            self.previous.append(previous)
            return await super().generate(summary, context, error, previous)

    provider = CaptureProvider()
    service = Backend(settings, provider)
    try:
        first = await proposed(service)
        await service.confirm_build(first, first.proposal_id)
        await first.task
        first_package = first.package_id
        await service.stop(first)
        edited = await service.start(SessionStart(device_id="pc-editor", project_id=first.project_id))
        assert edited.history and "last_confirmed_summary" in service.context_for(edited)
        await service.text(edited, "Lag en sirkel")
        await service.confirm_build(edited, edited.proposal_id)
        await edited.task
        assert provider.previous[0] is None and "function update" in provider.previous[1]
        folder = service.store.path("builds", edited.build_id, "")
        assert json.loads((folder / "request.json").read_text(encoding="utf-8"))["base_package_id"] == first_package
    finally:
        await service.close()

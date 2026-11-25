import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.config import Settings
from fire_backend.models import Capabilities, DeviceEvent, SessionStart
from fire_backend.protocol import dispatch
from fire_backend.service import Backend


ADMIN = "a" * 32
TOKEN = "d" * 32
OTHER = "b" * 32
CAPS = {"services": ["display", "buttons", "rgb", "imu", "time"], "max_memory": 131072,
        "max_runtime_ms": 10000, "audio_input": True, "audio_output": True}


def configured(tmp_path, **extra):
    return Settings(_env_file=None, fire_workspace=tmp_path, fire_ai_mode="mock",
                    fire_backend_token=ADMIN, fire_device_tokens=json.dumps({"fire-01": TOKEN, "fire-02": OTHER}), **extra)


class Device:
    def __init__(self, socket, device_id="fire-01", boot_id="boot-01"):
        self.socket, self.device_id, self.boot_id = socket, device_id, boot_id
        self.session_id = None
        self.counter = 0
        self.events = []

    def send(self, name, **values):
        self.counter += 1
        envelope = {"type": "device_event", "protocol_version": "0.2", "event_id": f"{self.boot_id}-{self.counter}",
                    "device_id": self.device_id, "boot_id": self.boot_id, "event": name}
        if self.session_id:
            envelope["session_id"] = self.session_id
        envelope.update(values)
        self.socket.send_json(envelope)
        return envelope

    def until(self, kind, predicate=lambda e: True):
        for _ in range(200):
            event = self.socket.receive_json()
            self.events.append(event)
            if event["type"] == kind and predicate(event):
                return event
            if event["type"] == "error":
                raise AssertionError(event)
        raise AssertionError(f"Expected {kind}")

    def ack(self, sent):
        return self.until("event_ack", lambda e: e["event_id"] == sent["event_id"])

    def start(self, **values):
        self.send("session_start", target="device", capabilities=CAPS, **values)
        started = self.until("session_started")
        self.session_id = started["session_id"]
        return started

    def build(self, text="Lag en sirkel"):
        self.send("text", text=text)
        proposal = self.until("build_proposal")
        confirmation = self.send("build_confirm", proposal_id=proposal["proposal_id"])
        install = self.until("install_request")
        return install, confirmation

    def install(self, offer):
        sent = self.send("device_install_result", package_id=offer["package_id"], install_id=offer["install_id"],
                         archive_sha256=offer["archive_sha256"], status="ok")
        self.ack(sent)

    def run(self, package_id):
        confirmation = self.send("run_confirm", package_id=package_id)
        run = self.until("run_request")
        return run, confirmation

    def healthy(self, run):
        started = self.send("app_started", package_id=run["package_id"], run_id=run["run_id"])
        self.ack(started)
        healthy = self.send("app_healthy", package_id=run["package_id"], run_id=run["run_id"])
        self.ack(healthy)

    def stop_run(self, run):
        self.send("app_stop")
        stop = self.until("stop_request")
        sent = self.send("app_stopped", package_id=run["package_id"], run_id=run["run_id"], stop_id=stop["stop_id"])
        self.ack(sent)


def headers(token=TOKEN):
    return {"Authorization": "Bearer " + token}


def test_full_device_lifecycle_and_idempotency(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            start = device.start()
            install, confirmed = device.build()
            package_id = install["package_id"]
            status = client.get("/devices/fire-01", headers=headers()).json()
            assert status["current"] is None and status["installed_package_id"] is None
            denied = device.send("run_confirm", package_id=package_id)
            device.until("error")
            device.install(install)
            status = client.get("/devices/fire-01", headers=headers()).json()
            assert status["installed_package_id"] == package_id and status["current"] is None
            socket.send_json(confirmed)
            assert device.ack(confirmed)["status"] == "duplicate"
            assert len(client.app.state.backend.store.list("builds")) == 1
            run, confirmed_run = device.run(package_id)
            assert client.get("/devices/fire-01", headers=headers()).json().get("running_package_id") is None
            device.healthy(run)
            status = client.get("/devices/fire-01", headers=headers()).json()
            assert status["running_package_id"] == status["current"] == package_id
            assert client.get(f"/projects/{start['project_id']}", headers=headers()).json()["current"] is None
            socket.send_json(confirmed_run)
            assert device.ack(confirmed_run)["status"] == "duplicate"
            assert len([c for c in client.app.state.backend.store.list("commands") if c["kind"] == "run"]) == 1
            device.stop_run(run)
            assert client.get("/devices/fire-01", headers=headers()).json()["runtime_status"] == "stopped"


def test_token_scope_download_range_and_deletion_guard(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            start = device.start()
            offer, _ = device.build()
            response = client.get(offer["download_url"], headers={**headers(), "Range": "bytes=0-31"})
            assert response.status_code == 206 and len(response.content) == 32
            assert response.headers["etag"]
            assert client.get(offer["download_url"], headers=headers(OTHER)).status_code == 403
            assert client.get(f"/sessions/{start['session_id']}", headers=headers(OTHER)).status_code == 403
            assert client.get("/devices/fire-01", headers=headers(OTHER)).status_code == 403
            device.install(offer)
            device.send("session_stop")
            device.until("session_stopped")
        assert client.delete(f"/projects/{start['project_id']}", headers=headers(ADMIN)).status_code == 409


def test_wrong_boot_hash_ids_and_event_mutation_rejected(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            install, _ = device.build()
            device.send("device_install_result", package_id=install["package_id"], install_id=install["install_id"],
                        archive_sha256="0" * 64, status="ok")
            device.until("error")
            device.send("device_install_result", package_id=install["package_id"], install_id=install["install_id"],
                        archive_sha256=install["archive_sha256"], status="ok", boot_id="old-boot")
            device.until("error")
            assert client.get("/devices/fire-01", headers=headers()).json()["installed_package_id"] is None
            device.install(install)
            run, confirmation = device.run(install["package_id"])
            device.send("app_started", package_id=run["package_id"], run_id="run-fake")
            device.until("error")
            socket.send_json({**confirmation, "package_id": "build-fake"})
            device.until("error")
            assert client.get("/devices/fire-01", headers=headers()).json().get("running_package_id") is None


def test_three_versions_and_confirmed_rollback(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            ids = []
            for _ in range(3):
                install, _ = device.build()
                ids.append(install["package_id"])
                device.install(install)
                run, _ = device.run(install["package_id"])
                device.healthy(run)
                if len(ids) < 3:
                    device.stop_run(run)
            status = client.get("/devices/fire-01", headers=headers()).json()
            assert [status[k] for k in ("backup", "previous", "current")] == ids
            device.send("app_failed", package_id=ids[2], run_id=run["run_id"], error_code="lua-error")
            rollback = device.until("rollback_request")
            assert rollback["package_id"] == ids[1] and rollback["start"] is False
            restored=client.app.state.backend.store.get('packages',ids[1])
            failed=client.app.state.backend.store.get('packages',ids[2])
            assert rollback['source_sha256']==restored['manifest']['checksum']
            assert rollback['archive_sha256']==restored['archive_sha256']!=failed['archive_sha256']
            saved=client.app.state.backend.store.get('commands',rollback['rollback_id'])
            assert (saved['source_sha256'],saved['archive_sha256'])==(rollback['source_sha256'],rollback['archive_sha256'])
            assert client.get("/devices/fire-01", headers=headers()).json()["current"] == ids[2]
            sent = device.send("rollback_result", package_id=ids[1], rollback_id=rollback["rollback_id"], status="ok")
            device.ack(sent)
            status = client.get("/devices/fire-01", headers=headers()).json()
            assert status["current"] == ids[1] and status["running_package_id"] is None


def test_resume_preserves_history_proposal_and_no_automatic_run(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            first = device.start()
            device.send("text", text="Lag en sirkel")
            proposal = device.until("build_proposal")
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            resumed = Device(socket)
            resumed.counter = 100
            started = resumed.start(resume_session_id=first["session_id"])
            snapshot = resumed.until("session_snapshot")
            assert started["session_id"] == first["session_id"]
            assert snapshot["proposal_id"] == proposal["proposal_id"]
            assert snapshot["pending_commands"] == []
            assert client.app.state.backend.session(first["session_id"]).history


def test_admin_cannot_impersonate_device_and_device_cannot_impersonate_peer(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        for token, device_id in ((ADMIN, "fire-01"), (TOKEN, "fire-02")):
            with client.websocket_connect("/ws/device", headers=headers(token)) as socket:
                device = Device(socket, device_id=device_id)
                device.send("session_start", target="device", capabilities=CAPS)
                assert device.until("error")["code"] == "event_rejected"


async def test_restart_expires_commands_and_preserves_resumable_project(tmp_path):
    settings = configured(tmp_path)
    service = Backend(settings)
    request = SessionStart(device_id="fire-01", target="device", protocol_version="0.2", boot_id="boot-01", capabilities=Capabilities(**CAPS))
    session = await service.start(request, principal="fire-01")
    await service.text(session, "Lag en sirkel")
    await service.confirm_build(session, session.proposal_id)
    await session.task
    package_id = session.package_id
    await service.close()
    replacement = Backend(settings)
    try:
        resumed = await replacement.start(request.model_copy(update={"resume_session_id": session.id}), principal="fire-01")
        assert resumed.package_id == package_id
        assert resumed.state == "awaiting_install"
        old_commands = [c for c in replacement.store.list("commands") if c["status"] == "unknown"]
        assert old_commands
        assert not replacement.pending_commands(resumed)
        assert replacement.device_record(resumed)["current"] is None
    finally:
        await replacement.close()


async def test_capability_mismatch_never_offers_invalid_package(tmp_path):
    service = Backend(configured(tmp_path,fire_max_corrections=3))
    try:
        session = await service.start(SessionStart(device_id="fire-01", target="device", protocol_version="0.2", boot_id="boot-01",
                                                 capabilities=Capabilities(**{**CAPS, "services": ["display"]})), principal="fire-01")
        await service.text(session, "Lag RGB")
        await service.confirm_build(session, session.proposal_id)
        await session.task
        assert session.state == "failed"
        assert service.store.list("packages") == []
        assert service.store.get("builds", session.build_id)["attempts"] == 4
    finally:
        await service.close()


async def test_expired_run_receipt_cannot_claim_running(tmp_path):
    service = Backend(configured(tmp_path))
    try:
        session = await service.start(SessionStart(device_id="fire-01", target="device", protocol_version="0.2", boot_id="boot-01", capabilities=Capabilities(**CAPS)), principal="fire-01")
        await service.text(session, "Lag en sirkel")
        await service.confirm_build(session, session.proposal_id)
        await session.task
        install = service.pending_commands(session)[0]
        receipt = DeviceEvent(device_id=session.device_id, event="device_install_result", boot_id=session.boot_id,
                              install_id=install["id"], package_id=session.package_id, archive_sha256=install["archive_sha256"], status="ok")
        await service.device_receipt(session, receipt)
        result = await service.confirm_run(session, session.package_id)
        command = service.store.get("commands", result["run_id"])
        command["expires_at"] = time.time() - 1
        service.store.put("commands", command["id"], command)
        with pytest.raises(ValueError):
            await service.device_receipt(session, DeviceEvent(device_id=session.device_id, event="app_started", boot_id=session.boot_id,
                                                              run_id=command["id"], package_id=session.package_id))
        assert service.device_record(session)["running_package_id"] is None
    finally:
        await service.close()

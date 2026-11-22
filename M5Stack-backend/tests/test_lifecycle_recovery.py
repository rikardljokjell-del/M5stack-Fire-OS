import json
import time

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.config import Settings
from fire_backend.models import Capabilities, DeviceEvent, Manifest, SessionStart
from fire_backend.service import Backend, Conflict

from test_device_protocol import CAPS, Device, configured, headers


def test_natural_stop_and_late_stop_receipt_cannot_clear_a_new_run(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            offer, _ = device.build()
            device.install(offer)
            run, _ = device.run(offer["package_id"])
            device.healthy(run)
            device.send("app_stop")
            stop = device.until("stop_request")
            device.ack(device.send("app_stopped", package_id=run["package_id"], run_id=run["run_id"], reason="runtime_limit"))
            next_run, _ = device.run(offer["package_id"])
            device.healthy(next_run)
            device.send("app_stopped", package_id=run["package_id"], run_id=run["run_id"], stop_id=stop["stop_id"])
            device.until("error")
            assert client.get("/devices/fire-01", headers=headers()).json()["active_run_id"] == next_run["run_id"]


def test_superseded_install_and_failed_install_preserve_current(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            old, _ = device.build()
            new, _ = device.build()
            device.send("device_install_result", package_id=old["package_id"], install_id=old["install_id"], archive_sha256=old["archive_sha256"], status="ok")
            device.until("error")
            device.ack(device.send("device_install_result", package_id=new["package_id"], install_id=new["install_id"], archive_sha256=new["archive_sha256"], status="failed", error_code="sd-full"))
            status = client.get("/devices/fire-01", headers=headers()).json()
            assert status["current"] is None and status["installed_package_id"] is None


def test_device_reboot_invalidates_previous_session_without_mutating_history(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            old = Device(socket)
            old_start = old.start()
            old_offer, _ = old.build()
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            rebooted = Device(socket, boot_id="boot-02")
            new_start = rebooted.start()
            assert new_start["session_id"] != old_start["session_id"]
            rebooted.send("device_install_result", package_id=old_offer["package_id"], install_id=old_offer["install_id"], archive_sha256=old_offer["archive_sha256"], status="ok")
            rebooted.until("error")
            assert client.get("/devices/fire-01", headers=headers()).json()["installed_package_id"] is None


async def test_resume_expiry_and_project_version_isolation(tmp_path):
    service = Backend(configured(tmp_path))
    request = SessionStart(device_id="fire-01", target="device", protocol_version="0.2", boot_id="boot-01", capabilities=Capabilities(**CAPS))
    try:
        first = await service.start(request, principal="fire-01")
        device = service.device_record(first)
        device.update(current="build-history", projects={first.project_id: {"current": "build-history", "previous": None, "backup": None}})
        service.store.put("devices", device["id"], device)
        await service.stop(first)
        second = await service.start(request, principal="fire-01")
        selected = service.device_record(second)
        assert selected["current"] is None
        assert selected["projects"][first.project_id]["current"] == "build-history"
        await service.detach(second, None)
        second.disconnected_at = time.time() - service.settings.fire_session_resume_seconds - 1
        service.persist(second)
        await service.expire_sessions()
        with pytest.raises(Conflict):
            await service.start(request.model_copy(update={"resume_session_id": second.id}), principal="fire-01")
        assert service.sessions == {}
    finally:
        await service.close()


async def test_durable_processing_tombstone_does_not_execute_on_replay(tmp_path):
    from fire_backend.protocol import begin_event, dispatch
    service = Backend(configured(tmp_path))
    try:
        request = SessionStart(device_id="fire-01", target="device", protocol_version="0.2", boot_id="boot-01", capabilities=Capabilities(**CAPS))
        session = await service.start(request, principal="fire-01")
        await service.text(session, "Lag en sirkel")
        event = DeviceEvent(protocol_version="0.2", event_id="interrupted-event", device_id=session.device_id, session_id=session.id,
                            boot_id=session.boot_id, event="build_confirm", proposal_id=session.proposal_id)
        begin_event(service, event)  # crash occurred before recording effect completion
        result = await dispatch(service, session, event)
        assert result["status"] == "unknown"
        assert service.store.list("builds") == []
    finally:
        await service.close()


@pytest.mark.parametrize("tokens", [{"fire-01": "short"}, {"fire-01": "d" * 32, "fire-02": "d" * 32}, ["invalid"]])
def test_invalid_scoped_token_configuration_rejected(tokens):
    with pytest.raises(ValueError):
        Settings(_env_file=None, fire_device_tokens=json.dumps(tokens))


def test_event_specific_receipts_require_correlating_fields():
    with pytest.raises(ValueError):
        DeviceEvent(protocol_version="0.2", event_id="event-1", session_id="session-1", device_id="fire-01", event="app_started")


async def test_legacy_current_migrates_only_into_simulation_history(tmp_path):
    service = Backend(configured(tmp_path))
    service.store.put("projects", "app-old", {"id": "app-old", "current": "build-old", "previous": "build-older", "backup": None, "candidate": None})
    await service.close()
    recovered = Backend(configured(tmp_path))
    try:
        project = recovered.store.get("projects", "app-old")
        assert project["last_simulated_package_id"] == "build-old"
        assert project["current"] is None and project["previous"] is None
    finally:
        await recovered.close()


async def test_delivery_failure_preserves_valid_package_and_can_retry_without_ai(tmp_path):
    from fire_backend.protocol import dispatch
    service = Backend(configured(tmp_path))
    original_offer = service.offer_install

    async def broken_offer(*args):
        raise ValueError("Simulated delivery failure")

    try:
        session = await service.start(SessionStart(device_id="fire-01", target="device", protocol_version="0.2", boot_id="boot-01", capabilities=Capabilities(**CAPS)), principal="fire-01")
        service.offer_install = broken_offer
        await service.text(session, "Lag en sirkel")
        await service.confirm_build(session, session.proposal_id)
        await session.task
        assert session.state == "failed" and session.package_id
        assert service.store.get("builds", session.build_id)["status"] == "ready"
        assert service.store.get("packages", session.package_id)
        service.offer_install = original_offer
        result = await dispatch(service, session, DeviceEvent(protocol_version="0.2", device_id=session.device_id, session_id=session.id,
                              boot_id=session.boot_id, event_id="retry-delivery", event="install_retry", package_id=session.package_id))
        assert result["install_id"] and session.state == "awaiting_install"
        assert len(service.store.list("builds")) == 1
    finally:
        await service.close()

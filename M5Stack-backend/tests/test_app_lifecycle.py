import asyncio
import hashlib
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from fire_backend.ai import MockProvider
from fire_backend.app import create_app
from fire_backend.models import APP_EVENT_DEFAULTS, DeviceEvent, SessionStart
from fire_backend.protocol import begin_event, dispatch
from fire_backend.service import Backend
from fire_backend.storage import canonical

from test_device_protocol import ADMIN, OTHER, CAPS, Device, configured, headers


def select(device, mode="new", **values):
    sent = device.send("app_select", app_mode=mode, **values)
    chosen = device.until("app_selected")
    device.ack(sent)
    return chosen


def inventory(device, apps, ready=True, complete=True):
    device.ack(device.send("app_inventory", apps=apps, storage_ready=ready, complete=complete))


def library(client):
    return client.get("/desktop/status", headers=headers(ADMIN)).json()["apps"]


def test_device_delete_preserves_history_blocks_stale_commands_and_gates_pc_delete(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            started = device.start()
            request = device.until("app_inventory_request")
            assert request["boot_id"] == device.boot_id
            offer, _ = device.build()
            device.install(offer)
            run, _ = device.run(offer["package_id"])
            device.healthy(run)
            app_id = library(client)[0]["app_id"]
            url = "/projects/" + started["project_id"]
            assert client.delete(url, headers=headers(ADMIN)).status_code == 409
            device.ack(device.send("app_deleted", app_id=app_id))
            row = library(client)[0]
            assert row["device_presence"] == "deleted" and row["had_install_receipt"]
            assert not row["installed_receipt"] and not row["running"] and not row["current_healthy"]
            assert client.get(f"/packages/{offer['package_id']}", headers=headers()).status_code == 200
            device.send("run_confirm", package_id=offer["package_id"])
            assert device.until("error")["code"] == "event_rejected"
            device.send("device_install_result", package_id=offer["package_id"], install_id=offer["install_id"],
                        status="ok", archive_sha256=offer["archive_sha256"])
            device.until("error")
            assert client.delete(url, headers=headers(ADMIN)).status_code == 409  # Current conversation still selects it.
            select(device)
            assert library(client)[0]["can_delete_backend"]
            assert client.delete(url, headers=headers()).status_code == 403
            assert client.delete(url, headers=headers(ADMIN)).status_code == 200
            assert not library(client)
            assert client.get(f"/packages/{offer['package_id']}/download", headers=headers()).status_code == 404
            assert client.get(url, headers=headers(ADMIN)).status_code == 404


def test_only_complete_ready_inventory_confirms_absence_and_reconnect_requires_fresh_report(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            started = device.start()
            offer, _ = device.build(); device.install(offer)
            app_id = library(client)[0]["app_id"]
            url = "/projects/" + started["project_id"]
            select(device)
            inventory(device, [], ready=False)
            assert library(client)[0]["device_presence"] == "present"
            assert client.delete(url, headers=headers(ADMIN)).status_code == 409
            inventory(device, [], complete=False)
            assert client.delete(url, headers=headers(ADMIN)).status_code == 409
            inventory(device, [])
            assert library(client)[0]["device_presence"] == "missing" and library(client)[0]["can_delete_backend"]
        assert client.delete(url, headers=headers(ADMIN)).status_code == 409  # Offline is insufficient.
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket, boot_id="boot-01")
            device.counter = 50
            device.start()
            assert client.delete(url, headers=headers(ADMIN)).status_code == 409  # Same boot, new connection.
            inventory(device, [])
            assert library(client)[0]["can_delete_backend"]
            inventory(device, [], ready=False)
            inventory(device, [], complete=False)
            assert client.delete(url, headers=headers(ADMIN)).status_code == 409
            inventory(device, [])
            assert client.delete(url, headers=headers(ADMIN)).status_code == 200


class CaptureProvider(MockProvider):
    def __init__(self):
        self.previous = []

    async def generate(self, summary, context, error=None, previous=None):
        self.previous.append(previous)
        result = await super().generate(summary, context, error, previous)
        return result.model_copy(update={"main_lua": result.main_lua + "\n-- version " + str(len(self.previous))})


def test_update_selected_old_version_preserves_folder_and_increments_version(tmp_path):
    provider = CaptureProvider()
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True), provider)) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket); started = device.start()
            first, _ = device.build(); device.install(first)
            second, _ = device.build(); device.install(second)
            rows = library(client)
            app_id = rows[0]["app_id"]
            chosen = select(device, "update", app_id=app_id, base_package_id=first["package_id"])
            assert chosen["project_id"] == started["project_id"]
            third, _ = device.build()
            versions = client.get(f"/projects/{started['project_id']}/versions", headers=headers()).json()
            assert [p["version"] for p in versions] == ["0.1.3", "0.1.2", "0.1.1"]
            assert all(p["manifest"]["id"] == app_id for p in versions)
            assert "-- version 1" in provider.previous[-1] and "-- version 2" not in provider.previous[-1]
            before = len(provider.previous)
            selected = select(device)
            assert selected["project_id"] != started["project_id"] and not selected["base_package_id"]
            assert len(provider.previous) == before  # Selection never calls AI.
            assert client.get("/devices/fire-01/apps", headers=headers(OTHER)).status_code == 403
            assert client.get(f"/projects/{started['project_id']}/versions", headers=headers(OTHER)).status_code == 403
            device.send("app_select", app_mode="update", project_id=started["project_id"], base_package_id="build-unknown")
            device.until("error")
            assert client.app.state.backend.session(device.session_id).project_id == selected["project_id"]


def test_start_accepts_scoped_sd_app_id_and_explicit_new_does_not_resume_previous(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket); original = device.start()
            offer, _ = device.build(); device.install(offer)
            app_id = library(client)[0]["app_id"]
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket, boot_id="boot-02")
            updated = device.start(project_id=app_id)
            assert updated["project_id"] == original["project_id"] and updated["app_mode"] == "update"
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket, boot_id="boot-02"); device.counter = 10
            fresh = device.start(app_mode="new")
            assert fresh["project_id"] != original["project_id"] and not fresh["base_package_id"]


def test_foreign_selection_and_inventory_do_not_change_other_device(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            owner = Device(socket); project = owner.start()
            offer, _ = owner.build(); owner.install(offer)
            app_id = library(client)[0]["app_id"]
        with client.websocket_connect("/ws/device", headers=headers(OTHER)) as socket:
            other = Device(socket, device_id="fire-02", boot_id="boot-other"); before = other.start()
            other.send("app_select", app_mode="update", project_id=project["project_id"])
            other.until("error")
            other.send("app_inventory", apps=[{"app_id": app_id, "package_id": offer["package_id"]}],
                       storage_ready=True, complete=True)
            other.until("error")
            session = client.app.state.backend.session(other.session_id)
            assert session.project_id == before["project_id"]
            assert "apps" not in client.app.state.backend.device_record(session)


def test_invalid_schema_diagnostics_do_not_echo_values_or_extra_field_names(tmp_path, caplog):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            socket.send_json({"type": "device_event", "protocol_version": "0.2", "event": "listen_start",
                "device_id": "fire-01", "event_id": "evt-invalid", "turn_id": "turn-invalid", "sk-private-property": "sk-private-value"})
            reply = socket.receive_json()
            assert reply["code"] == "session_start_rejected" and "extra_fields" in reply["diagnostic_message"]
            assert "sk-private" not in json.dumps(reply) and "sk-private" not in caplog.text
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            socket.send_json({"type": "device_event", "protocol_version": "0.2", "event": "listen_start",
                "device_id": "fire-01", "event_id": "evt-invalid-2", "turn_id": "turn-invalid"})
            assert "session_id" in socket.receive_json()["diagnostic_message"]


@pytest.mark.parametrize("payload", [{"storage_ready": True, "complete": True},
    {"storage_ready": True, "complete": True, "apps": [{"app_id": "same"}, {"app_id": "same"}]},
    {"storage_ready": "yes", "complete": True, "apps": []}])
def test_bad_inventory_cannot_be_interpreted_as_empty_sd(payload):
    with pytest.raises(ValueError):
        DeviceEvent(event="app_inventory", device_id="fire-01", event_id="evt-test", protocol_version="0.2",
                    session_id="session-test", boot_id="boot-test", **payload)


class Peer:
    def __init__(self):
        self.events = []
    async def send_json(self, value):
        self.events.append(value)


class GateProvider(MockProvider):
    def __init__(self):
        self.block = False
        self.started, self.release = asyncio.Event(), asyncio.Event()
    async def generate(self, *args, **kwargs):
        if self.block:
            self.started.set(); await self.release.wait()
        return await super().generate(*args, **kwargs)


async def test_delete_during_build_and_restart_never_resurrects_app(tmp_path):
    provider = GateProvider()
    service = Backend(configured(tmp_path), provider)
    request = SessionStart(device_id="fire-01", protocol_version="0.2", target="device", boot_id="boot-race", capabilities=CAPS)
    session = await service.start(request, Peer(), "fire-01")
    async def event(name, **data):
        return await dispatch(service, session, DeviceEvent(device_id="fire-01", protocol_version="0.2", boot_id=session.boot_id,
            session_id=session.id, event_id="evt-"+name, event=name, **data))
    try:
        await service.text(session, "Lag en sirkel"); await service.confirm_build(session, session.proposal_id); await session.task
        first = service.store.get("packages", session.package_id)
        install = service.pending_commands(session)[0]
        await event("device_install_result", package_id=first["id"], install_id=install["id"], status="ok", archive_sha256=first["archive_sha256"])
        provider.block = True
        await service.text(session, "Lag en sirkel"); await service.confirm_build(session, session.proposal_id)
        await asyncio.wait_for(provider.started.wait(), 5)
        await event("app_deleted", app_id=first["manifest"]["id"])
        provider.release.set(); await session.task
        assert not session.install_permitted and session.state == "failed"
        assert len(service.store.list("packages")) == 2
        assert len([c for c in service.store.list("commands") if c["kind"] == "install"]) == 1
    finally:
        await service.close()
    restored = Backend(configured(tmp_path))
    try:
        resumed = await restored.start(request, Peer(), "fire-01")
        assert not resumed.install_permitted and resumed.state == "failed"
        assert not restored.pending_commands(resumed)
    finally:
        await restored.close()


async def test_pre_extension_event_replay_hash_still_matches(tmp_path):
    service = Backend(configured(tmp_path))
    try:
        event = DeviceEvent(device_id="fire-01", protocol_version="0.2", event="ping", event_id="evt-legacy",
                            session_id="session-old", boot_id="boot-old")
        old = {k: v for k, v in event.model_dump().items() if k not in APP_EVENT_DEFAULTS}
        service.store.put("events", event.event_id, {"id": event.event_id, "device_id": event.device_id,
            "digest": hashlib.sha256(canonical(old)).hexdigest(), "status": "completed", "result": {"status": "ok"}})
        record, duplicate = begin_event(service, event)
        assert record is None and duplicate["status"] == "duplicate"
    finally:
        await service.close()

"""Offline completion receipts; Mock/TestClient does not establish physical runs."""
import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fire_backend import devices
from fire_backend.ai import MockProvider
from fire_backend.app import create_app
from test_device_protocol import Device, configured, headers
from test_session_reconnect import bounded_receive


class CountingMock(MockProvider):
    def __init__(self):
        self.calls = {"dialog": 0, "generate": 0, "review": 0}

    async def dialog(self, *args, **kwargs):
        self.calls["dialog"] += 1
        return await super().dialog(*args, **kwargs)

    async def generate(self, *args, **kwargs):
        self.calls["generate"] += 1
        return await super().generate(*args, **kwargs)

    async def review(self, *args, **kwargs):
        self.calls["review"] += 1
        return await super().review(*args, **kwargs)


def reply(device, sent, kind):
    """Observe both the intended reply and its rejection; receive is bounded to 3s."""
    for _ in range(100):
        packet = device.socket.receive_json()
        device.events.append(packet)
        if packet["type"] == "error":
            return packet
        if packet["type"] == kind and packet.get("event_id") == sent["event_id"]:
            return packet
    raise AssertionError(f"No {kind} for {sent['event_id']}")


@contextmanager
def run_flow(tmp_path, stage="healthy"):
    provider = CountingMock()
    with TestClient(create_app(configured(tmp_path), provider)) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            bounded_receive(socket)
            device = Device(socket)
            started = device.start()
            offer, confirmation = device.build()
            assert any(packet["type"] == "event_ack" and packet.get("event_id") == confirmation["event_id"]
                       for packet in device.events)
            device.install(offer)
            run, confirmation = device.run(offer["package_id"])
            device.ack(confirmation)
            service = client.app.state.backend
            source = service.store.get("packages", offer["package_id"])["manifest"]["checksum"]
            if stage in {"started", "healthy"}:
                device.ack(device.send("app_started", package_id=offer["package_id"],
                                       run_id=run["run_id"], source_sha256=source))
            if stage == "healthy":
                device.ack(device.send("app_healthy", package_id=offer["package_id"], run_id=run["run_id"]))
            command = service.store.get("commands", run["run_id"])
            assert command["status"] == stage
            yield SimpleNamespace(client=client, device=device, service=service, offer=offer,
                                  run=run, command=command, started=started, provider=provider)


def work_snapshot(flow):
    return copy.deepcopy({"calls": flow.provider.calls,
                          "builds": flow.service.store.list("builds"),
                          "packages": flow.service.store.list("packages"),
                          "usage": flow.service.usage.records(),
                          "commands": flow.service.store.list("commands"),
                          "device": flow.service.store.get("devices", flow.device.device_id)})


def assert_no_work(flow, before):
    after = work_snapshot(flow)
    for name in ("calls", "builds", "packages", "usage"):
        assert after[name] == before[name], name
    assert {row["id"] for row in after["commands"]} == {row["id"] for row in before["commands"]}
    for command in before["commands"]:
        if command["id"] != flow.run["run_id"]:
            assert flow.service.store.get("commands", command["id"]) == command


def advance_grant_clock(monkeypatch, flow, *, expired=True):
    # Replace only the lifecycle module clock: never sleep or alter the global
    # session/provider clock, the recorded grant or its configured duration.
    now = flow.command["expires_at"] + (1 if expired else -1)
    monkeypatch.setattr(devices, "time", SimpleNamespace(time=lambda: now))


@pytest.mark.parametrize("stage", ["started", "healthy"])
@pytest.mark.parametrize("expired", [False, True], ids=["before-grant-expiry", "after-grant-expiry"])
def test_healthy_run_natural_exit_allows_new_app_without_new_work(tmp_path, monkeypatch, expired, stage):
    with run_flow(tmp_path, stage) as flow:
            device, service, run, offer = flow.device, flow.service, flow.run, flow.offer
            current = service.store.get("devices", device.device_id)
            assert current["active_run_id"] == run["run_id"]
            assert current["running_package_id"] == offer["package_id"]
            before = work_snapshot(flow)
            projects = copy.deepcopy(service.store.list("projects"))
            advance_grant_clock(monkeypatch, flow, expired=expired)
            stopped = device.send("app_stopped", run_id=run["run_id"],
                                  package_id=offer["package_id"], reason="user_exit")
            stop_reply = reply(device, stopped, "event_ack")
            selected = device.send("app_select", app_mode="new")
            select_reply = reply(device, selected, "app_selected")
            current = service.store.get("devices", device.device_id)

            # This assertion preserves both observable failures when completion
            # is rejected and the stale current run then blocks app selection.
            assert stop_reply["type"] == "event_ack", json.dumps({
                "natural_stop": stop_reply,
                "select_new_app": select_reply,
                "current_run": {key: current.get(key) for key in
                                ("active_run_id", "pending_run_id", "running_package_id", "runtime_status")},
            }, ensure_ascii=False, indent=2)
            assert stop_reply["result"] == {"status": "recorded", "package_id": offer["package_id"]}
            assert select_reply["type"] == "app_selected", select_reply
            device.ack(selected)
            assert select_reply["project_id"] != flow.started["project_id"]
            after_projects = service.store.list("projects")
            assert {row["id"] for row in after_projects} - {row["id"] for row in projects} == {select_reply["project_id"]}
            assert len(after_projects) == len(projects) + 1
            for project in projects:
                assert service.store.get("projects", project["id"]) == project
            assert current.get("active_run_id") is None
            assert current.get("pending_run_id") is None
            assert current.get("running_package_id") is None
            assert current["runtime_status"] == "stopped"
            completed = service.store.get("commands", run["run_id"])
            assert completed["status"] == "stopped"
            assert completed["expires_at"] == flow.command["expires_at"]
            assert_no_work(flow, before)


@pytest.mark.parametrize("event", ["app_started", "app_healthy", "app_stopped"])
def test_expired_pending_grant_never_authorizes_start_or_completion(tmp_path, monkeypatch, event):
    with run_flow(tmp_path, "pending") as flow:
        advance_grant_clock(monkeypatch, flow)
        before = work_snapshot(flow)
        fields = {"run_id": flow.run["run_id"], "package_id": flow.offer["package_id"]}
        if event == "app_stopped":
            fields["reason"] = "user_exit"
        sent = flow.device.send(event, **fields)
        rejected = reply(flow.device, sent, "event_ack")
        assert rejected["type"] == "error", rejected
        assert work_snapshot(flow) == before


@pytest.mark.parametrize("mismatch", ["owner", "session", "boot", "package", "not-current",
                                       "status-failed", "status-unknown", "status-superseded"])
def test_expired_completion_keeps_all_current_scope_guards(tmp_path, monkeypatch, mismatch):
    with run_flow(tmp_path) as flow:
        command = copy.deepcopy(flow.command)
        fields = {"run_id": flow.run["run_id"], "package_id": flow.offer["package_id"], "reason": "user_exit"}
        if mismatch in {"owner", "session", "boot"}:
            key = {"owner": "device_id", "session": "session_id", "boot": "boot_id"}[mismatch]
            command[key] = {"owner": "fire-02", "session": "session-other", "boot": "boot-other"}[mismatch]
            flow.service.store.put("commands", command["id"], command)
        elif mismatch == "package":
            fields["package_id"] = "build-other"
        elif mismatch == "not-current":
            # A later current run must never be cleared by its predecessor's
            # completion. Only this isolated guard fixture changes the pointer.
            later = {**command, "id": "run-later-current"}
            flow.service.store.put("commands", later["id"], later)
            device = flow.service.store.get("devices", flow.device.device_id)
            device["active_run_id"] = later["id"]
            flow.service.store.put("devices", device["id"], device)
        else:
            command["status"] = mismatch.removeprefix("status-")
            flow.service.store.put("commands", command["id"], command)
        advance_grant_clock(monkeypatch, flow)
        before = work_snapshot(flow)
        sent = flow.device.send("app_stopped", **fields)
        rejected = reply(flow.device, sent, "event_ack")
        assert rejected["type"] == "error", rejected
        assert work_snapshot(flow) == before


def test_expired_natural_stop_replay_is_idempotent_and_fresh_stop_cannot_revive_run(tmp_path, monkeypatch):
    with run_flow(tmp_path) as flow:
        advance_grant_clock(monkeypatch, flow)
        sent = flow.device.send("app_stopped", run_id=flow.run["run_id"],
                                package_id=flow.offer["package_id"], reason="user_exit")
        recorded = reply(flow.device, sent, "event_ack")
        assert recorded["type"] == "event_ack", recorded
        assert recorded["status"] == "accepted"
        before = work_snapshot(flow)
        flow.device.socket.send_json(sent)
        duplicate = reply(flow.device, sent, "event_ack")
        assert duplicate["type"] == "event_ack" and duplicate["status"] == "duplicate"
        assert duplicate["result"] == recorded["result"]
        assert work_snapshot(flow) == before
        fresh = flow.device.send("app_stopped", run_id=flow.run["run_id"],
                                 package_id=flow.offer["package_id"], reason="user_exit")
        rejected = reply(flow.device, fresh, "event_ack")
        assert rejected["type"] == "error", rejected
        assert work_snapshot(flow) == before
        project_ids = {project["id"] for project in flow.service.store.list("projects")}
        selected = flow.device.send("app_select", app_mode="new")
        selected_reply = reply(flow.device, selected, "app_selected")
        assert selected_reply["type"] == "app_selected", selected_reply
        flow.device.ack(selected)
        assert {project["id"] for project in flow.service.store.list("projects")} - project_ids == {selected_reply["project_id"]}
        assert_no_work(flow, before)

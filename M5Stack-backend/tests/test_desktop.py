import asyncio
import json
import os
from pathlib import Path
import socket
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.desktop_config import DesktopConfig, DesktopStore, WindowsVault
from fire_backend.desktop_runtime import DesktopRuntime, WorkspaceLock, check_api_key

from test_device_protocol import Device, configured, headers, ADMIN
from test_handoff import native_start
from test_audio import recording, wav_data


class MemoryVault:
    def __init__(self):
        self.values = {}

    def get(self, target):
        return self.values.get(target, "")

    def put(self, target, value):
        if value:
            self.values[target] = value
        else:
            self.values.pop(target, None)


def test_desktop_secrets_never_enter_settings_file_or_ambient_env(tmp_path, monkeypatch):
    vault = MemoryVault()
    store = DesktopStore(tmp_path, vault)
    key = "sk-test-private-" + uuid.uuid4().hex
    token = store.secret("device/m5stack-fire-01")
    store.save(store.config, api_key=key)
    persisted = store.path.read_text()
    assert key not in persisted and token not in persisted
    assert store.secret("admin") not in persisted
    monkeypatch.setenv("OPENAI_API_KEY", "sk-unrelated-terminal-key")
    monkeypatch.setenv("FIRE_BACKEND_PORT", "9999")
    monkeypatch.setenv("FIRE_AI_MODE", "openai")
    restored = DesktopStore(tmp_path, vault)
    settings = restored.settings()
    assert settings.openai_api_key.get_secret_value() == key
    assert settings.fire_backend_port == 8765 and settings.fire_ai_mode == "mock"
    assert settings.fire_backend_host == "0.0.0.0" and settings.fire_desktop_enabled
    assert settings.device_tokens()["m5stack-fire-01"] == token
    restored.save(restored.config, api_key="")
    assert restored.secret("openai") == ""


def test_invalid_save_does_not_replace_working_config_or_credentials(tmp_path):
    vault = MemoryVault()
    store = DesktopStore(tmp_path, vault)
    before = dict(vault.values)
    with pytest.raises(ValueError):
        store.save(store.config, api_key="contains whitespace private", device_tokens={"m5stack-fire-01": "bad"})
    assert vault.values == before
    with pytest.raises(ValueError):
        DesktopConfig(device_ids=["INVALID ID"])
    with pytest.raises(ValueError):
        DesktopConfig(port=80)


@pytest.mark.skipif(os.name != "nt", reason="Windows credential round-trip")
def test_windows_credential_round_trip_uses_owned_temporary_target():
    vault = WindowsVault()
    target = "FIREBackend/test-" + uuid.uuid4().hex
    try:
        assert vault.get(target) == ""
        vault.put(target, "private-test-æøå")
        assert vault.get(target) == "private-test-æøå"
        vault.put(target, "replacement")
        assert vault.get(target) == "replacement"
    finally:
        vault.put(target, "")
    assert vault.get(target) == ""


def test_workspace_lock_rejects_second_writer_and_releases(tmp_path):
    lock = WorkspaceLock(tmp_path)
    try:
        with pytest.raises((ValueError, PermissionError)):
            WorkspaceLock(tmp_path)
    finally:
        lock.close()
    second = WorkspaceLock(tmp_path)
    second.close()


def test_desktop_endpoints_are_disabled_by_default_and_scoped(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        assert client.get("/desktop/status", headers=headers(ADMIN)).status_code == 403
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        assert client.get("/desktop/status").status_code == 401
        assert client.get("/desktop/status", headers=headers()).status_code == 403
        assert client.get("/desktop/status", headers={**headers(ADMIN), "Origin": "http://example.com"}).status_code == 403
        response = client.get("/desktop/status", headers=headers(ADMIN))
        assert response.status_code == 200 and response.json()["physical_verified"] is False


@pytest.mark.asyncio
async def test_desktop_api_rejects_network_clients_even_with_admin(tmp_path):
    app = create_app(configured(tmp_path, fire_desktop_enabled=True))
    transport = httpx.ASGITransport(app=app, client=("192.168.1.20", 55000))
    async with httpx.AsyncClient(transport=transport, base_url="http://backend") as client:
        assert (await client.get("/desktop/status", headers=headers(ADMIN))).status_code == 403


def test_desktop_text_targets_real_session_without_implicit_build_or_run(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            native_start(device)
            url = f"/desktop/sessions/{device.session_id}/text"
            assert client.post(url, json={"text": "Lag en sirkel"}, headers=headers()).status_code == 403
            assert client.post(url, json={"text": "Lag en sirkel", "extra": 1}, headers=headers(ADMIN)).status_code == 422
            assert client.post(url, json={"text": "Lag en sirkel"}, headers=headers(ADMIN)).status_code == 200
            proposal = device.until("build_proposal")
            snapshot = client.get("/desktop/status", headers=headers(ADMIN)).json()
            assert snapshot["builds"] == []
            assert snapshot["sessions"][0]["proposal_id"] == proposal["proposal_id"]
            assert snapshot["sessions"][0]["history"][-1]["role"] == "assistant"
        assert client.post(url, json={"text": "Lag en sirkel"}, headers=headers(ADMIN)).status_code == 409


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_desktop_runtime_start_stop_restart_and_real_http(tmp_path, host):
    runtime = DesktopRuntime()
    store = DesktopStore(tmp_path, MemoryVault())
    if host == "::1" and not socket.has_ipv6:
        pytest.skip("IPv6 loopback unavailable")
    with socket.socket(socket.AF_INET6 if host == "::1" else socket.AF_INET) as available:
        available.bind((host, 0))
        port = available.getsockname()[1]
    store.save(store.config.model_copy(update={"port": port, "allow_lan": False}))
    try:
        for _ in range(2):
            runtime.start(store.settings().model_copy(update={"fire_backend_host": host}))
            deadline = time.monotonic() + 8
            while not runtime.ready and time.monotonic() < deadline:
                time.sleep(0.05)
            assert runtime.ready, runtime.failure
            assert runtime.request("GET", "/health")["mode"] == "mock"
            assert runtime.snapshot()["sessions"] == []
            runtime.stop()
            assert not runtime.alive
    finally:
        runtime.stop()


def test_desktop_requires_key_before_starting_openai(tmp_path):
    store = DesktopStore(tmp_path, MemoryVault())
    store.save(store.config.model_copy(update={"mode": "openai"}))
    runtime = DesktopRuntime()
    with pytest.raises(ValueError, match="API-nøkkel"):
        runtime.start(store.settings())
    assert not runtime.alive


def test_new_native_input_only_profile_transcribes_without_speech(tmp_path):
    from fire_backend.ai import MockProvider
    from test_handoff import NATIVE
    class InputOnlyProvider(MockProvider):
        speech_calls = 0

        async def speech(self, text):
            self.speech_calls += 1
            yield b"\x00\x01"

    provider = InputOnlyProvider()
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True, fire_audio_enabled=True), provider)) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.send("session_start", target="device", capabilities={**NATIVE, "audio_input": True})
            start = device.until("session_started")
            device.session_id = start["session_id"]
            assert start["effective_capabilities"]["conversation_audio"]["input_enabled"]
            assert not start["effective_capabilities"]["conversation_audio"]["output_enabled"]
            assert device.until("capability_status")["code"] == "audio_output_unavailable"
            turn_id = recording(device)
            response = client.post(f"/sessions/{device.session_id}/audio/{turn_id}", content=wav_data(),
                                   headers={**headers(), "Content-Type": "audio/wav"})
            assert response.status_code == 202
            assert device.until("transcript")["mode"] == "mock"
            assert device.until("build_proposal")["proposal_id"]
            assert provider.speech_calls == 0
            assert client.app.state.backend.store.list("builds") == []
            assert not list(tmp_path.glob("audio/*.pcm"))


def test_desktop_cannot_claim_an_occupied_port_or_stop_its_owner(tmp_path):
    store = DesktopStore(tmp_path, MemoryVault())
    runtime = DesktopRuntime()
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        store.save(store.config.model_copy(update={"port": listener.getsockname()[1], "allow_lan": False}))
        runtime.start(store.settings())
        runtime.thread.join(timeout=5)
        assert not runtime.ready and runtime.failure
        runtime.stop()
        assert listener.getsockname()[1] == store.config.port


def test_api_check_does_not_generate_and_does_not_expose_provider_error(monkeypatch):
    import openai
    class Rejected:
        def __init__(self, **kwargs):
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def list(self):
            raise RuntimeError("private-key-and-raw-provider-body")
    monkeypatch.setattr(openai, "OpenAI", Rejected)
    with pytest.raises(ValueError) as error:
        check_api_key(DesktopConfig(), "key-private")
    assert "private" not in str(error.value)


def test_bundled_worker_entry_returns_bounded_file_result(tmp_path, monkeypatch):
    from fire_backend.desktop_entry import main
    import sys
    source = "function init() end function update(dt) end"
    request, response = tmp_path / "input.json", tmp_path / "output.json"
    request.write_text(json.dumps({"main_lua": source, "required_services": []}))
    monkeypatch.setattr(sys, "argv", ["FIREBackend.exe", "--lua-worker", str(request), str(response)])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 0 and json.loads(response.read_text())["ok"]


def test_local_conversation_controls_preserve_scope_and_disable_chat_builds(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            url = f"/desktop/sessions/{device.session_id}/conversation"
            assert client.post(url, json={"conversation_mode":"chat"}, headers=headers()).status_code == 403
            assert client.post(url, json={"action":"unknown"}, headers=headers(ADMIN)).status_code == 422
            assert client.post(url, json={"conversation_mode":"chat"}, headers=headers(ADMIN)).json() == {"conversation_mode":"chat"}
            device.send("text", text="Lag en RGB-app")
            device.until("assistant_message")
            status = client.get("/desktop/status", headers=headers(ADMIN)).json()["sessions"][0]
            assert status["conversation_mode"] == "chat" and status["proposal_id"] is None
            assert not client.app.state.backend.store.list("builds")
            assert client.post(url, json={"action":"cancel"}, headers=headers(ADMIN)).json()["status"] == "cancelled"

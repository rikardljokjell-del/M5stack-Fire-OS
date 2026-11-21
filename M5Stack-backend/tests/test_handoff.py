"""Current native profile, exercised on PC; no physical verification implied."""
import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.audio import AudioManager
from fire_backend.capabilities import CapabilityError, policy
from fire_backend.lua_worker import simulate
from fire_backend.models import Capabilities, DeviceEvent, SessionStart
from fire_backend.service import Backend, Conflict

from test_device_protocol import CAPS, Device, configured, headers


NATIVE = {**CAPS, "api_version": "fire-lua-0.1", "audio_input": False,
          "audio_output": False, "firmware_version": "fire-os-0.2"}


def native_start(device):
    device.send("session_start", target="device", capabilities=NATIVE)
    started = device.until("session_started")
    device.session_id = started["session_id"]
    return started


def native_request(**values):
    return SessionStart(device_id="fire-01", target="device", protocol_version="0.2",
                        boot_id="boot-native", capabilities=Capabilities(**NATIVE), **values)


def test_native_no_audio_start_text_build_receipts_and_visible_status(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_audio_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            started = native_start(device)
            assert started["state"] == "idle" and started["physical_verified"] is False
            effective = started["effective_capabilities"]
            assert effective["lua_services"] == sorted(NATIVE["services"])
            assert effective["max_memory"] == 131072
            assert not effective["conversation_audio"]["input_enabled"]
            assert not effective["conversation_audio"]["output_enabled"]
            report = device.until("capability_status")
            assert report["code"] == "audio_input_unavailable"
            visible = device.until("assistant_message")
            assert "tekst fra PC" in visible["text"] and visible["audio"] is False
            backend = client.app.state.backend
            session = backend.session(device.session_id)
            assert "Authoritative capability policy" in backend.context_for(session)
            assert '"audio_input": false' in backend.context_for(session)
            offer, _ = device.build()
            package = backend.store.get("packages", offer["package_id"])
            assert package["manifest"]["max_memory"] == 131072
            assert package["manifest"]["max_runtime_ms"] == 10000
            before = client.get("/devices/fire-01", headers=headers()).json()
            assert before["current"] is None and before["installed_package_id"] is None
            device.install(offer)
            run, _ = device.run(offer["package_id"])
            device.healthy(run)
            after = client.get("/devices/fire-01", headers=headers()).json()
            assert after["current"] == offer["package_id"]
            assert after["physical_verified"] is False
            assert backend.store.list("audio") == []
            assert not any(e["type"] == "audio_ready" for e in device.events)


@pytest.mark.parametrize("backend_audio", [False, True])
def test_no_audio_input_preserves_proposal_and_http_returns_clear_conflict(tmp_path, backend_audio):
    with TestClient(create_app(configured(tmp_path, fire_audio_enabled=backend_audio))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            native_start(device)
            device.send("text", text="Lag en sirkel")
            proposal = device.until("build_proposal")
            for name in ("listen_start", "listen_stop"):
                device.send(name, turn_id="turn-no-audio")
                assert device.until("error")["code"] == "audio_input_unavailable"
            session = client.app.state.backend.session(device.session_id)
            assert session.proposal_id == proposal["proposal_id"]
            response = client.post(f"/sessions/{session.id}/audio/turn-no-audio", content=b"invalid",
                                   headers={**headers(), "Content-Type": "audio/wav"})
            assert response.status_code == 409
            assert response.json()["code"] == "audio_input_unavailable"
            assert client.app.state.backend.store.list("audio") == []
            assert client.app.state.backend.store.list("builds") == []
            device.ack(device.send("cancel_turn"))
            assert session.state == "idle"


@pytest.mark.parametrize("input_flag,output_flag,backend_flag", [
    (False, False, True), (False, True, True), (True, False, True), (True, True, False),
])
def test_audio_directions_are_independent(tmp_path, input_flag, output_flag, backend_flag):
    settings = configured(tmp_path, fire_audio_enabled=backend_flag)
    effective = policy(settings, "device", {**NATIVE, "audio_input": input_flag, "audio_output": output_flag})
    assert effective["conversation_audio"]["input_enabled"] == (input_flag and backend_flag)
    assert effective["conversation_audio"]["output_enabled"] == (output_flag and backend_flag)
    assert effective["physical_verified"] is False
    assert policy(settings, "device", None)["lua_services"] == []


@pytest.mark.asyncio
async def test_audio_guards_run_before_reading_or_calling_provider(tmp_path):
    backend = Backend(configured(tmp_path, fire_audio_enabled=True))
    session = await backend.start(native_request(), principal="fire-01")
    audio = AudioManager(backend)

    async def unread_stream():
        raise AssertionError("Unsupported audio stream must not be consumed")
        yield b""

    with pytest.raises(CapabilityError, match="taleopptak"):
        await audio.receive(session, "turn-native", unread_stream())
    calls = []

    async def forbidden_speech(text):
        calls.append(text)
        yield b"\x00\x01"

    backend.provider.speech = forbidden_speech
    await audio.speak(session, "Dette skal bare være tekst")
    assert calls == []
    assert backend.store.list("audio") == []


def test_native_websocket_reconnect_without_resume_hint(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            started = native_start(device)
            device.send("text", text="Lag en sirkel")
            proposal = device.until("build_proposal")
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            reconnected = Device(socket)
            reconnected.counter = 100  # native counter persists across reconnect
            resumed = native_start(reconnected)
            assert resumed["session_id"] == started["session_id"]
            assert resumed["project_id"] == started["project_id"]
            assert resumed["proposal_id"] == proposal["proposal_id"]
            assert reconnected.until("capability_status")["code"] == "audio_input_unavailable"


@pytest.mark.parametrize("hash_fields", [{}, {"archive_sha256": ""}, {"archive_sha256": None}])
def test_successful_install_still_requires_full_checksum(hash_fields):
    with pytest.raises(ValueError):
        DeviceEvent(device_id="fire-01", protocol_version="0.2", event_id="evt-ok",
                    session_id="session-native", boot_id="boot-native", event="device_install_result",
                    package_id="build-native", install_id="install-native", status="ok", **hash_fields)


@pytest.mark.asyncio
async def test_implicit_offline_resume_keeps_history_and_rejects_capability_change(tmp_path):
    backend = Backend(configured(tmp_path))
    session = await backend.start(native_request(), principal="fire-01")
    session.proposal_id, session.summary = "proposal-native", "Behold forslaget"
    session.history = [{"role": "user", "content": "Lag en sirkel"}]
    await backend.detach(session, None)
    changed = native_request().model_copy(update={"capabilities": Capabilities(**{**NATIVE, "audio_input": True})})
    with pytest.raises(Conflict, match="capabilities"):
        await backend.start(changed, principal="fire-01")
    # Reconstruct backend to exercise the persisted reconnect path too.
    restarted = Backend(configured(tmp_path))
    resumed = await restarted.start(native_request(), principal="fire-01")
    assert resumed.id == session.id and resumed.proposal_id == "proposal-native"
    assert resumed.history == session.history
    assert not resumed.capabilities["audio_input"]
    assert len(restarted.store.list("projects")) == 1


@pytest.mark.asyncio
async def test_implicit_resume_never_takes_live_socket_or_previous_boot(tmp_path):
    backend = Backend(configured(tmp_path))
    session = await backend.start(native_request(), principal="fire-01")
    session.sockets.add(object())
    with pytest.raises(Conflict):
        await backend.start(native_request(), principal="fire-01")
    session.sockets.clear()
    await backend.detach(session, None)
    request = native_request().model_copy(update={"boot_id": "boot-new"})
    new_session = await backend.start(request, principal="fire-01")
    assert new_session.id != session.id and session.stopped


@pytest.mark.parametrize("hash_fields", [{}, {"archive_sha256": ""}, {"archive_sha256": "0" * 64}])
def test_failed_install_accepts_native_observed_hash_without_promoting(tmp_path, hash_fields):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            native_start(device)
            offer, _ = device.build()
            failed = device.send("device_install_result", install_id=offer["install_id"],
                                 package_id=offer["package_id"], status="failed",
                                 message="SD/download/checksum failure", **hash_fields)
            device.ack(failed)
            record = client.get("/devices/fire-01", headers=headers()).json()
            assert record["installed_package_id"] is None and record["current"] is None
            assert record.get("pending_install_id") is None
            assert client.app.state.backend.store.get("commands", offer["install_id"])["status"] == "failed"


@pytest.mark.parametrize("call", ["circle(1.5,2,3,4)", "circle(1,2,3.5,4)",
                                  "rect(1,2,3.5,4,5)", "line(1,2,3,4.5,5)", "text(1.5,2,'a',3)"])
def test_native_integer_drawing_requirement(call):
    source = f"function init() fire.display.{call} end function update(dt) end"
    with pytest.raises(Exception, match="integer"):
        simulate({"main_lua": source, "required_services": ["display"]})


def test_simulator_uses_boot_uptime_and_only_native_pressed_callbacks():
    source = '''local start=0
function init() start=fire.time.millis(); fire.display.text(0,0,tostring(start),1) end
function update(dt) end
function on_button(b,a) fire.display.text(0,0,a,1) end'''
    result = simulate({"main_lua": source, "required_services": ["display", "time"]})
    texts = [entry[3] for entry in result["trace"] if entry[0] == "text"]
    assert texts[0] == "60000" and set(texts[1:]) == {"pressed"}


def test_context_endpoint_reports_source_without_physical_claim(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        response = client.get("/device/context", headers=headers())
        data = response.json()
        assert data["firmware_source_revision"].startswith("df06c65")
        assert data["firmware_runtime_implemented_in_source"] is True
        assert data["firmware_runtime_verified"] is False and data["physical_verified"] is False

import asyncio

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.audio import AudioManager
from fire_backend.models import DeviceEvent, SessionStart
from fire_backend.protocol import dispatch
from fire_backend.service import Backend

from test_audio import wav_data
from test_device_protocol import ADMIN, CAPS, Device, configured, headers


async def setup_audio(tmp_path):
    service = Backend(configured(tmp_path, fire_audio_enabled=True))
    service.audio = AudioManager(service)
    session = await service.start(SessionStart(device_id="fire-01", protocol_version="0.2", target="device",
        boot_id="boot-pipeline", capabilities={**CAPS, "audio_output": False}), principal="fire-01")
    return service, session


async def listen(service, session, event, turn="turn-pipeline", suffix="1"):
    await dispatch(service, session, DeviceEvent(device_id="fire-01", protocol_version="0.2",
        event_id=event+"-"+suffix, event=event, session_id=session.id, boot_id=session.boot_id, turn_id=turn))


async def stream(data):
    for offset in range(0, len(data), 4096):
        yield data[offset:offset+4096]


async def test_missing_wav_times_out_and_new_recording_recovers_without_implicit_build(tmp_path):
    service, session = await setup_audio(tmp_path)
    try:
        await listen(service, session, "listen_start")
        await listen(service, session, "listen_stop")
        service.audio.awaiting[session.id] = (session.turn_id, 0)
        await service.audio.expire_waiting()
        assert session.state == "failed" and session.activity == "idle"
        assert "kom ikke frem" in session.last_error
        await listen(service, session, "listen_start", "turn-retry", "2")
        assert session.last_error == ""
        await listen(service, session, "listen_stop", "turn-retry", "2")
        await service.audio.receive(session, "turn-retry", stream(wav_data()))
        await session.input_task
        assert session.state == "awaiting_build_confirmation" and session.proposal_id
        assert not service.store.list("builds")
    finally:
        await service.close()


async def test_http_upload_can_overtake_listen_stop_but_cannot_invent_it(tmp_path):
    service, session = await setup_audio(tmp_path)
    try:
        await listen(service, session, "listen_start")
        upload = asyncio.create_task(service.audio.receive(session, session.turn_id, stream(wav_data())))
        await asyncio.sleep(0.03)
        assert not upload.done()
        await listen(service, session, "listen_stop")
        assert (await upload)["status"] == "accepted"
        await session.input_task
        assert session.proposal_id and not service.store.list("builds")
        with pytest.raises(ValueError, match="matching listen"):
            await service.audio.receive(session, "turn-never-started", stream(wav_data()))
    finally:
        await service.close()


@pytest.mark.parametrize("kind", ["disconnect", "invalid_wav"])
async def test_failed_wav_clears_processing_and_reports_safe_error(tmp_path, kind):
    service, session = await setup_audio(tmp_path)
    async def broken():
        yield b"RIFF"
        if kind == "disconnect":
            raise ConnectionError("private peer details must not escape")
    try:
        await listen(service, session, "listen_start")
        await listen(service, session, "listen_stop")
        with pytest.raises(ValueError):
            await service.audio.receive(session, session.turn_id, broken())
        assert session.state == "failed" and session.activity == "idle" and session.last_error
        assert "private peer" not in session.last_error
        assert session.id not in service.audio.uploads and session.id not in service.audio.awaiting
        assert not list((tmp_path/"audio").glob("*.wav")) and not service.store.list("builds")
    finally:
        await service.close()


def test_app_library_uses_receipts_and_preserves_apps_path_and_offline_status(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            offer, _ = device.build()
            def app():
                return next(a for a in client.get("/desktop/status", headers=headers(ADMIN)).json()["apps"]
                            if a["package_id"] == offer["package_id"])
            assert not app()["installed_receipt"] and not app()["current_healthy"]
            assert app()["sd_path"].startswith("/apps/") and "app-" not in app()["app_id"]
            device.install(offer)
            assert app()["installed_receipt"] and not app()["running"]
            run, _ = device.run(offer["package_id"])
            device.healthy(run)
            assert app()["running"] and app()["current_healthy"] and not app()["physical_verified"]
        assert not app()["running"] and app()["current_healthy"]
        assert client.get("/desktop/status", headers=headers()).status_code == 403


def test_saved_package_can_be_installed_after_reboot_without_ai_or_implicit_run(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            first = device.start()
            offer, _ = device.build()
            device.install(offer)
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket, boot_id="boot-02")
            fresh = device.start()
            assert first["project_id"] != fresh["project_id"]
            url = f"/desktop/sessions/{device.session_id}/install"
            data = {"package_id": offer["package_id"]}
            assert client.post(url, headers=headers(), json=data).status_code == 403
            assert client.post(url, headers=headers(ADMIN), json=data).status_code == 200
            repeated = device.until("install_request")
            assert repeated["package_id"] == offer["package_id"]
            assert repeated["install_id"] != offer["install_id"] and repeated["boot_id"] == "boot-02"
            device.install(repeated)
            service = client.app.state.backend
            session = service.session(device.session_id)
            assert session.project_id == first["project_id"] and session.state == "installed"
            assert len(service.store.list("builds")) == 1
            assert not [c for c in service.store.list("commands") if c["kind"] == "run"]


@pytest.mark.parametrize("denied", ["other_device", "capabilities", "corrupt_zip"])
def test_saved_install_validates_before_switching_project(tmp_path, denied):
    with TestClient(create_app(configured(tmp_path, fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            offer, _ = device.build()
            device.install(offer)
        token = "b" * 32 if denied == "other_device" else "d" * 32
        with client.websocket_connect("/ws/device", headers=headers(token)) as socket:
            device = Device(socket, device_id="fire-02" if denied == "other_device" else "fire-01", boot_id="boot-new")
            if denied == "capabilities":
                device.send("session_start", target="device", capabilities={**CAPS, "services": []})
                started = device.until("session_started"); device.session_id = started["session_id"]
            else:
                started = device.start()
            service = client.app.state.backend
            session = service.session(device.session_id)
            if denied == "corrupt_zip":
                service.store.path("packages", offer["package_id"], ".zip").write_bytes(b"broken")
            response = client.post(f"/desktop/sessions/{session.id}/install", headers=headers(ADMIN), json={"package_id": offer["package_id"]})
            assert response.status_code in {400, 403, 409}
            assert session.project_id == started["project_id"] and session.package_id is None
            assert not [c for c in service.store.list("commands") if c["session_id"] == session.id]

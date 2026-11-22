import time
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fire_backend.app import create_app
from fire_backend.builds import validate_release
from fire_backend.models import DeviceDiagnostics, DeviceEvent
from fire_backend.protocol import dispatch
from fire_backend.quality import Quality
from fire_backend.security import Redactor
from fire_backend.service import Backend
from fire_backend.storage import Store
from test_conversation_flow import conversation
from test_device_protocol import Device,configured,headers
from test_audio import recording,wav_data
from test_repair_target import saved_app,session


async def test_heavy_init_is_rejected_but_simpler_complete_scene_passes(tmp_path):
    store=Store(tmp_path,Redactor(),10_000_000)
    source="function init() for i=1,30 do fire.display.line(i,0,i,239,1) end end function update(dt) end"
    with pytest.raises(ValueError,match="Per-callback display work"):
        await validate_release({"main_lua":source,"required_services":["display"]},store,"heavy-init")
    fixed="function init() fire.display.clear(0) end function update(dt) for j=1,5 do fire.display.line(j,0,j,239,1) end fire.display.circle(20,20,5,2016) end"
    result=await validate_release({"main_lua":fixed,"required_services":["display"]},store,"incremental-init")
    assert all(p["max_callback_operations"]<=6 for p in result["profiles"])


async def test_device_vm_failure_does_not_loop_into_another_app_rewrite(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        project,package=saved_app(service,"Slangespill")
        s,_=await session(service)
        s.project_id,s.base_package_id,s.app_mode=project["id"],package["id"],"update"
        device=service.device_record(s);device.update(runtime_status="failed",installed_package_id=package["id"])
        service.store.put("devices",device["id"],device)
        service.quality.record(project_id=project["id"],package_id=package["id"],device_id=s.device_id,
            source_hash=package["manifest"]["checksum"],message="load_error: Invalid Lua source",provenance="device_diagnostic")
        await service.text(s,"Funker ikke. Fiks spillet.")
        assert s.repair_context["blocked_device_runtime"] and not s.proposal_id
        assert "firmware" in s.history[-1]["content"] and "A BUILD" not in s.history[-1]["content"]
        assert len(service.store.list("builds"))==1
        device["runtime_status"]="unknown"  # New boot invalidates the current failure state.
        service.store.put("devices",device["id"],device)
        await service.text(s,"Fiks spillet")
        assert not s.repair_context["blocked_device_runtime"] and s.proposal_id
        command=service.issue_command(s,"run",package["id"])
        service.finish_command(command,"failed")
        await service.text(s,"Fiks spillet")
        assert s.repair_context["blocked_device_runtime"] and not s.proposal_id
        s.boot_id="boot-after-firmware-fix"
        await service.text(s,"Fiks spillet")
        assert not s.repair_context["blocked_device_runtime"] and s.proposal_id
    finally:await service.close()


@pytest.mark.parametrize("bad",[{"callback_us":-1},{"free_heap":True},{"raw_log":"secret"},{"phase":"anything"}])
def test_feedback_is_small_typed_metadata(bad):
    with pytest.raises(ValidationError):DeviceDiagnostics(**bad)


async def test_light_feedback_records_verified_identity_and_metrics(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        project,package=saved_app(service,"Slangespill")
        s,_=await session(service)
        event=DeviceEvent(device_id=s.device_id,event="app_diagnostic",protocol_version="0.2",event_id="diagnostic-feedback",
            session_id=s.id,boot_id=s.boot_id,app_id=package["manifest"]["id"],package_id=package["id"],error_code="init_error",
            message="callback budget",diagnostics={"phase":"init","callback_us":13000,"free_heap":100000,"source_bytes":123})
        await dispatch(service,s,event)
        report=service.store.list("feedback")[0]
        assert report["source_sha256"]==package["manifest"]["checksum"] and report["diagnostics"]["callback_us"]==13000
        await dispatch(service,s,event)
        assert len(service.store.list("feedback"))==1
        assert len(service.store.list("builds"))==1
    finally:await service.close()


async def test_voice_timeout_retries_once_then_preserves_exact_build_offer(tmp_path):
    async with conversation(tmp_path) as flow:
        await flow.record("turn-timeout");await flow.upload("turn-timeout");await flow.finish_reply()
        s,service=flow.session,flow.service
        proposal=s.proposal_id;audio=s.audio_id
        item=service.store.get("audio",audio);item["ready_at"]=time.time()-13;service.store.put("audio",audio,item)
        before=len([e for e in flow.socket.events if e["type"]=="audio_ready"])
        await service.audio.expire_waiting();await service.audio.expire_waiting()
        assert len([e for e in flow.socket.events if e["type"]=="audio_ready"])==before+1
        item=service.store.get("audio",audio);item["ready_at"]=time.time()-36;service.store.put("audio",audio,item)
        await service.audio.expire_waiting()
        assert s.audio_status["phase"]=="playback_failed" and s.activity=="idle" and s.proposal_id==proposal
        assert not service.store.path("audio",audio,".pcm").exists()
        assert [e for e in flow.socket.events if e["type"]=="build_proposal"][-1]["proposal_id"]==proposal
        await flow.send("audio_playback_finished",audio_id=audio,turn_id=s.turn_id)
        assert s.audio_status["phase"]=="playback_failed"


def test_audio_http_send_is_measured_separately_from_physical_playback(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_audio_enabled=True))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            device=Device(socket);device.start();turn=recording(device)
            assert client.post(f"/sessions/{device.session_id}/audio/{turn}",content=wav_data(),headers={**headers(),"Content-Type":"audio/wav"}).status_code==202
            clip=device.until("audio_ready")
            response=client.get(clip["download_url"],headers=headers())
            assert response.status_code==200
            backend=client.app.state.backend;s=backend.session(device.session_id)
            stats=s.audio_status["server_transfer"]
            assert stats["finished"] and stats["sent_bytes"]==len(response.content)==clip["size_bytes"]
            assert s.audio_status["phase"]!="played"
            device.ack(device.send("audio_playback_failed",audio_id=clip["audio_id"],turn_id=turn,error_code="speaker_unavailable",
                diagnostics={"phase":"audio_playback","free_heap":50000}))
            assert s.audio_status["phase"]=="playback_failed" and s.proposal_id
            assert client.get(clip["download_url"],headers=headers()).status_code==404



def test_local_voice_retry_preserves_turn_and_proposal_and_is_admin_only(tmp_path):
    from test_device_protocol import ADMIN
    with TestClient(create_app(configured(tmp_path,fire_audio_enabled=True,fire_desktop_enabled=True))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            device=Device(socket);device.start();turn=recording(device)
            client.post(f"/sessions/{device.session_id}/audio/{turn}",content=wav_data(),headers={**headers(),"Content-Type":"audio/wav"})
            first=device.until("audio_ready")
            s=client.app.state.backend.session(device.session_id);proposal=s.proposal_id
            url=f"/desktop/sessions/{s.id}/voice"
            assert client.post(url,json={"test":True},headers=headers()).status_code==403
            assert client.post(url,json={"test":"true"},headers=headers(ADMIN)).status_code==422
            assert client.post(url,json={"test":True},headers=headers(ADMIN)).json()["turn_id"]==turn
            second=device.until("audio_ready",lambda e:e["audio_id"]!=first["audio_id"])
            assert second["turn_id"]==turn and s.proposal_id==proposal
            assert client.get(first["download_url"],headers=headers()).status_code==404
            device.ack(device.send("audio_playback_started",audio_id=second["audio_id"],turn_id=turn))
            device.ack(device.send("audio_playback_finished",audio_id=second["audio_id"],turn_id=turn))
            assert s.audio_status["phase"]=="played" and s.proposal_id==proposal
            late=device.send("audio_playback_finished",audio_id=first["audio_id"],turn_id=turn)
            assert device.ack(late)["result"]["status"]=="ignored"
            assert s.audio_status["phase"]=="played"

"""Resolve repair requests within an authenticated device, without a PC picker."""
import pytest

from fire_backend.builds import sha256, write_archive
from fire_backend.models import Manifest, SessionStart
from fire_backend.service import Backend
from fire_backend.storage import new_id
from fire_backend.quality import RepairChoiceNeeded
from test_device_protocol import CAPS, configured


class Peer:
    def __init__(self): self.events=[]
    async def send_json(self,event): self.events.append(event)


def saved_app(service,name,owner="fire-01",slug="snake"):
    project=service.new_project(owner,"device")
    package_id=new_id("build")
    source=b"function init() fire.display.clear(0) end function update(dt) end"
    manifest=Manifest(id=slug,name=name,version="0.1.1",required_services=["display"],permissions=["fire.display"],
                      max_memory=131072,max_runtime_ms=16,checksum=sha256(source)).model_dump()
    path=service.store.path("packages",package_id,".zip")
    write_archive(path,manifest,source)
    package={"id":package_id,"project_id":project["id"],"build_id":package_id,"manifest":manifest,
             "archive_sha256":sha256(path.read_bytes()),"validation":{"suite":"release-v1"},"mode":"mock"}
    service.store.put("builds",package_id,{"id":package_id,"project_id":project["id"],"status":"ready","summary":"Behold dette spillets funksjoner og kontroller."})
    service.store.put("packages",package_id,package)
    project.update(name=name,app_id=slug,latest_package=package_id,next_version=2)
    service.store.put("projects",project["id"],project)
    return project,package


async def session(service):
    peer=Peer()
    s=await service.start(SessionStart(device_id="fire-01",protocol_version="0.2",target="device",boot_id="boot-repair-target",capabilities=CAPS),peer,"fire-01")
    return s,peer


@pytest.mark.parametrize("utterance", [
    "Fiks slangespillet. Jeg får app error når jeg starter det.",
    "REPARER SLANGESPILL!", "Fiks slangespill.",
])
async def test_named_repair_from_new_app_session_selects_source_automatically(tmp_path,utterance):
    service=Backend(configured(tmp_path))
    try:
        project,package=saved_app(service,"Slangespill")
        s,peer=await session(service)
        s.turn_id="turn-original"
        await service.text(s,utterance)
        assert s.project_id==project["id"] and s.base_package_id==package["id"]
        assert s.app_mode=="update" and s.turn_id=="turn-original"
        assert s.proposal_id and s.repair_context["package_id"]==package["id"]
        assert any(e["type"]=="app_selected" and e["project_id"]==project["id"] for e in peer.events)
        assert not any("Velg appen under" in e.get("text","") for e in peer.events)
        assert len(service.store.list("builds"))==1  # No implicit BUILD/RUN.
        assert service.store.get("projects",project["id"])["next_version"]==2
    finally: await service.close()


async def test_named_target_overrides_other_selection_without_leaking_history(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        snake,pkg=saved_app(service,"Slangespill")
        other,other_pkg=saved_app(service,"Kalkulator",slug="kalkulator")
        s,_=await session(service)
        s.project_id,s.base_package_id=other["id"],other_pkg["id"]
        s.history=[{"role":"user","content":"OTHER APP CONTEXT"}]
        await service.text(s,"Fiks slangespillet")
        assert s.project_id==snake["id"] and s.base_package_id==pkg["id"]
        assert "OTHER APP CONTEXT" not in str(s.history)
        assert not service.store.get("packages",other_pkg["id"]).get("quality")
    finally: await service.close()


async def test_duplicate_names_require_only_app_disambiguation_without_mutation(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        _,first=saved_app(service,"Slangespill",slug="snake-1")
        _,second=saved_app(service,"Slangespill",slug="snake-2")
        s,_=await session(service); original=s.project_id
        await service.text(s,"Fiks slangespillet")
        assert s.project_id==original and not s.proposal_id
        assert "Hvilken app" in s.history[-1]["content"]
        assert not service.store.get("packages",first["id"]).get("quality")
        assert not service.store.get("packages",second["id"]).get("quality")
    finally: await service.close()


async def test_foreign_app_name_is_not_a_repair_target(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        _,foreign=saved_app(service,"Slangespill",owner="fire-other")
        own,package=saved_app(service,"Kalkulator",slug="kalkulator")
        s,_=await session(service);s.project_id,s.base_package_id=own["id"],package["id"]
        await service.text(s,"Fiks slangespillet")
        assert s.project_id==own["id"] and not s.proposal_id
        assert not service.store.get("packages",foreign["id"]).get("quality")
        assert not service.store.get("packages",package["id"]).get("quality")
    finally: await service.close()


async def test_generic_repair_uses_only_saved_app_or_selected_base(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        project,package=saved_app(service,"Kalkulator",slug="kalkulator")
        s,_=await session(service)
        await service.text(s,"Fiks appen som ikke fungerer")
        assert s.project_id==project["id"] and s.base_package_id==package["id"] and s.proposal_id
    finally: await service.close()


async def test_unknown_named_target_does_not_fall_back_to_unrelated_selected_app(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        project,package=saved_app(service,"Kalkulator",slug="kalkulator")
        s,_=await session(service);s.project_id,s.base_package_id=project["id"],package["id"]
        await service.text(s,"Fiks værappen")
        assert not s.proposal_id and not service.store.get("packages",package["id"]).get("quality")
    finally: await service.close()


async def test_resume_after_automatic_target_change_keeps_repair_even_with_stale_device_project(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        snake,package=saved_app(service,"Slangespill")
        other,other_pkg=saved_app(service,"Kalkulator",slug="kalkulator")
        s,_=await session(service)
        s.project_id,s.base_package_id=other["id"],other_pkg["id"]
        await service.text(s,"Fiks slangespillet")
        proposal=s.proposal_id
        await service.detach(s,next(iter(s.sockets)))
        resumed=await service.start(SessionStart(device_id="fire-01",protocol_version="0.2",target="device",boot_id="boot-repair-target",capabilities=CAPS,
            project_id=other["id"],resume_session_id=s.id),Peer(),"fire-01")
        assert resumed.id==s.id and resumed.project_id==snake["id"]
        assert resumed.base_package_id==package["id"] and resumed.proposal_id==proposal
    finally: await service.close()


async def test_spoken_wrong_name_uses_explicitly_selected_app_and_names_it_in_feedback(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        snake,package=saved_app(service,"Slangespill")
        s,peer=await session(service)
        s.project_id,s.base_package_id,s.app_mode=snake["id"],package["id"],"update"
        await service.text(s,"Fiks sjakkespill.",source="voice")
        assert s.project_id==snake["id"] and s.repair_context["package_id"]==package["id"]
        assert s.proposal_id and "Slangespill" in s.history[-1]["content"]
        assert "Fiks sjakkespill." == s.history[-2]["content"]  # Never rewrite raw ASR as certainty.
    finally:await service.close()


async def test_followup_spelling_error_keeps_active_repair_without_resetting_app(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        snake,package=saved_app(service,"Slangespill")
        s,_=await session(service)
        await service.text(s,"Fiks slangespillet.")
        old=s.proposal_id
        await service.text(s,"Fiks sjakkespill.")
        assert s.project_id==snake["id"] and s.base_package_id==package["id"]
        assert s.proposal_id and s.proposal_id!=old and "Slangespill" in s.history[-1]["content"]
        assert len(service.store.list("builds"))==1
    finally:await service.close()


async def test_recognized_similar_sounding_voice_name_keeps_selected_game_until_explicit_switch(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        snake,package=saved_app(service,"Slangespill")
        chess,chess_package=saved_app(service,"Sjakkespill",slug="sjakk")
        s,_=await session(service)
        s.project_id,s.base_package_id,s.app_mode=snake["id"],package["id"],"update"
        await service.text(s,"Fiks sjakkespill",source="voice")
        assert s.project_id==snake["id"]
        assert not service.store.get("packages",chess_package["id"]).get("quality")
        await service.text(s,"Bytt til sjakkespill og reparer det",source="voice")
        assert s.project_id==chess["id"] and s.base_package_id==chess_package["id"]
    finally:await service.close()


async def test_unknown_explicit_voice_switch_does_not_repair_selected_app(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        snake,package=saved_app(service,"Slangespill")
        s,_=await session(service)
        s.project_id,s.base_package_id,s.app_mode=snake["id"],package["id"],"update"
        await service.text(s,"Bytt til værappen og fiks den",source="voice")
        assert not s.proposal_id and not service.store.get("packages",package["id"]).get("quality")
    finally:await service.close()


async def test_no_selected_app_does_not_guess_wrong_asr_name(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        _,package=saved_app(service,"Slangespill")
        s,_=await session(service)
        await service.text(s,"Fiks sjakkespill",source="voice")
        assert not s.proposal_id and not service.store.get("packages",package["id"]).get("quality")
    finally:await service.close()


async def test_audio_pipeline_preserves_selected_app_for_misrecognized_name(tmp_path):
    from fire_backend.ai import MockProvider
    from fire_backend.audio import AudioManager
    from fire_backend.models import DeviceEvent
    from fire_backend.protocol import dispatch
    from test_audio import wav_data
    class Misheard(MockProvider):
        async def transcribe(self,data):return "Fiks sjakkespill."
    service=Backend(configured(tmp_path,fire_audio_enabled=True),Misheard())
    service.audio=AudioManager(service)
    try:
        snake,package=saved_app(service,"Slangespill")
        s,_=await session(service)
        s.project_id,s.base_package_id,s.app_mode=snake["id"],package["id"],"update"
        for event in ("listen_start","listen_stop"):
            await dispatch(service,s,DeviceEvent(device_id=s.device_id,event=event,event_id="voice-"+event,
                protocol_version="0.2",session_id=s.id,boot_id=s.boot_id,turn_id="turn-misheard"))
        async def body():yield wav_data()
        await service.audio.receive(s,"turn-misheard",body())
        await s.input_task
        if s.speech_task:await s.speech_task
        assert s.proposal_id and s.repair_context["package_id"]==package["id"]
        assert s.audio_status["transcript"]=="Fiks sjakkespill." and "Slangespill" in s.history[-1]["content"]
    finally:await service.close()

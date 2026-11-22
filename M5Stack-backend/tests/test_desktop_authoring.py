import copy
import time

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.builds import write_archive,sha256
from fire_backend.models import State
from fire_backend.service import Backend
from test_device_protocol import configured,headers,ADMIN
from test_repair_target import saved_app,session


async def test_pc_authoring_creates_device_owned_versions_without_device_receipts(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        pc=await service.desktop_conversation("fire-01")
        assert pc.target=="pc_simulation" and not service.store.list("devices")
        await service.text(pc,"Lag en sirkel")
        assert pc.proposal_id and not service.store.list("packages")
        await service.confirm_build(pc,pc.proposal_id);await pc.task
        first=service.store.get("packages",pc.package_id)
        project=service.store.get("projects",pc.project_id)
        assert project["owner_device_id"]=="fire-01" and project["current"] is None
        assert pc.state==State.ready_to_run and not service.store.list("commands")
        update=await service.desktop_conversation("fire-01",project["id"],first["id"])
        await service.text(update,"Lag en sirkel som er litt tregere")
        await service.confirm_build(update,update.proposal_id);await update.task
        second=service.store.get("packages",update.package_id)
        assert second["manifest"]["id"]==first["manifest"]["id"] and second["manifest"]["version"]=="0.1.2"
        assert len(service.app_versions(service.store.get("projects",project["id"])))==2
        assert not service.store.list("devices") and not service.store.list("commands")
        with pytest.raises(PermissionError):await service.desktop_conversation("fire-02",project["id"],first["id"])
    finally:await service.close()


async def test_delete_one_version_preserves_other_bytes_and_monotonic_version_number(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        project,first=saved_app(service,"Slangespill")
        source=b"function init() end function update(dt) fire.display.circle(20,20,5,2016) end"
        second=copy.deepcopy(first);second.update(id="build-second",build_id="build-second")
        second["manifest"].update(version="0.1.2",checksum=sha256(source))
        path=service.store.path("packages",second["id"],".zip");write_archive(path,second["manifest"],source)
        second.update(archive_sha256=sha256(path.read_bytes()),size_bytes=path.stat().st_size)
        service.store.put("packages",second["id"],second)
        service.store.put("builds",second["id"],{"id":second["id"],"project_id":project["id"],"status":"ready"})
        project.update(latest_package=second["id"],next_version=3)
        service.store.put("projects",project["id"],project)
        s,_=await session(service)
        with pytest.raises(ValueError):service.delete_app_version(project,second["id"])
        d=service.device_record(s);d["storage_ready"]=True
        d.setdefault("apps",{})[first["manifest"]["id"]]={"state":"deleted","boot_id":s.boot_id,"connection_epoch":d["connection_epoch"],"reported_at":time.time()}
        service.store.put("devices",d["id"],d)
        before=service.store.path("packages",first["id"],".zip").read_bytes()
        service.delete_app_version(project,second["id"])
        remaining=service.store.get("projects",project["id"])
        assert remaining["next_version"]==3 and remaining["latest_package"]==first["id"]
        assert before==service.store.path("packages",first["id"],".zip").read_bytes()
        assert not path.exists() and len(service.app_versions(remaining))==1
        service.delete_app_version(remaining,first["id"])
        assert not service.store.path("projects",project["id"]).exists()
    finally:await service.close()


def test_pc_conversation_endpoint_is_local_admin_only_and_accepts_offline_device(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as client:
        assert client.post("/desktop/conversations",json={"device_id":[]},headers=headers(ADMIN)).status_code==422
        assert client.post("/desktop/conversations",json={"device_id":"fire-01"},headers=headers()).status_code==403
        r=client.post("/desktop/conversations",json={"device_id":"fire-01"},headers=headers(ADMIN))
        assert r.status_code==200 and r.json()["desktop_device_id"]=="fire-01"
        assert client.get("/desktop/status",headers=headers(ADMIN)).json()["sessions"][0]["target"]=="pc_simulation"
        sid=r.json()["session_id"]
        assert client.post(f"/desktop/sessions/{sid}/text",json={"text":"Lag en sirkel"},headers=headers(ADMIN)).json()["status"]=="accepted"
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            status=client.get(f"/sessions/{sid}",headers=headers(ADMIN)).json()
            if status["state"]=="awaiting_build_confirmation":break
            time.sleep(.02)
        assert status["proposal_id"]
        assert client.delete(f"/projects/{status['project_id']}/versions/build-foreign",headers=headers()).status_code==403

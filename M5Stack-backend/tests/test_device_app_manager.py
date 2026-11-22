import copy
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fire_backend.app import create_app
from fire_backend.builds import sha256,write_archive
from fire_backend.models import DeviceEvent
from test_app_lifecycle import inventory,select
from test_device_protocol import Device,OTHER,ADMIN,configured,headers


def version(backend,first,number=2):
    """Seed another immutable tested version of a real mock-built package."""
    p=copy.deepcopy(first);p.update(id=f"build-version-{number}",build_id=f"build-version-{number}")
    with zipfile.ZipFile(backend.store.path("packages",first["id"],".zip")) as archive:
        source=archive.read(f"apps/{first['manifest']['id']}/main.lua")
    p["manifest"]["version"]=f"0.1.{number}"
    path=backend.store.path("packages",p["id"],".zip");write_archive(path,p["manifest"],source)
    p.update(archive_sha256=sha256(path.read_bytes()),size_bytes=path.stat().st_size)
    backend.store.put("packages",p["id"],p)
    backend.store.put("builds",p["id"],{"id":p["id"],"project_id":p["project_id"],"status":"ready"})
    project=backend.store.get("projects",p["project_id"]);project.update(latest_package=p["id"],next_version=number+1)
    backend.store.put("projects",project["id"],project)
    return p


def prepare(device,project_id,scope="all",**values):
    sent=device.send("app_backend_delete_prepare",project_id=project_id,delete_scope=scope,**values)
    ready=device.until("app_backend_delete_ready");device.ack(sent)
    return ready


def test_manager_lists_versions_downloads_and_installs_without_running(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            d=Device(socket);started=d.start();offer,_=d.build();d.install(offer)
            backend=client.app.state.backend;first=backend.store.get("packages",offer["package_id"])
            second=version(backend,first);select(d)
            s=backend.session(d.session_id);before=(s.project_id,s.turn_id,list(s.history))
            sent=d.send("app_list");catalog=d.until("app_catalog");d.ack(sent)
            assert len(catalog["apps"])==1 and catalog["apps"][0]["version_count"]==2
            assert catalog["apps"][0]["downloadable"] and not catalog["apps"][0]["can_delete_from_device"]
            sent=d.send("app_versions",project_id=started["project_id"])
            versions=d.until("app_versions");d.ack(sent)
            assert [v["version"] for v in versions["versions"]]==["0.1.2","0.1.1"]
            assert all(v["downloadable"] and v["size_bytes"]>0 for v in versions["versions"])
            assert (s.project_id,s.turn_id,s.history)==before
            sent=d.send("app_download",project_id=started["project_id"],package_id=second["id"])
            request=d.until("install_request");ack=d.ack(sent)
            assert request["package_id"]==second["id"] and ack["result"]["install_id"]==request["install_id"]
            raw=client.get(request["download_url"],headers=headers()).content
            assert len(raw)==second["size_bytes"] and sha256(raw)==second["archive_sha256"]
            d.install(request)
            socket.send_json(sent);assert d.ack(sent)["status"]=="duplicate"
            assert not any(c["kind"]=="run" for c in backend.store.list("commands"))
            assert backend.session(d.session_id).state=="installed"


@pytest.mark.parametrize("scope",["version","all"])
def test_device_can_confirm_backend_delete_after_local_absence_even_when_selected(tmp_path,scope):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            d=Device(socket);started=d.start();offer,_=d.build();d.install(offer)
            backend=client.app.state.backend;first=backend.store.get("packages",offer["package_id"]);second=version(backend,first)
            # The direct admin-only route remains unavailable to device tokens.
            assert client.delete(f"/projects/{started['project_id']}",headers=headers()).status_code==403
            sent=d.send("app_backend_delete_prepare",project_id=started["project_id"],delete_scope="all")
            assert d.until("error")["code"]=="event_rejected"
            inventory(d,[])
            sent=d.send("app_list");row=d.until("app_catalog")["apps"][0];d.ack(sent)
            assert row["can_delete_from_device"] and not row["can_delete_backend"]
            kwargs={"package_id":second["id"]} if scope=="version" else {}
            ready=prepare(d,started["project_id"],scope,**kwargs)
            assert backend.store.path("packages",second["id"],".zip").exists() # Prepare does not delete.
            old=backend.store.path("packages",first["id"],".zip").read_bytes()
            sent=d.send("app_backend_delete_confirm",delete_id=ready["delete_id"])
            result=d.until("app_backend_deleted");ack=d.ack(sent)
            assert result["remaining_versions"]==(1 if scope=="version" else 0)
            assert ack["result"]["status"]=="deleted" and result["replacement_project_id"]
            assert backend.session(d.session_id).project_id==result["replacement_project_id"]
            assert not backend.store.path("packages",second["id"]).exists()
            if scope=="version":
                assert backend.store.path("packages",first["id"],".zip").read_bytes()==old
                assert backend.store.get("projects",first["project_id"])["next_version"]==3
            else:assert not backend.store.path("projects",first["project_id"]).exists()
            socket.send_json(sent);assert d.ack(sent)["status"]=="duplicate"
            assert client.get(f"/packages/{second['id']}/download",headers=headers()).status_code==404


@pytest.mark.parametrize("change",["expired","revision","sd_present","sd_unknown","download","other_session"])
def test_delete_rechecks_every_condition_at_confirmation(tmp_path,change):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            d=Device(socket);started=d.start();offer,_=d.build();d.install(offer);inventory(d,[])
            backend=client.app.state.backend;s=backend.session(d.session_id);pkg=backend.store.get("packages",offer["package_id"])
            ready=prepare(d,started["project_id"])
            if change=="expired":
                job=backend.store.get("app_deletions",ready["delete_id"]);job["expires_at"]=time.time()-1
                backend.store.put("app_deletions",job["id"],job)
            elif change=="revision":version(backend,pkg)
            elif change=="sd_present":inventory(d,[{"app_id":pkg["manifest"]["id"],"package_id":pkg["id"]}])
            elif change=="sd_unknown":inventory(d,[],ready=False)
            elif change=="download":backend.active_downloads[pkg["id"]]=1
            elif change=="other_session":
                from dataclasses import replace
                backend.sessions["session-other"]=replace(s,id="session-other")
            sent=d.send("app_backend_delete_confirm",delete_id=ready["delete_id"])
            assert d.until("error")["code"]=="event_rejected"
            assert backend.store.path("packages",pkg["id"],".zip").exists()
            assert s.project_id==started["project_id"]


def test_other_device_and_wrong_boot_cannot_delete_or_download(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            owner=Device(socket);started=owner.start();offer,_=owner.build();owner.install(offer);inventory(owner,[])
            ready=prepare(owner,started["project_id"])
            backend=client.app.state.backend;job=backend.store.get("app_deletions",ready["delete_id"])
            job["boot_id"]="other-boot";backend.store.put("app_deletions",job["id"],job)
            owner.send("app_backend_delete_confirm",delete_id=job["id"]);owner.until("error")
            with client.websocket_connect("/ws/device",headers=headers(OTHER)) as other_socket:
                other=Device(other_socket,device_id="fire-02",boot_id="boot-other");other.start()
                before=backend.session(other.session_id).project_id
                for name,values in [("app_download",{"package_id":offer["package_id"]}),
                    ("app_backend_delete_prepare",{"project_id":started["project_id"],"delete_scope":"all"}),
                    ("app_backend_delete_confirm",{"delete_id":ready["delete_id"]})]:
                    other.send(name,**values);assert other.until("error")["code"]=="event_rejected"
                other.send("app_list");assert other.until("app_catalog")["apps"]==[]
                assert backend.session(other.session_id).project_id==before
            assert backend.store.path("packages",offer["package_id"]).exists()


def test_readonly_catalog_is_paged_bounded_and_preserves_active_dialog(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            d=Device(socket);d.start();offer,_=d.build();d.install(offer)
            backend=client.app.state.backend;s=backend.session(d.session_id)
            first=backend.store.get("packages",offer["package_id"])
            for number in range(5):
                project=backend.new_project(d.device_id,"device")
                package=copy.deepcopy(first);package.update(id=f"build-catalog-{number}",build_id=f"build-catalog-{number}",project_id=project["id"])
                package["manifest"].update(id=f"catalog-{number}",name=f"App {number}")
                with zipfile.ZipFile(backend.store.path("packages",first["id"],".zip")) as archive:
                    source=archive.read(f"apps/{first['manifest']['id']}/main.lua")
                path=backend.store.path("packages",package["id"],".zip");write_archive(path,package["manifest"],source)
                package.update(archive_sha256=sha256(path.read_bytes()),size_bytes=path.stat().st_size)
                backend.store.put("packages",package["id"],package)
                backend.store.put("builds",package["id"],{"id":package["id"],"project_id":project["id"],"status":"ready"})
                project.update(name=package["manifest"]["name"],app_id=package["manifest"]["id"],latest_package=package["id"])
                backend.store.put("projects",project["id"],project)
            before=(s.project_id,s.turn_id,list(s.history));s.activity="listening"
            sent=d.send("app_list");first_page=d.until("app_catalog");d.ack(sent)
            assert len(first_page["apps"])==4 and first_page["next_offset"]==4
            assert first_page["request_event_id"]==sent["event_id"] and len(json.dumps(first_page).encode())<8192
            sent=d.send("app_list",offset=4);second_page=d.until("app_catalog");d.ack(sent)
            assert len(second_page["apps"])==2 and second_page["next_offset"] is None
            assert {p["project_id"] for p in first_page["apps"]}.isdisjoint(p["project_id"] for p in second_page["apps"])
            assert (s.project_id,s.turn_id,s.history)==before and s.activity=="listening"
            assert all(not p["can_delete_from_device"] for p in first_page["apps"])


@pytest.mark.parametrize("kind",["blocked","old_suite","corrupt"])
def test_unusable_packages_cannot_be_installed_by_manager(tmp_path,kind):
    with TestClient(create_app(configured(tmp_path))) as client:
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            d=Device(socket);started=d.start();offer,_=d.build();d.install(offer);select(d)
            backend=client.app.state.backend;pkg=backend.store.get("packages",offer["package_id"])
            if kind=="blocked":pkg["quality"]={"blocked":True}
            elif kind=="old_suite":pkg["validation"]["suite"]="release-v2"
            else:backend.store.path("packages",pkg["id"],".zip").write_bytes(b"corrupt")
            backend.store.put("packages",pkg["id"],pkg)
            before=backend.session(d.session_id).project_id;count=len(backend.store.list("commands"))
            d.send("app_download",project_id=started["project_id"],package_id=pkg["id"]);d.until("error")
            assert backend.session(d.session_id).project_id==before and len(backend.store.list("commands"))==count


@pytest.mark.parametrize("values",[{}, {"delete_scope":"all"},{"delete_scope":"version","project_id":"app-x"},
    {"delete_scope":"all","project_id":"app-x","package_id":"build-x"}])
def test_invalid_delete_selection_never_reaches_dispatch(values):
    with pytest.raises(ValidationError):
        DeviceEvent(event="app_backend_delete_prepare",device_id="fire-01",protocol_version="0.2",event_id="evt-delete",session_id="session-x",boot_id="boot-x",**values)

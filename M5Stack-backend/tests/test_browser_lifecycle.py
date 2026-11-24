import asyncio
import base64
import json
import time

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.config import Settings
from fire_backend.firmware_catalog import REPOSITORY, index_entries

ADMIN = "fake-local-admin-only-" + "z" * 24


def login(client):
    code = client.post("/desktop/web-login", headers={"Authorization": "Bearer "+ADMIN}, json={}).json()["path"].split("signin=")[1]
    result = client.post("/web/local-login", headers={"Origin": "http://testserver"}, json={"code": code})
    client.headers.update({"Origin": "http://testserver", "X-Fire-CSRF": result.json()["csrf"]})


def test_restart_closes_admission_and_rechecks_already_admitted_work(tmp_path):
    from fire_backend.desktop_config import DesktopStore
    class Vault:
        def __init__(self): self.data={}
        def get(self,key): return self.data.get(key,"")
        def put(self,key,value): self.data[key]=value
    store=DesktopStore(tmp_path / "config", Vault())
    settings=Settings(_env_file=None,fire_ai_mode="mock",fire_workspace=tmp_path/"data",
                      fire_backend_token=ADMIN,fire_desktop_enabled=True)
    called=[]
    app=create_app(settings,config_store=store,restart_callback=lambda:called.append(True))
    with TestClient(app) as client:
        login(client)
        assert client.post("/web/settings/apply",json={}).status_code==200
        # New builds/audio/settings must not be admitted in the drain interval.
        assert client.post("/web/conversations",json={"device_id":"m5stack-fire-01"}).status_code==503
        # Simulate work admitted before the gate: actual loop recheck must win.
        client.portal.call(app.state.backend.build_lock.acquire)
        time.sleep(1.1)
        assert called==[] and not app.state.restart_pending
        assert "Jobben fortsetter" in app.state.restart_message
        client.portal.call(app.state.backend.build_lock.release)
        assert client.post("/web/settings/apply",json={}).status_code==200
        time.sleep(1.1)
        assert called==[True]


def test_browser_package_download_rejects_tampered_archive_and_nonready_build(tmp_path):
    settings=Settings(_env_file=None,fire_ai_mode="mock",fire_workspace=tmp_path,
                      fire_backend_token=ADMIN,fire_desktop_enabled=True,
                      fire_device_tokens=json.dumps({"fire01":"device-"+"d"*32}))
    app=create_app(settings)
    with TestClient(app) as client:
        login(client)
        s=client.post("/web/conversations",json={"device_id":"fire01"}).json()
        sid=s["session_id"]
        client.post(f"/web/conversations/{sid}/text",json={"text":"Lag en RGB-app"})
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            session=app.state.backend.session(sid)
            if session.proposal_id:break
            time.sleep(.01)
        response=client.post(f"/web/conversations/{sid}/build",json={"proposal_id":session.proposal_id})
        assert response.status_code==200,response.text
        build=response.json()
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            saved=app.state.backend.store.get("builds",build["id"])
            if saved["status"] in {"ready","failed"}:break
            time.sleep(.05)
        assert saved["status"]=="ready",saved.get("error")
        package_id=saved["package_id"]
        path=f"/web/packages/{package_id}/download"
        assert client.get(path).status_code==200
        archive=app.state.backend.store.path("packages",package_id,".zip")
        archive.write_bytes(archive.read_bytes()+b"tampered")
        assert client.get(path).status_code==400
        saved["status"]="failed"
        app.state.backend.store.put("builds",saved["id"],saved)
        assert client.get(path).status_code==409


def test_signed_index_metadata_is_not_presented_as_verified_firmware():
    payload={"schema":2,"repository":REPOSITORY,"target":"m5stack-fire","layout":"fire-ab-recovery-v1",
             "min_recovery":1,"files":[{"name":"fire-test.bin","version":"1.2.0","notes":"Ny norsk versjon"}]}
    envelope={"schema":2,"algorithm":"ecdsa-p256-sha256","key_id":"test","signature":"not-a-real-signature",
              "payload":base64.b64encode(json.dumps(payload).encode()).decode()}
    entries=index_entries(envelope)
    assert entries[0]["signed"] and entries[0]["signature_verified"] is False
    envelope["payload"]="bad!"
    with pytest.raises(ValueError):index_entries(envelope)
    payload["target"]="another-device"
    with pytest.raises(ValueError):index_entries(payload)


def test_legacy_index_is_explicitly_unsigned():
    entries=index_entries({"schema":1,"repository":REPOSITORY,"target":"m5stack-fire",
                           "files":[{"name":"fire-os-1.1.bin","version":"fire-os-1.1"}]})
    assert entries[0]["legacy_unsigned"] and not entries[0]["signed"]
    assert entries[0]["signature_verified"] is False

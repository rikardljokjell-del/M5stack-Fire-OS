import time

from fastapi.testclient import TestClient

from fire_backend.app import create_app
from test_device_protocol import Device,CAPS,configured,headers,ADMIN,OTHER


def image():
    data=bytearray(96);data[0]=0xE9;data[1]=1
    return bytes(data)


def upload(client,data=None,**extra):
    return client.post("/desktop/firmware",content=image() if data is None else data,headers={**headers(ADMIN),
        "Content-Type":"application/octet-stream","X-Firmware-Name":"firmware.bin","X-Firmware-Version":"test-1",**extra})


def start(device,**caps):
    device.send("session_start",target="device",capabilities={**CAPS,"firmware_version":"test-running",**caps})
    result=device.until("session_started");device.session_id=result["session_id"]


def test_firmware_file_scope_hash_receipt_and_no_implicit_flashing(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as client:
        response=upload(client);assert response.status_code==200
        item=response.json();assert not item["flash_verified"]
        assert upload(client).json()["id"]==item["id"]
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            device=Device(socket);start(device,firmware_storage=True)
            r=client.post(f"/desktop/firmware/{item['id']}/send",json={"device_id":"fire-01"},headers=headers(ADMIN))
            assert r.status_code==200
            offer=device.until("firmware_store_request")
            assert offer["sd_path"].startswith("/firmware/") and offer["sd_path"].endswith(".bin")
            assert client.get(offer["download_url"],headers=headers(OTHER)).status_code==403
            assert client.get(offer["download_url"],headers=headers(ADMIN)).status_code==403
            assert client.get(offer["download_url"],headers=headers()).content==image()
            bad=device.send("firmware_store_result",firmware_id=item["id"],transfer_id=offer["transfer_id"],status="ok",sha256="f"*64)
            assert device.until("error")["code"]=="event_rejected"
            sent=device.send("firmware_store_result",firmware_id=item["id"],transfer_id=offer["transfer_id"],status="ok",sha256=offer["sha256"])
            assert device.ack(sent)["result"]["status"]=="stored"
            socket.send_json(sent);assert device.ack(sent)["status"]=="duplicate"
            assert client.get(offer["download_url"],headers=headers()).status_code==403
            backend=client.app.state.backend
            assert backend.device_record(backend.session(device.session_id))["capabilities"]["firmware_version"]=="test-running"
            assert not backend.store.list("packages") and not backend.store.list("commands")


def test_unsupported_expired_or_corrupt_firmware_never_has_a_success_receipt(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as client:
        item=upload(client).json()
        with client.websocket_connect("/ws/device",headers=headers()) as socket:
            device=Device(socket);start(device)
            url=f"/desktop/firmware/{item['id']}/send"
            assert client.post(url,json={"device_id":"fire-01"},headers=headers(ADMIN)).status_code==400
            backend=client.app.state.backend;s=backend.session(device.session_id)
            s.capabilities["firmware_storage"]=True
            assert client.post(url,json={"device_id":"fire-01"},headers=headers(ADMIN)).status_code==200
            offer=device.until("firmware_store_request")
            backend.store.path("firmware",item["id"],".bin").write_bytes(b"corrupt")
            assert client.get(offer["download_url"],headers=headers()).status_code==400
            job=backend.store.get("firmware_jobs",offer["transfer_id"]);job["expires_at"]=time.time()-1
            backend.store.put("firmware_jobs",job["id"],job)
            assert client.get(offer["download_url"],headers=headers()).status_code==403
            assert backend.firmware.catalog()["transfers"][0]["status"]=="expired"


def test_firmware_upload_auth_limits_header_and_secret_rejection(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as client:
        assert upload(client,Authorization=headers()["Authorization"]).status_code==403
        assert upload(client,Origin="http://untrusted.invalid").status_code==403
        assert upload(client,**{"Content-Length":str(4194305)}).status_code==413
        assert upload(client,b"not firmware").status_code==400
        assert upload(client,image()+ADMIN.encode()).status_code==400
        assert upload(client,**{"X-Firmware-Name":"../firmware.bin"}).status_code==400
        bad=bytearray(image());bad[12]=9
        assert upload(client,bytes(bad)).status_code==400
        assert not client.app.state.backend.firmware.catalog()["files"]

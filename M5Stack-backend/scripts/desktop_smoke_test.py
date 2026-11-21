"""Exercise the running Windows bundle with a PC peer, never physical proof.

Reads this Windows user's desktop credentials; never prints or exports them.
Requires the desktop's mock mode. No real OpenAI calls are made.
"""
import asyncio
import argparse
import hashlib
import json
from pathlib import Path
import uuid

import httpx
from websockets.asyncio.client import connect

from fire_backend.builds import verify_archive
from fire_backend.desktop_config import DesktopStore


async def check(input_audio=False):
    store = DesktopStore()
    settings = store.settings()
    if settings.fire_ai_mode != "mock":
        raise ValueError("Desktop smoke requires test mode; it never makes paid calls.")
    base = f"http://127.0.0.1:{settings.fire_backend_port}"
    device_id = store.config.device_ids[0]
    device_headers = {"Authorization": "Bearer " + settings.device_tokens()[device_id]}
    admin_headers = {"Authorization": "Bearer " + settings.fire_backend_token.get_secret_value()}
    boot = "boot-pc-test-" + uuid.uuid4().hex[:16]
    session_id = None
    reports = []
    async with httpx.AsyncClient(base_url=base, headers=admin_headers, timeout=30, trust_env=False) as http:
        assert (await http.get("/health")).json()["mode"] == "mock"
        async with connect(base.replace("http://", "ws://") + "/ws/device", additional_headers=device_headers, proxy=None) as socket:
            async def send(name, **data):
                event = {"type": "device_event", "event": name, "protocol_version": "0.2",
                         "event_id": "desktop-test-" + uuid.uuid4().hex, "device_id": device_id, "boot_id": boot,
                         **({"session_id": session_id} if session_id else {}), **data}
                await socket.send(json.dumps(event))
                return event["event_id"]

            async def until(kind, event_id=None):
                async with asyncio.timeout(120):
                    while True:
                        message = json.loads(await socket.recv())
                        if message["type"] == "error":
                            raise ValueError(message["message"])
                        if message["type"] == kind and (not event_id or message.get("event_id") == event_id):
                            return message

            await send("session_start", target="device", capabilities={"api_version": "fire-lua-0.1",
                "services": ["display", "buttons", "rgb", "imu", "time"], "max_memory": 131072,
                "max_runtime_ms": 10000, "audio_input": False, "audio_output": False,
                "firmware_version": "pc-desktop-test"})
            start = await until("session_started")
            session_id = start["session_id"]
            assert start["state"] == "idle" and not start["physical_verified"]
            assert (await until("capability_status"))["code"] == "audio_input_unavailable"
            for prompt in ("Lag en sirkel", "Lag Snake", "Lag RGB-effekt", "Lag IMU-graf"):
                response = await http.post(f"/desktop/sessions/{session_id}/text", json={"text": prompt})
                response.raise_for_status()
                proposal = await until("build_proposal")
                snapshot = (await http.get("/desktop/status")).json()
                selected = next(s for s in snapshot["sessions"] if s["session_id"] == session_id)
                assert selected["proposal_id"] == proposal["proposal_id"]
                response = await http.post("/build/confirm", json={"session_id": session_id,
                    "proposal_id": proposal["proposal_id"], "event_id": "desktop-build-" + uuid.uuid4().hex})
                response.raise_for_status()
                ready = await until("package_ready")
                offer = await until("install_request")
                response = await http.get(offer["download_url"], headers=device_headers)
                response.raise_for_status()
                assert len(response.content) == offer["size_bytes"]
                assert hashlib.sha256(response.content).hexdigest() == offer["archive_sha256"]
                import tempfile
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "package.zip"
                    path.write_bytes(response.content)
                    verify_archive(path, ready["manifest"], offer["archive_sha256"])
                run_confirmation = {"session_id": session_id, "package_id": ready["package_id"],
                                    "event_id": "desktop-run-" + uuid.uuid4().hex}
                assert (await http.post("/run/confirm", json=run_confirmation)).status_code in {400, 409}
                event_id = await send("device_install_result", package_id=ready["package_id"], install_id=offer["install_id"],
                                      status="ok", archive_sha256=offer["archive_sha256"])
                await until("event_ack", event_id)
                run_confirmation["event_id"] = "desktop-run-" + uuid.uuid4().hex
                (await http.post("/run/confirm", json=run_confirmation)).raise_for_status()
                run = await until("run_request")
                await until("event_ack", await send("app_started", package_id=ready["package_id"], run_id=run["run_id"]))
                await until("event_ack", await send("app_healthy", package_id=ready["package_id"], run_id=run["run_id"]))
                device = (await http.get("/devices/" + device_id)).json()
                assert device["current"] == ready["package_id"] and not device["physical_verified"]
                await until("event_ack", await send("app_stopped", package_id=ready["package_id"], run_id=run["run_id"], reason="completed"))
                reports.append({"prompt": prompt, "package_id": ready["package_id"], "physical_verified": False,
                                "native_audio_flags": False, "validation": "bundled Lua worker passed"})
            await send("session_stop")
            await until("session_stopped")
        if input_audio:
            from device_smoke_test import tone_wav
            session_id = None
            boot = "boot-pc-audio-" + uuid.uuid4().hex[:16]
            async with connect(base.replace("http://", "ws://") + "/ws/device", additional_headers=device_headers, proxy=None) as socket:
                await send("session_start", target="device", capabilities={"api_version": "fire-lua-0.1",
                    "services": ["display", "buttons", "rgb", "imu", "time"], "max_memory": 131072,
                    "max_runtime_ms": 10000, "audio_input": True, "audio_output": False,
                    "firmware_version": "pc-input-only-test"})
                session_id = (await until("session_started"))["session_id"]
                assert (await until("capability_status"))["code"] == "audio_output_unavailable"
                turn = "turn-pc-" + uuid.uuid4().hex[:16]
                await until("event_ack", await send("listen_start", turn_id=turn))
                await until("event_ack", await send("listen_stop", turn_id=turn))
                response = await http.post(f"/sessions/{session_id}/audio/{turn}", content=tone_wav(),
                    headers={**device_headers, "Content-Type": "audio/wav"})
                assert response.status_code == 202
                assert (await until("transcript"))["mode"] == "mock"
                assert (await until("build_proposal"))["proposal_id"]
                await send("session_stop")
                await until("session_stopped")
    destination = Path("workspace/logs/desktop-smoke-report.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "examples": len(reports), "input_only_audio": input_audio,
                      "physical_verified": False, "target": "running Windows app"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-audio", action="store_true", help="Also test new native input-only profile with a synthetic WAV")
    asyncio.run(check(parser.parse_args().input_audio))

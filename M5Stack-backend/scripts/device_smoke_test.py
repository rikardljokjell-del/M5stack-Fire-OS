"""Real HTTP/WS integration with an emulated firmware peer, NEVER physical proof."""
import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import struct
import tempfile
import uuid
import wave
import zipfile
from pathlib import Path

import httpx
from dotenv import load_dotenv
from websockets.asyncio.client import connect

from fire_backend.builds import simulate, verify_archive
from fire_backend.security import Redactor
from fire_backend.storage import Store


def tone_wav():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", int(1800 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(8000)))
    return stream.getvalue()


async def test_peer(url, device_id, all_examples=False, audio=False, live=False):
    load_dotenv()
    token = os.getenv("FIRE_MOCK_DEVICE_TOKEN") or json.loads(os.getenv("FIRE_DEVICE_TOKENS", "{}")).get(device_id)
    if not token:
        raise ValueError("Set FIRE_MOCK_DEVICE_TOKEN or configure this ID in FIRE_DEVICE_TOKENS locally")
    headers = {"Authorization": "Bearer " + token}
    reports = []
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=30) as http:
        health = (await http.get("/health")).json()
        if health["mode"] != "mock" and not live:
            raise ValueError("--live is required to test paid OpenAI calls")
        if audio and (health["mode"] != "mock" or not health["audio_enabled"]):
            raise ValueError("Synthetic audio smoke requires mock mode and FIRE_AUDIO_ENABLED=true")
        prompts = ["Lag en animasjon med en sirkel som beveger seg."]
        if all_examples:
            prompts += ["Lag Snake", "Lag en RGB-effekt", "Lag en enkel IMU-graf"]
        if audio:
            prompts.append(None)
        for prompt in prompts:
            boot_id = "boot-" + uuid.uuid4().hex[:16]
            session_id = None
            seq = 0
            async with connect(url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/device", additional_headers=headers) as socket:
                async def send(event, **values):
                    event_id = "event-" + uuid.uuid4().hex
                    await socket.send(json.dumps({"type": "device_event", "protocol_version": "0.2", "device_id": device_id,
                        "boot_id": boot_id, "event_id": event_id, "event": event,
                        **({"session_id": session_id} if session_id else {}), **values}))
                    return event_id

                async def until(kind, event_id=None):
                    nonlocal seq
                    async with asyncio.timeout(240):
                        while True:
                            event = json.loads(await socket.recv())
                            if "seq" in event:
                                assert event["seq"] > seq
                                seq = event["seq"]
                            if event["type"] == "error":
                                raise ValueError(event["message"])
                            if event["type"] == kind and (event_id is None or event.get("event_id") == event_id):
                                return event

                await send("session_start", target="device", capabilities={"services": ["display", "buttons", "rgb", "imu", "time"],
                    "max_memory": 131072, "max_runtime_ms": 10000, "audio_input": True, "audio_output": True,
                    "firmware_version": "pc-device-emulator"})
                started = await until("session_started")
                session_id = started["session_id"]
                if prompt is None:
                    turn_id = "turn-" + uuid.uuid4().hex[:16]
                    await until("event_ack", await send("listen_start", turn_id=turn_id))
                    await until("event_ack", await send("listen_stop", turn_id=turn_id))
                    response = await http.post(f"/sessions/{session_id}/audio/{turn_id}", content=tone_wav(), headers={"Content-Type": "audio/wav"})
                    response.raise_for_status()
                    await until("transcript")
                else:
                    await send("text", text=prompt)
                proposal = await until("build_proposal")
                if prompt is None:
                    clip = await until("audio_ready")
                    response = await http.get(clip["download_url"])
                    response.raise_for_status()
                    assert hashlib.sha256(response.content).hexdigest() == clip["sha256"]
                    await until("event_ack", await send("audio_playback_started", turn_id=turn_id, audio_id=clip["audio_id"]))
                    await until("event_ack", await send("audio_playback_finished", turn_id=turn_id, audio_id=clip["audio_id"]))
                assert (await http.get("/devices/" + device_id)).json()["current"] is None
                await send("build_confirm", proposal_id=proposal["proposal_id"])
                ready = await until("package_ready")
                offer = await until("install_request")
                response = await http.get(offer["download_url"])
                response.raise_for_status()
                assert len(response.content) == offer["size_bytes"]
                assert hashlib.sha256(response.content).hexdigest() == offer["archive_sha256"]
                with tempfile.TemporaryDirectory(prefix="fire-device-emulator-") as temp:
                    archive_path = Path(temp) / "package.zip"
                    archive_path.write_bytes(response.content)
                    verify_archive(archive_path, ready["manifest"], ready["archive_sha256"])
                    with zipfile.ZipFile(archive_path) as archive:
                        source = archive.read(f"apps/{ready['manifest']['id']}/main.lua").decode("utf-8")
                    await until("event_ack", await send("device_install_result", package_id=offer["package_id"], install_id=offer["install_id"],
                        status="ok", archive_sha256=offer["archive_sha256"]))
                    assert (await http.get("/devices/" + device_id)).json().get("running_package_id") is None
                    await send("run_confirm", package_id=offer["package_id"])
                    run = await until("run_request")
                    store = Store(Path(temp) / "simulation", Redactor(token, os.getenv("OPENAI_API_KEY", "")), 4 * 1024 * 1024)
                    result = await simulate({"main_lua": source, **ready["manifest"]}, store, ready["package_id"])
                    await until("event_ack", await send("app_started", package_id=ready["package_id"], run_id=run["run_id"]))
                    await until("event_ack", await send("app_healthy", package_id=ready["package_id"], run_id=run["run_id"]))
                    status = (await http.get("/devices/" + device_id)).json()
                    assert status["current"] == status["running_package_id"] == ready["package_id"]
                    await until("event_ack", await send("app_stopped", package_id=ready["package_id"], run_id=run["run_id"], reason="completed"))
                reports.append({"input": prompt or "synthetic_audio", "mode": health["mode"], "target": "device_emulation",
                    "physical_verified": False, "package_id": ready["package_id"], "frames": result["frames"],
                    "archive_sha256": ready["archive_sha256"], "audio_transport_tested": prompt is None})
                await send("session_stop")
                await until("session_stopped")
    report_path = Path(os.getenv("FIRE_WORKSPACE", "workspace")) / "logs" / "device-smoke-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "examples": len(reports), "target": "device_emulation", "physical_verified": False,
                      "report": str(report_path.resolve())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--device-id", default="fire-01")
    parser.add_argument("--all-examples", action="store_true")
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    asyncio.run(test_peer(args.url, args.device_id, args.all_examples, args.audio, args.live))

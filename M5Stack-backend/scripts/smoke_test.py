"""End-to-end test against a real running backend. Explicitly confirms test builds/runs."""
import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from websockets.asyncio.client import connect


async def smoke(url, all_examples=False, live=False):
    load_dotenv()
    token = os.getenv("FIRE_BACKEND_TOKEN", "")
    headers = {"Authorization": "Bearer " + token} if token else {}
    reports = []
    async with httpx.AsyncClient(base_url=url, headers=headers) as http:
        health = (await http.get("/health")).json()
        if health["mode"] != "mock" and not live:
            raise RuntimeError("Expected mock mode. --live explicitly enables paid OpenAI testing.")
        commands = ["Lag en animasjon med en sirkel som beveger seg."]
        if all_examples:
            commands += ["Lag Snake", "Lag en RGB-effekt", "Lag en enkel IMU-graf"]
        for index, command in enumerate(commands):
            device_id = f"smoke-{index}"
            ws_url = url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/device"
            events = []
            async with connect(ws_url, additional_headers=headers) as socket:
                async def send(event, **values):
                    await socket.send(json.dumps({"type": "device_event", "device_id": device_id, "event": event, **values}))

                async def until(kind):
                    async with asyncio.timeout(240):
                        while True:
                            event = json.loads(await socket.recv())
                            events.append(event)
                            if event["type"] == "error":
                                raise RuntimeError(event["message"])
                            if event["type"] == kind:
                                return event

                await send("session_start")
                start = await until("session_started")
                await send("text", text=command)
                proposal = await until("build_proposal")
                project = (await http.get(f"/projects/{start['project_id']}")).json()
                assert project["latest_package"] is None, "Build started without confirmation"
                await send("build_confirm", proposal_id=proposal["proposal_id"])
                ready = await until("package_ready")
                package_id = ready["package_id"]
                response = await http.get(f"/packages/{package_id}/download")
                response.raise_for_status()
                project = (await http.get(f"/projects/{start['project_id']}")).json()
                assert project["current"] is None, "Run started without confirmation"
                await send("run_confirm", package_id=package_id)
                run = await until("run_result")
                assert run["status"] == "completed"
                reports.append({"command": command, "mode": health["mode"], "build_id": package_id,
                                "project_id": start["project_id"], "run": run,
                                "manifest": ready["manifest"], "archive_sha256": ready["archive_sha256"],
                                "progress_phases": [e["phase"] for e in events if e["type"] == "build_progress"]})
                await send("session_stop")
                await until("session_stopped")
    destination = Path(os.getenv("FIRE_WORKSPACE", "workspace")) / "logs" / "smoke-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "examples": len(reports), "mode": health["mode"], "report": str(destination.resolve())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--all-examples", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    asyncio.run(smoke(args.url, args.all_examples, args.live))

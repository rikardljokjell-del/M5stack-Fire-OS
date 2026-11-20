import argparse
import asyncio
import json
import os

from dotenv import load_dotenv
from websockets.asyncio.client import connect


async def mock(url, demo=False):
    load_dotenv()
    token = os.getenv("FIRE_BACKEND_TOKEN", "")
    headers = {"Authorization": "Bearer " + token} if token else {}
    device_id = "pc-mock-01"
    proposal_id = package_id = None

    async with connect(url, additional_headers=headers, max_size=32768) as socket:
        async def send(event, **values):
            await socket.send(json.dumps({"type": "device_event", "device_id": device_id, "event": event, **values}))

        await send("session_start")

        async def receive():
            nonlocal proposal_id, package_id
            async for raw in socket:
                event = json.loads(raw)
                print(json.dumps(event, ensure_ascii=False), flush=True)
                if event["type"] == "build_proposal":
                    proposal_id = event["proposal_id"]
                elif event["type"] == "package_ready":
                    package_id = event["package_id"]
                elif event["type"] == "session_stopped":
                    return

        if demo:
            print("Demo sender bare tekst. Bruk /build og /run for eksplisitt bekreftelse.")
            await send("text", text="Lag en animasjon med en sirkel som beveger seg.")

        async def terminal():
            while True:
                line = await asyncio.to_thread(input, "> ")
                if line == "/quit":
                    await send("session_stop")
                    return
                if line == "/build":
                    await send("build_confirm", proposal_id=proposal_id)
                elif line == "/run":
                    await send("run_confirm", package_id=package_id)
                elif line == "/ping":
                    await send("ping")
                elif line.strip():
                    await send("text", text=line)

        print("Skriv en melding. /build bekrefter bygging; /run bekrefter PC-test; /quit avslutter.")
        listener = asyncio.create_task(receive())
        try:
            await terminal()
            await asyncio.wait_for(listener, timeout=3)
        finally:
            listener.cancel()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws/device")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(mock(args.url, args.demo))
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()

"""Test actual configured AI -> bounded Lua -> /apps ZIP, without touching FIRE.

--live uses the saved Windows key/models and may incur API charges. Artifacts
are retained locally; no fabricated install/run receipts are submitted.
"""
import argparse
import asyncio
import json
from pathlib import Path
import secrets
import uuid

from pydantic import SecretStr

from fire_backend.audio import validate_wav
from fire_backend.builds import verify_archive
from fire_backend.desktop_config import DesktopStore
from fire_backend.models import SessionStart
from fire_backend.service import Backend


async def check(live=False, wav=None):
    desktop = DesktopStore()
    root = desktop.root / "verification" / ("pipeline-" + uuid.uuid4().hex[:12])
    settings = desktop.settings().model_copy(update={
        "fire_ai_mode": "openai" if live else "mock", "fire_workspace": root,
        "fire_reverse_host": "", "fire_reverse_device_id": "",
        "fire_device_tokens": SecretStr(json.dumps({"pipeline-check": secrets.token_urlsafe(32)})),
    })
    service = Backend(settings)
    try:
        session = await service.start(SessionStart(device_id="pipeline-check", target="device",
            protocol_version="0.2", boot_id="boot-pc-check", capabilities={
                "api_version": "fire-lua-0.1", "services": ["display", "buttons", "rgb", "imu", "time"],
                "max_memory": 131072, "max_runtime_ms": 10000, "audio_input": True, "audio_output": False,
                "firmware_version": "pc-pipeline-check"}), principal="pipeline-check")
        text = "Lag en enkel animasjon med en grønn sirkel som beveger seg og spretter i skjermkantene."
        transcription = False
        if wav:
            data = Path(wav).read_bytes()
            if len(data) > settings.fire_audio_max_input_bytes:
                raise ValueError("WAV exceeds input limit")
            validate_wav(data)
            async with asyncio.timeout(settings.fire_ai_timeout_seconds):
                text = await service.provider.transcribe(data)
            transcription = bool(text.strip())
        await service.text(session, text)
        if not session.proposal_id:
            raise ValueError(session.last_error or "AI asked for clarification instead of a concrete app plan")
        await service.confirm_build(session, session.proposal_id)
        await session.task
        if not session.package_id:
            raise ValueError(session.last_error or "Package build failed")
        package = service.verify_package(session, session.package_id)
        verify_archive(service.store.path("packages", package["id"], ".zip"), package["manifest"], package["archive_sha256"])
        result = {"status": "passed", "mode": settings.fire_ai_mode, "live_ai_verified": live,
                  "transcription_verified": transcription, "physical_verified": False,
                  "manifest": package["manifest"], "size_bytes": package["size_bytes"],
                  "artifacts": str(root), "device_installation": "not_attempted"}
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "mode": settings.fire_ai_mode,
                          "error": service.redactor.text(str(error))[:600],
                          "artifacts": str(root), "physical_verified": False}, ensure_ascii=True))
        return 1
    finally:
        await service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--wav", help="Optional real Norwegian PCM16 mono 16000-Hz recording")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.live, args.wav)))

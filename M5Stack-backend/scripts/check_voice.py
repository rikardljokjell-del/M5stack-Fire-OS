"""Paid, isolated voice -> transcript -> RGB app -> spoken reply check.

Uses saved Windows settings, never the live FIRE session. Without --wav the
input is explicitly AI-generated Norwegian speech, not a physical microphone.
"""
import argparse
import array
import asyncio
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import uuid
import wave

from pydantic import SecretStr

from fire_backend.audio import AudioManager, validate_wav
from fire_backend.desktop_config import DesktopStore
from fire_backend.models import DeviceEvent, SessionStart
from fire_backend.protocol import dispatch
from fire_backend.service import Backend


def wav_from_pcm(pcm, rate):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(rate)
        handle.writeframes(pcm)
    return output.getvalue()


def input_wav(pcm):
    values = array.array("h", pcm)
    if sys.byteorder != "little":
        values.byteswap()
    # Small test recording: linear 24-kHz -> 16-kHz conversion, no new runtime
    # dependencies. Production FIRE supplies its native 16-kHz recording.
    result = array.array("h")
    for i in range(len(values) * 2 // 3):
        at = i * 3 // 2
        result.append(values[at] if i % 2 == 0 else (values[at] + values[min(at+1, len(values)-1)]) // 2)
    if sys.byteorder != "little":
        result.byteswap()
    return wav_from_pcm(result.tobytes(), 16000)


class Peer:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


async def check(live, wav=None):
    if not live:
        print(json.dumps({"status": "not_run", "reason": "--live required", "physical_verified": False}))
        return 2
    desktop = DesktopStore()
    root = desktop.root / "verification" / ("voice-" + uuid.uuid4().hex[:12])
    settings = desktop.settings().model_copy(update={"fire_ai_mode": "openai", "fire_workspace": root,
        "fire_reverse_host": "", "fire_reverse_device_id": "", "fire_audio_enabled": True,
        "fire_device_tokens": SecretStr(json.dumps({"voice-check": secrets.token_urlsafe(32)}))})
    service = Backend(settings)
    service.audio = AudioManager(service)
    peer = Peer()
    try:
        if wav:
            with Path(wav).open("rb") as handle:
                data = handle.read(settings.fire_audio_max_input_bytes + 1)
        else:
            pcm = bytearray()
            async with asyncio.timeout(settings.fire_ai_timeout_seconds):
                async for chunk in service.provider.speech("Lag en app som blinker med RGB-lys."):
                    pcm.extend(chunk)
                    if len(pcm) > settings.fire_audio_max_output_bytes:
                        raise ValueError("Test speech exceeded limit")
            data = input_wav(pcm)
        if len(data) > settings.fire_audio_max_input_bytes:
            raise ValueError("Input recording exceeds limit")
        validate_wav(data)
        session = await service.start(SessionStart(device_id="voice-check", target="device", protocol_version="0.2",
            boot_id="boot-voice-pc", capabilities={"services": ["display", "buttons", "rgb", "imu", "time"],
                "max_memory": 131072, "max_runtime_ms": 10000, "audio_input": True, "audio_output": True,
                "firmware_version": "pc-voice-check"}), peer, "voice-check")
        for event in ("listen_start", "listen_stop"):
            await dispatch(service, session, DeviceEvent(device_id=session.device_id, protocol_version="0.2",
                event_id=event, session_id=session.id, boot_id=session.boot_id, event=event, turn_id="turn-voice-check"))
        async def stream():
            for at in range(0, len(data), 4096):
                yield data[at:at+4096]
        await service.audio.receive(session, "turn-voice-check", stream())
        await session.input_task
        if not session.proposal_id or service.store.list("builds"):
            raise ValueError(session.last_error or "Voice did not produce a pending proposal")
        if session.speech_task:
            await session.speech_task
        ready = next((m for m in peer.messages if m["type"] == "audio_ready"), None)
        if not ready:
            raise ValueError("No playable spoken reply was produced")
        item, path = service.audio.clip(ready["audio_id"], session.device_id)
        speech = path.read_bytes()
        (root / "spoken-reply.wav").write_bytes(wav_from_pcm(speech, 24000))
        for event in ("audio_playback_started", "audio_playback_finished"):
            await dispatch(service, session, DeviceEvent(device_id=session.device_id, protocol_version="0.2",
                event_id=event, session_id=session.id, boot_id=session.boot_id, event=event,
                turn_id="turn-voice-check", audio_id=ready["audio_id"]))
        await service.confirm_build(session, session.proposal_id)
        await session.task
        if not session.package_id:
            raise ValueError(session.last_error or "Voice app build failed")
        package = service.verify_package(session, session.package_id)
        if not wav and "rgb" not in package["manifest"]["required_services"]:
            raise ValueError("Spoken RGB request did not produce an RGB app")
        transcript = next(m["text"] for m in peer.messages if m["type"] == "transcript")
        result = {"status": "passed", "input_source": "wav_file" if wav else "AI-generated Norwegian test speech",
                  "transcript": transcript, "speech_bytes": len(speech), "speech_sha256": hashlib.sha256(speech).hexdigest(),
                  "manifest": package["manifest"], "artifacts": str(root), "physical_verified": False,
                  "device_microphone_verified": False, "device_speaker_verified": False}
        (root / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": service.redactor.text(str(error))[:600],
                          "artifacts": str(root), "physical_verified": False}, ensure_ascii=True))
        return 1
    finally:
        await service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--wav")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.live, args.wav)))

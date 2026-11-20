"""Explicit paid provider check. Never prints keys, headers or raw provider errors."""
import argparse
import asyncio
import json
import contextlib
from importlib.resources import files
from pathlib import Path

from fire_backend.ai import OpenAIProvider
from fire_backend.config import Settings


async def check(live, speech, wav=None):
    settings = Settings()
    if not live or not settings.openai_api_key.get_secret_value():
        print(json.dumps({"status": "not_run", "reason": "--live and OPENAI_API_KEY are required", "live_verified": False}))
        return 2
    provider = OpenAIProvider(settings)
    manager = None
    try:
        context = files("fire_backend").joinpath("data/FIRE_DEVICE_CONTEXT.md").read_text(encoding="utf-8")
        async with asyncio.timeout(settings.fire_ai_timeout_seconds):
            manager, connection = await provider.connect_dialog(context)
            reply = await provider.dialog([{"role": "user", "content": "Lag en animasjon med en sirkel som beveger seg."}], context, connection)
            generated = await provider.generate(reply.build_summary or "Lag en grønn sirkel som beveger seg.", context)
            transcription_verified = False
            if wav:
                from fire_backend.audio import validate_wav
                with Path(wav).open("rb") as handle:
                    data = handle.read(settings.fire_audio_max_input_bytes + 1)
                if len(data) > settings.fire_audio_max_input_bytes:
                    raise ValueError("Audio input size exceeded")
                validate_wav(data)
                transcription_verified = bool((await provider.transcribe(data)).strip())
            speech_bytes = 0
            if speech:
                async for chunk in provider.speech("Backendtesten er ferdig."):
                    speech_bytes += len(chunk)
                    if speech_bytes > settings.fire_audio_max_output_bytes:
                        raise ValueError("Speech size exceeded")
        print(json.dumps({"status": "passed", "live_verified": True, "dialog_model": settings.openai_realtime_model,
                          "code_model": settings.openai_code_model, "lua_chars": len(generated.main_lua),
                          "speech_bytes": speech_bytes, "transcription_verified": transcription_verified, "physical_verified": False}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "live_verified": False}))
        return 1
    finally:
        if manager:
            with contextlib.suppress(Exception):
                await manager.__aexit__(None, None, None)
        await provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--speech", action="store_true")
    parser.add_argument("--wav", help="Optional real mono PCM16/16000 Hz Norwegian recording")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.live, args.speech, args.wav)))

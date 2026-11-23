import asyncio
import base64
import io
import wave
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from fire_backend.ai import OpenAIProvider
from fire_backend.config import Settings


@pytest.mark.parametrize("model", ["gpt-transcribe", "gpt-4o-mini-transcribe", "gpt-4o-transcribe-diarize"])
async def test_transcription_uses_real_sdk_multipart_and_language_hints(model):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"text": "Lag en sirkel", "languages": [{"code": "no"}]})

    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="sk-sdk-secret", openai_transcribe_model=model))
    provider.client = AsyncOpenAI(api_key="sk-sdk-secret", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        wav=io.BytesIO()
        with wave.open(wav,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(bytes(1600))
        assert await provider.transcribe(wav.getvalue()) == "Lag en sirkel"
        request = calls[0]
        assert str(request.url) == "https://api.openai.com/v1/audio/transcriptions"
        assert model.encode() in request.content and b'turn.wav' in request.content
        if model == "gpt-transcribe":
            assert b'name="languages"' in request.content or b'name="languages[]"' in request.content
            assert b'keywords' in request.content
            assert b'name="language"' not in request.content
        else:
            assert b'name="language"' in request.content
            assert b'keywords' not in request.content and b'languages' not in request.content
        assert b'no' in request.content
        assert ('Norsk samtale'.encode() in request.content) is ("diarize" not in model)
        assert b'Snake' not in request.content  # Do not bias every recording towards one demo app.
        assert b'sk-sdk-secret' not in request.content
    finally:
        await provider.close()


async def test_speech_uses_realtime_pcm_and_closes_connection():
    calls = []

    class Connection:
        def __init__(self):
            self.session = SimpleNamespace(update=self.update)
            self.conversation = SimpleNamespace(item=SimpleNamespace(create=self.item))
            self.response = SimpleNamespace(create=self.create)

        async def update(self, **values):
            calls.append(values)

        async def item(self, **values):
            calls.append(values)

        async def create(self,**values):
            assert values['response']['max_output_tokens']==1200

        def __aiter__(self):
            async def events():
                yield SimpleNamespace(type="response.output_audio.delta", delta=base64.b64encode(b"\x00\x01" * 100).decode())
                yield SimpleNamespace(type="response.done", response=SimpleNamespace(status="completed"))
            return events()

    class Manager:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            calls.append("closed")

    def connect(**values):
        assert values["model"] == "gpt-realtime-2.1-mini"
        return Manager()

    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="test"))
    provider.client = SimpleNamespace(realtime=SimpleNamespace(connect=connect))
    chunks = [chunk async for chunk in provider.speech("Hei fra FIRE")]
    assert b"".join(chunks) == b"\x00\x01" * 100
    assert calls[0]["session"]["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert "Hei fra FIRE" in calls[1]["item"]["content"][0]["text"]
    assert calls[-1] == "closed"


async def test_cancelling_speech_releases_provider_connection_immediately():
    started, closed = asyncio.Event(), asyncio.Event()

    class Connection:
        def __init__(self):
            self.session = SimpleNamespace(update=self.ignore)
            self.conversation = SimpleNamespace(item=SimpleNamespace(create=self.ignore))
            self.response = SimpleNamespace(create=self.ignore)

        async def ignore(self, **values):
            pass

        def __aiter__(self):
            async def events():
                started.set()
                await asyncio.Event().wait()
                yield  # never produces audio after cancellation
            return events()

    class Manager:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *args):
            closed.set()

    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="test"))
    provider.client = SimpleNamespace(realtime=SimpleNamespace(connect=lambda **values: Manager()))
    async def consume():
        return [chunk async for chunk in provider.speech("Dette avbrytes.")]
    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert closed.is_set()


async def test_interrupted_realtime_function_is_not_an_accepted_plan():
    class Connection:
        def __init__(self):
            self.response = SimpleNamespace(create=self.create)

        async def create(self, **kwargs):
            pass

        def __aiter__(self):
            async def events():
                yield SimpleNamespace(type="response.function_call_arguments.done", name="dialog_reply", arguments='{"message":"Bygg","clarification_needed":false,"build_summary":"Sirkel"}')
                yield SimpleNamespace(type="response.done", response=SimpleNamespace(status="cancelled"))
            return events()

    provider = OpenAIProvider(Settings(_env_file=None))
    with pytest.raises(ValueError, match="did not complete"):
        await provider.dialog([{"role": "user", "content": "Sirkel"}], "Context", Connection())

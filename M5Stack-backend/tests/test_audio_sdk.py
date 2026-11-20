import base64
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from fire_backend.ai import OpenAIProvider
from fire_backend.config import Settings


async def test_transcription_uses_real_sdk_multipart_and_language_hints():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"text": "Lag en sirkel", "languages": [{"code": "no"}]})

    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="sk-sdk-secret", openai_transcribe_model="gpt-transcribe"))
    provider.client = AsyncOpenAI(api_key="sk-sdk-secret", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        assert await provider.transcribe(b"test-wav-content") == "Lag en sirkel"
        request = calls[0]
        assert str(request.url) == "https://api.openai.com/v1/audio/transcriptions"
        assert b'gpt-transcribe' in request.content and b'turn.wav' in request.content
        assert b'languages' in request.content and b'no' in request.content
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

        async def create(self):
            pass

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

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from fire_backend.ai import MockProvider, OpenAIProvider
from fire_backend.app import create_app
from fire_backend.config import Settings
from fire_backend.models import GeneratedApp, SessionStart
from fire_backend.service import Backend
from fastapi.testclient import TestClient


async def test_actual_sdk_responses_request_contains_context_and_error(tmp_path):
    requests = []
    source = "function init() end function update(dt) end"

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "resp_test", "created_at": 1, "object": "response", "status": "completed",
            "model": "configured-code-model", "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "output": [{"id": "msg_test", "type": "message", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "annotations": [], "text": json.dumps({
                            "name": "Test", "main_lua": source, "required_services": []})}]}],
        })

    settings = Settings(_env_file=None, openai_api_key="sk-test-secret-key", openai_code_model="configured-code-model")
    provider = OpenAIProvider(settings)
    provider.client = AsyncOpenAI(api_key="sk-test-secret-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    try:
        app = await provider.generate("Confirmed plan", "COMPACT HARDWARE CONTEXT", "syntax error line 4", "broken code")
        assert app.main_lua == source
        request = requests[0]
        body = json.loads(request.content)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert body["model"] == "configured-code-model"
        assert 'instructions' not in body
        assert body['input'][0]['role']=='developer'
        assert "COMPACT HARDWARE CONTEXT" in body['input'][0]['content']
        assert body['input'][1]['role']=='user'
        assert "syntax error line 4" in body['input'][1]['content']
        assert body["store"] is False
        assert body["text"]["format"]["type"] == "json_schema"
        assert "sk-test" not in request.content.decode()
    finally:
        await provider.close()


class FakeRealtime:
    def __init__(self):
        self.calls = []
        self.session = SimpleNamespace(update=self.update)
        self.conversation = SimpleNamespace(item=SimpleNamespace(create=self.item))
        self.response = SimpleNamespace(create=self.create)

    async def update(self, **kwargs):
        self.calls.append(("update", kwargs))

    async def item(self, **kwargs):
        self.calls.append(("item", kwargs))

    async def create(self, **kwargs):
        self.calls.append(("response", kwargs))

    def __aiter__(self):
        async def stream():
            yield SimpleNamespace(type="response.function_call_arguments.done", name="dialog_reply", arguments=json.dumps({
                "message": "Hva skal appen gjøre?", "clarification_needed": True, "build_summary": ""}))
            yield SimpleNamespace(type="response.done", response=SimpleNamespace(status="completed"))
        return stream()


async def test_realtime_text_contract_and_backend_owned_connection():
    connection = FakeRealtime()

    class Manager:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, *args):
            pass

    def connect(**kwargs):
        assert kwargs["model"] == "configured-realtime"
        return Manager()

    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="secret", openai_realtime_model="configured-realtime"))
    provider.client = SimpleNamespace(realtime=SimpleNamespace(connect=connect))
    manager, active = await provider.connect_dialog("DEVICE CONTEXT GPIO39")
    result = await provider.dialog([{"role": "user", "content": "Hei"}], "context", active)
    assert result.clarification_needed
    assert connection.calls[0][1]["session"]["output_modalities"] == ["text"]
    assert "GPIO39" in connection.calls[0][1]["session"]["instructions"]
    response = connection.calls[1][1]["response"]
    assert response["conversation"] == "none"
    assert json.loads(response["input"][0]["content"][0]["text"])[-1]["content"] == "Hei"
    await manager.__aexit__(None, None, None)


@pytest.mark.parametrize("context,expected", [
    ("conversation_mode=chat\nDevice context", ""),
    ("conversation_mode=develop\nDevice context", "Lag en sirkel"),
    ("Device context\nconversation_mode=chat", "Lag en sirkel"),
])
async def test_provider_cannot_create_an_app_plan_in_authoritative_chat_mode(context, expected):
    class Plan(FakeRealtime):
        def __aiter__(self):
            async def events():
                yield SimpleNamespace(type="response.function_call_arguments.done", name="dialog_reply", arguments=json.dumps({
                    "message": "En sirkel som spretter.", "clarification_needed": False, "build_summary": "Lag en sirkel"}))
                yield SimpleNamespace(type="response.done", response=SimpleNamespace(status="completed"))
            return events()
    connection = Plan()
    provider = OpenAIProvider(Settings(_env_file=None))
    reply = await provider.dialog([{"role": "user", "content": "Lag en sirkel"}], context, connection)
    assert reply.build_summary == expected
    assert reply.message == "En sirkel som spretter."
    assert not reply.clarification_needed


async def test_reconnect_request_retains_corrections_and_agreed_requirements():
    history = [
        {"role": "user", "content": "Lag en grønn sirkel som spretter."},
        {"role": "assistant", "content": "Forslag: en grønn sirkel som spretter."},
        {"role": "user", "content": "Gjør den blå, og litt raskere."},
    ]
    connection = FakeRealtime()
    provider = OpenAIProvider(Settings(_env_file=None))
    await provider.dialog(history, "conversation_mode=develop\nDevice", connection)
    request = connection.calls[0][1]["response"]
    assert json.loads(request["input"][0]["content"][0]["text"]) == history
    assert request["conversation"] == "none"
    assert "a short correction" in request["instructions"]
    assert "all still-agreed requirements" in request["instructions"].replace("\n", " ")


class LeakyProvider(MockProvider):
    async def generate(self, *args, **kwargs):
        return GeneratedApp(name="No key", main_lua="local s='sk-test-very-secret-key'\nfunction init() end function update(dt) end", required_services=[])


async def test_secret_redaction_across_code_packages_events_logs(tmp_path):
    key = "sk-test-very-secret-key"
    settings = Settings(_env_file=None, openai_api_key=key, fire_ai_mode="mock", fire_workspace=tmp_path)
    service = Backend(settings, LeakyProvider())
    try:
        session = await service.start(SessionStart())
        await service.text(session, "Lag en sirkel " + key)
        await service.confirm_build(session, session.proposal_id)
        await session.task
        assert session.package_id
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert key.encode() not in path.read_bytes(), str(path)
    finally:
        await service.close()


def test_http_validation_does_not_echo_secrets(tmp_path):
    settings = Settings(_env_file=None, fire_ai_mode="mock", fire_workspace=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post("/session/start", json={"device_id": "sk-secret", "OPENAI_API_KEY": "sk-test-key-must-not-echo"})
        assert response.status_code == 422
        assert "sk-test" not in response.text


async def test_no_key_fails_cleanly_without_fake_live_success(tmp_path):
    settings = Settings(_env_file=None, openai_api_key="", fire_ai_mode="openai", fire_workspace=tmp_path)
    service = Backend(settings)
    try:
        session = await service.start(SessionStart())
        await service.text(session, "Lag en sirkel")
        assert session.state == "failed"
        assert not service.store.list("builds")
        assert "OPENAI_API_KEY is missing" in service.store.path("logs", session.id, ".log").read_text()
    finally:
        await service.close()

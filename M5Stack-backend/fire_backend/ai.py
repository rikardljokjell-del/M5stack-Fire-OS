import asyncio
import json
from importlib.resources import files

from openai import AsyncOpenAI

from .models import DialogReply, GeneratedApp


class OpenAIProvider:
    """Only text/dialog and structured code; never grants tools or shell access."""

    def __init__(self, settings):
        self.settings = settings
        self.client = None

    def api(self):
        if not self.settings.openai_api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is missing; configure .env or use explicit mock mode")
        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                timeout=self.settings.fire_ai_timeout_seconds, max_retries=0,
            )
        return self.client

    async def close(self):
        if self.client:
            await self.client.close()

    async def connect_dialog(self, context):
        manager = self.api().realtime.connect(model=self.settings.openai_realtime_model)
        connection = await manager.__aenter__()
        try:
            await connection.session.update(session={
                "type": "realtime", "output_modalities": ["text"],
                "instructions": context + "\nReply ONLY with a JSON object containing message (string), "
                "clarification_needed (boolean), build_summary (string). "
                "Do not generate code. Set clarification_needed=false only when you can describe "
                "the complete requested app in build_summary. Never start builds or runs.",
            })
            return manager, connection
        except BaseException:
            await manager.__aexit__(None, None, None)
            raise

    async def dialog(self, history, context, connection):
        await connection.conversation.item.create(item={
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": history[-1]["content"]}],
        })
        await connection.response.create()
        output = ""
        async for event in connection:
            if event.type == "response.output_text.delta":
                output += event.delta
                if len(output) > 16000:
                    raise ValueError("Realtime response exceeds limit")
            elif event.type == "error":
                # No raw provider objects, headers or error body go to clients/logs.
                raise ValueError("OpenAI Realtime returned an error")
            elif event.type == "response.done":
                if event.response.status != "completed":
                    raise ValueError("OpenAI Realtime response did not complete")
                return DialogReply.model_validate_json(output)
        raise ValueError("OpenAI Realtime connection closed")

    async def generate(self, summary, context, error=None, previous=None):
        request = {"confirmed_app": summary, "previous_code": previous, "validation_error": error}
        response = await self.api().responses.parse(
            model=self.settings.openai_code_model,
            instructions=context + "\nGenerate a complete Lua app for this confirmed plan. "
            "Follow the prototype API exactly. Return name, main_lua, required_services. "
            "Only display/buttons/rgb/imu/time are implemented. Never include credentials.",
            input=json.dumps(request, ensure_ascii=False),
            text_format=GeneratedApp, store=False, max_output_tokens=8000,
        )
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("OpenAI code response incomplete or refused")
        return response.output_parsed


class MockProvider:
    """Explicit offline fixture, never presented as a live OpenAI test."""
    async def connect_dialog(self, context):
        return None, None

    async def close(self):
        pass

    async def dialog(self, history, context, connection=None):
        text = history[-1]["content"].lower()
        clear = any(word in text for word in ("sirkel", "circle", "snake", "rgb", "imu", "animasjon"))
        if not clear:
            return DialogReply(message="Hva skal appen gjøre på skjermen?", clarification_needed=True, build_summary="")
        if "snake" in text:
            return DialogReply(message="Jeg lager Snake med A/C for å svinge. Bekreft bygging.",
                               clarification_needed=False, build_summary="Lag Snake med A/C for å svinge.")
        if "rgb" in text:
            return DialogReply(message="Jeg lager en RGB-effekt med rødt og blått. Bekreft bygging.",
                               clarification_needed=False, build_summary="Lag RGB-effekt med rødt og blått.")
        if "imu" in text:
            return DialogReply(message="Jeg lager en enkel IMU-graf. Bekreft bygging.",
                               clarification_needed=False, build_summary="Lag en enkel IMU-graf.")
        return DialogReply(
            message="Jeg lager en grønn sirkel som beveger seg sidelengs på svart bakgrunn. Bekreft bygging for å fortsette.",
            clarification_needed=False, build_summary="Lag en grønn sirkel som beveger seg sidelengs og spretter ved skjermkanten.",
        )

    async def generate(self, summary, context, error=None, previous=None):
        await asyncio.sleep(0)
        kind, name, services = "circle", "Sirkelanimasjon", ["display"]
        if "snake" in summary.lower():
            kind, name, services = "snake", "Snake", ["display", "buttons"]
        elif "rgb" in summary.lower():
            kind, name, services = "rgb", "RGB-effekt", ["rgb"]
        elif "imu" in summary.lower():
            kind, name, services = "imu", "IMU-graf", ["display", "imu"]
        return GeneratedApp(name=name, main_lua=files("fire_backend").joinpath(f"data/{kind}.lua").read_text(encoding="utf-8"), required_services=services)

from pathlib import Path
import json
import re
from typing import Literal

from pydantic import Field, SecretStr, model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    openai_api_key: SecretStr = SecretStr("")
    openai_realtime_model: str = "gpt-realtime-2.1-mini"
    openai_code_model: str = "gpt-6.2-sol"
    openai_review_model: str = "gpt-6.2-sol"
    fire_daily_budget_usd: float = Field(default=2.0,gt=0,le=1000,allow_inf_nan=False)
    fire_request_budget_usd: float = Field(default=.25,gt=0,le=100,allow_inf_nan=False)
    fire_build_budget_usd: float = Field(default=.60,gt=0,le=100,allow_inf_nan=False)
    fire_max_corrections: int = Field(default=1,ge=0,le=3)
    fire_backend_host: str = "127.0.0.1"
    fire_backend_port: int = Field(default=8765, ge=1, le=65535)
    fire_ai_mode: Literal["openai", "mock"] = "openai"
    fire_workspace: Path = Path("workspace")
    fire_backend_token: SecretStr = SecretStr("")
    fire_build_timeout_seconds: int = Field(default=900, ge=5, le=900)
    fire_max_workspace_mb: int = Field(default=256, ge=1)
    fire_max_build_kb: int = Field(default=512, ge=8, le=4096)
    fire_progress_interval_seconds: float = Field(default=10, ge=1, le=30)
    fire_ai_timeout_seconds: int = Field(default=90, ge=2, le=300)
    fire_max_sessions: int = Field(default=8, ge=1, le=32)
    fire_device_tokens: SecretStr = SecretStr("{}")
    fire_session_resume_seconds: int = Field(default=600, ge=30, le=3600)
    fire_command_timeout_seconds: int = Field(default=30, ge=5, le=120)
    fire_audio_enabled: bool = False
    fire_desktop_enabled: bool = False
    fire_reverse_host: str = ""
    fire_reverse_port: int = Field(default=8766, ge=1024, le=65535)
    fire_reverse_device_id: str = Field(default="", pattern=r"^(?:[a-z0-9][a-z0-9_-]{0,63})?$")
    fire_audio_max_input_bytes: int = Field(default=524288, ge=32044, le=524288)
    fire_audio_max_output_bytes: int = Field(default=1440000, ge=48000, le=1440000)
    fire_audio_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    openai_transcribe_model: str = "gpt-transcribe"
    openai_speech_model: str = "gpt-realtime-2.1-mini"
    openai_speech_voice: str = "marin"

    def device_tokens(self):
        return json.loads(self.fire_device_tokens.get_secret_value())

    @field_validator("fire_reverse_host")
    @classmethod
    def reverse_address(cls, value):
        from .reverse_tcp import fire_address
        return fire_address(value)

    @model_validator(mode="after")
    def lan_requires_token(self):
        try:
            tokens = self.device_tokens()
            if not isinstance(tokens, dict) or any(
                not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", key)
                or not isinstance(value, str) or len(value) < 24
                for key, value in tokens.items()
            ) or len(set(tokens.values())) != len(tokens):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("FIRE_DEVICE_TOKENS must map unique device IDs to unique tokens of at least 24 characters") from None
        if self.fire_backend_token.get_secret_value() in tokens.values():
            raise ValueError("Admin token and device tokens must differ")
        if self.fire_reverse_host and self.fire_reverse_device_id not in tokens:
            raise ValueError("Reverse TCP requires a configured device ID/token")
        if self.fire_backend_host not in {"127.0.0.1", "localhost", "::1"}:
            if len(self.fire_backend_token.get_secret_value()) < 24:
                raise ValueError("LAN binding requires FIRE_BACKEND_TOKEN of at least 24 characters")
        return self

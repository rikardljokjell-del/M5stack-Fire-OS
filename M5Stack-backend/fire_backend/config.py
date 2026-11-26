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
    openai_code_model: str = "gpt-6-luna"
    openai_review_model: str = "gpt-6-luna"
    openai_runtime_model: str = 'gpt-6-luna'
    fire_runtime_ai_enabled: bool = True
    fire_runtime_ai_developer_mode: Literal['auto','off'] = 'auto'
    fire_runtime_ai_limits_enabled: bool = False
    fire_runtime_ai_request_budget_usd: float = Field(default=0,ge=0,allow_inf_nan=False)
    fire_runtime_ai_daily_budget_usd: float = Field(default=0,ge=0,allow_inf_nan=False)
    fire_runtime_ai_daily_calls: int = Field(default=0,ge=0)
    fire_runtime_ai_output_tokens: int = Field(default=1024,ge=16,le=4096)
    fire_cost_limits_enabled: bool = False
    fire_evolution_cost_limits_enabled: bool = True
    fire_output_limits_enabled: bool = False
    fire_daily_budget_usd: float = Field(default=0,ge=0,allow_inf_nan=False)
    fire_request_budget_usd: float = Field(default=0,ge=0,allow_inf_nan=False)
    fire_build_budget_usd: float = Field(default=0,ge=0,allow_inf_nan=False)
    fire_max_corrections: int = Field(default=0,ge=0)
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
    fire_speech_enabled: bool = True
    fire_desktop_enabled: bool = False
    fire_public_enabled: bool = False
    fire_web_origin: str = ""
    fire_device_host: str = ""
    fire_access_issuer: str = ""
    fire_access_audience: str = ""
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
        if self.fire_public_enabled:
            from urllib.parse import urlsplit
            origin = urlsplit(self.fire_web_origin)
            issuer = urlsplit(self.fire_access_issuer)
            if (origin.scheme != "https" or not origin.hostname or origin.path or origin.query or origin.fragment
                    or origin.username or origin.port not in (None, 443)
                    or not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", self.fire_device_host)
                    or self.fire_device_host == origin.hostname
                    or issuer.scheme != "https" or not issuer.hostname
                    or not issuer.hostname.endswith(".cloudflareaccess.com")
                    or issuer.path or issuer.query or issuer.fragment or issuer.username
                    or issuer.port not in (None, 443) or not self.fire_access_audience
                    or len(self.fire_backend_token.get_secret_value()) < 24):
                raise ValueError("Public access requires distinct HTTPS browser/device hosts, Cloudflare issuer/audience and admin credential")
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

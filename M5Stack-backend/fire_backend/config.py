from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    openai_api_key: SecretStr = SecretStr("")
    openai_realtime_model: str = "gpt-realtime-2.1"
    openai_code_model: str = "gpt-6.2-astra"
    fire_backend_host: str = "127.0.0.1"
    fire_backend_port: int = Field(default=8765, ge=1, le=65535)
    fire_ai_mode: Literal["openai", "mock"] = "openai"
    fire_workspace: Path = Path("workspace")
    fire_backend_token: SecretStr = SecretStr("")
    fire_build_timeout_seconds: int = Field(default=180, ge=5, le=900)
    fire_max_workspace_mb: int = Field(default=256, ge=1)
    fire_max_build_kb: int = Field(default=512, ge=8, le=4096)
    fire_progress_interval_seconds: float = Field(default=10, ge=1, le=30)
    fire_ai_timeout_seconds: int = Field(default=90, ge=2, le=300)
    fire_max_sessions: int = Field(default=8, ge=1, le=32)

    @model_validator(mode="after")
    def lan_requires_token(self):
        if self.fire_backend_host not in {"127.0.0.1", "localhost", "::1"}:
            if len(self.fire_backend_token.get_secret_value()) < 24:
                raise ValueError("LAN binding requires FIRE_BACKEND_TOKEN of at least 24 characters")
        return self

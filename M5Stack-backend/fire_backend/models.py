from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Identifier = str
ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
SERVICES = {"display", "buttons", "rgb", "imu", "mic", "speaker", "wifi", "bluetooth", "sd", "time"}
PROTOTYPE_SERVICES = {"display", "buttons", "rgb", "imu", "time"}


class State(StrEnum):
    idle = "idle"
    listening = "listening"
    processing = "processing"
    clarification_needed = "clarification_needed"
    awaiting_build_confirmation = "awaiting_build_confirmation"
    building = "building"
    testing = "testing"
    ready_to_run = "ready_to_run"
    running = "running"
    failed = "failed"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DialogReply(StrictModel):
    message: str = Field(max_length=4000)
    clarification_needed: bool
    build_summary: str = Field(max_length=4000)


class GeneratedApp(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    main_lua: str = Field(min_length=1, max_length=100_000)
    required_services: list[str] = Field(max_length=10)

    @field_validator("required_services")
    @classmethod
    def valid_services(cls, value):
        if not set(value) <= PROTOTYPE_SERVICES or len(value) != len(set(value)):
            raise ValueError("Only implemented prototype services may be requested")
        return value


class Manifest(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(pattern=r"^0\.1\.[1-9][0-9]*$")
    api_version: Literal["fire-lua-0.1"] = "fire-lua-0.1"
    entry: Literal["main.lua"] = "main.lua"
    required_services: list[str]
    max_memory: int = Field(default=262144, ge=65536, le=262144)
    max_runtime_ms: int = Field(default=10000, ge=1, le=10000)
    permissions: list[str]
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")


class SessionStart(StrictModel):
    device_id: str = Field(default="pc-mock-01", pattern=ID_PATTERN)
    project_id: str | None = Field(default=None, pattern=ID_PATTERN)


class SessionAction(StrictModel):
    session_id: str = Field(pattern=ID_PATTERN)


class BuildConfirm(SessionAction):
    proposal_id: str = Field(pattern=ID_PATTERN)


class RunConfirm(SessionAction):
    package_id: str = Field(pattern=ID_PATTERN)


class DeviceEvent(StrictModel):
    type: Literal["device_event"] = "device_event"
    device_id: str = Field(pattern=ID_PATTERN)
    event: Literal["session_start", "session_stop", "text", "button", "build_confirm", "run_confirm", "ping", "app_failed", "app_stopped"]
    text: str | None = Field(default=None, max_length=4000)
    button: Literal["A", "B", "C"] | None = None
    action: Literal["pressed", "released", "long_pressed"] | None = None
    proposal_id: str | None = Field(default=None, pattern=ID_PATTERN)
    package_id: str | None = Field(default=None, pattern=ID_PATTERN)
    project_id: str | None = Field(default=None, pattern=ID_PATTERN)

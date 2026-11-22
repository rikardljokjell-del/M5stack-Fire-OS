from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    awaiting_install = "awaiting_install"
    installed = "installed"
    starting = "starting"
    stopping = "stopping"
    rollback_pending = "rollback_pending"
    running = "running"
    failed = "failed"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DialogReply(StrictModel):
    message: str = Field(min_length=1, max_length=1000)
    clarification_needed: bool
    build_summary: str = Field(max_length=1000)


class GeneratedApp(StrictModel):
    name: str = Field(min_length=1, max_length=32)
    main_lua: str = Field(min_length=1, max_length=100_000)
    required_services: list[str] = Field(max_length=10)

    @field_validator("name")
    @classmethod
    def short_name(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Appnavnet må være kort, lesbart og uten kontrolltegn")
        return " ".join(value.split())

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
    max_runtime_ms: int = Field(default=10000, ge=0, le=10000)
    permissions: list[str]
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def permissions_match(self):
        GeneratedApp.valid_services(self.required_services)
        if sorted(self.permissions) != sorted("fire." + s for s in self.required_services):
            raise ValueError("Manifest permissions must exactly match required_services")
        return self


class SessionStart(StrictModel):
    device_id: str = Field(default="pc-mock-01", pattern=ID_PATTERN)
    project_id: str | None = Field(default=None, pattern=ID_PATTERN)
    protocol_version: Literal["0.1", "0.2"] = "0.1"
    target: Literal["pc_simulation", "device"] = "pc_simulation"
    boot_id: str | None = Field(default=None, pattern=ID_PATTERN)
    capabilities: "Capabilities | None" = None
    resume_session_id: str | None = Field(default=None, pattern=ID_PATTERN)
    app_mode: Literal["new", "update"] | None = None
    conversation_mode: Literal["chat", "develop"] | None = None
    app_id: str | None = Field(default=None, pattern=ID_PATTERN)
    base_package_id: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode="after")
    def device_contract(self):
        if self.target == "device" and (self.protocol_version != "0.2" or not self.boot_id or self.capabilities is None):
            raise ValueError("Device sessions require protocol 0.2, boot_id and capabilities")
        if self.app_mode == "new" and (self.project_id or self.app_id or self.base_package_id or self.resume_session_id):
            raise ValueError("Explicit new app cannot resume an existing project")
        if self.app_mode == "update" and not (self.project_id or self.app_id):
            raise ValueError("Update requires project_id or app_id")
        return self


class Capabilities(StrictModel):
    api_version: Literal["fire-lua-0.1"] = "fire-lua-0.1"
    services: list[str] = Field(max_length=5)
    max_memory: int = Field(ge=65536, le=262144)
    max_runtime_ms: int = Field(ge=0, le=10000)
    audio_input: bool = False
    audio_output: bool = False
    firmware_version: str = Field(default="unknown", max_length=64)

    @field_validator("services")
    @classmethod
    def supported(cls, value):
        if not set(value) <= PROTOTYPE_SERVICES or len(value) != len(set(value)):
            raise ValueError("Unsupported or duplicate services")
        return value


class SessionAction(StrictModel):
    session_id: str = Field(pattern=ID_PATTERN)
    event_id: str | None = Field(default=None, pattern=ID_PATTERN)


class BuildConfirm(SessionAction):
    proposal_id: str = Field(pattern=ID_PATTERN)


class RunConfirm(SessionAction):
    package_id: str = Field(pattern=ID_PATTERN)


class DeviceApp(StrictModel):
    app_id: str = Field(pattern=ID_PATTERN)
    package_id: str | None = Field(default=None, pattern=ID_PATTERN)
    version: str | None = Field(default=None, max_length=32)
    checksum: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


# Excluding absent extension defaults keeps pre-extension event replay hashes
# compatible with persisted protocol-0.2 events.
APP_EVENT_DEFAULTS = {"app_mode": None, "app_id": None, "base_package_id": None,
                      "offset": 0, "apps": [], "storage_ready": None, "complete": None, "conversation_mode": None}


class DeviceEvent(StrictModel):
    type: Literal["device_event"] = "device_event"
    device_id: str = Field(pattern=ID_PATTERN)
    event: Literal["session_start", "session_stop", "text", "button", "build_confirm", "run_confirm", "ping", "app_failed", "app_stopped", "device_install_result", "app_started", "app_healthy", "rollback_result", "app_stop", "audio_playback_started", "audio_playback_finished", "cancel_turn", "listen_start", "listen_stop", "install_retry", "app_list", "app_versions", "app_select", "app_deleted", "app_inventory", "mode_select", "app_diagnostic"]
    conversation_mode: Literal["chat", "develop"] | None = None
    app_mode: Literal["new", "update"] | None = None
    app_id: str | None = Field(default=None, pattern=ID_PATTERN)
    base_package_id: str | None = Field(default=None, pattern=ID_PATTERN)
    offset: int = Field(default=0, ge=0, le=100000)
    apps: list[DeviceApp] = Field(default_factory=list, max_length=32)
    storage_ready: bool | None = Field(default=None, strict=True)
    complete: bool | None = Field(default=None, strict=True)
    text: str | None = Field(default=None, max_length=4000)
    button: Literal["A", "B", "C"] | None = None
    action: Literal["pressed", "released", "long_pressed"] | None = None
    proposal_id: str | None = Field(default=None, pattern=ID_PATTERN)
    package_id: str | None = Field(default=None, pattern=ID_PATTERN)
    project_id: str | None = Field(default=None, pattern=ID_PATTERN)
    protocol_version: Literal["0.1", "0.2"] = "0.1"
    event_id: str | None = Field(default=None, pattern=ID_PATTERN)
    session_id: str | None = Field(default=None, pattern=ID_PATTERN)
    boot_id: str | None = Field(default=None, pattern=ID_PATTERN)
    target: Literal["pc_simulation", "device"] = "pc_simulation"
    capabilities: Capabilities | None = None
    resume_session_id: str | None = Field(default=None, pattern=ID_PATTERN)
    install_id: str | None = Field(default=None, pattern=ID_PATTERN)
    run_id: str | None = Field(default=None, pattern=ID_PATTERN)
    stop_id: str | None = Field(default=None, pattern=ID_PATTERN)
    rollback_id: str | None = Field(default=None, pattern=ID_PATTERN)
    turn_id: str | None = Field(default=None, pattern=ID_PATTERN)
    audio_id: str | None = Field(default=None, pattern=ID_PATTERN)
    status: Literal["ok", "failed"] | None = None
    archive_sha256: str | None = Field(default=None, pattern=r"^(?:[a-f0-9]{64})?$")
    error_code: str | None = Field(default=None, pattern=ID_PATTERN)
    message: str | None = Field(default=None, max_length=240)
    reason: Literal["completed", "user_exit", "runtime_limit", "requested"] | None = None

    @model_validator(mode="after")
    def versioned_envelope(self):
        if self.event == "mode_select" and not self.conversation_mode:
            raise ValueError("conversation_mode is required")
        if self.protocol_version == "0.2":
            if not self.event_id:
                raise ValueError("Protocol 0.2 requires event_id")
            if self.event != "session_start" and not self.session_id:
                raise ValueError("session_id required after session_start")
            required = {
                "text": ("text",), "button": ("button", "action"), "build_confirm": ("proposal_id",),
                "run_confirm": ("package_id",), "device_install_result": ("install_id", "package_id", "status"),
                "install_retry": ("package_id",),
                "app_started": ("run_id", "package_id"), "app_healthy": ("run_id", "package_id"),
                "app_failed": ("run_id", "package_id", "error_code"), "app_stopped": ("run_id", "package_id"),
                "rollback_result": ("rollback_id", "package_id", "status"),
                "listen_start": ("turn_id",), "listen_stop": ("turn_id",),
                "app_diagnostic": ("app_id", "package_id", "error_code"),
                "audio_playback_started": ("audio_id", "turn_id"), "audio_playback_finished": ("audio_id", "turn_id"),
            }
            if any(not getattr(self, name) for name in required.get(self.event, ())):
                raise ValueError("Missing event-specific fields")
            if self.event == "device_install_result" and self.status == "ok" and not self.archive_sha256:
                raise ValueError("Successful installation requires archive_sha256")
            if self.event == "app_stopped" and not self.stop_id and self.reason not in {"completed", "user_exit", "runtime_limit"}:
                raise ValueError("Natural stop requires reason")
            if self.event == "app_select":
                if not self.app_mode:
                    raise ValueError("app_mode is required")
                if self.app_mode == "new" and (self.project_id or self.app_id or self.base_package_id):
                    raise ValueError("New app cannot select an existing project/package")
                if self.app_mode == "update" and not (self.project_id or self.app_id):
                    raise ValueError("Update requires project_id or app_id")
            if self.event == "app_versions" and not (self.project_id or self.app_id):
                raise ValueError("Versions require project_id or app_id")
            if self.event == "app_deleted" and not self.app_id:
                raise ValueError("app_id is required")
            if self.event == "app_inventory":
                if self.storage_ready is None or self.complete is None or "apps" not in self.model_fields_set:
                    raise ValueError("Inventory requires storage_ready, complete and an explicit apps list")
                if len({app.app_id for app in self.apps}) != len(self.apps):
                    raise ValueError("Inventory contains duplicate app IDs")
        return self


SessionStart.model_rebuild()

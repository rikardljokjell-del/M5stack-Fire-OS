from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer
from .api_registry import ALL_SERVICES,BASE_SERVICES,BASE_API,HARDWARE_API,API_CONTRACT,service_closure

Identifier = str
ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
SERVICES = ALL_SERVICES
PROTOTYPE_SERVICES = BASE_SERVICES  # Legacy callers retain the original profile.


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


class AppTestSequence(StrictModel):
    name: str = Field(pattern=ID_PATTERN)
    buttons: list[Literal["A","B","C"]] = Field(min_length=1,max_length=32)
    interval_ms: int = Field(default=250,ge=100,le=1000,strict=True)


class GeneratedApp(StrictModel):
    name: str = Field(min_length=1, max_length=32)
    main_lua: str = Field(min_length=1, max_length=100_000)
    required_services: list[str] = Field(max_length=24)
    test_sequences: list[AppTestSequence] = Field(default_factory=list,max_length=6)

    @field_validator("name")
    @classmethod
    def short_name(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Appnavnet mÃ¥ vÃ¦re kort, lesbart og uten kontrolltegn")
        return " ".join(value.split())

    @field_validator("required_services")
    @classmethod
    def valid_services(cls, value):
        if not set(value) <= ALL_SERVICES or len(value) != len(set(value)):
            raise ValueError("Unknown or duplicate Lua services")
        return value


class Manifest(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(pattern=r"^0\.1\.[1-9][0-9]*$")
    api_version: Literal["fire-lua-0.1","fire-lua-0.2"] = "fire-lua-0.1"
    api_contract: str | None = Field(default=None,pattern=r"^[a-f0-9]{64}$")
    entry: Literal["main.lua"] = "main.lua"
    required_services: list[str]
    max_memory: int = Field(default=262144, ge=65536, le=262144)
    max_runtime_ms: int = Field(default=10000, ge=0, le=10000)
    permissions: list[str]
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def permissions_match(self):
        GeneratedApp.valid_services(self.required_services)
        if self.api_version==BASE_API and not set(self.required_services)<=BASE_SERVICES:
            raise ValueError("Extended hardware services require fire-lua-0.2")
        if self.api_version==BASE_API and self.api_contract is not None:
            raise ValueError("Legacy manifest has no hardware contract field")
        if self.api_version==HARDWARE_API and self.api_contract!=API_CONTRACT:
            raise ValueError("Hardware manifest contract mismatch")
        if set(service_closure(self.required_services,self.api_version))!=set(self.required_services):
            raise ValueError("Hardware service dependencies invalid")
        if sorted(self.permissions) != sorted("fire." + s for s in self.required_services):
            raise ValueError("Manifest permissions must exactly match required_services")
        return self

    @model_serializer(mode="wrap")
    def serialize_contract(self,handler):
        result=handler(self)
        if self.api_version==BASE_API:result.pop("api_contract",None)
        return result


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


class HardwareResources(StrictModel):
    gpio_read: list[int] = Field(default_factory=list,max_length=40)
    gpio_write: list[int] = Field(default_factory=list,max_length=34)
    adc: list[int] = Field(default_factory=list,max_length=40)
    dac: list[int] = Field(default_factory=list,max_length=2)
    pwm: list[int] = Field(default_factory=list,max_length=34)
    i2c: list[int] = Field(default_factory=list,max_length=2)
    i2c_write_addresses: list[int] = Field(default_factory=list,max_length=126)
    uart: list[int] = Field(default_factory=list,max_length=2)
    spi: list[int] = Field(default_factory=list,max_length=2)

    @field_validator("*",mode="before")
    @classmethod
    def strict_resource_list(cls,value):
        if not isinstance(value,list) or any(type(n) is not int for n in value) or len(value)!=len(set(value)):
            raise ValueError("Resources must be unique integer lists")
        return value

    @model_validator(mode="after")
    def resource_bounds(self):
        protected={6,7,8,9,10,11,16,17} # FIRE flash/PSRAM; never general GPIO.
        gpio=(set(range(20))|{21,22,23,25,26,27,32,33,34,35,36,37,38,39})-protected
        adc={0,2,4,12,13,14,15,25,26,27,32,33,34,35,36,37,38,39}
        for kind,values in self.model_dump().items():
            allowed=({0,1} if kind=="i2c" else {1,2} if kind in {"uart","spi"} else set(range(1,127)) if kind=="i2c_write_addresses"
                     else {25,26} if kind=="dac" else adc if kind=="adc" else gpio&set(range(34)) if kind in {"gpio_write","pwm"} else gpio)
            if not set(values)<=allowed:raise ValueError("Unsupported or reserved hardware resource")
        return self


class Capabilities(StrictModel):
    api_version: Literal["fire-lua-0.1","fire-lua-0.2"] = "fire-lua-0.1"
    services: list[str] = Field(max_length=24)
    api_contract: str | None = Field(default=None,pattern=r"^[a-f0-9]{64}$")
    hardware: HardwareResources | None = None
    max_memory: int = Field(ge=65536, le=262144)
    max_runtime_ms: int = Field(ge=0, le=10000)
    audio_input: bool = False
    audio_output: bool = False
    firmware_version: str = Field(default="unknown", max_length=64)
    firmware_storage: bool = Field(default=False,strict=True)
    firmware_max_bytes: int = Field(default=4194304,ge=1024,le=4194304,strict=True)

    @field_validator("services")
    @classmethod
    def supported(cls, value):
        if not set(value) <= ALL_SERVICES or len(value) != len(set(value)):
            raise ValueError("Unsupported or duplicate services")
        return value

    @model_validator(mode="after")
    def negotiated_api(self):
        if self.api_version==BASE_API and not set(self.services)<=BASE_SERVICES:
            raise ValueError("Hardware services require fire-lua-0.2")
        if self.api_version==HARDWARE_API:
            if self.api_contract!=API_CONTRACT:raise ValueError("Hardware API contract mismatch")
            from .api_registry import methods_for
            dependencies={dep for service in self.services for method in methods_for(HARDWARE_API)[service].values() for dep in method.get("requires",[])}
            if not dependencies<=set(self.services):raise ValueError("Hardware service dependencies must be announced")
            if set(self.services)&{"gpio","adc","dac","pwm","i2c","uart","spi"} and self.hardware is None:
                raise ValueError("Hardware profile must announce its resources")
        return self


class SessionAction(StrictModel):
    session_id: str = Field(pattern=ID_PATTERN)
    event_id: str | None = Field(default=None, pattern=ID_PATTERN)


class BuildConfirm(SessionAction):
    proposal_id: str = Field(pattern=ID_PATTERN)
    repair_id: str | None = Field(default=None,pattern=ID_PATTERN)


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
                      "offset": 0, "apps": [], "storage_ready": None, "complete": None, "conversation_mode": None, "diagnostics": None,
                      "firmware_id":None,"transfer_id":None,"sha256":None,"delete_id":None,"delete_scope":None,
                      "repair_id":None,"app_version":None,"build_id":None,"notification_action":None}
CAPABILITY_DEFAULTS={"firmware_storage":False,"firmware_max_bytes":4194304,"api_contract":None,"hardware":None}


class DeviceDiagnostics(StrictModel):
    phase: Literal["load","init","update","on_button","install","start","stop","audio_download","audio_playback"] | None = None
    elapsed_ms: int | None = Field(default=None,ge=0,le=4294967295,strict=True)
    callback_us: int | None = Field(default=None,ge=0,le=60000000,strict=True)
    free_heap: int | None = Field(default=None,ge=0,le=16777216,strict=True)
    min_free_heap: int | None = Field(default=None,ge=0,le=16777216,strict=True)
    lua_bytes: int | None = Field(default=None,ge=0,le=16777216,strict=True)
    source_bytes: int | None = Field(default=None,ge=0,le=100000,strict=True)
    frames: int | None = Field(default=None,ge=0,le=4294967295,strict=True)


class DeviceEvent(StrictModel):
    type: Literal["device_event"] = "device_event"
    device_id: str = Field(pattern=ID_PATTERN)
    event: Literal["session_start", "session_stop", "text", "button", "build_confirm", "run_confirm", "ping", "app_failed", "app_stopped", "device_install_result", "app_started", "app_healthy", "rollback_result", "app_stop", "audio_playback_started", "audio_playback_finished", "cancel_turn", "listen_start", "listen_stop", "install_retry", "app_list", "app_versions", "app_select", "app_deleted", "app_inventory", "mode_select", "app_diagnostic", "audio_playback_failed", "firmware_store_result", "app_download", "app_backend_delete_prepare", "app_backend_delete_confirm", "app_repair_prepare", "app_repair_status", "build_background", "build_jobs", "build_notice_ack", "build_resume", "build_cancel"]
    build_id: str | None = Field(default=None,pattern=ID_PATTERN)
    notification_action: Literal['open','dismiss'] | None = None
    repair_id: str | None = Field(default=None,pattern=ID_PATTERN)
    app_version: str | None = Field(default=None,max_length=32)
    conversation_mode: Literal["chat", "develop"] | None = None
    diagnostics: DeviceDiagnostics | None = None
    firmware_id: str | None = Field(default=None,pattern=ID_PATTERN)
    transfer_id: str | None = Field(default=None,pattern=ID_PATTERN)
    sha256: str | None = Field(default=None,pattern=r"^[a-f0-9]{64}$")
    delete_id: str | None = Field(default=None,pattern=ID_PATTERN)
    delete_scope: Literal["version","all"] | None = None
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
                "app_repair_prepare": ("app_id",),
                "build_background": ("build_id",),"build_resume": ("build_id",),"build_cancel": ("build_id",),
                "build_notice_ack": ("build_id","notification_action"),
                "audio_playback_started": ("audio_id", "turn_id"), "audio_playback_finished": ("audio_id", "turn_id"),
                "audio_playback_failed": ("audio_id", "turn_id", "error_code"),
                "firmware_store_result": ("firmware_id","transfer_id","status"),
                "app_download": ("package_id",),
                "app_backend_delete_prepare": ("delete_scope",),
                "app_backend_delete_confirm": ("delete_id",),
            }
            if any(not getattr(self, name) for name in required.get(self.event, ())):
                raise ValueError("Missing event-specific fields")
            if self.event=="app_repair_status" and not (self.repair_id or self.app_id):
                raise ValueError("Repair status requires repair_id or app_id")
            if self.event == "device_install_result" and self.status == "ok" and not self.archive_sha256:
                raise ValueError("Successful installation requires archive_sha256")
            if self.event == "firmware_store_result" and self.status == "ok" and not self.sha256:
                raise ValueError("Stored firmware requires sha256")
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
            if self.event=="app_backend_delete_prepare":
                if not (self.project_id or self.app_id):raise ValueError("Deletion requires project_id or app_id")
                if self.delete_scope=="version" and not self.package_id:raise ValueError("Version deletion requires package_id")
                if self.delete_scope=="all" and self.package_id:raise ValueError("All-version deletion cannot specify package_id")
            if self.event == "app_deleted" and not self.app_id:
                raise ValueError("app_id is required")
            if self.event == "app_inventory":
                if self.storage_ready is None or self.complete is None or "apps" not in self.model_fields_set:
                    raise ValueError("Inventory requires storage_ready, complete and an explicit apps list")
                if len({app.app_id for app in self.apps}) != len(self.apps):
                    raise ValueError("Inventory contains duplicate app IDs")
        return self


SessionStart.model_rebuild()

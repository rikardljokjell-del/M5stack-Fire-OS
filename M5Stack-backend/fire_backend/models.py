from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer
from .api_registry import ALL_SERVICES,BASE_SERVICES,BASE_API,HARDWARE_API,API_CONTRACT,service_closure
from .app_sdk import SDK_VERSION,SDK_CONTRACT
from .runtime_contract import VERSION as AI_VERSION,CONTRACT as AI_CONTRACT,LIMITS as AI_LIMITS
from .data_contract import VERSION as DATA_VERSION,CONTRACT as DATA_CONTRACT,LIMITS as DATA_LIMITS
from .evolution_contract import VERSION as EVOLUTION_VERSION,CONTRACT as EVOLUTION_CONTRACT,LIMITS as EVOLUTION_LIMITS
from .app_icons import ALLOWED_ICONS

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
    display_text: str = Field(default='',max_length=28)

    @field_validator('display_text')
    @classmethod
    def short_display(cls,value):
        if not value:return value
        from .status_text import checked
        try:return checked(value)
        except ValueError:return 'AI-svaret er klart'


class AppTestSequence(StrictModel):
    name: str = Field(pattern=ID_PATTERN)
    buttons: list[Literal["A","B","C"]] = Field(min_length=1,max_length=32)
    interval_ms: int = Field(default=250,ge=100,le=1000,strict=True)


class GeneratedApp(StrictModel):
    name: str = Field(min_length=1, max_length=32)
    icon: str | None = Field(default=None, description='Optional curated OS app icon; null selects an appropriate icon automatically.',
        json_schema_extra={'anyOf':[{'type':'string','enum':list(ALLOWED_ICONS)},{'type':'null'}]})
    main_lua: str = Field(min_length=1, max_length=100_000,
        description="Complete executable Lua source only. No prose, Markdown, progress text or requests for confirmation.")
    required_services: list[str] = Field(max_length=24,
        description="Bare Lua service names, e.g. display, buttons, rgb. Never fire.display or permission names.",
        json_schema_extra={"items":{"type":"string","enum":sorted(ALL_SERVICES)}})
    test_sequences: list[AppTestSequence] = Field(default_factory=list,max_length=6)

    @field_validator('icon')
    @classmethod
    def supported_icon(cls,value):
        from .app_icons import valid_icon
        if value is not None and not valid_icon(value):raise ValueError('Unknown OS app icon')
        return value

    @field_validator("name")
    @classmethod
    def short_name(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Appnavnet må være kort, lesbart og uten kontrolltegn")
        return " ".join(value.split())

    @field_validator("required_services",mode="before")
    @classmethod
    def candidate_service_names(cls,value):
        # AI candidates may confuse a Lua namespace with a service ID. This
        # lossless spelling fix grants no new service and never applies to
        # manifests or device capabilities, which retain strict validation.
        if isinstance(value,list):
            return [item[5:] if isinstance(item,str) and item.startswith('fire.') and item[5:] in ALL_SERVICES
                    else item for item in value]
        return value

    @field_validator("required_services")
    @classmethod
    def valid_services(cls, value):
        if not set(value) <= ALL_SERVICES or len(value) != len(set(value)):
            raise ValueError("Unknown or duplicate Lua services")
        return value


class RuntimeAICapability(StrictModel):
    version: Literal['fire-runtime-ai-1.0']
    contract: str = Field(pattern=r'^[a-f0-9]{64}$',json_schema_extra={'const':AI_CONTRACT})

    @field_validator('contract')
    @classmethod
    def exact_contract(cls,value):
        if value!=AI_CONTRACT:raise ValueError('Runtime AI contract mismatch')
        return value


class DataEngineExtension(StrictModel):
    version: Literal['fire-data-engine-1.0']
    contract: str = Field(pattern=r'^[a-f0-9]{64}$', json_schema_extra={'const': DATA_CONTRACT})

    @field_validator('contract')
    @classmethod
    def exact_contract(cls, value):
        if value != DATA_CONTRACT:
            raise ValueError('Data Engine contract mismatch')
        return value


class DataCaptureLimit(StrictModel):
    duration_ms_max: int = Field(ge=1, le=2147483647, strict=True)
    sample_rate_hz_min: int | None = Field(default=None, ge=1, le=1000000, strict=True)
    sample_rate_hz_max: int | None = Field(default=None, ge=1, le=1000000, strict=True)
    sample_rates_hz: list[int] | None = Field(default=None, max_length=16)
    max_records: int | None = Field(default=None, ge=1, le=DATA_LIMITS['dataset_bytes'], strict=True)

    @model_validator(mode='after')
    def rates(self):
        if self.sample_rate_hz_min and self.sample_rate_hz_max and self.sample_rate_hz_min > self.sample_rate_hz_max:
            raise ValueError('Invalid capture sample rate bounds')
        if self.sample_rates_hz is not None and (not self.sample_rates_hz or
                len(set(self.sample_rates_hz)) != len(self.sample_rates_hz) or
                any(type(v) is not int or not 1 <= v <= 1000000 for v in self.sample_rates_hz)):
            raise ValueError('Invalid capture sample rates')
        return self


class DataEngineCapability(DataEngineExtension):
    capture_sources: list[str] = Field(default_factory=list, max_length=8)
    capture_limits: dict[str, DataCaptureLimit] = Field(default_factory=dict, max_length=8)

    @field_validator('capture_sources')
    @classmethod
    def bounded_sources(cls, values):
        if len(values) != len(set(values)) or any(not v or len(v.encode('utf-8')) > 32 for v in values):
            raise ValueError('Invalid Data Engine capture sources')
        return values

    @model_validator(mode='after')
    def limits_match(self):
        if set(self.capture_limits) != set(self.capture_sources):
            raise ValueError('Capture limits must exactly match announced sources')
        return self


class DataComponent(StrictModel):
    size: int = Field(ge=0, le=DATA_LIMITS['dataset_bytes'], strict=True)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class DataDescriptor(StrictModel):
    dataset_id: str = Field(pattern=ID_PATTERN, max_length=DATA_LIMITS['identifier_bytes'])
    kind: Literal['csv', 'text', 'binary', 'audio']
    label: str = Field(max_length=DATA_LIMITS['label_bytes'])
    size: int = Field(ge=0, le=DATA_LIMITS['dataset_bytes'], strict=True)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    metadata_json: str = Field(default='{}', max_length=DATA_LIMITS['metadata_bytes'])
    origin_package_id: str = Field(pattern=ID_PATTERN)
    origin_source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    origin_run_id: str = Field(pattern=ID_PATTERN)
    created_ms: int = Field(ge=0, le=2**53-1, strict=True)
    components: dict[Literal['data','index','events'], DataComponent]
    acquisition: Literal['app_recorded','native_imu_fifo','native_imu_poll','native_mic','native_ble','native_uart','native_adc'] = 'app_recorded'

    @model_validator(mode='after')
    def utf8_bounds(self):
        if len(self.label.encode('utf-8')) > DATA_LIMITS['label_bytes'] or len(self.metadata_json.encode('utf-8')) > DATA_LIMITS['metadata_bytes']:
            raise ValueError('Data descriptor exceeds UTF8 limit')
        if set(self.components) != {'data','index','events'} or sum(c.size for c in self.components.values()) > DATA_LIMITS['dataset_bytes']:
            raise ValueError('Invalid dataset components')
        if self.components['data'].size != self.size or self.components['data'].sha256 != self.sha256:
            raise ValueError('Data component mismatch')
        return self


class Manifest(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = Field(default=None,json_schema_extra={'anyOf':[{'type':'string','enum':list(ALLOWED_ICONS)},{'type':'null'}]})
    version: str = Field(pattern=r"^0\.1\.[1-9][0-9]*$")
    api_version: Literal["fire-lua-0.1","fire-lua-0.2","fire-app-sdk-1.0"] = "fire-lua-0.1"
    api_contract: str | None = Field(default=None,pattern=r"^[a-f0-9]{64}$")
    entry: Literal["main.lua"] = "main.lua"
    required_services: list[str]
    max_memory: int = Field(default=262144, ge=65536, le=262144)
    max_runtime_ms: int = Field(default=10000, ge=0, le=10000)
    permissions: list[str]
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_ai: RuntimeAICapability | None = None
    data_engine: DataEngineExtension | None = None

    @field_validator('icon')
    @classmethod
    def supported_icon(cls,value):return GeneratedApp.supported_icon(value)

    @model_validator(mode="after")
    def permissions_match(self):
        if ('data' in self.required_services) != (self.data_engine is not None):
            raise ValueError('Data Engine extension must exactly match data permission')
        if self.data_engine and self.api_version != SDK_VERSION:
            raise ValueError('Data Engine requires SDK')
        if ('ai' in self.required_services)!=(self.runtime_ai is not None):raise ValueError('Runtime AI extension must exactly match ai permission')
        if self.runtime_ai and self.api_version!=SDK_VERSION:raise ValueError('Runtime AI requires SDK')
        GeneratedApp.valid_services(self.required_services)
        if self.api_version==BASE_API and not set(self.required_services)<=BASE_SERVICES:
            raise ValueError("Extended hardware services require fire-lua-0.2")
        if self.api_version==BASE_API and self.api_contract is not None:
            raise ValueError("Legacy manifest has no hardware contract field")
        if self.api_version==HARDWARE_API and self.api_contract!=API_CONTRACT:
            raise ValueError("Hardware manifest contract mismatch")
        if self.api_version==SDK_VERSION and self.api_contract!=SDK_CONTRACT:
            raise ValueError('SDK manifest contract mismatch')
        if set(service_closure(self.required_services,self.api_version))!=set(self.required_services):
            raise ValueError("Hardware service dependencies invalid")
        if sorted(self.permissions) != sorted("fire." + s for s in self.required_services):
            raise ValueError("Manifest permissions must exactly match required_services")
        return self

    @model_serializer(mode="wrap")
    def serialize_contract(self,handler):
        result=handler(self)
        if self.api_version==BASE_API:result.pop("api_contract",None)
        if self.runtime_ai is None:result.pop('runtime_ai',None)
        if self.data_engine is None:result.pop('data_engine',None)
        if self.icon is None:result.pop('icon',None)
        return result


class SessionStart(StrictModel):
    development_context_id: str | None = Field(default=None, pattern=ID_PATTERN)
    runtime_ai_mode: Literal['auto','off'] | None = None
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


class AppSdkCapability(StrictModel):
    version: Literal['fire-app-sdk-1.0']
    contract: str = Field(pattern=r'^[a-f0-9]{64}$',json_schema_extra={'const':SDK_CONTRACT})

    @field_validator('contract')
    @classmethod
    def same_contract(cls,value):
        if value!=SDK_CONTRACT:raise ValueError('SDK capability contract mismatch')
        return value


class EvolutionCapability(StrictModel):
    version: Literal['fire-evolution-1.0']
    contract: str = Field(json_schema_extra={'const':EVOLUTION_CONTRACT})

    @field_validator('contract')
    @classmethod
    def exact_contract(cls,value):
        if value!=EVOLUTION_CONTRACT:raise ValueError('Evolution contract mismatch')
        return value


class Capabilities(StrictModel):
    evolution: EvolutionCapability | None = None
    service_methods: dict[str,list[str]] | None = Field(default=None,max_length=32)
    service_modes: dict[str,list[str]] | None = Field(default=None,max_length=32)
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
    app_sdk: AppSdkCapability | None = None
    runtime_ai: RuntimeAICapability | None = None
    data_engine: DataEngineCapability | None = None

    @field_validator("services")
    @classmethod
    def supported(cls, value):
        if not set(value) <= ALL_SERVICES or len(value) != len(set(value)):
            raise ValueError("Unsupported or duplicate services")
        return value

    @model_validator(mode="after")
    def negotiated_api(self):
        from .api_registry import methods_for
        known=methods_for(SDK_VERSION if self.app_sdk else self.api_version,self.services)
        for service,names in (self.service_methods or {}).items():
            if (service not in self.services or len(names)>64 or len(names)!=len(set(names)) or not set(names)<=set(known.get(service,{}))):
                raise ValueError('Unknown announced service methods')
        for key,values in (self.service_modes or {}).items():
            if key.count('.')!=1 or not values or len(values)>16 or len(values)!=len(set(values)):
                raise ValueError('Invalid service modes')
            service,method=key.split('.')
            spec=known.get(service,{}).get(method)
            if not spec or (self.service_methods or {}).get(service) is not None and method not in self.service_methods[service]:
                raise ValueError('Mode requires an announced method')
            options=next((a['values'] for a in spec.get('args',[]) if a.get('type')=='enum'),[])
            if not set(values)<=set(options):raise ValueError('Unsupported service mode')
        if (('data' in self.services) != (self.data_engine is not None) or
                self.data_engine and (not self.app_sdk or not {'jobs','sd'} <= set(self.services))):
            raise ValueError('Data Engine capability requires SDK and data/jobs/sd services')
        if ('ai' in self.services)!=(self.runtime_ai is not None) or self.runtime_ai and (not self.app_sdk or 'jobs' not in self.services):
            raise ValueError('Runtime AI capability requires SDK and ai/jobs services')
        if self.api_version==BASE_API and not set(self.services)<=BASE_SERVICES:
            raise ValueError("Hardware services require fire-lua-0.2")
        if self.app_sdk and (self.api_version!=HARDWARE_API or 'display' not in self.services):
            raise ValueError('SDK capability requires hardware API and display')
        if self.api_version==HARDWARE_API:
            if self.api_contract!=API_CONTRACT:raise ValueError("Hardware API contract mismatch")
            from .api_registry import methods_for
            dependencies={dep for service in self.services for method in methods_for(SDK_VERSION if self.app_sdk else HARDWARE_API,self.services)[service].values() for dep in method.get("requires",[])}
            if not dependencies<=set(self.services):raise ValueError("Hardware service dependencies must be announced")
            if set(self.services)&{"gpio","adc","dac","pwm","i2c","uart","spi"} and self.hardware is None:
                raise ValueError("Hardware profile must announce its resources")
        return self

    @model_serializer(mode='wrap')
    def serialize_extensions(self,handler):
        result=handler(self)
        if self.evolution is None:result.pop('evolution',None)
        if self.app_sdk is None:result.pop('app_sdk',None)
        if self.runtime_ai is None:result.pop('runtime_ai',None)
        if self.data_engine is None:result.pop('data_engine',None)
        if self.service_methods is None:result.pop('service_methods',None)
        if self.service_modes is None:result.pop('service_modes',None)
        return result


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
                      "repair_id":None,"app_version":None,"build_id":None,"notification_action":None,"request_id":None,"source_sha256":None,"instructions":None,"data_json":None,"schema_json":None,"timeout_ms":None,'runtime_ai_mode':None,"operation":None,"dataset_id":None,"options_json":None,"datasets":[],"mode":None,"instruction":None,"dataset_ids":[],"context_id":None,"development_context_id":None,"observation_action":None}
APP_EVENT_DEFAULTS.update({k:None for k in ('expected_revision','evolution_json','telemetry_json','evolution_action','evolution_job_id','evolution_mandate_id','view','settings_json','role','job_action')})
APP_EVENT_DEFAULTS['serial_audio'] = False
CAPABILITY_DEFAULTS={"firmware_storage":False,"firmware_max_bytes":4194304,"api_contract":None,"hardware":None,'app_sdk':None,'runtime_ai':None,'data_engine':None,'service_methods':None,'service_modes':None,'evolution':None}


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
    serial_audio: bool = Field(default=False, strict=True)
    expected_revision: int | None = Field(default=None,ge=0,strict=True)
    evolution_json: str | None = Field(default=None,max_length=EVOLUTION_LIMITS['control_json_bytes'])
    telemetry_json: str | None = Field(default=None,max_length=EVOLUTION_LIMITS['telemetry_json_bytes'])
    settings_json: str | None = Field(default=None,max_length=EVOLUTION_LIMITS['control_json_bytes'])
    role: Literal['dialog_model','code_model','review_model','transcribe_model','speech_model','runtime_model'] | None = None
    evolution_action: Literal['pause','resume','stop','revoke'] | None = None
    evolution_job_id: str | None = Field(default=None,pattern=ID_PATTERN)
    evolution_mandate_id: str | None = Field(default=None,pattern=ID_PATTERN)
    view: Literal['summary','settings','findings','history','compare','models','usage','limits'] | None = None
    observation_action: Literal['confirm','reject'] | None = None
    operation: Literal['process','develop','sync','configure','generate','repair','optimize','expand','evolve','strategy_app','strategy_owner'] | None = None
    dataset_id: str | None = Field(default=None, pattern=ID_PATTERN, max_length=DATA_LIMITS['identifier_bytes'])
    options_json: str | None = Field(default=None, max_length=DATA_LIMITS['options_bytes'])
    datasets: list[DataDescriptor] = Field(default_factory=list, max_length=DATA_LIMITS['context_dataset_refs'])
    mode: Literal['update','fork','feedback'] | None = None
    instruction: str | None = Field(default=None, max_length=DATA_LIMITS['instruction_bytes'])
    dataset_ids: list[str] = Field(default_factory=list, max_length=DATA_LIMITS['context_dataset_refs'])
    context_id: str | None = Field(default=None, pattern=ID_PATTERN)
    development_context_id: str | None = Field(default=None, pattern=ID_PATTERN)
    runtime_ai_mode: Literal['auto','off'] | None = None
    type: Literal["device_event"] = "device_event"
    device_id: str = Field(pattern=ID_PATTERN)
    event: Literal["session_start", "session_stop", "text", "button", "build_confirm", "run_confirm", "ping", "app_failed", "app_stopped", "device_install_result", "app_started", "app_healthy", "rollback_result", "app_stop", "audio_playback_started", "audio_playback_finished", "cancel_turn", "listen_start", "listen_stop", "audio_input_commit", "install_retry", "app_list", "app_versions", "app_select", "app_deleted", "app_inventory", "mode_select", "app_diagnostic", "audio_playback_failed", "firmware_store_result", "app_download", "app_backend_delete_prepare", "app_backend_delete_confirm", "app_repair_prepare", "app_repair_status", "app_repair_cancel", "build_background", "build_jobs", "build_notice_ack", "build_resume", "build_cancel", "job_control", "runtime_ai_request", "runtime_ai_cancel", "data_request", "data_cancel", "app_develop_request", "app_observation_confirm", "evolution_status", "evolution_prepare", "evolution_confirm", "evolution_control", "evolution_telemetry", "backend_settings_status", "backend_settings_prepare", "backend_settings_confirm"]
    request_id: str | None = Field(default=None,pattern=ID_PATTERN)
    source_sha256: str | None = Field(default=None,pattern=r"^[a-f0-9]{64}$")
    instructions: str | None = Field(default=None,max_length=AI_LIMITS['instructions_bytes'])
    data_json: str | None = Field(default=None,max_length=AI_LIMITS['data_bytes'])
    schema_json: str | None = Field(default=None,max_length=AI_LIMITS['schema_bytes'])
    timeout_ms: int | None = Field(default=None,ge=AI_LIMITS['timeout_min_ms'],le=AI_LIMITS['timeout_max_ms'],strict=True)
    build_id: str | None = Field(default=None,pattern=ID_PATTERN)
    notification_action: Literal['open','dismiss'] | None = None
    job_action: Literal['resume','pause','cancel','background','context','delete'] | None = None
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
        if self.event == 'audio_input_commit' and self.protocol_version != '0.2':
            raise ValueError('Audio commit requires protocol 0.2')
        if self.serial_audio and (self.event != 'listen_stop' or self.protocol_version != '0.2'):
            raise ValueError('Serial audio requires protocol 0.2 listen_stop')
        if self.event=='job_control':
            if self.protocol_version!='0.2' or not self.job_action or bool(self.build_id)==bool(self.repair_id):
                raise ValueError('Job control requires exactly one owned build or repair')
            if self.text is not None and (self.job_action!='context' or not self.text.strip() or len(self.text.encode('utf-8'))>2000):
                raise ValueError('Only context accepts 1-2000 UTF8 bytes')
        if self.event.startswith('backend_settings_'):
            required={'backend_settings_status':('request_id',),'backend_settings_prepare':('request_id','expected_revision','settings_json'),
                'backend_settings_confirm':('request_id','proposal_id','expected_revision')}[self.event]
            if any(getattr(self,k) is None for k in required):raise ValueError('Missing settings fields')
            if self.settings_json is not None and len(self.settings_json.encode('utf-8'))>EVOLUTION_LIMITS['control_json_bytes']:raise ValueError('Settings UTF8 bound exceeded')
        if self.event.startswith('evolution_'):
            fields={'evolution_status':('request_id','app_id'),
                'evolution_prepare':('request_id','app_id','operation','expected_revision','evolution_json'),
                'evolution_confirm':('request_id','app_id','proposal_id','expected_revision'),
                'evolution_control':('request_id','app_id','evolution_action','expected_revision'),
                'evolution_telemetry':('request_id','app_id','package_id','source_sha256','telemetry_json')}[self.event]
            if any(getattr(self,k) is None for k in fields):raise ValueError('Missing Evolution fields')
            if self.event=='evolution_prepare' and self.operation not in {'configure','generate','repair','optimize','expand','evolve','strategy_app','strategy_owner'}:raise ValueError('Invalid Evolution operation')
            for key,limit in (('evolution_json',EVOLUTION_LIMITS['control_json_bytes']),('telemetry_json',EVOLUTION_LIMITS['telemetry_json_bytes'])):
                value=getattr(self,key)
                if value is not None and len(value.encode('utf-8'))>limit:raise ValueError('Evolution UTF8 limit exceeded')
        if self.event=='data_request' and self.operation not in {'process','develop','sync'}:raise ValueError('Invalid data operation')
        if self.event == "mode_select" and not (self.conversation_mode or self.runtime_ai_mode):
            raise ValueError("conversation_mode or runtime_ai_mode is required")
        if self.protocol_version == "0.2":
            if not self.event_id:
                raise ValueError("Protocol 0.2 requires event_id")
            if self.event != "session_start" and not self.session_id:
                raise ValueError("session_id required after session_start")
            required = {
                "runtime_ai_request": ("request_id","app_id","package_id","source_sha256","run_id","instructions","data_json","schema_json","timeout_ms"),
                "runtime_ai_cancel": ("request_id","app_id","package_id","source_sha256","run_id"),
                "data_request": ("request_id","app_id","package_id","source_sha256","run_id","operation"),
                "data_cancel": ("request_id","app_id","package_id","source_sha256","run_id"),
                "app_develop_request": ("request_id","app_id","package_id","source_sha256","run_id","mode"),
                "app_observation_confirm": ("context_id","observation_action"),
                "text": ("text",), "button": ("button", "action"), "build_confirm": ("proposal_id",),
                "run_confirm": ("package_id",), "device_install_result": ("install_id", "package_id", "status"),
                "install_retry": ("package_id",),
                "app_started": ("run_id", "package_id"), "app_healthy": ("run_id", "package_id"),
                "app_failed": ("run_id", "package_id", "error_code"), "app_stopped": ("run_id", "package_id"),
                "rollback_result": ("rollback_id", "package_id", "status"),
                "listen_start": ("turn_id",), "listen_stop": ("turn_id",),
                "audio_input_commit": ("turn_id", "sha256"),
                "app_diagnostic": ("app_id", "package_id", "error_code"),
                "app_repair_prepare": ("app_id",),
                "app_repair_cancel": ("repair_id",),
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

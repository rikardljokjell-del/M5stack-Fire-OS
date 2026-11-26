"""Per-user desktop configuration. Secrets live only in Windows Credential Manager."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import Settings
from .model_catalog import ECONOMY_MODELS


def data_directory():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FIRE Backend"


COST_PROFILE_VERSION = 3


class DesktopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    credential_namespace: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    mode: str = Field(default="mock", pattern=r"^(mock|openai)$")
    allow_lan: bool = True
    public_enabled: bool = False
    web_origin: str = ""
    device_host: str = ""
    access_issuer: str = ""
    access_audience: str = ""
    transport: Literal["direct", "reverse_tcp"] = "direct"
    reverse_host: str = ""
    reverse_port: int = Field(default=8766, ge=1024, le=65535)
    reverse_device_id: str = ""
    port: int = Field(default=8765, ge=1024, le=65535)
    workspace: str = Field(default_factory=lambda: str(data_directory() / "workspace"))
    device_ids: list[str] = Field(default_factory=lambda: ["m5stack-fire-01"], min_length=1, max_length=16)
    audio_enabled: bool = True
    speech_enabled: bool = True
    runtime_ai_enabled: bool = True
    runtime_ai_developer_mode: Literal['auto','off'] = 'auto'
    runtime_model: str = 'gpt-6-luna'
    runtime_ai_limits_enabled: bool = False
    runtime_ai_request_budget_usd: float = Field(default=0,ge=0,allow_inf_nan=False)
    runtime_ai_daily_budget_usd: float = Field(default=0,ge=0,allow_inf_nan=False)
    runtime_ai_daily_calls: int = Field(default=0,ge=0)
    runtime_ai_output_tokens: int = Field(default=1024,ge=16,le=4096)
    cost_profile_version: int = Field(default=COST_PROFILE_VERSION, ge=0)
    cost_limits_enabled: bool = False
    evolution_cost_limits_enabled: bool = True
    output_limits_enabled: bool = False
    dialog_model: str = ECONOMY_MODELS["dialog_model"]
    code_model: str = ECONOMY_MODELS["code_model"]
    review_model: str = ECONOMY_MODELS["review_model"]
    transcribe_model: str = ECONOMY_MODELS["transcribe_model"]
    speech_model: str = "gpt-realtime-2.1-mini"
    speech_voice: str = "marin"
    max_workspace_mb: int = Field(default=512, ge=16, le=16384)
    daily_budget_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    build_budget_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    request_budget_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    max_corrections: int = Field(default=0, ge=0)

    @field_validator("reverse_host")
    @classmethod
    def reverse_address(cls, value):
        from .reverse_tcp import fire_address
        return fire_address(value)

    @model_validator(mode="after")
    def reverse_target(self):
        if self.public_enabled:
            Settings(_env_file=None, fire_public_enabled=True, fire_web_origin=self.web_origin,
                     fire_device_host=self.device_host, fire_access_issuer=self.access_issuer,
                     fire_access_audience=self.access_audience, fire_backend_token="validation-only-credential-123456")
        if self.transport == "reverse_tcp" and not self.reverse_host:
            raise ValueError("Oppgi FIREs egen Wi-Fi-adresse for omvendt TCP.")
        if self.reverse_device_id and self.reverse_device_id not in self.device_ids:
            raise ValueError("Omvendt TCP krever en lagret enhets-ID.")
        return self

    @field_validator("device_ids")
    @classmethod
    def valid_ids(cls, values):
        import re
        if len(set(values)) != len(values) or any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value) for value in values):
            raise ValueError("Bruk unik enhets-ID med små bokstaver, tall og bindestrek.")
        return values

    @field_validator("dialog_model", "code_model", "review_model", "transcribe_model", "speech_model", "speech_voice", "runtime_model")
    @classmethod
    def valid_model(cls, value):
        if not value.strip() or len(value) > 120 or any(c.isspace() for c in value):
            raise ValueError("Modellnavn kan ikke være tomt eller inneholde mellomrom.")
        return value

    @field_validator("workspace")
    @classmethod
    def absolute_workspace(cls, value):
        if not Path(value).is_absolute():
            raise ValueError("Velg en absolutt sti for datamappen.")
        return str(Path(value).resolve())


class Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


class WindowsVault:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Windows legitimasjonsbehandling krever Windows.")
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL

    def get(self, target):
        pointer = ctypes.POINTER(Credential)()
        if not self.api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return ""
            raise OSError("Kan ikke lese Windows legitimasjonsbehandling.")
        try:
            value = pointer.contents
            return ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode("utf-16-le")
        finally:
            self.api.CredFree(pointer)

    def put(self, target, value):
        if not value:
            if not self.api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
                raise OSError("Kan ikke fjerne nøkkelen fra Windows.")
            return
        encoded = value.encode("utf-16-le")
        if len(encoded) > 2560:
            raise ValueError("Nøkkelen er for lang for Windows legitimasjonsbehandling.")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = Credential(Type=1, TargetName=target, Comment="FIRE Backend – lokal konfigurasjon",
                                CredentialBlobSize=len(encoded), CredentialBlob=blob, Persist=2, UserName="FIRE Backend")
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise OSError("Kan ikke lagre nøkkelen i Windows legitimasjonsbehandling.")


class DesktopStore:
    def __init__(self, root=None, vault=None):
        self.root = Path(root) if root else data_directory()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "settings.json"
        self.vault = vault if vault is not None else WindowsVault()
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            raw.setdefault("cost_profile_version", 0)
            self.config = DesktopConfig.model_validate(raw)
        else:
            self.config = DesktopConfig(workspace=str((self.root / "workspace").resolve()))
            self.save(self.config)

    def migrate_cost_profile(self):
        """Apply the user's requested economy migration once, preserving custom settings."""
        if self.config.cost_profile_version >= COST_PROFILE_VERSION:
            return False
        legacy = {"code_model": {"gpt-6.2-astra", "gpt-6.2-sol"},
                  "review_model": {"gpt-6.2-astra", "gpt-6.2-sol"}}
        if self.config.cost_profile_version>=2:legacy={}
        if self.config.cost_profile_version < 1:
            legacy["dialog_model"] = {"gpt-realtime-2.1"}
        changes = {name: ECONOMY_MODELS[name] for name, old in legacy.items() if getattr(self.config, name) in old}
        changes.update(cost_limits_enabled=False,output_limits_enabled=False,max_corrections=0,
                       daily_budget_usd=0,build_budget_usd=0,request_budget_usd=0)
        changes["cost_profile_version"] = COST_PROFILE_VERSION
        self.save(self.config.model_copy(update=changes))
        return True

    def target(self, name):
        return f"FIREBackend/{self.config.credential_namespace}/{name}"

    def secret(self, name):
        return self.vault.get(self.target(name))

    def save(self, config, api_key=None, device_tokens=None):
        config = DesktopConfig.model_validate(config.model_dump())
        if config.credential_namespace != self.config.credential_namespace:
            raise ValueError("Konfigurasjonsprofilen kan ikke byttes.")
        if api_key is not None and (api_key and (len(api_key) < 8 or any(c.isspace() for c in api_key))):
            raise ValueError("API-nøkkelen er ugyldig. Lim inn hele nøkkelen uten mellomrom.")
        tokens = {device_id: (device_tokens or {}).get(device_id) or self.secret("device/" + device_id) or secrets.token_urlsafe(32)
                  for device_id in config.device_ids}
        admin = self.secret("admin") or secrets.token_urlsafe(48)
        if any(len(token) < 24 or any(c.isspace() for c in token) for token in tokens.values()):
            raise ValueError("Enhetstoken må ha minst 24 tegn uten mellomrom.")
        if len(set(tokens.values())) != len(tokens) or admin in tokens.values():
            raise ValueError("Hver enhet må ha sitt eget token.")
        if api_key is not None:
            self.vault.put(self.target("openai"), api_key)
        self.vault.put(self.target("admin"), admin)
        for device_id, token in tokens.items():
            self.vault.put(self.target("device/" + device_id), token)
        self.save_values(config)

    def save_values(self,config):
        """Atomically save non-secret settings without rewriting credentials."""
        config=DesktopConfig.model_validate(config.model_dump())
        if config.credential_namespace!=self.config.credential_namespace:
            raise ValueError('Konfigurasjonsprofilen kan ikke byttes.')
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.config = config

    def settings(self):
        config = self.config
        # Explicit init values override inherited terminal/.env settings, including
        # all secrets; desktop settings are its sole source of configuration.
        defaults = {name: field.default for name, field in Settings.model_fields.items()}
        defaults.update(openai_api_key=self.secret("openai"), fire_backend_token=self.secret("admin"),
                        fire_device_tokens=json.dumps({key: self.secret("device/" + key) for key in config.device_ids}),
                        fire_backend_host="0.0.0.0" if config.allow_lan else "127.0.0.1", fire_backend_port=config.port,
                        fire_workspace=Path(config.workspace), fire_ai_mode=config.mode, fire_audio_enabled=config.audio_enabled,
                        fire_speech_enabled=config.speech_enabled,
                        openai_runtime_model=config.runtime_model,fire_runtime_ai_enabled=config.runtime_ai_enabled,
                        fire_runtime_ai_developer_mode=config.runtime_ai_developer_mode,
                        fire_runtime_ai_limits_enabled=config.runtime_ai_limits_enabled,
                        fire_runtime_ai_request_budget_usd=config.runtime_ai_request_budget_usd,
                        fire_runtime_ai_daily_budget_usd=config.runtime_ai_daily_budget_usd,
                        fire_runtime_ai_daily_calls=config.runtime_ai_daily_calls,fire_runtime_ai_output_tokens=config.runtime_ai_output_tokens,
                        fire_desktop_enabled=True,
                        fire_public_enabled=config.public_enabled, fire_web_origin=config.web_origin,
                        fire_device_host=config.device_host, fire_access_issuer=config.access_issuer,
                        fire_access_audience=config.access_audience,
                        fire_reverse_host=config.reverse_host if config.transport == "reverse_tcp" else "",
                        fire_reverse_port=config.reverse_port,
                        fire_reverse_device_id=(config.reverse_device_id or config.device_ids[0]) if config.transport == "reverse_tcp" else "",
                        openai_realtime_model=config.dialog_model, openai_code_model=config.code_model,
                        openai_review_model=config.review_model,
                        openai_transcribe_model=config.transcribe_model, openai_speech_model=config.speech_model,
                        openai_speech_voice=config.speech_voice, fire_max_workspace_mb=config.max_workspace_mb,
                        fire_cost_limits_enabled=config.cost_limits_enabled,fire_output_limits_enabled=config.output_limits_enabled,
                        fire_evolution_cost_limits_enabled=config.evolution_cost_limits_enabled,
                        fire_daily_budget_usd=config.daily_budget_usd, fire_build_budget_usd=config.build_budget_usd,
                        fire_request_budget_usd=config.request_budget_usd, fire_max_corrections=config.max_corrections)
        return Settings(_env_file=None, **defaults)

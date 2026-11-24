"""Executable Home v1 wire validation, also used by the setup/test utilities."""
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, TypeAdapter, model_validator

IDENTIFIER = r"^[a-z0-9][a-z0-9_-]{0,31}$"
HEX16 = r"^[a-f0-9]{16}$"
REV = r"^[a-f0-9]{8,32}$"
LIMITS = {"catalog": 8192, "state": 4096, "ack": 512, "request": 512}
OPS = {"light": {"on", "off", "brightness"}, "switch": {"on", "off"},
       "climate": {"temperature", "heat_mode"}, "sensor": set(), "binary_sensor": set(),
       "script": {"run"}, "scene": {"run"}}


def _card_schema(schema):
    schema["properties"]["ops"]["uniqueItems"]=True
    schema["properties"]["modes"]["uniqueItems"]=True
    schema["properties"]["name"]["x-max-utf8-bytes"]=96
    schema["properties"]["unit"]["x-max-utf8-bytes"]=24
    rules=[]
    for kind,ops in OPS.items():
        rules.append({"if":{"properties":{"kind":{"const":kind}}},
                      "then":{"properties":{"ops":{"items":{"enum":sorted(ops)}} if ops else {"maxItems":0}}}})
    rules += [{"if":{"properties":{"ops":{"contains":{"const":"temperature"}}}},
               "then":{"required":["min","max","step"],"properties":{"min":{"type":"number"},"max":{"type":"number"},"step":{"type":"number","exclusiveMinimum":0}}}},
              {"if":{"properties":{"ops":{"contains":{"const":"heat_mode"}}}},
               "then":{"required":["modes"],"properties":{"modes":{"type":"array","minItems":1,"uniqueItems":True}}}},
              {"if":{"properties":{"kind":{"not":{"const":"climate"}}}},
               "then":{"not":{"anyOf":[{"required":[key]} for key in ("min","max","step","modes")]}}}]
    schema["allOf"]=rules


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    v: StrictInt = Field(ge=1, le=1)


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False,json_schema_extra=_card_schema)
    id: str = Field(pattern=IDENTIFIER)
    name: str = Field(min_length=1, max_length=32)
    kind: Literal["light", "switch", "climate", "sensor", "binary_sensor", "script", "scene"]
    unit: str = Field(default="", max_length=12)
    ops: list[Literal["on", "off", "brightness", "temperature", "heat_mode", "run"]] = Field(max_length=3)
    min: StrictFloat | StrictInt | None = None
    max: StrictFloat | StrictInt | None = None
    step: StrictFloat | StrictInt | None = None
    modes: list[Literal["off", "heat", "auto"]] | None = Field(default=None, max_length=3)

    @model_validator(mode="after")
    def bounds(self):
        if len(self.name.encode("utf-8")) > 96 or len(self.unit.encode("utf-8")) > 24:
            raise ValueError("Card UTF-8 text limit")
        if len(set(self.ops)) != len(self.ops) or not set(self.ops) <= OPS[self.kind]:
            raise ValueError("Operation does not belong to card kind")
        climate_fields = (self.min, self.max, self.step, self.modes)
        if self.kind != "climate" and self.model_fields_set.intersection({"min","max","step","modes"}):
            raise ValueError("Climate metadata on another card kind")
        if "temperature" in self.ops and (any(x is None for x in (self.min, self.max, self.step))
                or self.min >= self.max or self.step <= 0 or self.step > self.max - self.min):
            raise ValueError("Temperature operation requires valid min/max/step")
        if "heat_mode" in self.ops and (not self.modes or len(set(self.modes)) != len(self.modes)):
            raise ValueError("Heat mode operation requires explicit unique modes")
        return self


class Catalog(Wire):
    site: str = Field(pattern=IDENTIFIER)
    device: str = Field(pattern=IDENTIFIER)
    route: Literal["local", "remote"]
    epoch: str = Field(pattern=HEX16)
    rev: str = Field(pattern=REV)
    issued: StrictInt = Field(ge=0)
    ttl: StrictInt = Field(ge=1, le=90)
    last_seq: StrictInt = Field(ge=0, le=2147483647)
    remote_allowed: StrictBool
    cards: list[Card] = Field(max_length=12)

    @model_validator(mode="after")
    def identity(self):
        if len({c.id for c in self.cards}) != len(self.cards):
            raise ValueError("Duplicate card identity")
        if self.route == "remote" and not self.remote_allowed and self.cards:
            raise ValueError("Remote-disabled catalog must be empty")
        return self


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    state: Literal["on", "off", "ok", "unavailable", "unknown"]
    value: StrictFloat | StrictInt | StrictBool | None
    target: StrictFloat | StrictInt | None = None
    mode: Literal["off", "heat", "auto", "unknown"] | None = None


class State(Wire):
    epoch: str = Field(pattern=HEX16)
    rev: str = Field(pattern=REV)
    issued: StrictInt = Field(ge=0)
    ttl: StrictInt = Field(ge=1, le=90)
    values: dict[str, Value] = Field(max_length=12)

    @model_validator(mode="after")
    def ids(self):
        import re
        if any(not re.fullmatch(IDENTIFIER, key) for key in self.values):
            raise ValueError("Invalid state card identity")
        return self


class Hello(Wire):
    type: Literal["hello"]
    rid: str = Field(pattern=HEX16)


class Command(Wire):
    type: Literal["command"]
    rid: str = Field(pattern=HEX16)
    epoch: str = Field(pattern=HEX16)
    rev: str = Field(pattern=REV)
    seq: StrictInt = Field(ge=1, le=2147483647)
    issued: StrictInt = Field(ge=0)
    ttl: StrictInt = Field(ge=1, le=15)
    card: str = Field(pattern=IDENTIFIER)
    op: Literal["on", "off", "brightness", "temperature", "heat_mode", "run"]
    value: StrictFloat | StrictInt | StrictBool | StrictStr | None

    @model_validator(mode="after")
    def operation_value(self):
        if self.op in {"on", "off", "run"} and self.value is not None:
            raise ValueError("This operation requires null")
        if self.op == "brightness" and (type(self.value) is not int or not 0 <= self.value <= 255):
            raise ValueError("Brightness requires integer 0..255")
        if self.op == "temperature" and (type(self.value) not in {int, float} or not math.isfinite(self.value)):
            raise ValueError("Temperature requires finite number")
        if self.op == "heat_mode" and self.value not in {"off", "heat", "auto"}:
            raise ValueError("Unsupported heat mode")
        return self


class Ack(Wire):
    rid: str = Field(pattern=HEX16)
    seq: StrictInt = Field(ge=1, le=2147483647)
    status: Literal["executed", "rejected", "unknown"]
    code: Literal["ok", "schema", "expired", "session", "revision", "sequence", "denied", "unavailable", "action_failed"]


MODELS = {"catalog": Catalog, "state": State, "ack": Ack, "request": TypeAdapter(Hello | Command)}


class DeviceProfile(BaseModel):
    """Local setup upload, not an MQTT message; passwords never go into Lua."""
    model_config = ConfigDict(extra="forbid",strict=True)
    profile: StrictInt = Field(ge=0,le=1)
    site: str = Field(pattern=IDENTIFIER)
    device: str = Field(pattern=IDENTIFIER)
    local_host: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9.\-]{0,252}$")
    remote_host: str = Field(pattern=r"^(?:[a-zA-Z0-9][a-zA-Z0-9.\-]{0,252})?$")
    local_user: str = Field(min_length=1,max_length=64)
    local_password: str = Field(min_length=24,max_length=128)
    remote_user: str = Field(min_length=1,max_length=64)
    remote_password: str = Field(min_length=24,max_length=128)
    ca: str = Field(min_length=128,max_length=4096,pattern=r"^-----BEGIN CERTIFICATE-----[\s\S]+-----END CERTIFICATE-----\s*$")

    @model_validator(mode="after")
    def public_ca(self):
        from cryptography import x509
        if "PRIVATE KEY" in self.ca:
            raise ValueError("Only the public CA certificate belongs on FIRE")
        certificate=x509.load_pem_x509_certificate(self.ca.encode())
        if not certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("FIRE must trust the local CA, not a server leaf")
        return self


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("Duplicate JSON field")
        result[k] = v
    return result


def validate_wire(kind, payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if kind not in MODELS or len(payload) > LIMITS[kind]:
        raise ValueError("Unknown message kind or byte limit exceeded")
    data = json.loads(payload, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    model = MODELS[kind]
    return model.validate_python(data) if isinstance(model, TypeAdapter) else model.model_validate(data)


def schemas():
    return {kind: model.json_schema() if isinstance(model, TypeAdapter) else model.model_json_schema()
            for kind, model in MODELS.items()}

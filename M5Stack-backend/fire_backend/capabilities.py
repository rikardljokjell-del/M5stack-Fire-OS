"""Hardware-first policy: simulator support never grants a device capability."""
import json

from .models import PROTOTYPE_SERVICES


FIRMWARE_SOURCE_REVISION = "7787ed0"
HANDOFF_PATH = "M5Stack-device/BACKEND_HANDOFF.md"


class CapabilityError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def policy(settings, target, capabilities):
    device = target == "device"
    caps = capabilities or {}
    input_declared = bool(caps.get("audio_input", False)) if device else True
    output_declared = bool(caps.get("audio_output", False)) if device else True
    return {
        "target": target, "lua_services": sorted(caps.get("services", [])) if device else sorted(PROTOTYPE_SERVICES),
        "max_memory": caps.get("max_memory", 131072 if device else 262144),
        "max_runtime_ms": caps.get("max_runtime_ms", 10000),
        "conversation_audio": {
            "input_announced": input_declared, "output_announced": output_declared,
            "input_enabled": input_declared and settings.fire_audio_enabled,
            "output_enabled": output_declared and settings.fire_audio_enabled,
            "backend_enabled": settings.fire_audio_enabled,
        },
        "physical_verified": False,
    }


def audio_input_error(settings, target, capabilities):
    effective = policy(settings, target, capabilities)
    audio = effective["conversation_audio"]
    if not audio["input_announced"]:
        return CapabilityError("audio_input_unavailable", "Enheten annonserer ikke taleopptak. Bruk tekst fra PC til mikrofonflyten er implementert og fysisk testet.")
    if not audio["backend_enabled"]:
        return CapabilityError("backend_audio_disabled", "Lyd er deaktivert på backend. Tekst kan brukes; tale krever FIRE_AUDIO_ENABLED=true og støtte i enheten.")
    return None


def require_audio_input(settings, session):
    error = audio_input_error(settings, session.target, session.capabilities)
    if error:
        raise error


def status(settings, session):
    effective = policy(settings, session.target, session.capabilities)
    error = audio_input_error(settings, session.target, session.capabilities)
    if error:
        code, message = error.code, str(error)
    elif not effective["conversation_audio"]["output_enabled"]:
        code, message = "audio_output_unavailable", "Taleopptak er tilgjengelig, men enheten annonserer ikke talesvar. Svaret sendes som tekst."
    else:
        code, message = "audio_transport_available", "Lydtransport er aktivert for annonserte funksjoner. Backend har ikke selv verifisert den fysiske enheten."
    return {"type": "capability_status", "code": code, "message": message, "effective_capabilities": effective}


def generation_policy(settings, session):
    effective = policy(settings, "device" if session.desktop_device_id else session.target, session.capabilities)
    disabled = sorted((PROTOTYPE_SERVICES - set(effective["lua_services"])) | {"mic", "speaker", "wifi", "bluetooth", "sd"})
    return (
        "\nAuthoritative capability policy for THIS session (overrides PC example availability):\n"
        + json.dumps(effective, ensure_ascii=False)
        + "\nOnly the listed lua_services may be declared or called. Unavailable fire services: " + ", ".join(disabled)
        + ". Conversation audio flags NEVER grant fire.mic/fire.speaker or other Lua APIs. "
        "App lifetime: max_runtime_ms=0 means until user exit, NOT a zero-duration app. "
        "Keep callback/instruction/memory protection; never implement an app auto-close timer. "
        "Keep every init/update/button callback below24 display operations and120000 estimated display-work units. "
        "Simplify the complete scene; never split its visible rendering across updates. A legacy ten-second lifetime note is not a requested ten-second game round. "
        "Do not propose an unavailable feature; explain the limitation and ask for a supported alternative. "
        "Source presence and advertised budgets are not proof of physical testing or firmware enforcement."
    )

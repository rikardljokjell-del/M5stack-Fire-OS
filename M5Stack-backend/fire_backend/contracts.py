"""Generate the firmware-facing schemas from the validated backend models."""
import copy
import json
from pathlib import Path

from .models import DeviceEvent, Manifest, PROTOTYPE_SERVICES
from .api_registry import REGISTRY,API_CONTRACT,ALL_SERVICES


REQUIRED = {
    "build_background":["build_id"],"build_resume":["build_id"],"build_cancel":["build_id"],
    "build_notice_ack":["build_id","notification_action"],
    "app_repair_prepare":["app_id"],"app_repair_cancel":["repair_id"],
    "app_download":["package_id"],
    "app_backend_delete_prepare":["delete_scope"],
    "app_backend_delete_confirm":["delete_id"],
    "firmware_store_result": ["firmware_id","transfer_id","status"],
    "text": ["text"], "button": ["button", "action"], "build_confirm": ["proposal_id"],
    "run_confirm": ["package_id"], "device_install_result": ["install_id", "package_id", "status"],
    "install_retry": ["package_id"],
    "app_started": ["run_id", "package_id"], "app_healthy": ["run_id", "package_id"],
    "app_failed": ["run_id", "package_id", "error_code"], "app_stopped": ["run_id", "package_id"],
    "rollback_result": ["rollback_id", "package_id", "status"], "listen_start": ["turn_id"], "listen_stop": ["turn_id"],
    "audio_playback_started": ["audio_id", "turn_id"], "audio_playback_finished": ["audio_id", "turn_id"],
    "app_select": ["app_mode"], "app_deleted": ["app_id"], "app_inventory": ["apps", "storage_ready", "complete"],
    "mode_select": ["conversation_mode"],
    "app_diagnostic": ["app_id", "package_id", "error_code"],
    "audio_playback_failed": ["audio_id", "turn_id", "error_code"],
}


def schemas():
    event = DeviceEvent.model_json_schema()
    event["properties"]["protocol_version"] = {"type": "string", "const": "0.2"}
    event["required"] = sorted(set(event["required"] + ["type", "protocol_version", "event_id"]))

    def nonnull(name):
        shape = copy.deepcopy(event["properties"][name])
        if "anyOf" in shape:
            shape = next(option for option in shape["anyOf"] if option.get("type") != "null")
        shape.pop("default", None)
        return shape

    event["properties"]["event_id"] = nonnull("event_id")
    conditions = []
    for name, required in REQUIRED.items():
        conditions.append({"if": {"properties": {"event": {"const": name}}},
                           "then": {"required": required, "properties": {field: nonnull(field) for field in required}}})
    conditions.append({"if": {"properties": {"event": {"not": {"const": "session_start"}}}},
                       "then": {"required": ["session_id"], "properties": {"session_id": nonnull("session_id")}}})
    conditions.append({"if": {"properties": {"event": {"const": "session_start"}, "target": {"const": "device"}}, "required": ["target"]},
                       "then": {"required": ["boot_id", "capabilities"], "properties": {name: nonnull(name) for name in ("boot_id", "capabilities")}}})
    conditions.append({"if": {"properties": {"event": {"const": "app_stopped"}}},
                       "then": {"anyOf": [{"required": ["stop_id"], "properties": {"stop_id": nonnull("stop_id")}},
                                          {"required": ["reason"], "properties": {"reason": {"enum": ["completed", "user_exit", "runtime_limit"]}}}]}})
    conditions.append({"if": {"properties": {"event": {"const": "device_install_result"}, "status": {"const": "ok"}}},
                       "then": {"required": ["archive_sha256"], "properties": {"archive_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}})
    conditions.append({"if":{"properties":{"event":{"const":"app_repair_status"}}},
                       "then":{"anyOf":[{"required":[name],"properties":{name:nonnull(name)}} for name in ('repair_id','app_id')]}})
    event["allOf"] = conditions
    conditions.append({"if":{"properties":{"event":{"const":"firmware_store_result"},"status":{"const":"ok"}}},
                       "then":{"required":["sha256"],"properties":{"sha256":nonnull("sha256")}}})
    for event_name in ("app_versions", "app_select", "app_backend_delete_prepare"):
        condition = {"event": {"const": event_name}}
        if event_name == "app_select":
            condition["app_mode"] = {"const": "update"}
        conditions.append({"if": {"properties": condition}, "then": {"anyOf": [
            {"required": [name], "properties": {name: nonnull(name)}} for name in ("app_id", "project_id")]}})
    conditions.append({"if":{"properties":{"event":{"const":"app_backend_delete_prepare"},"delete_scope":{"const":"version"}}},
                       "then":{"required":["package_id"],"properties":{"package_id":nonnull("package_id")}}})
    conditions.append({"if":{"properties":{"event":{"const":"app_backend_delete_prepare"},"delete_scope":{"const":"all"}}},
                       "then":{"properties":{"package_id":{"type":"null"}}}})
    conditions.append({"if": {"properties": {"event": {"const": "app_select"}, "app_mode": {"const": "new"}}},
                       "then": {"properties": {name: {"type": "null"} for name in ("app_id", "project_id", "base_package_id")}}})
    manifest = Manifest.model_json_schema()
    legacy=copy.deepcopy(manifest);legacy["properties"]["api_version"]={"const":"fire-lua-0.1","default":"fire-lua-0.1","title":"Api Version","type":"string"}
    legacy["properties"].pop("api_contract",None)
    legacy["properties"]["required_services"].update(items={"enum":sorted(PROTOTYPE_SERVICES)},uniqueItems=True)
    legacy["properties"]["permissions"].update(items={"enum":["fire."+name for name in sorted(PROTOTYPE_SERVICES)]},uniqueItems=True)
    manifest["properties"]["api_version"]={"const":"fire-lua-0.2","type":"string"}
    manifest["properties"]["api_contract"]={"type":"string","const":API_CONTRACT}
    manifest["required"]+= ["api_version","api_contract"]
    manifest["properties"]["required_services"].update(items={"enum": sorted(ALL_SERVICES)}, uniqueItems=True)
    manifest["properties"]["permissions"].update(items={"enum": ["fire." + name for name in sorted(ALL_SERVICES)]}, uniqueItems=True)
    return {"device-event-v0.2.schema.json": event, "manifest-fire-lua-0.1.schema.json": legacy,
            "manifest-fire-lua-0.2.schema.json":manifest,"HARDWARE_API-v0.2.json":{"api_contract":API_CONTRACT,"registry":REGISTRY}}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "contracts"
    root.mkdir(exist_ok=True)
    for name, schema in schemas().items():
        (root / name).write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

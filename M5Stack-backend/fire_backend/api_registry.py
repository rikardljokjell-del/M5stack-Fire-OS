"""Reviewed Lua API contracts. A simulator entry never grants a device service."""
import hashlib
import json
from importlib.resources import files
from .app_sdk import SDK_VERSION,SDK_CONTRACT,available as sdk_available,contract as sdk_contract,callback_budgets

BASE_API="fire-lua-0.1"
HARDWARE_API="fire-lua-0.2"
REGISTRY=json.loads(files("fire_backend").joinpath("data/HARDWARE_API-v0.2.json").read_text(encoding="utf-8"))
API_CONTRACT=hashlib.sha256(json.dumps(REGISTRY,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
BASE_SERVICES={name for name,spec in REGISTRY["services"].items() if any(m["since"]==BASE_API for m in spec["methods"].values())}
ALL_SERVICES=set(REGISTRY["services"])


def methods_for(api_version):
    if api_version not in {BASE_API,HARDWARE_API,SDK_VERSION}:raise ValueError("Unsupported Lua API version")
    result={service:{name:method for name,method in spec["methods"].items() if api_version!=BASE_API or method["since"]==BASE_API}
            for service,spec in REGISTRY["services"].items() if api_version!=BASE_API or service in BASE_SERVICES}
    if api_version==SDK_VERSION:result['display'].update(sdk_contract()['registry']['display']['methods'])
    return result


def generation_contract(api_version,services):
    methods=methods_for(api_version)
    result={"api_version":api_version,"api_contract":SDK_CONTRACT if api_version==SDK_VERSION else API_CONTRACT if api_version==HARDWARE_API else None,
            "services":{name:methods[name] for name in sorted(services) if name in methods},
            "limits":REGISTRY["limits"],"semantics":REGISTRY["semantics"],
            "result_shapes":REGISTRY["result_shapes"],"environment":REGISTRY["environment"] if api_version!=BASE_API else {}}
    if api_version==SDK_VERSION:
        result["limits"]={**result["limits"],**callback_budgets(api_version)}
        result["display_semantics"]={k:v for k,v in sdk_contract()["registry"]["display"].items() if k!="methods"}
    return result


def preview_capabilities():
    return {"api_version":HARDWARE_API,"api_contract":API_CONTRACT,"services":sorted(ALL_SERVICES),
            "app_sdk":{"version":SDK_VERSION,"contract":SDK_CONTRACT},
            "max_memory":131072,"max_runtime_ms":0,"audio_input":False,"audio_output":False,
            "firmware_version":"PC hardware simulation ONLY","hardware":{
                "gpio_read":[26,36],"gpio_write":[26],"adc":[36],"dac":[26],"pwm":[26],
                "i2c":[0],"i2c_write_addresses":[64],"uart":[2],"spi":[2]}}


def service_closure(services,api_version=HARDWARE_API):
    required=set(services);methods=methods_for(api_version)
    if api_version==SDK_VERSION:required.add('display')
    if not required<=set(methods):raise ValueError("Unknown service for this API")
    while True:
        dependencies={dep for name in required for method in methods[name].values() for dep in method.get("requires",[])}
        if dependencies<=required:return sorted(required)
        required.update(dependencies)


def package_compatibility(package,capabilities):
    manifest=package["manifest"]
    if not set(manifest['required_services'])<=set(capabilities.get('services',[])):
        return 'Appen krever tjenester som denne enheten ikke annonserer.'
    if manifest.get('api_version')==SDK_VERSION:
        if not sdk_available(capabilities):return 'Appen krever annonsert FIRE App SDK med samme kontrakt i firmware.'
        if (manifest.get('api_contract')!=SDK_CONTRACT or capabilities.get('api_version')!=HARDWARE_API
                or capabilities.get('api_contract')!=API_CONTRACT):
            return 'SDK-pakken og firmware har ulike SDK-/maskinvarekontrakter.'
    if set(service_closure(manifest['required_services'],manifest.get('api_version',BASE_API)))!=set(manifest['required_services']):
        return "Appakken mangler nødvendige maskinvareavhengigheter; bygg en korrigert versjon."
    if manifest.get("api_version",BASE_API)==HARDWARE_API and capabilities.get("api_version",BASE_API)!=HARDWARE_API:
        return "Appversjonen krever det utvidede maskinvare-API-et i firmware."
    if manifest.get("api_version")==HARDWARE_API and (capabilities.get("api_contract")!=API_CONTRACT or manifest.get("api_contract")!=API_CONTRACT):
        return "Firmware og backend har ulike maskinvarekontrakter."
    resources=(package.get("validation") or {}).get("resources_used",{})
    advertised=capabilities.get("hardware") or {}
    if any(not set(values)<=set(advertised.get(kind,[])) for kind,values in resources.items()):
        return "Appen bruker pinner eller busser som denne firmwareprofilen ikke tilbyr."
    return ""

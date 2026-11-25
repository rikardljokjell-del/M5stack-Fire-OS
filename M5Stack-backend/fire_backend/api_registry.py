"""Reviewed Lua API contracts. A simulator entry never grants a device service."""
import hashlib
import json
import copy
from importlib.resources import files
from .app_sdk import SDK_VERSION,SDK_CONTRACT,available as sdk_available,contract as sdk_contract,callback_budgets
from .runtime_contract import REGISTRY as AI_REGISTRY,EXTENSION as AI_EXTENSION,available as ai_available
from .data_contract import REGISTRY as DATA_REGISTRY,EXTENSION as DATA_EXTENSION,available as data_available

BASE_API="fire-lua-0.1"
HARDWARE_API="fire-lua-0.2"
REGISTRY=json.loads(files("fire_backend").joinpath("data/HARDWARE_API-v0.2.json").read_text(encoding="utf-8"))
API_CONTRACT=hashlib.sha256(json.dumps(REGISTRY,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
BASE_SERVICES={name for name,spec in REGISTRY["services"].items() if any(m["since"]==BASE_API for m in spec["methods"].values())}
ALL_SERVICES=set(REGISTRY["services"])|{'ai','data'}


def methods_for(api_version,services=None):
    if api_version not in {BASE_API,HARDWARE_API,SDK_VERSION}:raise ValueError("Unsupported Lua API version")
    result={service:{name:method for name,method in spec["methods"].items() if api_version!=BASE_API or method["since"]==BASE_API}
            for service,spec in REGISTRY["services"].items() if api_version!=BASE_API or service in BASE_SERVICES}
    if api_version==SDK_VERSION:
        result['display'].update(sdk_contract()['registry']['display']['methods'])
        result['ai']=AI_REGISTRY['methods']
        result['data']=DATA_REGISTRY['methods']
        if services and 'data' in services:
            for service,methods in DATA_REGISTRY.get('hardware_methods',{}).items():
                result[service].update(methods)
    return result


def restricted_methods(methods,capabilities):
    result=copy.deepcopy(methods)
    caps=capabilities or {}
    for service,names in (caps.get('service_methods') or {}).items():
        if service in result:result[service]={k:v for k,v in result[service].items() if k in names}
    for key,values in (caps.get('service_modes') or {}).items():
        service,method=key.split('.',1)
        spec=result.get(service,{}).get(method)
        if spec:
            for arg in spec.get('args',[]):
                if arg.get('type')=='enum':
                    arg['values']=[v for v in arg['values'] if v in values]
                    break
    return result


def generation_contract(api_version,services,capabilities=None):
    methods=methods_for(api_version,services)
    methods=restricted_methods(methods,capabilities)
    result={"api_version":api_version,"api_contract":SDK_CONTRACT if api_version==SDK_VERSION else API_CONTRACT if api_version==HARDWARE_API else None,
            "services":{name:methods[name] for name in sorted(services) if name in methods},
            "limits":REGISTRY["limits"],"semantics":REGISTRY["semantics"],
            "result_shapes":REGISTRY["result_shapes"],"environment":REGISTRY["environment"] if api_version!=BASE_API else {}}
    if api_version==SDK_VERSION:
        result["limits"]={**result["limits"],**callback_budgets(api_version)}
        result["display_semantics"]={k:v for k,v in sdk_contract()["registry"]["display"].items() if k!="methods"}
        if 'ai' in services:result['runtime_ai']={'extension':AI_EXTENSION,'limits':AI_REGISTRY['limits'],'semantics':AI_REGISTRY['semantics']}
        if 'data' in services:result['data_engine']={'extension':DATA_EXTENSION,'limits':DATA_REGISTRY['limits'],
            'formats':DATA_REGISTRY['formats'],'semantics':DATA_REGISTRY['semantics'],
            'capture_sources':((capabilities or {}).get('data_engine') or {}).get('capture_sources',[]),
            'capture_limits':((capabilities or {}).get('data_engine') or {}).get('capture_limits',{})}
    return result


def preview_capabilities():
    return {"api_version":HARDWARE_API,"api_contract":API_CONTRACT,"services":sorted(ALL_SERVICES),
            "app_sdk":{"version":SDK_VERSION,"contract":SDK_CONTRACT},
            "runtime_ai":dict(AI_EXTENSION),
            "data_engine":{**DATA_EXTENSION,'capture_sources':[],'capture_limits':{}},
            "max_memory":131072,"max_runtime_ms":0,"audio_input":False,"audio_output":False,
            "firmware_version":"PC hardware simulation ONLY","hardware":{
                "gpio_read":[26,36],"gpio_write":[26],"adc":[36],"dac":[26],"pwm":[26],
                "i2c":[0],"i2c_write_addresses":[64],"uart":[2],"spi":[2]}}


def service_closure(services,api_version=HARDWARE_API):
    required=set(services);methods=methods_for(api_version,services)
    if api_version==SDK_VERSION:required.add('display')
    if not required<=set(methods):raise ValueError("Unknown service for this API")
    while True:
        dependencies={dep for name in required for method in methods[name].values() for dep in method.get("requires",[])}
        if 'data' in required:dependencies.update(DATA_REGISTRY['requires'])
        if dependencies<=required:return sorted(required)
        required.update(dependencies)


def package_compatibility(package,capabilities):
    manifest=package["manifest"]
    calls=package.get('validation',{}).get('io_calls',{})
    for name,count in calls.items():
        if not count or '.' not in name:continue
        service,method=name.split('.',1)
        names=(capabilities.get('service_methods') or {}).get(service)
        if names is not None and method not in names:
            return 'Appen bruker en metode som denne firmwareprofilen ikke annonserer: '+name
    for name,allowed in (capabilities.get('service_modes') or {}).items():
        if calls.get(name):
            used=package.get('validation',{}).get('service_modes_used',{}).get(name)
            if not used or not set(used)<=set(allowed):
                return 'Appen må testes med firmwareprofilens støttede modus: '+name
    if 'data' in manifest['required_services'] and (not data_available(capabilities) or manifest.get('data_engine')!=DATA_EXTENSION):
        return 'Appen krever annonsert Data Engine med samme kontrakt i firmware.'
    if 'ai' in manifest['required_services'] and (not ai_available(capabilities) or manifest.get('runtime_ai')!=AI_EXTENSION):
        return 'Appen krever annonsert Runtime AI med samme kontrakt i firmware.'
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

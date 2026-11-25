"""Optional Data Engine contract, loaded from the single packaged registry."""
import hashlib
import json
from importlib.resources import files

from .runtime_contract import bounded, parse, RuntimeAIError


_wrapper = json.loads(files('fire_backend').joinpath('data/DATA_ENGINE-v1.json').read_text(encoding='utf-8'))
REGISTRY = _wrapper['registry']
CONTRACT = hashlib.sha256(json.dumps(REGISTRY, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
if CONTRACT != _wrapper['api_contract']:
    raise ValueError('Data Engine contract checksum mismatch')
VERSION = REGISTRY['api_version']
EXTENSION = {'version': VERSION, 'contract': CONTRACT}
LIMITS = REGISTRY['limits']


def available(capabilities):
    from .app_sdk import available as sdk_available
    capabilities = capabilities or {}
    return (sdk_available(capabilities) and set(REGISTRY['requires']) <= set(capabilities.get('services', []))
            and 'data' in capabilities.get('services', [])
            and all((capabilities.get('data_engine') or {}).get(k) == v for k, v in EXTENSION.items()))


def object_json(text, limit):
    try:
        value = parse(text, limit)
        bounded(value)
        if not isinstance(value, dict):
            raise ValueError('object required')
    except (RuntimeAIError, ValueError, TypeError):
        raise ValueError('invalid_json') from None
    return value


def generation_context(capabilities):
    if not available(capabilities):
        return ''
    return ('\nData Engine (optional; only declared data/jobs/sd permission):\n' +
            json.dumps({'extension': EXTENSION, 'methods': REGISTRY['methods'], 'limits': LIMITS,
                        'formats': REGISTRY['formats'], 'semantics': REGISTRY['semantics']},
                       ensure_ascii=False, separators=(',', ':')))

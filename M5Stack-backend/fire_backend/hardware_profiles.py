"""Small documented hardware facts; neither a driver registry nor permissions."""
import copy
import json
import re
from importlib.resources import files

CATALOG = json.loads(files('fire_backend').joinpath('data/hardware_profiles.json').read_text(encoding='utf-8'))
MAX_CONTEXT_BYTES = 3500


def _mentioned(text, alias):
    return re.search(r'(?<!\w)' + re.escape(alias.casefold()) + r'(?!\w)', text) is not None


def select(request, limit=3):
    text = str(request).casefold()
    matches = []
    for profile in CATALOG['profiles']:
        if any(_mentioned(text, x) for x in profile.get('exclude_aliases', [])):
            continue
        score = max((len(a) for a in profile['aliases'] if _mentioned(text, a)), default=0)
        if score:
            matches.append((score, profile['id'], profile))
    return [copy.deepcopy(p) for _, _, p in sorted(matches, key=lambda x: (-x[0], x[1]))[:max(0, min(3, limit))]]


def context_for(request, caps):
    """Return bounded actual facts, never invent attached modules or grants."""
    selected = select(request)
    if not selected:
        return ''
    services = set((caps or {}).get('services', []))
    profiles = []
    for p in selected:
        missing = sorted(set(p['required_services']) - services)
        profiles.append({k: p[k] for k in ('id', 'label', 'required_services', 'facts', 'source_urls', 'evidence', 'physical_verified')})
        profiles[-1].update(api_services_available=not missing and not p.get('native_adapter_required', False),
                            missing_services=missing, attached=False,
                            native_adapter_required=p.get('native_adapter_required', False))
        if 'i2c_addresses' in p:
            profiles[-1]['documented_i2c_addresses'] = p['i2c_addresses']
    value = {'rules': CATALOG['rules'], 'profiles': profiles,
             'selection_is_not_wiring_or_permission': True}
    def encode():
        return '\nRelevant documented hardware:\n' + json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    # Drop lower-ranked profiles before optional factual details; never slice JSON.
    while len(encode().encode('utf-8')) > MAX_CONTEXT_BYTES and len(profiles) > 1:
        profiles.pop()
    if len(encode().encode('utf-8')) > MAX_CONTEXT_BYTES:
        raise ValueError('A documented hardware profile exceeds the context bound')
    return encode()

"""Load the one packaged OS-control contract; no Lua hardware permission."""
import hashlib
import json
import math
from importlib.resources import files

from .storage import canonical

_wrapper=json.loads(files('fire_backend').joinpath('data/EVOLUTION-v1.json').read_text(encoding='utf-8'))
REGISTRY=_wrapper['registry']
CONTRACT=hashlib.sha256(canonical(REGISTRY)).hexdigest()
if CONTRACT!=_wrapper['api_contract']:
    raise ValueError('Evolution contract checksum mismatch')
VERSION=REGISTRY['api_version']
EXTENSION={'version':VERSION,'contract':CONTRACT}
DEFAULTS=REGISTRY['defaults']
LIMITS=REGISTRY['limits']


def available(capabilities):
    return (capabilities or {}).get('evolution') == EXTENSION


def json_object(text, limit=LIMITS['control_json_bytes']):
    if not isinstance(text,str) or len(text.encode('utf-8'))>limit:
        raise ValueError('Evolution request exceeds UTF8 bound')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate Evolution JSON key')
            result[key]=value
        return result
    result=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    def bounded(value,depth=0):
        if depth>6:raise ValueError('Evolution JSON depth exceeded')
        if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite Evolution JSON')
        if isinstance(value,dict):
            if len(value)>32:raise ValueError('Evolution object too large')
            for v in value.values():bounded(v,depth+1)
        elif isinstance(value,list):
            if len(value)>32:raise ValueError('Evolution array too large')
            for v in value:bounded(v,depth+1)
    if not isinstance(result,dict):raise ValueError('Expected Evolution JSON object')
    bounded(result)
    return result

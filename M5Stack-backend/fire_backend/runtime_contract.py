"""Bounded optional Runtime AI extension; canonical registry owns its limits."""
import hashlib
import json
import math
import re
from pathlib import Path

_wrapper=json.loads((Path(__file__).parent/'data/RUNTIME_AI-v1.json').read_text(encoding='utf-8'))
REGISTRY=_wrapper['registry']
CONTRACT=hashlib.sha256(json.dumps(REGISTRY,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
if CONTRACT!=_wrapper['api_contract']:raise ValueError('Runtime AI contract checksum mismatch')
VERSION=REGISTRY['api_version']
LIMITS=REGISTRY['limits']
EXTENSION={'version':VERSION,'contract':CONTRACT}
GENERATION_MARKER='\nRuntime AI generation policy:\n'


def explicitly_requested(text):
    return bool(re.search(r'\b(?:runtime\s*(?:ai|ki)|(?:bruk\w*|med|using|uses?|with|powered by)\s+(?:ai|ki)|(?:ai|ki)[ -](?:analyse|analysis|assistent|oppdrag|drevet)|kunstig intelligens)\b',text,re.I))


def generation_mode(context,settings):
    if GENERATION_MARKER in context:
        try:return json.JSONDecoder().raw_decode(context.split(GENERATION_MARKER,1)[1])[0]['mode']
        except (ValueError,KeyError,TypeError):pass
    return settings.fire_runtime_ai_developer_mode


def generation_context(settings,caps,mode=None):
    facts={'mode':mode or settings.fire_runtime_ai_developer_mode,'available':available(caps),
           'global_enabled':settings.fire_runtime_ai_enabled,'extension':EXTENSION,'limits':LIMITS}
    instruction=('AUTO: include ai only for real value or an explicit runtime-AI request; a normal clock needs no AI. '
        'OFF: never add ai; explain conflicts with explicit AI requirements or an existing AI feature, never fake an AI result. '
        'Only announced capabilities grant ai. AI requires jobs and the exact optional runtime_ai manifest extension. '
        'Keep meaningful local operation/fallback while offline, pending, disabled, cancelled or timed out. '
        'Use a button-driven request, bounded automatic aggregation of relevant real app data, no manual data entry or whole-log upload. '
        'Choose app-specific short labels, enums/numbers and bounded strings that fit320x240; paginate via buttons when needed. Never dump raw JSON/Markdown/emoji to the LCD. Label AI assessment separately from measurements, with pending/offline/retry states. No extra summarization call. '
        'Init only configures local state; request is operational only from update/on_button after actual run binding. '
        'Use jobs.poll/result/cancel/close without waiting, keep drawing and input responsive. '
        'Cache the last result and aggregate new observations while pending; call only on a real button/event transition with fresh basis, never every frame or blind retry. '
        'On ready use result.ok and result.data fields from the exact JSON schema; distinguish assessment from measured facts. '
        'Include a tested pending/result/error/stop sequence; never call every frame or automatically replay charged requests. '
        'Runtime AI must enhance requested features, not replace core deterministic gameplay or measurement.')
    if facts['available'] and facts['mode']=='auto':
        facts['methods']=REGISTRY['methods']
        facts['schema_semantics']=REGISTRY['semantics']['schema']
        facts['schema_bounds']='Every string needs maxLength or a finite typed enum; every array needs maxItems and items. All object keys must appear in required, additionalProperties=false.'
        facts['request_example']={'instructions':'Vurder målte data kort.',
            'data_json':compact({'norm_g':1,'samples':16}),
            'schema_json':compact({'type':'object','properties':{'status':{'type':'string','enum':['normal','sjekk']},'vurdering':{'type':'string','maxLength':40}},
                'required':['status','vurdering'],'additionalProperties':False})}
        instruction+=' Pass data_json and schema_json as correctly escaped JSON strings, not Lua tables; consume the exact result.data fields in your schema.'
    return GENERATION_MARKER+compact(facts)+'\n'+instruction


class RuntimeAIError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def available(caps):
    from .app_sdk import available as sdk_available
    return sdk_available(caps) and (caps or {}).get('runtime_ai')==EXTENSION and {'ai','jobs'}<=set(caps.get('services',[]))


def compact(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def parse(text,limit,code='invalid_json'):
    if not isinstance(text,str) or len(text.encode('utf-8'))>limit:raise RuntimeAIError('payload_too_large')
    def pairs(items):
        obj={}
        for key,value in items:
            if key in obj:raise ValueError('duplicate key')
            obj[key]=value
        return obj
    try:return json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
    except (ValueError,RecursionError):raise RuntimeAIError(code) from None


def bounded(value,depth=1):
    if depth>LIMITS['json_depth']:raise RuntimeAIError('invalid_json')
    if isinstance(value,dict):
        if len(value)>LIMITS['json_object_keys']:raise RuntimeAIError('invalid_json')
        for k,v in value.items():
            if len(k.encode('utf-8'))>LIMITS['json_string_bytes']:raise RuntimeAIError('invalid_json')
            bounded(v,depth+1)
    elif isinstance(value,list):
        if len(value)>LIMITS['json_array_items']:raise RuntimeAIError('invalid_json')
        for v in value:bounded(v,depth+1)
    elif isinstance(value,str):
        if len(value.encode('utf-8'))>LIMITS['json_string_bytes']:raise RuntimeAIError('invalid_json')
    elif type(value) in {int,float}:
        try:finite=math.isfinite(value)
        except OverflowError:finite=False
        # Native LUA_32BITS converts JSON numbers to finite IEEE float32.
        if not finite or abs(value)>3.4028234663852886e38:raise RuntimeAIError('invalid_json')
    elif value is not None and type(value) not in {bool,int,float}:raise RuntimeAIError('invalid_json')


def schema_check(s,depth=1):
    allowed={'type','properties','required','additionalProperties','items','minItems','maxItems','minLength','maxLength','enum','minimum','maximum','description'}
    if not isinstance(s,dict) or set(s)-allowed or depth>LIMITS['json_depth']:raise RuntimeAIError('invalid_schema')
    kind=s.get('type')
    if kind not in {'object','array','string','number','integer','boolean','null'}:raise RuntimeAIError('invalid_schema')
    typed={'object':{'properties','required','additionalProperties'},'array':{'items','minItems','maxItems'},
           'string':{'minLength','maxLength'},'number':{'minimum','maximum'},'integer':{'minimum','maximum'},'boolean':set(),'null':set()}
    if set(s)-({'type','description','enum'}|typed[kind]):raise RuntimeAIError('invalid_schema')
    if 'enum' in s and kind in {'object','array'}:raise RuntimeAIError('invalid_schema')
    if kind=='object':
        props=s.get('properties');required=s.get('required')
        if (not isinstance(props,dict) or len(props)>LIMITS['json_object_keys'] or
            any(not isinstance(k,str) or len(k.encode('utf-8'))>LIMITS['json_string_bytes'] for k in props) or
            not isinstance(required,list) or not all(isinstance(k,str) for k in required) or
            len(required)!=len(set(required)) or set(required)!=set(props) or s.get('additionalProperties') is not False):raise RuntimeAIError('invalid_schema')
        for child in props.values():schema_check(child,depth+1)
    if kind=='array':
        n=s.get('maxItems')
        if type(n) is not int or not 0<=n<=LIMITS['json_array_items']:raise RuntimeAIError('invalid_schema')
        schema_check(s.get('items'),depth+1)
    if kind=='string' and ('enum' not in s or 'maxLength' in s) and (type(s.get('maxLength')) is not int or not 0<=s['maxLength']<=LIMITS['json_string_bytes']):raise RuntimeAIError('invalid_schema')
    for key in ('minimum','maximum','minItems','minLength'):
        if key in s:
            try:valid=type(s[key]) in {int,float} and math.isfinite(s[key]) and abs(s[key])<=3.4028234663852886e38
            except OverflowError:valid=False
            if not valid:raise RuntimeAIError('invalid_schema')
    if any(key in s and (type(s[key]) is not int or s[key]<0) for key in ('minItems','minLength')):raise RuntimeAIError('invalid_schema')
    for low,high in (('minimum','maximum'),('minItems','maxItems'),('minLength','maxLength')):
        if low in s and high in s and s[low]>s[high]:raise RuntimeAIError('invalid_schema')
    if 'description' in s and (not isinstance(s['description'],str) or len(s['description'].encode('utf-8'))>256):raise RuntimeAIError('invalid_schema')
    if 'enum' in s:
        if not isinstance(s['enum'],list) or not 1<=len(s['enum'])<=16:raise RuntimeAIError('invalid_schema')
        bounded(s['enum'])
        if any(not matches(v,{k:v2 for k,v2 in s.items() if k!='enum'}) for v in s['enum']):raise RuntimeAIError('invalid_schema')


def matches(value,s):
    kind=s['type']
    if kind=='object':return isinstance(value,dict) and set(value)==set(s['properties']) and all(matches(value[k],child) for k,child in s['properties'].items())
    if kind=='array':return isinstance(value,list) and s.get('minItems',0)<=len(value)<=s['maxItems'] and all(matches(v,s['items']) for v in value)
    valid=(isinstance(value,str) if kind=='string' else type(value) in {int,float} if kind=='number' else type(value) is int if kind=='integer' else type(value) is bool if kind=='boolean' else value is None)
    if not valid:return False
    if 'enum' in s and not any(type(v) is type(value) and v==value for v in s['enum']):return False
    if kind=='string' and not s.get('minLength',0)<=len(value)<=s.get('maxLength',LIMITS['json_string_bytes']):return False
    if kind in {'number','integer'} and not s.get('minimum',-math.inf)<=value<=s.get('maximum',math.inf):return False
    return True


def request_data(instructions,data_json,schema_json,timeout_ms):
    texts=[instructions,data_json,schema_json]
    for text,key in zip(texts,['instructions_bytes','data_bytes','schema_bytes']):
        if not isinstance(text,str) or not text or len(text.encode('utf-8'))>LIMITS[key]:raise RuntimeAIError('payload_too_large')
    if sum(len(v.encode('utf-8')) for v in texts)>LIMITS['request_bytes']:raise RuntimeAIError('payload_too_large')
    if type(timeout_ms) is not int or not LIMITS['timeout_min_ms']<=timeout_ms<=LIMITS['timeout_max_ms']:raise RuntimeAIError('invalid_json')
    data=parse(data_json,LIMITS['data_bytes']);schema=parse(schema_json,LIMITS['schema_bytes'],'invalid_schema')
    if not isinstance(data,dict):raise RuntimeAIError('invalid_json')
    bounded(data);schema_check(schema)
    if schema['type']!='object':raise RuntimeAIError('invalid_schema')
    return data,schema


def result_data(text,schema):
    if not isinstance(text,str):raise RuntimeAIError('invalid_result')
    value=parse(text,16384,'invalid_result')
    try:bounded(value)
    except RuntimeAIError:raise RuntimeAIError('invalid_result') from None
    if not matches(value,schema):raise RuntimeAIError('invalid_result')
    result=compact(value)
    if len(result.encode('utf-8'))>LIMITS['result_bytes']:raise RuntimeAIError('result_too_large')
    return result

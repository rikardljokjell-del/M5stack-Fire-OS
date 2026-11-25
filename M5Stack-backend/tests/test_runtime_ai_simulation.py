"""Bounded PC-only Runtime AI fixtures; never evidence of live inference."""
import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from fire_backend.app_sdk import SDK_VERSION,SDK_CONTRACT
from fire_backend.lua_worker import simulate
from fire_backend.runtime_contract import EXTENSION,LIMITS,RuntimeAIError,request_data,result_data

ROOT=Path(__file__).parents[1]
SCHEMA={'type':'object','properties':{'label':{'type':'string','maxLength':24}},'required':['label'],'additionalProperties':False}


def run(source,**changes):
    return simulate(dict(main_lua=source,api_version=SDK_VERSION,api_contract=SDK_CONTRACT,runtime_ai=EXTENSION,
        required_services=['display','buttons','ai','jobs','imu'],profile='idle',preview_duration_ms=1500,
        capture_at_ms=[1500],native_host_policy='fire-native-host-v1',**changes))


@pytest.mark.parametrize('data,schema',[
    ('null',SCHEMA),('[]',SCHEMA),('{"x":1.}',SCHEMA),('{"x":1e40}',SCHEMA),
    ('{}',{'type':'object','properties':{},'required':{},'additionalProperties':False}),
    ('{}',{'type':'object','properties':[], 'required':[],'additionalProperties':False}),
    ('{}',{'type':'object','properties':{'x':{'type':'string','enum':[1]}},'required':['x'],'additionalProperties':False}),
    ('{}',{'type':'object','properties':{'x':{'type':'boolean','minItems':0}},'required':['x'],'additionalProperties':False}),
])
def test_private_parser_rejects_same_invalid_json_and_schema_as_backend(data,schema):
    spec=json.dumps(schema,separators=(',',':'))
    with pytest.raises(RuntimeAIError):request_data('Check',data,spec,1000)
    lua=LuaRuntime(unpack_returned_tuples=True)
    parser=lua.execute((ROOT/'fire_backend/data/runtime_ai_sim.lua').read_text(encoding='utf-8')+'\nreturn runtime_ai_parser')
    value,code=parser(data,spec,lua.table_from(LIMITS))
    assert value is None and code in {'invalid_json','invalid_schema'}


def test_ai_init_is_stale_three_argument_default_and_one_pending_job_are_preserved():
    schema=json.dumps(SCHEMA,separators=(',',':'))
    source="""local job,invalid
function init()
 local id,e=fire.ai.request('Check','{}','SCHEMA')
 if id~=nil or e~='stale_run' then invalid='BAD init' end
end
function update(dt)
 if not job then
  job=fire.ai.request('Check','{}','SCHEMA')
  if not job then invalid='BAD request' end
  local other,e=fire.ai.request('Check','{}','SCHEMA',nil)
  if other~=nil or e~='busy' then invalid='BAD busy' end
 end
 fire.ui.screen('RUNTIME',invalid or 'PC fixture')
end""".replace('SCHEMA',schema)
    result=run(source)
    assert result['jobs_started']['ai.request']==1 and result['runtime_ai_simulated']
    assert not result['native_timing_measured']
    assert not any('BAD' in str(frame['ops']) for frame in result['visual_frames'])


def test_simulated_oversize_result_is_failed_without_truncating_data():
    schema={'type':'object','properties':{k:{'type':'string','minLength':250,'maxLength':250} for k in ['a','b','c']},'required':['a','b','c'],'additionalProperties':False}
    spec=json.dumps(schema,separators=(',',':'))
    source="""local job,done,invalid=nil,false,false
function init() end
function update(dt)
 if not job then job=fire.ai.request('Check','{}','SCHEMA') end
 if not done and fire.jobs.poll(job).done then
  local r=fire.jobs.result(job);invalid=r.ok or r.error_code~='result_too_large';done=true
 end
 fire.ui.screen('RESULT',invalid and 'BAD result' or done and 'Too large' or 'Pending')
end""".replace('SCHEMA',spec)
    measured=run(source)
    assert measured['jobs_started']['ai.request']==1
    assert any('Too large' in str(f['ops']) for f in measured['visual_frames'])
    assert not any('BAD result' in str(f['ops']) for f in measured['visual_frames'])
    with pytest.raises(RuntimeAIError,match='result_too_large'):result_data(json.dumps(dict.fromkeys(['a','b','c'],'x'*250)),schema)


@pytest.mark.parametrize('name',['analysis','quest'])
def test_real_examples_make_no_idle_calls_then_one_request_and_cache_repeated_trigger(name):
    source=(ROOT/'examples'/('runtime_ai_'+name+'.lua')).read_text(encoding='utf-8')
    idle=run(source)
    assert idle['jobs_started'].get('ai.request',0)==0
    options={'profile':'imu_flat','button_sequence':['A','A','A','B','B'],'interval_ms':1000} if name=='analysis' else {'button_sequence':['B','B'],'interval_ms':1000}
    options['max_runtime_ms']=5500 if name=='analysis' else 3000
    options['capture_at_ms']=[options['max_runtime_ms']]
    # Defaults are replaced explicitly to keep the actual fixture profile.
    request=dict(main_lua=source,api_version=SDK_VERSION,api_contract=SDK_CONTRACT,runtime_ai=EXTENSION,
        required_services=['display','buttons','ai','jobs','imu'],native_host_policy='fire-native-host-v1',profile='idle')
    request.update(options)
    result=simulate(request)
    assert result['jobs_started']['ai.request']==1
    texts=[op[3] for frame in result['visual_frames'] for op in frame['ops'] if op[0]=='text_style']
    assert any('AI: xxx' in text for text in texts)


@pytest.mark.parametrize('unavailable',['nil',"{x='bad',y=0,z=1}",'{x=0,y=0,z=0}'])
def test_analysis_missing_imu_keeps_local_fallback_and_does_not_invent_zero_measurement(unavailable):
    source=(ROOT/'examples/runtime_ai_analysis.lua').read_text(encoding='utf-8')
    # Source-local guard probe, not a new simulator fault-injection API.
    source=source.replace('local a=fire.imu.accel()','local a='+unavailable)
    request=dict(main_lua=source,api_version=SDK_VERSION,api_contract=SDK_CONTRACT,runtime_ai=EXTENSION,
        required_services=['display','buttons','ai','jobs','imu'],native_host_policy='fire-native-host-v1',
        profile='io_error',button_sequence=['B'],max_runtime_ms=3000,capture_at_ms=[3000])
    result=simulate(request)
    assert result['jobs_started'].get('ai.request',0)==0
    texts=[op[3] for frame in result['visual_frames'] for op in frame['ops'] if op[0]=='text_style']
    assert 'Ingen måling' in texts and not any(text=='0 g' for text in texts)

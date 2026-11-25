import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from fire_backend.ai import MockProvider,OpenAIProvider
from fire_backend.api_registry import preview_capabilities,package_compatibility
from fire_backend.app_sdk import SDK_VERSION,SDK_CONTRACT
from fire_backend.models import Capabilities,Manifest,DeviceEvent,SessionStart,DialogReply,GeneratedApp
from fire_backend.protocol import dispatch
from fire_backend.runtime_contract import EXTENSION,LIMITS,RuntimeAIError,request_data,result_data
from fire_backend.service import Backend
from test_device_protocol import configured

SCHEMA={'type':'object','properties':{'summary':{'type':'string','maxLength':40}},'required':['summary'],'additionalProperties':False}


class Fixture(MockProvider):
    def __init__(self,kind='analysis'):self.kind=kind;self.calls=0;self.wait=None;self.generations=0;self.requests=[]
    async def dialog(self,*args):return DialogReply(message='Manuell testapp.',clarification_needed=False,build_summary='Lag en test med Runtime AI uten lyd og RGB.')
    async def generate(self,*args):
        self.generations+=1
        return GeneratedApp(name='AI Analyse' if self.kind=='analysis' else 'AI Oppdrag',
            main_lua=(Path(__file__).parents[1]/'examples'/('runtime_ai_'+self.kind+'.lua')).read_text(encoding='utf-8'),
            required_services=['display','buttons','ai','jobs']+(['imu'] if self.kind=='analysis' else []),
            test_sequences=[{'name':'request-and-local','buttons':['A','A','A','B'] if self.kind=='analysis' else ['B','A','C'],
                             'interval_ms':1000 if self.kind=='analysis' else 500}])
    async def runtime_ai(self,*args):
        self.calls+=1
        self.requests.append(args)
        if self.wait:await self.wait.wait()
        schema=args[2]
        if 'vurdering' in schema.get('properties',{}):return '{"status":"normal","vurdering":"Stabilt utsnitt"}'
        if 'target' in schema.get('properties',{}):return '{"target":1,"label":"Finn felt 1"}'
        return '{"summary":"Kontrollert testresultat"}'


class Socket:
    def __init__(self):self.events=[]
    async def send_json(self,event):self.events.append(event)


async def built_and_started(tmp_path,kind='analysis'):
    provider=Fixture(kind);b=Backend(configured(tmp_path),provider)
    owner=next(iter(b.settings.device_tokens()))
    pc=await b.desktop_conversation(owner,hardware_preview=True)
    await b.text(pc,'Lag test med Runtime AI uten RGB og lyd.')
    assert pc.proposal_id
    await b.confirm_build(pc,pc.proposal_id);await pc.task
    saved=b.store.get('builds',pc.build_id)
    assert saved['status']=='ready',saved.get('error')
    package=b.store.get('packages',saved['package_id'])
    assert package['mode']=='mock' and package['validation']['runtime_ai_simulated']
    assert package['validation']['pre_delivery_review']['mode']=='mock_fixture'
    socket=Socket()
    s=await b.start(SessionStart(device_id=owner,target='device',protocol_version='0.2',boot_id='boot-runtime',
        project_id=pc.project_id,capabilities=Capabilities(**preview_capabilities())),socket=socket,principal=owner)
    event=DeviceEvent(device_id=owner,event='app_inventory',protocol_version='0.2',event_id='inventory-test',
        session_id=s.id,boot_id=s.boot_id,storage_ready=True,complete=True,apps=[{'app_id':package['manifest']['id'],
        'package_id':package['id'],'version':package['manifest']['version'],'checksum':package['manifest']['checksum']}])
    await dispatch(b,s,event)
    # Apps-list open intent uses normal explicit run_confirm, no forged install.
    run=await b.confirm_run(s,package['id'])
    assert b.device_record(s).get('active_run_id') is None
    ack=DeviceEvent(device_id=owner,event='app_started',protocol_version='0.2',event_id='started-test',session_id=s.id,
        boot_id=s.boot_id,run_id=run['run_id'],package_id=package['id'],source_sha256=package['manifest']['checksum'],
        diagnostics={'phase':'start','callback_us':60499})
    for event_id,checksum in [('missing-source',None),('wrong-source','0'*64)]:
        with pytest.raises(ValueError,match='checksum'):
            await dispatch(b,s,ack.model_copy(update={'event_id':event_id,'source_sha256':checksum}))
        record=b.device_record(s)
        assert record.get('active_run_id') is None and record.get('pending_run_id')==run['run_id']
        assert record['runtime_status']=='starting' and b.store.get('commands',run['run_id'])['status']=='pending'
    await dispatch(b,s,ack)
    assert b.device_record(s)['active_run_id']==run['run_id']
    return b,s,package,run,socket,provider


def event_for(s,p,run,request_id='runtime-test',**changes):
    values=dict(device_id=s.device_id,event='runtime_ai_request',protocol_version='0.2',event_id='event-'+request_id,
        request_id=request_id,app_id=p['manifest']['id'],package_id=p['id'],source_sha256=p['manifest']['checksum'],
        run_id=run['run_id'],boot_id=s.boot_id,session_id=s.id,instructions='Vurder data kort på norsk.',
        data_json='{"value":1}',schema_json=json.dumps(SCHEMA,separators=(',',':')),timeout_ms=1000)
    values.update(changes);return DeviceEvent(**values)


@pytest.mark.parametrize('kind',['analysis','quest'])
async def test_normal_fixture_build_apps_start_and_async_runtime_result(tmp_path,kind):
    b,s,p,run,socket,provider=await built_and_started(tmp_path,kind)
    try:
        source=(Path(__file__).parents[1]/'examples'/('runtime_ai_'+kind+'.lua')).read_text(encoding='utf-8')
        actual_schema=re.search(r"local schema='([^']+)'",source).group(1)
        instructions=re.search(r"fire.ai.request\('([^']+)'",source).group(1)
        data={'norm_g':1,'samples':16} if kind=='analysis' else {'position':2,'score':0}
        event=event_for(s,p,run,instructions=instructions,schema_json=actual_schema,data_json=json.dumps(data))
        await dispatch(b,s,event)
        task=b.runtime_ai.tasks[event.request_id]['task'];await task
        results=[r for r in socket.events if r.get('type')=='runtime_ai_result']
        parsed=json.loads(results[-1]['result_json'])
        assert results[-1]['state']=='completed'
        assert parsed==({'status':'normal','vurdering':'Stabilt utsnitt'} if kind=='analysis' else {'target':1,'label':'Finn felt 1'})
        assert provider.requests==[(instructions,data,json.loads(actual_schema))]
        from fire_backend.lua_worker import simulate
        measured=simulate({**p['manifest'],'main_lua':source,'profile':'imu_flat' if kind=='analysis' else 'idle',
            'button_sequence':['C','A','A','B'] if kind=='analysis' else ['B'],'interval_ms':1000,
            'max_runtime_ms':5500,'capture_at_ms':[5500],'native_host_policy':'fire-native-host-v1'})
        assert measured['jobs_started']['ai.request']==1
        drawn=[op[3] for frame in measured['visual_frames'] for op in frame['ops'] if op[0]=='text_style']
        assert any('AI: xxx' in text for text in drawn)
        assert results[-1]['source_sha256']==p['manifest']['checksum']
        await dispatch(b,s,event)
        assert provider.calls==1  # Event replay cannot buy another inference.
        record=b.store.get('runtime_ai',event.request_id)
        assert 'instructions' not in record and 'data_json' not in record and 'result_json' not in record
        assert p['manifest']['runtime_ai']==EXTENSION and p['validation']['physical_verified'] is False
    finally:await b.close()


@pytest.mark.parametrize('off',['global','app','stop','boot'])
async def test_pending_runtime_off_and_stale_results_are_not_delivered(tmp_path,off):
    b,s,p,run,socket,provider=await built_and_started(tmp_path)
    try:
        provider.wait=asyncio.Event();e=event_for(s,p,run);await dispatch(b,s,e);await asyncio.sleep(0)
        if off=='global':await b.runtime_ai.set_global_enabled(False)
        elif off=='app':await b.runtime_ai.set_app_enabled(p['project_id'],False)
        else:
            d=b.device_record(s)
            if off=='boot':d['boot_id']='boot-new'
            else:d.update(active_run_id=None,runtime_status='stopped')
            b.store.put('devices',s.device_id,d);provider.wait.set()
            await b.runtime_ai.tasks[e.request_id]['task']
        results=[r for r in socket.events if r.get('type')=='runtime_ai_result']
        if off in {'global','app'}:assert results[-1]['error_code']=='disabled' and not results[-1]['result_json']
        else:assert not results
        assert not b.runtime_ai.tasks
    finally:await b.close()


async def test_cancel_before_coroutine_start_is_terminal_and_does_not_call_provider(tmp_path):
    b,s,p,run,socket,provider=await built_and_started(tmp_path)
    try:
        e=event_for(s,p,run)
        # Admission directly, without dispatch's awaited acknowledgement.
        await b.runtime_ai.request(s,e);await b.runtime_ai.set_app_enabled(p['project_id'],False)
        assert provider.calls==0 and b.store.get('runtime_ai',e.request_id)['state']=='cancelled'
        assert not b.runtime_ai.tasks and socket.events[-1]['error_code']=='disabled'
    finally:await b.close()


@pytest.mark.parametrize('model,effort',[('gpt-6-luna','none'),('gpt-6.2-sol','low')])
async def test_same_openai_client_runtime_request_has_small_output_and_metering(tmp_path,model,effort):
    from fire_backend.usage import UsageLedger
    from fire_backend.storage import Store
    from fire_backend.security import Redactor
    settings=configured(tmp_path,openai_runtime_model=model,openai_api_key='offline-provider-fixture-key')
    provider=OpenAIProvider(settings);calls=[]
    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status='completed',output_text='{"summary":"OK"}',usage={'input_tokens':100,'output_tokens':20},id='response-runtime')
    provider.client=SimpleNamespace(responses=SimpleNamespace(create=create))
    provider.usage_ledger=UsageLedger(Store(tmp_path/'meter',Redactor(''),1000000),settings)
    assert await provider.runtime_ai('Vurder',{'value':1},SCHEMA)=='{"summary":"OK"}'
    assert calls[0]['reasoning']['effort']==effort and calls[0]['max_output_tokens']==1024
    assert calls[0]['store'] is False and 'tools' not in calls[0]
    records=provider.usage_ledger.snapshot()['recent']
    assert records[0]['operation']=='runtime_ai' and records[0]['price_kind']=='provider'


@pytest.mark.parametrize('schema',[
    {'type':'object','properties':{},'required':[{}],'additionalProperties':False},
    {'type':'object','properties':{},'required':[],'additionalProperties':True},
    {'type':'object','$ref':'https://bad.example/schema'},
    {'type':'object','properties':{'x':{'type':'integer','minimum':True}},'required':['x'],'additionalProperties':False},
    {'type':'object','properties':{'x':{'type':'string','enum':[1]}},'required':['x'],'additionalProperties':False},
])
def test_schema_is_rejected_before_provider(schema):
    with pytest.raises(RuntimeAIError):request_data('Vurder','{}',json.dumps(schema),1000)


@pytest.mark.parametrize('text',['{"summary":NaN}','{"summary":"a","summary":"b"}','{"extra":1}','{"summary":"'+('x'*41)+'"}'])
def test_results_are_strict_and_schema_validated(text):
    with pytest.raises(RuntimeAIError):result_data(text,SCHEMA)


def test_runtime_extension_requires_jobs_and_is_absent_from_old_non_ai_wire():
    caps=preview_capabilities();caps['services'].remove('jobs')
    with pytest.raises(ValueError):Capabilities(**caps)
    m=Manifest(id='old-app',name='App',version='0.1.1',required_services=['display'],permissions=['fire.display'],checksum='0'*64)
    assert 'runtime_ai' not in m.model_dump()
    caps=preview_capabilities();caps['services'].remove('ai');caps.pop('runtime_ai')
    assert 'runtime_ai' not in Capabilities(**caps).model_dump()
    assert package_compatibility({'manifest':{'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT,'runtime_ai':EXTENSION,'required_services':['display','ai','jobs']}},caps)


@pytest.mark.parametrize('kind',['app_failed','app_stopped'])
async def test_stale_stop_receipt_cannot_cancel_current_ai_run(tmp_path,kind):
    b,s,p,run,socket,provider=await built_and_started(tmp_path)
    try:
        provider.wait=asyncio.Event();e=event_for(s,p,run);await dispatch(b,s,e);await asyncio.sleep(0)
        fields={'error_code':'runtime_error'} if kind=='app_failed' else {'reason':'user_exit'}
        receipt=DeviceEvent(device_id=s.device_id,event=kind,protocol_version='0.2',event_id='stale-receipt',
            session_id=s.id,boot_id=s.boot_id,run_id='run-stale',package_id=p['id'],**fields)
        with pytest.raises(ValueError):await dispatch(b,s,receipt)
        assert e.request_id in b.runtime_ai.tasks and not b.runtime_ai.tasks[e.request_id]['task'].done()
        await dispatch(b,s,receipt.model_copy(update={'event_id':'valid-receipt','run_id':run['run_id']}))
        assert not b.runtime_ai.tasks
        assert not [r for r in socket.events if r.get('type')=='runtime_ai_result' and r['state']=='completed']
    finally:await b.close()


@pytest.mark.parametrize('failure',['timeout','budget'])
async def test_runtime_timeout_and_cost_admission_keep_local_run_alive(tmp_path,failure):
    b,s,p,run,socket,provider=await built_and_started(tmp_path)
    try:
        if failure=='timeout':provider.wait=asyncio.Event()
        else:
            from pydantic import SecretStr
            b.settings.openai_api_key=SecretStr('offline-test-key')
            b.settings.fire_runtime_ai_limits_enabled=True;b.settings.fire_runtime_ai_request_budget_usd=1e-10
            model=OpenAIProvider(b.settings);model.usage_ledger=b.usage
            async def forbidden(**kwargs):raise AssertionError('Budget must reject before provider')
            model.client=SimpleNamespace(responses=SimpleNamespace(create=forbidden));b.provider=model
        e=event_for(s,p,run);await dispatch(b,s,e);await b.runtime_ai.tasks[e.request_id]['task']
        result=[r for r in socket.events if r.get('type')=='runtime_ai_result'][-1]
        assert result['error_code']==('timeout' if failure=='timeout' else 'budget_exceeded')
        assert b.device_record(s)['active_run_id']==run['run_id'] and not b.runtime_ai.tasks
        if failure=='budget':b.provider=provider  # Test SDK stub has no close method.
    finally:await b.close()


@pytest.mark.parametrize('mode,capability',[('off',True),('auto',False)])
async def test_confirmed_ai_request_stops_clearly_before_generation_when_off_or_unavailable(tmp_path,mode,capability):
    provider=Fixture();b=Backend(configured(tmp_path),provider)
    try:
        s=await b.desktop_conversation(next(iter(b.settings.device_tokens())),hardware_preview=True,runtime_ai_mode=mode)
        if not capability:s.capabilities.pop('runtime_ai');s.capabilities['services'].remove('ai')
        await b.text(s,'Bruk Runtime AI til måleanalyse.')
        assert s.proposal_id
        await b.confirm_build(s,s.proposal_id);await s.task
        row=b.store.get('builds',s.build_id)
        assert row['status']=='failed' and provider.generations==0 and not b.store.list('packages')
        assert row['error_code'] in {'runtime_ai_disabled','runtime_ai_unavailable'}
    finally:await b.close()


async def test_actual_generation_and_review_requests_include_bounded_schema_example(tmp_path):
    from fire_backend.app_quality import FireAppReview
    from fire_backend.runtime_contract import REGISTRY,GENERATION_MARKER
    from test_pre_delivery import approve
    calls=[]
    generated=GeneratedApp(name='AI Analyse',main_lua='function init() end function update(dt) fire.ui.screen("TEST") end',required_services=['display','ai','jobs'])
    async def parsed(**request):
        calls.append(request)
        return SimpleNamespace(status='completed',output_parsed=generated if request['text_format'] is GeneratedApp else FireAppReview(**approve().model_dump(),kind='app',**{k:True for k in FireAppReview.fire_checks()}))
    b=Backend(configured(tmp_path),Fixture())
    provider=OpenAIProvider(configured(tmp_path,openai_api_key='offline-request-test-key'))
    provider.client=SimpleNamespace(responses=SimpleNamespace(parse=parsed))
    try:
        session=await b.desktop_conversation(next(iter(b.settings.device_tokens())),hardware_preview=True)
        session.build_summary='Bruk Runtime AI til måleanalyse.'
        context=b.context_for(session)
        await provider.generate(session.build_summary,context)
        await provider.review(session.build_summary,context,generated,{'negotiated_contract':{'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT}})
        assert len(calls)==2
        for call in calls:
            content=call['input'][0]['content']
            sent=content if isinstance(content,str) else '\n'.join(block.get('text','') for block in content)
            facts=json.JSONDecoder().raw_decode(sent.split(GENERATION_MARKER,1)[1])[0]
            assert facts['schema_semantics']==REGISTRY['semantics']['schema']
            assert 'maxLength' in facts['schema_bounds'] and 'maxItems' in facts['schema_bounds']
            example=facts['request_example']
            data,schema=request_data(example['instructions'],example['data_json'],example['schema_json'],30000)
            assert data=={'norm_g':1,'samples':16} and set(schema['properties'])=={'status','vurdering'}
            assert 'escaped JSON strings' in sent and 'never every frame or blind retry' in sent
    finally:await b.close()

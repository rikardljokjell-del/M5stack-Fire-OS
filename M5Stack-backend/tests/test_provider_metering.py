"""Real SDK request/usage parsing through MockTransport: never a paid API call."""
import asyncio
import base64
import io
import json
import wave
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI, RateLimitError

from fire_backend.ai import OpenAIProvider
from fire_backend.config import Settings
from fire_backend.metering import usage_scope
from fire_backend.security import Redactor
from fire_backend.storage import Store
from fire_backend.usage import UsageLedger, UsageBudgetError


def provider(tmp_path, handle=None, **config):
    config.setdefault('fire_cost_limits_enabled',True)
    config.setdefault('fire_output_limits_enabled',True)
    settings=Settings(_env_file=None,openai_api_key='sk-metering-private-test',**config)
    result=OpenAIProvider(settings)
    result.usage_ledger=UsageLedger(Store(tmp_path,Redactor('sk-metering-private-test'),10_000_000),settings)
    if handle:
        result.client=AsyncOpenAI(api_key='sk-metering-private-test',max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    return result


def generated(usage):
    return {'id':'resp_metered','created_at':1,'object':'response','status':'completed',
        'model':'gpt-6.2-sol','parallel_tool_calls':False,'tool_choice':'auto','tools':[],
        'usage':usage,'output':[{'id':'msg_metered','type':'message','status':'completed','role':'assistant',
            'content':[{'type':'output_text','annotations':[],'text':json.dumps({
                'name':'Prøve','main_lua':'function init() end function update(dt) end','required_services':[]})}]}]}


@pytest.mark.parametrize('model', ['gpt-6-luna', 'gpt-5.6-luna', 'gpt-6.1-terra', 'gpt-6.2-sol', 'gpt-6.1-sol', 'gpt-6.2-astra'])
async def test_real_sdk_records_returned_usage_cache_and_attribution(tmp_path, model):
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(200,headers={'x-request-id':'req_metered'},json=generated({
            'input_tokens':1000,'output_tokens':200,'total_tokens':1200,
            'input_tokens_details':{'cached_tokens':700,'cache_write_tokens':200},'output_tokens_details':{'reasoning_tokens':150}}))
    p=provider(tmp_path,handle,openai_code_model=model,fire_request_budget_usd=1,fire_build_budget_usd=2)
    token=usage_scope.set({'build_id':'build-one','project_id':'app-one'})
    try:
        await p.generate('Lag en sirkel','FIRE context')
        row=p.usage_ledger.snapshot()['recent'][0]
        assert row['input_tokens']==1000 and row['output_tokens']==200 and row['cached_tokens']==700
        from fire_backend.model_catalog import PRICES
        price=PRICES[model]
        assert row['estimated_usd']==pytest.approx((100*price.text_in+700*price.text_cache+200*price.text_in*1.25+200*price.text_out)/1e6)
        assert row['cache_write_tokens']==200 and row['cache_write_ttl']=='30m'
        assert row['build_id']=='build-one' and row['project_id']=='app-one'
        assert row['request_id']=='req_metered' and row['usage_source']=='provider'
        assert len(calls)==1
        body=json.loads(calls[0].content)
        assert body['model']==row['model']==model
        assert body['prompt_cache_options']=={'mode':'explicit','ttl':'30m'}
        assert body['input'][0]['content'][0]['prompt_cache_breakpoint']=={'mode':'explicit'}
        assert body['reasoning']=={'effort':'low'}
        assert 'sk-metering-private-test' not in p.usage_ledger.store.path('usage',row['id']).read_text()
    finally:
        usage_scope.reset(token);await p.close()


async def test_budget_failure_is_before_any_http_request(tmp_path):
    calls=[]
    def handle(request):calls.append(request);raise AssertionError('No request should be made')
    p=provider(tmp_path,handle,fire_request_budget_usd=.001)
    try:
        with pytest.raises(UsageBudgetError):await p.generate('Lag en sirkel','context')
        assert not calls and not p.usage_ledger.records()
    finally:await p.close()


async def test_real_sdk_failed_request_retains_reservation_and_no_error_body(tmp_path):
    def handle(request):
        return httpx.Response(429,json={'error':{'message':'private provider response','type':'insufficient_quota','code':'credit_balance_exhausted'}})
    p=provider(tmp_path,handle)
    try:
        with pytest.raises(RateLimitError):await p.generate('Lag en sirkel','context')
        row=p.usage_ledger.snapshot()['recent'][0]
        assert row['status']=='failed' and row['estimated_usd']>0 and row['usage_source']=='reservation'
        assert 'private provider response' not in p.usage_ledger.store.path('usage',row['id']).read_text()
    finally:await p.close()


async def test_transcription_records_duration_without_fabricated_tokens(tmp_path):
    calls=[]
    def handle(request):
        calls.append(request);return httpx.Response(200,json={'text':'Lag en sirkel','usage':{'type':'duration','seconds':3}})
    p=provider(tmp_path,handle)
    data=io.BytesIO()
    with wave.open(data,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(3*16000*2))
    try:
        assert await p.transcribe(data.getvalue())=='Lag en sirkel'
        row=p.usage_ledger.snapshot()['recent'][0]
        assert row['operation']=='transcribe' and row['audio_seconds']==3
        assert row['estimated_usd']==pytest.approx(3/60*.0045) and row['usage_source']=='duration'
        assert row['input_tokens']==row['output_tokens']==0 and len(calls)==1
    finally:await p.close()


class Realtime:
    def __init__(self,events):
        self.events=events;self.calls=[]
        self.response=SimpleNamespace(create=self.create)
        self.session=SimpleNamespace(update=self.update)
        self.conversation=SimpleNamespace(item=SimpleNamespace(create=self.create))
    async def create(self,**kw):self.calls.append(kw)
    async def update(self,**kw):self.calls.append(kw)
    def __aiter__(self):
        async def events():
            for event in self.events:
                yield event
                await asyncio.sleep(0)
        return events()


async def test_realtime_dialog_usage_is_measured_after_response_done(tmp_path):
    events=[SimpleNamespace(type='response.function_call_arguments.done',name='dialog_reply',arguments=json.dumps({
        'message':'Hei','build_summary':'','clarification_needed':False})),
        SimpleNamespace(type='response.done',response=SimpleNamespace(id='resp_dialog',status='completed',usage={
            'input_tokens':1000,'output_tokens':100,'input_token_details':{'cached_tokens':600,'text_tokens':1000,'audio_tokens':0},
            'output_token_details':{'text_tokens':100,'audio_tokens':0}}))]
    p=provider(tmp_path)
    try:
        assert (await p.dialog([{'role':'user','content':'Hei'}],'conversation_mode=chat',Realtime(events))).message=='Hei'
        row=p.usage_ledger.snapshot()['recent'][0]
        assert row['operation']=='dialog' and row['status']=='completed' and row['usage_source']=='provider'
        assert row['estimated_usd']==pytest.approx((400*.6+600*.06+100*2.4)/1e6)
    finally:await p.close()


async def test_cancelling_speech_before_usage_keeps_unknown_cost(tmp_path):
    connection=Realtime([SimpleNamespace(type='response.output_audio.delta',delta=base64.b64encode(bytes(480)).decode())])
    class Manager:
        async def __aenter__(self):return connection
        async def __aexit__(self,*args):pass
    p=provider(tmp_path)
    p.client=SimpleNamespace(realtime=SimpleNamespace(connect=lambda **kw:Manager()))
    clip=p.speech('Hei')
    assert await anext(clip)==bytes(480)
    await clip.aclose()
    row=p.usage_ledger.snapshot()['recent'][0]
    assert row['operation']=='speech' and row['status']=='cancelled'
    assert row['estimated_usd']>0 and row['usage_source']=='reservation'


async def test_context_attribution_is_task_local_for_parallel_requests(tmp_path):
    async def handle(request):
        await asyncio.sleep(.01)
        return httpx.Response(200,json=generated({'input_tokens':100,'output_tokens':50,'total_tokens':150}))
    p=provider(tmp_path,handle)
    async def one(build):
        token=usage_scope.set({'build_id':build,'project_id':'app-'+build})
        try:await p.generate('Lag en sirkel','context')
        finally:usage_scope.reset(token)
    try:
        await asyncio.gather(one('one'),one('two'))
        assert {(r['build_id'],r['project_id']) for r in p.usage_ledger.records()}=={('one','app-one'),('two','app-two')}
        assert usage_scope.get()=={}
    finally:await p.close()

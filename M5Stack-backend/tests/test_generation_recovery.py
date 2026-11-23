"""Real SDK with local HTTP fixtures: no paid API requests."""
import asyncio
import json

import httpx
import pytest

from fire_backend.generation_errors import GenerationResponseError
from fire_backend.metering import usage_scope
from fire_backend.usage import UsageBudgetError
from test_provider_metering import provider, generated


def truncated(limit,partial=False):
    result=generated({'input_tokens':1000,'output_tokens':limit,'total_tokens':1000+limit,
        'output_tokens_details':{'reasoning_tokens':limit if not partial else 1000}})
    result.update(status='incomplete',incomplete_details={'reason':'max_output_tokens'})
    if partial:result['output'][0]['content'][0]['text']='{"name":"Spill","main_lua":"function '
    else:result['output']=[]
    return result


@pytest.mark.parametrize('partial',[False,True])
async def test_token_exhaustion_recovers_once_and_keeps_actual_cost_and_diagnosis(tmp_path,partial):
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        return httpx.Response(200,json=truncated(body['max_output_tokens'],partial) if len(requests)==1 else
            generated({'input_tokens':1000,'output_tokens':500,'total_tokens':1500}))
    p=provider(tmp_path,handle)
    token=usage_scope.set({'build_id':'build-recovered','project_id':'app-rpg'})
    try:
        app=await p.generate('Lag et RPG-spill','device API')
        assert app.name=='Prøve' and len(requests)==2
        assert requests[0]['reasoning']=={'effort':'low'}
        assert requests[0]['max_output_tokens']==24000
        assert requests[1]['reasoning']=={'effort':'none'}
        assert requests[1]['max_output_tokens']==48000
        rows=sorted(p.usage_ledger.records(),key=lambda r:r['started_at'])
        assert rows[0]['status']=='failed' and rows[0]['failure_code']=='ai_output_limit'
        assert rows[0]['provider_status']=='incomplete' and rows[0]['incomplete_reason']=='max_output_tokens'
        assert rows[0]['output_tokens']==24000 and rows[0]['usage_source']=='provider'
        assert rows[0]['estimated_usd']==pytest.approx(.0121)
        assert rows[1]['status']=='completed' and rows[1]['failure_code']==''
        assert all(r['model']=='gpt-6-luna' and r['build_id']=='build-recovered' for r in rows)
    finally:usage_scope.reset(token);await p.close()


async def test_repeated_token_limit_is_bounded_and_never_returns_partial_app(tmp_path):
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        return httpx.Response(200,json=truncated(body['max_output_tokens'],True))
    p=provider(tmp_path,handle)
    try:
        with pytest.raises(GenerationResponseError,match='48000') as error:
            await p.generate('RPG','device API')
        assert error.value.code=='ai_output_limit'
        assert len(requests)==2 and len(p.usage_ledger.records())==2
        assert all(r['status']=='failed' for r in p.usage_ledger.records())
    finally:await p.close()


@pytest.mark.parametrize('kind',['refusal','filter','invalid'])
async def test_refusal_filter_and_invalid_json_are_distinguished_without_body_logs(tmp_path,kind):
    requests=[]
    def handle(request):
        requests.append(request)
        result=generated({'input_tokens':100,'output_tokens':10,'total_tokens':110})
        if kind=='refusal':result['output'][0]['content']=[{'type':'refusal','refusal':'PRIVATE_PROVIDER_TEXT'}]
        elif kind=='filter':result.update(status='incomplete',incomplete_details={'reason':'content_filter'},output=[])
        else:result['output'][0]['content'][0]['text']='PRIVATE_PROVIDER_TEXT invalid JSON'
        return httpx.Response(200,json=result)
    p=provider(tmp_path,handle)
    try:
        with pytest.raises(GenerationResponseError) as error:await p.generate('RPG','device API')
        assert error.value.code==('ai_invalid_response' if kind=='invalid' else 'ai_refused')
        assert len(requests)==(2 if kind=='invalid' else 1)
        assert 'PRIVATE_PROVIDER_TEXT' not in str(error.value)
        assert all('PRIVATE_PROVIDER_TEXT' not in path.read_text(encoding='utf-8') for path in tmp_path.rglob('*.json'))
        row=p.usage_ledger.records()[0]
        assert row['status']=='failed' and row['usage_source']=='provider' and row['output_tokens']==10
    finally:await p.close()


async def test_schema_error_has_one_corrective_attempt_without_doubling_token_cap(tmp_path):
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        result=generated({'input_tokens':1000,'output_tokens':100,'total_tokens':1100})
        if len(requests)==1:result['output'][0]['content'][0]['text']='{"name":"App"}'
        return httpx.Response(200,json=result)
    p=provider(tmp_path,handle)
    try:
        app=await p.generate('Lag en app','device API')
        assert app.name=='Prøve' and len(requests)==2
        assert requests[0]['max_output_tokens']==requests[1]['max_output_tokens']==24000
        assert 'previous response did not satisfy' in requests[1]['input'][-1]['content']
        assert any(r['failure_code']=='ai_invalid_response' for r in p.usage_ledger.records())
    finally:await p.close()


async def test_namespaced_service_candidate_is_fixed_without_an_extra_paid_request(tmp_path):
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        schema=body['text']['format']['schema']
        from fire_backend.api_registry import ALL_SERVICES
        assert set(schema['properties']['required_services']['items']['enum'])==ALL_SERVICES
        result=generated({'input_tokens':1000,'output_tokens':100,'total_tokens':1100})
        candidate=json.loads(result['output'][0]['content'][0]['text'])
        candidate['required_services']=['fire.display']
        result['output'][0]['content'][0]['text']=json.dumps(candidate)
        return httpx.Response(200,json=result)
    p=provider(tmp_path,handle)
    try:
        app=await p.generate('Blå skjerm','device API')
        assert app.required_services==['display'] and len(requests)==1
    finally:await p.close()


@pytest.mark.parametrize('services',[['fire.gps'],['display','fire.display'],['fire.wifi.invalid']])
def test_candidate_spelling_fix_cannot_grant_unknown_or_duplicate_services(services):
    from fire_backend.models import GeneratedApp,Capabilities
    with pytest.raises(ValueError):GeneratedApp(name='Test',main_lua='function init() end',required_services=services)
    with pytest.raises(ValueError):Capabilities(services=['fire.display'],max_memory=131072,max_runtime_ms=0)


async def test_adaptive_recovery_still_respects_user_spending_limit(tmp_path):
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        return httpx.Response(200,json=truncated(body['max_output_tokens']))
    p=provider(tmp_path,handle,fire_build_budget_usd=.03)
    token=usage_scope.set({'build_id':'build-limited','project_id':'app-rpg'})
    try:
        with pytest.raises(UsageBudgetError):await p.generate('RPG','device API')
        assert len(requests)==1  # Second reserve is rejected BEFORE network.
        assert len(p.usage_ledger.records())==1
        assert p.usage_ledger.records()[0]['failure_code']=='ai_output_limit'
    finally:usage_scope.reset(token);await p.close()


async def test_cancelling_adaptive_retry_retains_reservation_and_does_not_retry_again(tmp_path):
    requests=[];entered=asyncio.Event()
    async def handle(request):
        body=json.loads(request.content);requests.append(body)
        if len(requests)==1:return httpx.Response(200,json=truncated(body['max_output_tokens']))
        entered.set();await asyncio.Event().wait()
    p=provider(tmp_path,handle)
    try:
        task=asyncio.create_task(p.generate('RPG','device API'));await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert len(requests)==2
        cancelled=next(r for r in p.usage_ledger.records() if r['status']=='cancelled')
        assert cancelled['estimated_usd']>0 and cancelled['usage_source']=='reservation'
    finally:await p.close()

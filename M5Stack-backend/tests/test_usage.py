from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.security import Redactor
from fire_backend.storage import Store
from fire_backend.usage import UsageLedger, UsageBudgetError
from test_device_protocol import ADMIN, configured, headers


def ledger(tmp_path, clock=None, **limits):
    store=Store(tmp_path, Redactor('sk-secret-ledger-check'), 10_000_000)
    settings=SimpleNamespace(fire_request_budget_usd=.25, fire_daily_budget_usd=2, fire_build_budget_usd=.60)
    for key, value in limits.items():setattr(settings, key, value)
    return UsageLedger(store, settings, **({'clock':clock} if clock else {}))


def test_actual_tokens_cache_and_reasoning_are_not_double_charged(tmp_path):
    meter=ledger(tmp_path)
    item=meter.begin('generate','gpt-6.2-sol',10000,2000,build_id='build-one',project_id='app-one')
    result=meter.finish(item, {'input_tokens':10000,'output_tokens':2000,
        'input_tokens_details':{'cached_tokens':8000},'output_tokens_details':{'reasoning_tokens':1500}},request_id='resp_example')
    assert result['estimated_usd']==pytest.approx(.004+.0008+.02)
    assert result['reasoning_tokens']==1500 and result['usage_source']=='provider'
    summary=meter.snapshot()
    assert summary['since_reset']['requests']==1 and summary['by_operation'][0]['operation']=='generate'
    assert summary['by_model'][0]['model']=='gpt-6.2-sol'
    assert summary['by_build'][0]['project_id']=='app-one'
    assert meter.finish(item,None,status='failed')==result  # duplicate callback does not alter cost


def test_realtime_text_audio_and_modality_cache_are_accounted_once(tmp_path):
    meter=ledger(tmp_path)
    item=meter.begin('speech','gpt-realtime-2.1-mini',1000,1000,input_audio_tokens=500,max_output_audio_tokens=1000)
    result=meter.finish(item, {'input_tokens':1500,'output_tokens':1000,
        'input_token_details':{'text_tokens':1000,'audio_tokens':500,'cached_tokens':900,
                               'cached_tokens_details':{'text_tokens':700,'audio_tokens':200}},
        'output_token_details':{'text_tokens':100,'audio_tokens':900}})
    assert result['input_tokens']==1500 and result['output_tokens']==1000
    assert result['cached_tokens']==900
    assert result['estimated_usd']==pytest.approx((300*.60+700*.06+300*10+200*.30+100*2.40+900*20)/1e6)


def test_duration_priced_transcription_does_not_invent_token_usage(tmp_path):
    meter=ledger(tmp_path)
    item=meter.begin('transcribe','gpt-transcribe',0,0,audio_seconds=20)
    result=meter.finish(item,None,duration_seconds=20)
    assert result['usage_source']=='duration' and result['estimated_usd']==pytest.approx(.0015)
    assert result['input_tokens']==result['output_tokens']==0


def test_unreported_failed_cancelled_and_restarted_requests_keep_cost_reservation(tmp_path):
    now=[1000.]
    meter=ledger(tmp_path,lambda:now[0])
    first=meter.begin('generate','gpt-6.2-sol',1000,1000)
    pending=meter.begin('review','gpt-6.2-sol',2000,1000)
    result=meter.finish(first,None,status='cancelled')
    assert result['estimated_usd']>0 and result['usage_source']=='reservation'
    now[0]+=1
    restarted=ledger(tmp_path,lambda:now[0])
    recovered=restarted.store.get('usage',pending)
    assert recovered['status']=='unknown' and recovered['estimated_usd']>0
    assert restarted.snapshot()['lifetime']['unknown_usage_requests']==2
    # Invalid partial provider usage must not turn an unknown bill into zero.
    item=restarted.begin('dialog','gpt-realtime-2.1-mini',1000,100)
    assert restarted.finish(item,{'input_tokens':None,'output_tokens':None})['estimated_usd']>0


def test_reset_resets_display_only_and_inflight_completion_still_appears(tmp_path):
    now=[1000.]
    meter=ledger(tmp_path,lambda:now[0])
    completed=meter.begin('generate','gpt-6.2-sol',1000,1000,build_id='build-one')
    meter.finish(completed,{'input_tokens':1000,'output_tokens':1000})
    pending=meter.begin('review','gpt-6.2-sol',1000,1000,build_id='build-one')
    now[0]+=1
    assert meter.reset()['since_reset']['requests']==0
    assert meter.snapshot()['today']['requests']==2
    assert len(meter.records())==2
    now[0]+=1
    meter.finish(pending,{'input_tokens':1000,'output_tokens':1000})
    result=meter.snapshot()
    assert result['since_reset']['requests']==1 and result['today']['requests']==2
    restored=ledger(tmp_path,lambda:now[0])
    assert restored.snapshot()['since_reset']['requests']==1


def test_daily_per_request_build_limits_and_unknown_prices_stop_before_spend(tmp_path):
    meter=ledger(tmp_path,fire_request_budget_usd=.02,fire_build_budget_usd=.02,fire_daily_budget_usd=.03)
    with pytest.raises(UsageBudgetError):meter.begin('generate','gpt-6.2-astra',10000,2000)
    first=meter.begin('generate','gpt-6.2-sol',1000,1000,build_id='build-one')
    with pytest.raises(UsageBudgetError,match='Byggets'):meter.begin('review','gpt-6.2-sol',1000,1000,build_id='build-one')
    second=meter.begin('review','gpt-6.2-sol',1000,1000,build_id='build-two')
    meter.reset()
    with pytest.raises(UsageBudgetError,match='Dagens'):meter.begin('review','gpt-6.2-sol',1000,1000,build_id='build-three')
    with pytest.raises(UsageBudgetError,match='prisgrunnlag'):meter.begin('dialog','unknown-model',10,10)
    assert len(meter.records())==2


def test_cache_write_ttl_costs_replace_ordinary_input_instead_of_double_charging(tmp_path):
    meter=ledger(tmp_path)
    item=meter.begin('generate','gpt-6.2-sol',12000,2000)
    row=meter.finish(item,{'input_tokens':12000,'output_tokens':2000,
        'input_tokens_details':{'cached_tokens':4000,'cache_write_tokens':7000,
            'cache_write_tokens_details':{'ttl_30m_tokens':3000,'ttl_12h_tokens':4000}}})
    assert row['estimated_usd']==pytest.approx((1000*2+4000*.1+3000*2*1.25+4000*2*2.5+2000*10)/1e6)
    assert row['cache_write_tokens']==7000 and row['cache_write_split_known']
    assert meter.snapshot()['since_reset']['cache_write_tokens']==7000


def test_upfront_cache_write_reservation_and_known_request_ttl(tmp_path):
    meter=ledger(tmp_path)
    item=meter.begin('review','gpt-6.2-sol',10000,1000)
    pending=meter.store.get('usage',item)
    assert pending['reserved_usd']==pytest.approx((10000*2*1.25+1000*10)/1e6)
    row=meter.finish(item,{'input_tokens':10000,'output_tokens':1000,
        'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':10000}})
    assert row['estimated_usd']==pytest.approx((10000*2*1.25+1000*10)/1e6)
    assert row['cache_write_split_known'] is True and row['cache_write_ttl']=='30m'
    # Inconsistent split is unknown usage; preserve reservation rather than zero.
    item=meter.begin('review','gpt-6.2-sol',1000,1000)
    row=meter.finish(item,{'input_tokens':1000,'output_tokens':1000,
        'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':500,
            'cache_write_tokens_details':{'ttl_30m_tokens':10,'ttl_12h_tokens':0}}})
    assert row['usage_source']=='reservation' and row['estimated_usd']>0


def test_unknown_cache_write_ttl_stays_conservatively_priced(tmp_path):
    meter=ledger(tmp_path)
    item=meter.begin('review','gpt-6.1-sol',10000,1000)
    # Historical/custom records without a request TTL remain conservative,
    # even though new picker requests now explicitly select 30m retention.
    pending=meter.store.get('usage',item)
    pending['cache_write_ttl']=None
    meter.store.put('usage',item,pending)
    row=meter.finish(item,{'input_tokens':10000,'output_tokens':1000,
        'input_tokens_details':{'cached_tokens':0,'cache_write_tokens':10000}})
    assert row['estimated_usd']==pytest.approx((10000*2*2.5+1000*10)/1e6)
    assert row['cache_write_split_known'] is False


def test_sensitive_strings_cannot_become_ledger_metadata(tmp_path):
    meter=ledger(tmp_path)
    item=meter.begin('generate','gpt-6.2-sol',100,100,build_id='secret with spaces',project_id='https://private.invalid')
    meter.finish(item,{'input_tokens':100,'output_tokens':100},request_id='Bearer sk-secret-ledger-check')
    data=meter.store.path('usage',item).read_text(encoding='utf-8')
    assert 'secret with spaces' not in data and 'private.invalid' not in data and 'Bearer' not in data


def test_usage_endpoints_are_local_admin_only_and_reset_keeps_budget_history(tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as client:
        service=client.app.state.backend
        item=service.usage.begin('generate','gpt-6.2-sol',100,100)
        service.usage.finish(item,{'input_tokens':100,'output_tokens':100})
        assert client.get('/desktop/usage',headers=headers()).status_code==403
        assert client.post('/desktop/usage/reset',headers=headers()).status_code==403
        assert client.get('/desktop/usage',headers={**headers(ADMIN),'Origin':'https://external.invalid'}).status_code==403
        result=client.get('/desktop/usage',headers=headers(ADMIN))
        assert result.status_code==200 and result.json()['since_reset']['requests']==1
        reset=client.post('/desktop/usage/reset',headers=headers(ADMIN),json={})
        assert reset.status_code==200 and reset.json()['since_reset']['requests']==0
        assert reset.json()['today']['requests']==1
        assert client.post('/desktop/usage/reset',headers=headers(ADMIN),json={'unknown':True}).status_code==422

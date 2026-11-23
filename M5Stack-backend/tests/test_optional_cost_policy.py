import json
from types import SimpleNamespace

import httpx
import pytest

from fire_backend.config import Settings
from fire_backend.desktop_config import DesktopConfig,DesktopStore,COST_PROFILE_VERSION
from fire_backend.usage import UsageBudgetError
from test_desktop import MemoryVault
from test_provider_metering import provider,generated,Realtime
from test_usage import ledger


def test_defaults_are_zero_and_optional_caps_are_off():
    for config in (Settings(_env_file=None),DesktopConfig()):
        prefix='fire_' if isinstance(config,Settings) else ''
        for key in ('daily_budget_usd','build_budget_usd','request_budget_usd','max_corrections'):
            assert getattr(config,prefix+key)==0
        assert not getattr(config,prefix+'cost_limits_enabled')
        assert not getattr(config,prefix+'output_limits_enabled')


@pytest.mark.parametrize('key',['fire_daily_budget_usd','fire_build_budget_usd','fire_request_budget_usd'])
def test_zero_is_unlimited_independently_when_other_limits_are_enabled(tmp_path,key):
    limits=dict(fire_daily_budget_usd=100,fire_build_budget_usd=100,fire_request_budget_usd=100)
    limits[key]=0
    meter=ledger(tmp_path,**limits)
    item=meter.begin('generate','gpt-6.2-astra',20000,100000,build_id='build-zero')
    assert item and meter.settings.fire_cost_limits_enabled


def test_disabled_money_caps_do_not_block_and_reenabling_honors_lifetime_day_history(tmp_path):
    meter=ledger(tmp_path,fire_cost_limits_enabled=False,fire_request_budget_usd=.0001,fire_daily_budget_usd=.0001)
    item=meter.begin('generate','gpt-6-luna',1000,128000,build_id='build-off')
    meter.finish(item,{'input_tokens':1000,'output_tokens':1000})
    assert meter.snapshot()['limits']['daily_remaining_usd'] is None
    assert not meter.snapshot()['limits']['enabled']
    meter.reset()
    meter.settings.fire_cost_limits_enabled=True
    meter.settings.fire_request_budget_usd=0
    with pytest.raises(UsageBudgetError,match='Dagens'):meter.begin('generate','gpt-6-luna',1,1)


async def test_default_uncapped_request_has_no_backend_token_field_but_usage_is_recorded(tmp_path):
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append(body)
        return httpx.Response(200,json=generated({'input_tokens':500,'output_tokens':9000,'total_tokens':9500}))
    p=provider(tmp_path,handle,fire_cost_limits_enabled=False,fire_output_limits_enabled=False,
               fire_request_budget_usd=.00001)
    try:
        await p.generate('Lag et spill','context')
        assert len(requests)==1 and 'max_output_tokens' not in requests[0]
        assert requests[0]['reasoning']=={'effort':'low'}
        row=p.usage_ledger.records()[0]
        assert row['max_output_tokens'] is None and row['output_tokens']==9000
        assert row['estimated_usd']==pytest.approx(.00455) and row['usage_source']=='provider'
    finally:await p.close()


async def test_uncapped_realtime_dialog_uses_model_capacity_not_800_tokens(tmp_path):
    events=[SimpleNamespace(type='response.function_call_arguments.done',name='dialog_reply',arguments=json.dumps({
        'message':'Hei','build_summary':'','clarification_needed':False})),
        SimpleNamespace(type='response.done',response=SimpleNamespace(id='resp_uncapped',status='completed',usage={
            'input_tokens':100,'output_tokens':10}))]
    connection=Realtime(events)
    p=provider(tmp_path,fire_cost_limits_enabled=False,fire_output_limits_enabled=False)
    try:
        assert (await p.dialog([],'conversation_mode=chat',connection)).message=='Hei'
        assert connection.calls[0]['response']['max_output_tokens']=='inf'
    finally:await p.close()


def test_profile_migration_zeroes_limits_once_preserving_model_network_and_secrets(tmp_path):
    store=DesktopStore(tmp_path,MemoryVault());store.save(store.config,api_key='sk-private-migration-value')
    secrets=dict(store.vault.values)
    raw=store.config.model_dump();raw.pop('cost_limits_enabled');raw.pop('output_limits_enabled')
    raw.update(cost_profile_version=2,code_model='gpt-6.2-sol',review_model='gpt-6.1-terra',
        daily_budget_usd=5,build_budget_usd=.6,request_budget_usd=.25,max_corrections=1,port=8877)
    store.path.write_text(json.dumps(raw),encoding='utf-8')
    restored=DesktopStore(tmp_path,store.vault)
    assert restored.migrate_cost_profile()
    assert restored.config.cost_profile_version==COST_PROFILE_VERSION
    assert restored.config.code_model=='gpt-6.2-sol' and restored.config.review_model=='gpt-6.1-terra'
    assert restored.config.port==8877 and restored.vault.values==secrets
    for name in ('daily_budget_usd','build_budget_usd','request_budget_usd','max_corrections'):
        assert getattr(restored.config,name)==0
    restored.save(restored.config.model_copy(update={'cost_limits_enabled':True,'build_budget_usd':.2,'max_corrections':5}))
    assert not restored.migrate_cost_profile()
    assert restored.settings().fire_build_budget_usd==.2 and restored.settings().fire_max_corrections==5

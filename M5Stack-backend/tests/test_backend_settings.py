import copy
import pytest
from fire_backend.desktop_config import DesktopStore
from fire_backend.service import Backend
from fire_backend.model_catalog import ROLE_MODELS
from fire_backend.storage import new_id
from test_device_protocol import configured


class Vault:
    def __init__(self):self.data={};self.writes=0
    def get(self,key):return self.data.get(key,'')
    def put(self,key,value):self.writes+=1;self.data[key]=value


def setup(tmp_path):
    vault=Vault();store=DesktopStore(tmp_path/'settings',vault)
    b=Backend(configured(tmp_path/'workspace'))
    b.backend_settings.config_store=store
    return b,store,vault


async def test_model_picker_is_actual_catalog_and_confirm_atomic_without_credentials(tmp_path):
    b,store,vault=setup(tmp_path)
    try:
        adapter=b.backend_settings;before=copy.deepcopy(vault.data);writes=vault.writes
        snap=adapter.snapshot('fire-01','models','code_model')
        assert snap['choices']==list(ROLE_MODELS['code_model'])[:4]
        target=ROLE_MODELS['code_model'][-1]
        proposal=await adapter.prepare('fire-01',{'model_role':'code_model','model':target},snap['revision'])
        with pytest.raises(PermissionError):await adapter.confirm('fire-02',proposal['id'],snap['revision'],new_id('event'))
        result=await adapter.confirm('fire-01',proposal['id'],snap['revision'],new_id('event'))
        assert result['status']=='applied'
        assert b.settings.openai_code_model==store.config.code_model==target
        assert vault.data==before and vault.writes==writes
        assert adapter.snapshot('fire-01')['selected']['code_model']==target
        assert (await adapter.confirm('fire-01',proposal['id'],snap['revision'],new_id('event')))==result
        with pytest.raises(ValueError):await adapter.prepare('fire-01',{'model_role':'code_model','model':'invented'},adapter.revision())
    finally:await b.close()


async def test_disable_all_cost_limits_keeps_technical_quotas_and_audits_real_event(tmp_path):
    b,store,_=setup(tmp_path)
    try:
        store.save_values(store.config.model_copy(update={'cost_limits_enabled':True,'runtime_ai_limits_enabled':True,'evolution_cost_limits_enabled':True}))
        before=store.config.model_dump();a=b.backend_settings
        p=await a.prepare('fire-01',{'disable_all_limits':True},a.revision());event=new_id('evt')
        await a.confirm('fire-01',p['id'],p['revision'],event)
        for field in ('cost_limits_enabled','runtime_ai_limits_enabled','evolution_cost_limits_enabled'):
            assert getattr(b.settings,'fire_'+field) is False
        assert store.config.runtime_ai_output_tokens==before['runtime_ai_output_tokens']
        assert store.config.max_corrections==before['max_corrections']
        assert b.store.get('events',p['id'])['confirmed_event_id']==event
        p=await a.prepare('fire-01',{'limits':{'daily_budget_usd':2,'cost_limits_enabled':True}},a.revision())
        await a.confirm('fire-01',p['id'],p['revision'],new_id('evt'))
        assert b.settings.fire_daily_budget_usd==2 and b.settings.fire_cost_limits_enabled
        with pytest.raises(ValueError):await a.prepare('fire-01',{'limits':{'openai_api_key':'secret'}},a.revision())
    finally:await b.close()


async def test_active_model_call_is_busy_not_saved_and_off_cancels_runtime(tmp_path):
    b,store,_=setup(tmp_path)
    try:
        a=b.backend_settings;p=await a.prepare('fire-01',{'model_role':'review_model','model':ROLE_MODELS['review_model'][-1]},a.revision())
        await b.build_lock.acquire()
        result=await a.confirm('fire-01',p['id'],p['revision'],new_id('evt'))
        assert result['status']=='busy' and b.store.get('events',p['id'])['state']=='pending'
        b.build_lock.release()
        cancelled=[]
        async def cancel(rid,reason):cancelled.append((rid,reason));b.runtime_ai.tasks.pop(rid)
        b.runtime_ai.cancel=cancel;b.runtime_ai.tasks['pending-one']={}
        p=await a.prepare('fire-01',{'runtime_ai_mode':'off'},a.revision())
        await a.confirm('fire-01',p['id'],p['revision'],new_id('evt'))
        assert cancelled==[('pending-one','disabled')]
        assert not b.settings.fire_runtime_ai_enabled and b.settings.fire_runtime_ai_developer_mode=='off'
        p=await a.prepare('fire-01',{'runtime_ai_mode':'auto'},a.revision())
        await a.confirm('fire-01',p['id'],p['revision'],new_id('evt'))
        assert b.settings.fire_runtime_ai_enabled and b.settings.fire_runtime_ai_developer_mode=='auto'
    finally:await b.close()


async def test_usage_four_rows_totals_tokens_and_history_fit_native_envelope(tmp_path):
    import json
    b,store,_=setup(tmp_path)
    try:
        for i in range(5):
            p=b.new_project('fire-01','device');p['name']='Å'*32;b.store.put('projects',p['id'],p)
            if i<4:
                r=b.usage.begin('generate','gpt-6.2-astra',2000,4000,project_id=p['id'],build_id='build-'+str(i)*20)
                b.usage.finish(r,{'input_tokens':1000,'output_tokens':500})
        totals=b.usage.project_costs
        def with_history():
            rows=totals()
            for row in rows.values():row['historical_estimate']={'estimated_usd':1.18}
            return rows
        b.usage.project_costs=with_history
        value=b.backend_settings.snapshot('fire-01','usage')
        assert len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())<=3072
        assert len(value['items'])==len(value['app_totals'])==4 and value['app_totals_has_more']
        assert all(r['input_tokens']==1000 and r['output_tokens']==500 and r['tokens_measured'] for r in value['items'])
        assert all('budget_reserved_usd' not in r for r in value['items'])
        assert len(b.backend_settings.snapshot('fire-01','usage',offset=4)['app_totals'])==1
        revision=b.backend_settings.revision()
        proposal=await b.backend_settings.prepare('fire-01',{'runtime_ai_mode':'off'},revision)
        store.save_values(store.config.model_copy(update={'code_model':ROLE_MODELS['code_model'][-1]}))
        with pytest.raises(ValueError):await b.backend_settings.confirm('fire-01',proposal['id'],revision,new_id('evt'))
        assert b.backend_settings.snapshot('fire-01','models','code_model')['selected']['code_model']==b.settings.openai_code_model
    finally:await b.close()

import json
import os
import zipfile

import pytest

from fire_backend.historical_costs import backfill
from fire_backend.usage import UsageLedger
from fire_backend.desktop_ui import app_cost_detail, app_cost_text
from test_usage import ledger


def artifact(meter, build_id='build-old', *, model='gpt-6.2-astra', stamp=10, mode='openai', source=True, review=True):
    store=meter.store
    store.put('builds',build_id,{'id':build_id,'project_id':'app-old','created_at':stamp,'status':'failed'})
    folder=store.path('builds',build_id,'');folder.mkdir()
    store.write(folder/'request.json',{'mode':mode,'model':model,'context':'hardware context '*100,'summary':'Snake'})
    if source:(folder/'attempt-1.lua').write_text('function update(dt) end\n'*80,encoding='utf-8')
    if review:store.write(folder/'review-1.json',{'approved':False,'reason':'test'})
    return folder


def test_saved_expensive_model_failed_attempts_persist_separate_from_usage_and_reset(tmp_path):
    m=ledger(tmp_path,clock=lambda:100)
    folder=artifact(m)
    (folder/'attempt-2.lua').write_text('function update(dt) end',encoding='utf-8')
    backfill(m.store,100)
    row=m.project_costs()['app-old'];h=row['historical_estimate']
    assert h['estimated_calls']==3 and h['models']==['gpt-6.2-astra']
    assert 0<h['low_usd']<h['estimated_usd']<h['high_usd']
    assert row['estimated_usd']==h['estimated_usd'] and row['recorded_usd']==0
    assert m.snapshot()['lifetime']['requests']==0
    m.reset();backfill(m.store,100)
    assert m.project_costs()['app-old']==row
    # Artifact/version deletion must not erase the historical estimate.
    m.store.path('builds','build-old').unlink()
    (folder/'request.json').unlink()
    restarted=UsageLedger(m.store,m.settings,clock=lambda:101)
    assert restarted.project_costs()['app-old']==row
    serialized=json.dumps(m.store.list('historical_costs'))
    assert 'hardware context' not in serialized and 'function update' not in serialized


def test_actual_measurement_replaces_matching_operation_without_double_count(tmp_path):
    m=ledger(tmp_path,clock=lambda:100,fire_cost_limits_enabled=False)
    artifact(m);backfill(m.store,100)
    old=m.project_costs()['app-old']['historical_estimate']['estimated_usd']
    ticket=m.begin('generate','gpt-6.2-astra',10,10,build_id='build-old')
    imported=m.store.get('usage',ticket);imported['started_at']=10;m.store.put('usage',ticket,imported)
    actual=m.finish(ticket,{'input_tokens':10,'output_tokens':10})['estimated_usd']
    row=m.project_costs()['app-old']
    assert row['recorded_usd']==actual
    assert row['historical_estimate']['estimated_calls']==1  # only review remains
    assert actual<row['estimated_usd']<old


@pytest.mark.parametrize('kind',['new','mock','local','unknown','damaged'])
def test_no_estimates_for_new_mock_local_or_unknown_builds(tmp_path,kind):
    m=ledger(tmp_path,clock=lambda:100)
    folder=artifact(m,stamp=110 if kind=='new' else 10,mode='mock' if kind=='mock' else 'openai',
        model='not-priced' if kind=='unknown' else 'gpt-6.2-astra',source=kind!='local')
    if kind=='damaged':(folder/'request.json').write_text('{bad',encoding='utf-8')
    backfill(m.store,100)
    assert m.project_costs()=={}


def test_legacy_missing_timestamp_uses_request_age_and_ui_marks_estimate(tmp_path):
    m=ledger(tmp_path,clock=lambda:100)
    folder=artifact(m)
    m.store.put('builds','build-old',{'id':'build-old','project_id':'app-old'})
    os.utime(folder/'request.json',(10,10))
    backfill(m.store,100)
    row=m.project_costs()['app-old'];app={'cost':row['estimated_usd'],'cost_detail':row}
    assert app_cost_text(app).startswith('≈$')
    text=app_cost_detail(app)
    assert 'historisk anslag' in text and 'gpt-6.2-astra' in text and 'Eldre tale/dialog' in text


def test_update_includes_prior_packaged_source_in_input_estimate(tmp_path):
    m=ledger(tmp_path,clock=lambda:100)
    folder=artifact(m)
    request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    request['base_package_id']='package-base';m.store.write(folder/'request.json',request)
    with zipfile.ZipFile(m.store.path('packages','package-base','.zip'),'w') as archive:
        archive.writestr('apps/snake/main.lua','x'*4000)
    backfill(m.store,100)
    with_base=m.project_costs()['app-old']['estimated_usd']
    m.store.path('historical_costs','build-old').unlink()
    m.store.path('packages','package-base','.zip').unlink()
    backfill(m.store,100)
    assert with_base-m.project_costs()['app-old']['estimated_usd']==pytest.approx(.008)

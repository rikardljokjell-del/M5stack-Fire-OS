"""Reservations are risk accounting, never measured spend or realistic estimates."""
import pytest

from fire_backend.desktop_ui import usage_cost_text,amount_text
from test_usage import ledger


def test_real_build_and_cancelled_repair_are_separate_own_job_prices(tmp_path):
    meter=ledger(tmp_path,fire_cost_limits_enabled=False)
    for name in ('build-original','build-repair'):meter.store.put('builds',name,{'id':name,'project_id':'app-one'})
    first=meter.begin('generate','gpt-6.2-sol',100,100,build_id='build-original',project_id='app-one')
    r=meter.finish(first,{'input_tokens':10,'output_tokens':10});r['estimated_usd']=.2529886
    meter.store.put('usage',first,r)
    repair=meter.begin('generate','gpt-6.2-sol',100,100,build_id='build-repair',project_id='app-one')
    r=meter.finish(repair,status='cancelled');r.update(estimated_usd=1.4263775,reserved_usd=1.4263775)
    meter.store.put('usage',repair,r)
    jobs=meter.build_costs();app=meter.project_costs()['app-one']
    assert jobs['build-original']['estimated_usd']==pytest.approx(.2529886)
    assert jobs['build-repair']['provider_calculated_usd']==0
    assert jobs['build-repair']['estimated_usd']==0 and jobs['build-repair']['unestimated_requests']==1
    assert usage_cost_text(jobs['build-repair'])=='Ukjent'
    assert usage_cost_text(app)=='$0.2530 + ukjent'
    assert app['budget_reserved_usd']==pytest.approx(1.4263775)
    recent=next(r for r in meter.snapshot()['recent'] if r['id']==repair)
    assert recent['estimated_usd'] is None and not recent['tokens_measured']
    assert recent['input_tokens']==recent['output_tokens']==0
    assert meter.store.get('usage',repair)['estimated_usd']==1.4263775


def test_empirical_median_requires_three_actual_matching_samples_and_no_reserve(tmp_path):
    meter=ledger(tmp_path,fire_cost_limits_enabled=False)
    for n in range(3):
        rid=meter.begin('generate','gpt-6-luna',100,100)
        row=meter.finish(rid,{'input_tokens':100,'output_tokens':100});row['estimated_usd']=.045
        meter.store.put('usage',rid,row)
    rid=meter.begin('generate','gpt-6-luna',100000,128000,build_id='build-unknown',project_id='app-one')
    meter.finish(rid,status='unknown')
    public=next(r for r in meter.snapshot()['recent'] if r['id']==rid)
    assert public['price_kind']=='empirical' and public['empirical_samples']==3
    assert public['estimated_usd']==.045 and public['budget_reserved_usd']>.045
    assert usage_cost_text(public)=='Ukjent (≈$0.0450)'
    cost=meter.build_costs()['build-unknown']
    assert usage_cost_text(cost)=='Ukjent (≈$0.0450)'
    other=meter.begin('review','gpt-6-luna',100,100)
    meter.finish(other,status='failed')
    assert next(r for r in meter.snapshot()['recent'] if r['id']==other)['price_kind']=='unknown'


def test_runtime_usage_does_not_become_app_development_or_build_cost(tmp_path):
    meter=ledger(tmp_path,fire_cost_limits_enabled=False)
    dev=meter.begin('generate','gpt-6-luna',100,100,project_id='app-one',build_id='build-one')
    run=meter.begin('runtime_ai','gpt-6-luna',100,100,project_id='app-one',runtime_request_id='request-one')
    a=meter.finish(dev,{'input_tokens':100,'output_tokens':100})
    b=meter.finish(run,{'input_tokens':200,'output_tokens':100})
    assert meter.project_costs()['app-one']['estimated_usd']==a['estimated_usd']
    assert meter.build_costs()['build-one']['estimated_usd']==a['estimated_usd']
    assert meter.runtime_costs()['app-one']['estimated_usd']==b['estimated_usd']
    assert meter.snapshot()['runtime_ai']['requests']==1
    assert meter.snapshot()['development']['requests']==1


def test_display_reset_does_not_release_unknown_budget_exposure(tmp_path):
    meter=ledger(tmp_path,fire_daily_budget_usd=.01,fire_request_budget_usd=0,fire_build_budget_usd=0)
    rid=meter.begin('generate','gpt-6.2-sol',1000,500)
    reserve=meter.store.get('usage',rid)['estimated_usd'];meter.finish(rid,status='cancelled')
    meter.reset()
    snapshot=meter.snapshot()
    assert snapshot['today']['estimated_usd']==0
    assert snapshot['limits']['daily_remaining_usd']==pytest.approx(.01-reserve)


def test_small_runtime_prices_remain_visibly_nonzero():
    assert amount_text(.00006)=='$0.000060'
    assert amount_text(.0000001)=='<$0.000001'
    assert amount_text(0)=='$0.0000'


async def test_dialog_job_cost_is_only_its_session_and_its_voice_operations(tmp_path):
    from fire_backend.service import Backend
    from fire_backend.models import State
    from test_device_protocol import configured
    backend=Backend(configured(tmp_path,fire_cost_limits_enabled=False))
    try:
        owner=next(iter(backend.settings.device_tokens()))
        a=await backend.desktop_conversation(owner);b=await backend.desktop_conversation(owner)
        b.project_id=a.project_id;a.state=b.state=State.processing
        expected={a.id:0,b.id:0}
        for sid,op,n in [(a.id,'dialog',100),(a.id,'transcribe',200),(a.id,'speech',300),(b.id,'dialog',5000)]:
            rid=backend.usage.begin(op,'gpt-6-luna',n,100,project_id=a.project_id,session_id=sid)
            expected[sid]+=backend.usage.finish(rid,{'input_tokens':n,'output_tokens':100})['estimated_usd']
        # Same app/session does not make build or installed-runtime usage dialog cost.
        for op,build in [('generate','other-build'),('dialog','other-build'),('runtime_ai',None)]:
            rid=backend.usage.begin(op,'gpt-6-luna',10000,100,project_id=a.project_id,session_id=a.id,build_id=build)
            backend.usage.finish(rid,{'input_tokens':10000,'output_tokens':100})
        rows={row['id']:row for row in backend.jobs.snapshot()['jobs']}
        # Starting B closes the old desktop session A; its retained cost is
        # still session-scoped, while only B appears as the active dialog job.
        retained=backend.usage.conversation_costs()
        assert retained[a.id]['estimated_usd']==pytest.approx(expected[a.id])
        assert rows[b.id]['estimated_usd']==pytest.approx(expected[b.id])
        assert retained[a.id]['requests']==3 and rows[b.id]['cost_detail']['requests']==1
    finally:await backend.close()


async def test_dialog_job_missing_or_cancelled_usage_is_unknown_not_zero_or_reserve(tmp_path):
    from fire_backend.service import Backend
    from fire_backend.models import State
    from test_device_protocol import configured
    backend=Backend(configured(tmp_path,fire_cost_limits_enabled=False))
    try:
        session=await backend.desktop_conversation(next(iter(backend.settings.device_tokens())))
        session.state=State.processing
        row=next(r for r in backend.jobs.snapshot()['jobs'] if r['id']==session.id)
        assert row['estimated_usd'] is None and usage_cost_text(row['cost_detail'])=='Ukjent'
        rid=backend.usage.begin('speech','gpt-6-luna',100,128000,session_id=session.id)
        reserve=backend.usage.finish(rid,status='cancelled')['estimated_usd']
        row=next(r for r in backend.jobs.snapshot()['jobs'] if r['id']==session.id)
        assert usage_cost_text(row['cost_detail'])=='Ukjent' and row['estimated_usd']==0
        assert row['cost_detail']['budget_reserved_usd']==reserve>0
    finally:await backend.close()

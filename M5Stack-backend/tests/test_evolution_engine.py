import asyncio
import copy
import pytest

from fire_backend.ai import MockProvider
from fire_backend.models import GeneratedApp
from fire_backend.service import Backend
from fire_backend.evolution_models import EvolutionConfig
from fire_backend.evolution import finding_key
from test_device_protocol import configured,CAPS


class Provider(MockProvider):
    def __init__(self):self.calls=[]
    async def generate(self,summary,context,error=None,previous=None):
        self.calls.append((summary,context,previous))
        return GeneratedApp(name='Evolution klokke',required_services=['display','buttons'],
            main_lua='local n=0 function init() end function update(dt) fire.display.text(10,40,tostring(n),65535) end function on_button(b) n=n+1 end')


def setup(tmp_path):
    provider=Provider();service=Backend(configured(tmp_path),provider)
    project=service.new_project('fire-01','device')
    service.store.put('devices','fire-01',{'id':'fire-01','capabilities':copy.deepcopy(CAPS)})
    return service,project,provider


async def configure(service,project,autonomy='auto_build'):
    config=EvolutionConfig(enabled=True,flags={'generate':True,'repair':True,'optimize':True,'expand':True,'evolve':True},autonomy=autonomy)
    proposal=await service.evolution.prepare('fire-01',project['id'],'configure',config.model_dump(),0)
    await service.evolution.confirm('fire-01',project['id'],proposal['id'],0)
    return 1


async def prepared(service,project,autonomy='auto_build'):
    await configure(service,project,autonomy)
    proposal=await service.evolution.prepare('fire-01',project['id'],'generate',{'goal':'Lag en klokke med tell og nullstill.'},1)
    return proposal,await service.evolution.confirm('fire-01',project['id'],proposal['id'],1)


async def test_default_off_and_exact_proposal_duplicate(tmp_path):
    b,project,provider=setup(tmp_path)
    try:
        assert not b.evolution.snapshot('fire-01',project['id'])['config']['enabled']
        with pytest.raises(ValueError):await b.evolution.prepare('fire-01',project['id'],'generate',{'goal':'Klokke'},0)
        proposal,result=await prepared(b,project)
        assert (await b.evolution.confirm('fire-01',project['id'],proposal['id'],1))==result
        task=b.evolution.tasks.get(result['job_id'])
        if task:await asyncio.wait_for(asyncio.shield(task),30)
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='awaiting_install',job
        assert len(provider.calls)==1
        build=b.store.get('builds',job['build_ids'][0])
        assert build['authorization']['kind']=='evolution_mandate'
        assert len(b.store.list('commands'))==0
        assert job['comparison']['status']=='validated_candidate'
        assert not job['comparison']['physical_resolution_verified']
        assert b.store.get('projects',project['id']).get('current') is None
    finally:await b.close()


async def test_manual_has_real_current_build_confirm_and_revoke(tmp_path):
    b,project,provider=setup(tmp_path)
    try:
        _,result=await prepared(b,project,'manual')
        await b.evolution.tasks[result['job_id']]
        job=b.store.get('evolution_jobs',result['job_id'])
        worker=b.sessions[job['session_id']]
        assert not provider.calls and not b.store.list('builds')
        with pytest.raises(ValueError):await b.confirm_build(worker,'proposal-wrong')
        await b.evolution.control('fire-01',project['id'],'revoke',1,job_id=job['id'])
        with pytest.raises(ValueError):await b.confirm_build(worker,worker.proposal_id)
        assert not provider.calls
    finally:await b.close()


async def test_snapshot_job_cost_spans_three_projects_without_reservation_as_price(tmp_path):
    b,project,_=setup(tmp_path)
    try:
        _,result=await prepared(b,project,'manual')
        await b.evolution.tasks[result['job_id']]
        apps=[project]+[b.new_project('fire-01','device') for _ in range(2)]
        rows=[]
        for i,app in enumerate(apps):
            # Retained offline ledger fixtures: real token pricing, no provider call.
            item=b.usage.begin('review','gpt-6.2-sol',10000,2000,project_id=app['id'])
            row=b.usage.finish(item,{'input_tokens':100*(i+1),'output_tokens':20*(i+1)})
            row.update(evolution_job_id=result['job_id'],evolution_mandate_id=result['mandate_id'])
            b.store.put('usage',item,row)
            rows.append(row)
        item=b.usage.begin('generate','gpt-6.2-sol',10000,2000,project_id=apps[2]['id'])
        unknown=b.usage.finish(item,None,status='cancelled')
        unknown.update(evolution_job_id=result['job_id'],evolution_mandate_id=result['mandate_id'])
        b.store.put('usage',item,unknown)
        item=b.usage.begin('review','gpt-6.2-sol',1000,200,project_id=project['id'])
        other=b.usage.finish(item,{'input_tokens':50,'output_tokens':10})
        other['evolution_job_id']='evolution-other'
        b.store.put('usage',item,other)

        snapshot=b.evolution.snapshot('fire-01',project['id'])
        cost=snapshot['job']['cost']
        actual=sum(r['estimated_usd'] for r in rows)
        assert cost['requests']==4 and cost['unknown_usage_requests']==1
        assert cost['provider_calculated_usd']==pytest.approx(actual)
        assert cost['estimated_usd']==pytest.approx(actual)
        assert cost['budget_reserved_usd']==pytest.approx(unknown['reserved_usd'])
        assert cost['estimated_usd']<cost['budget_exposure_usd']
        expected=b.evolution.price([*rows,unknown])
        assert cost.keys()==expected.keys()
        for key,value in expected.items():
            # File enumeration may change the order of floating-point additions.
            assert cost[key]==(pytest.approx(value,rel=1e-12,abs=1e-12) if isinstance(value,float) else value)
        assert cost['estimated_usd']==pytest.approx(b.evolution.cost(result['job_id'])['estimated_usd'],rel=1e-12,abs=1e-12)
        own=rows[0]['estimated_usd']+other['estimated_usd']
        for key in ('app_cost','daily_cost'):
            assert snapshot[key]['requests']==2
            assert snapshot[key]['estimated_usd']==pytest.approx(own)
            assert snapshot[key]['unknown_usage_requests']==0
    finally:await b.close()


async def test_model_context_and_revision_change_invalidate(tmp_path):
    b,project,_=setup(tmp_path)
    try:
        _,result=await prepared(b,project,'manual');await b.evolution.tasks[result['job_id']]
        mandate=result['mandate_id'];assert b.evolution.validate_mandate(mandate)
        old=b.settings.openai_review_model;b.settings.openai_review_model='gpt-6.2-sol'
        with pytest.raises(ValueError):b.evolution.validate_mandate(mandate)
        b.settings.openai_review_model=old
        p=b.store.get('projects',project['id']);p['last_confirmed_summary']='Endret av bruker';b.store.put('projects',p['id'],p)
        with pytest.raises(ValueError):b.evolution.validate_mandate(mandate)
    finally:await b.close()


def test_material_finding_excludes_counts_and_timestamps():
    a={'category':'source_defect','summary':'Samme feil','count':1,'timestamp':1}
    assert finding_key('a'*64,a)==finding_key('a'*64,{**a,'count':99,'timestamp':100})
    assert finding_key('a'*64,a)!=finding_key('b'*64,a)


async def test_added_permissions_preserve_candidate_and_require_new_approval(tmp_path):
    b,project,p=setup(tmp_path)
    original=p.generate
    async def generate(*args):return (await original(*args)).model_copy(update={'required_services':['display','buttons','rgb']})
    p.generate=generate
    try:
        _,result=await prepared(b,project)
        await b.evolution.tasks[result['job_id']]
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='permission_required',job
        build=b.store.get('builds',job['build_ids'][0])
        assert build['error_code']=='evolution_permission_required'
        assert (b.store.path('builds',build['id'],'')/'attempt-1.lua').is_file()
        assert not b.store.list('commands') and not b.store.list('quality')
        assert 'fire.rgb' in job['requested_permissions']
        proposal=await b.evolution.prepare('fire-01',project['id'],'generate',{
            'goal':'Samme klokke med RGB','permissions':['fire.display','fire.buttons','fire.rgb']},1)
        assert proposal['scope']['permissions']==['fire.buttons','fire.display','fire.rgb']
        assert len(b.store.list('builds'))==1  # Preparing permissions cannot start paid work.
        snapshot=b.evolution.snapshot('fire-01',project['id'])
        request=snapshot['permission_request']
        retained=await b.evolution.prepare('fire-01',project['id'],request['operation'],request['prepare'],1)
        assert b.store.get('evolution_mandates',result['mandate_id'])['state']=='active'
        approved=await b.evolution.confirm('fire-01',project['id'],retained['id'],1)
        await b.evolution.tasks[approved['job_id']]
        done=b.store.get('evolution_jobs',approved['job_id'])
        assert done['state']=='awaiting_install',done
        assert len(p.calls)==1 and b.store.get('evolution_mandates',result['mandate_id'])['state']=='revoked'
        next_build=b.store.get('builds',done['build_ids'][0])
        assert next_build['reused_candidate_from']==build['id']
        assert next_build['summary']==build['summary']
    finally:await b.close()


async def test_completed_analysis_reused_and_unknown_result_never_repeated(tmp_path):
    b,project,p=setup(tmp_path);calls=[];original=p.evolution_analyze
    async def analyze(payload):calls.append(payload);return await original(payload)
    p.evolution_analyze=analyze
    try:
        _,result=await prepared(b,project,'manual');await b.evolution.tasks[result['job_id']]
        job=b.store.get('evolution_jobs',result['job_id']);payload={'goal':'Ett stabilt underlag'}
        first=await b.evolution.provider_operation(job,'evolution_analyze',payload)
        second=await b.evolution.provider_operation(job,'evolution_analyze',payload)
        assert first==second and len(calls)==1
        from fire_backend.evolution import Evolution
        b.evolution=Evolution(b)  # Restore without executing queued work.
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='paused'
        # Reuse is available only under a valid resumed mandate.
        await b.evolution.control('fire-01',project['id'],'resume',1,job_id=job['id'])
        await b.evolution.tasks[job['id']]
        job=b.store.get('evolution_jobs',job['id'])
        assert (await b.evolution.provider_operation(job,'evolution_analyze',payload))==first and len(calls)==1
        entered=asyncio.Event()
        async def blocked(payload):calls.append(payload);entered.set();await asyncio.Event().wait()
        p.evolution_reflect=blocked
        task=asyncio.create_task(b.evolution.provider_operation(job,'evolution_reflect',{'different':'input'}))
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        from fire_backend.usage import UsageBudgetError
        with pytest.raises(UsageBudgetError):await b.evolution.provider_operation(job,'evolution_reflect',{'different':'input'})
        assert len(calls)==2
    finally:await b.close()


async def test_suggest_deduplicates_material_finding_under_real_config_approval(tmp_path):
    from test_repair_target import saved_app
    b,unused,p=setup(tmp_path);calls=[];original=p.evolution_analyze
    async def analyze(payload):calls.append(payload);return await original(payload)
    p.evolution_analyze=analyze
    try:
        project,package=saved_app(b,'Klokke',slug='clock')
        await configure(b,project,'suggest')
        finding={'category':'source_defect','summary':'Telleren nullstilles ikke','count':1,'timestamp':1}
        first=await b.evolution.finding('fire-01',project['id'],package['id'],package['manifest']['checksum'],finding)
        await b.evolution.tasks[first['analysis_job_id']]
        again=await b.evolution.finding('fire-01',project['id'],package['id'],package['manifest']['checksum'],{**finding,'count':99,'timestamp':100})
        assert again['id']==first['id'] and len(calls)==1
        job=b.store.get('evolution_jobs',first['analysis_job_id']);mandate=b.store.get('evolution_mandates',job['mandate_id'])
        approval=b.evolution.state('fire-01',project['id'])['approval']
        assert mandate['authorization']['kind']=='previously_confirmed_suggest_configuration'
        assert mandate['authorization']['event_id']==approval['event_id']
        assert not job['build_ids'] and not b.store.list('commands')
    finally:await b.close()


async def test_non_improving_candidate_keeps_version_without_replacing_recommended_base(tmp_path,monkeypatch):
    from test_repair_target import saved_app
    b,_,p=setup(tmp_path)
    try:
        project,base=saved_app(b,'Clock',slug='clock')
        await configure(b,project)
        async def verdict(service,owner,base_id,candidate_id,evaluation,goal):
            pkg=service.store.get('packages',candidate_id)
            return {'status':'not_improved','candidate_source_sha256':pkg['manifest']['checksum'],'metric':goal['metric'],'deltas':{}}
        monkeypatch.setattr('fire_backend.evolution_compare.assess_packages',verdict)
        proposal=await b.evolution.prepare('fire-01',project['id'],'optimize',{'base_package_id':base['id'],
            'goal':'Mindre tegningsarbeid','metric':'max_callback_display_work','limits':{'max_builds':1},'permissions':['fire.display','fire.buttons']},1)
        result=await b.evolution.confirm('fire-01',project['id'],proposal['id'],1)
        await b.evolution.tasks[result['job_id']]
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='not_improved',job
        candidate=b.store.get('packages',job['candidate_ids'][0])
        assert candidate['evolution_adoption']=='not_adopted' and b.store.path('packages',candidate['id'],'.zip').is_file()
        assert b.store.get('projects',project['id'])['latest_package']==base['id']
        assert not candidate.get('quality',{}).get('blocked')
        with pytest.raises(ValueError):b.evolution.require_delivery(candidate)
    finally:await b.close()


async def test_gepa_reflection_stop_cancels_actual_owner_loop_callback(tmp_path,monkeypatch):
    from test_repair_target import saved_app
    b,_,provider=setup(tmp_path);entered=asyncio.Event();cancelled=asyncio.Event()
    async def reflect(payload):
        entered.set()
        try:await asyncio.Event().wait()
        finally:cancelled.set()
    provider.evolution_reflect=reflect
    def optimizer(seed,train,holdout,evaluate,propose,**kwargs):
        return propose(seed,{'guidance':[]},['guidance'])
    monkeypatch.setattr('fire_backend.evolution_gepa.optimize_strategy',optimizer)
    try:
        project,base=saved_app(b,'Clock',slug='clock');await configure(b,project)
        p=await b.evolution.prepare('fire-01',project['id'],'evolve',{'base_package_id':base['id'],
            'goal':'Mindre tegnearbeid','metric':'max_callback_display_work'},1)
        result=await b.evolution.confirm('fire-01',project['id'],p['id'],1)
        await asyncio.wait_for(entered.wait(),3)
        await asyncio.wait_for(b.evolution.control('fire-01',project['id'],'stop',1,job_id=result['job_id']),3)
        assert cancelled.is_set()
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='stopped' and any(a['state']=='unknown' for a in job['actions'].values())
        assert not b.store.list('commands')
    finally:await b.close()


async def test_manual_evolve_uses_gepa_and_waits_for_real_build_confirm(tmp_path,monkeypatch):
    from test_repair_target import saved_app
    b,_,provider=setup(tmp_path);invoked=[]
    def optimizer(seed,train,holdout,evaluate,propose,**kwargs):
        invoked.append(True)
        for case in train+holdout:evaluate(seed,case)
        candidate=propose(seed,{'guidance':[]},['guidance'])
        for case in train+holdout:evaluate(candidate,case)
        return {'optimizer':'offline-marshalling-fixture','candidate':candidate,'training_ids':[c['id'] for c in train],
            'holdout_ids':[c['id'] for c in holdout],'evaluation_calls':4,'validation_scores':[.5,.6]}
    monkeypatch.setattr('fire_backend.evolution_gepa.optimize_strategy',optimizer)
    try:
        project,base=saved_app(b,'Clock',slug='clock');await configure(b,project,'manual')
        from fire_backend.builds import write_archive,sha256
        source=b'function init() end function update(dt) fire.display.text(0,0,"BASELINE",65535) fire.display.text(0,20,"DETAIL",65535) end'
        base['manifest']['checksum']=sha256(source);path=b.store.path('packages',base['id'],'.zip')
        write_archive(path,base['manifest'],source);base['archive_sha256']=sha256(path.read_bytes());b.store.put('packages',base['id'],base)
        p=await b.evolution.prepare('fire-01',project['id'],'evolve',{'base_package_id':base['id'],
            'goal':'Mindre tegnearbeid','metric':'max_callback_display_work','permissions':['fire.display','fire.buttons']},1)
        result=await b.evolution.confirm('fire-01',project['id'],p['id'],1)
        async with asyncio.timeout(8):
            while True:
                job=b.store.get('evolution_jobs',result['job_id'])
                if job['state']=='awaiting_build_confirm':break
                await asyncio.sleep(.02)
        assert invoked and not provider.calls and not b.store.list('builds')[-1].get('evolution_job_id')
        worker=b.sessions[job['session_id']]
        await b.confirm_build(worker,worker.proposal_id)
        await asyncio.wait_for(asyncio.shield(b.evolution.tasks[job['id']]),30)
        job=b.store.get('evolution_jobs',job['id'])
        assert job.get('strategy_candidate_id'),job
        record=b.store.get('evolution_strategies',job['strategy_candidate_id'])
        assert record['parent_id']=='strategy-base' and len(provider.calls)==1
        assert not b.store.list('commands')
    finally:await b.close()


async def test_pause_finishes_sent_analysis_then_resume_reuses_it(tmp_path):
    b,project,p=setup(tmp_path);entered=asyncio.Event();release=asyncio.Event();calls=[]
    original=p.evolution_analyze
    async def analyze(payload):
        calls.append(payload);entered.set();await release.wait();return await original(payload)
    p.evolution_analyze=analyze
    try:
        _,result=await prepared(b,project,'suggest')
        task=b.evolution.tasks[result['job_id']];await entered.wait()
        await b.evolution.control('fire-01',project['id'],'pause',1,job_id=result['job_id'])
        assert not task.done()
        release.set();await task
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='paused' and job['analysis']
        assert all(a['state']=='completed' for a in job['actions'].values())
        await b.evolution.control('fire-01',project['id'],'resume',1,job_id=job['id'])
        await b.evolution.tasks[job['id']]
        assert b.store.get('evolution_jobs',job['id'])['state']=='suggested' and len(calls)==1
    finally:await b.close()


async def test_pause_during_generation_resumes_same_build_and_cached_typed_source(tmp_path):
    b,project,p=setup(tmp_path);entered=asyncio.Event();release=asyncio.Event();original=p.generate
    async def generate(*args):entered.set();await release.wait();return await original(*args)
    p.generate=generate
    try:
        await configure(b,project)
        proposal=await b.evolution.prepare('fire-01',project['id'],'generate',{'goal':'Tell med knapp','limits':{'max_builds':1}},1)
        result=await b.evolution.confirm('fire-01',project['id'],proposal['id'],1)
        task=b.evolution.tasks[result['job_id']];await entered.wait()
        await b.evolution.control('fire-01',project['id'],'pause',1,job_id=result['job_id'])
        assert b.jobs.snapshot()['active_count']==1
        release.set();await task
        job=b.store.get('evolution_jobs',result['job_id']);build_id=job['build_ids'][0]
        assert job['state']=='paused' and b.store.get('builds',build_id)['error_code']=='evolution_paused'
        assert len(p.calls)==1 and not b.store.list('quality')
        await b.evolution.control('fire-01',project['id'],'resume',1,job_id=job['id'])
        await asyncio.wait_for(asyncio.shield(b.evolution.tasks[job['id']]),30)
        job=b.store.get('evolution_jobs',job['id'])
        assert job['state']=='awaiting_install',job
        assert job['build_ids']==[build_id] and len(p.calls)==1
        assert b.jobs.snapshot()['active_count']==0
    finally:await b.close()


async def test_known_money_admission_can_resume_after_disable_without_auto_start(tmp_path):
    from fire_backend.usage import UsageBudgetError
    b,project,p=setup(tmp_path);original=p.evolution_analyze;called=[]
    async def analyze(payload):
        if b.settings.fire_evolution_cost_limits_enabled:raise UsageBudgetError('Eksplisitt offline admissionavslag',code='evolution_cost_limit')
        called.append(payload);return await original(payload)
    p.evolution_analyze=analyze
    try:
        _,result=await prepared(b,project,'suggest');await b.evolution.tasks[result['job_id']]
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='paused' and job['blocked_by_cost'] and not called
        assert all(a['state']=='not_admitted' for a in job['actions'].values())
        b.settings.fire_evolution_cost_limits_enabled=False
        await asyncio.sleep(0);assert not called
        await b.evolution.control('fire-01',project['id'],'resume',1,job_id=job['id'])
        await b.evolution.tasks[job['id']]
        assert len(called)==1 and b.store.get('evolution_jobs',job['id'])['state']=='suggested'
    finally:await b.close()


@pytest.mark.parametrize('autonomy',['auto_build','manual'])
async def test_owner_trial_reuses_builder_without_adopting_apps_and_needs_separate_owner_confirm(tmp_path,autonomy):
    from test_repair_target import saved_app
    from fire_backend.builds import write_archive,sha256
    from fire_backend.evolution_replay import prepare_evaluation
    from fire_backend.evolution_strategies import Strategies
    b,_,p=setup(tmp_path)
    async def generate(summary,context,error=None,previous=None):
        p.calls.append((summary,context,previous))
        return GeneratedApp(name='Mindre tegning',required_services=['display'],
            main_lua='function init() end function update(dt) fire.display.text(0,0,"OK",65535) end')
    p.generate=generate
    try:
        apps=[]
        for i in range(3):
            project,base=saved_app(b,'Kontroll '+str(i),slug='counter'+str(i))
            source=b'function init() end function update(dt) fire.display.text(0,0,"BASELINE",65535) fire.display.text(0,20,"DETAIL",65535) end'
            base['manifest']['checksum']=sha256(source);path=b.store.path('packages',base['id'],'.zip')
            write_archive(path,base['manifest'],source);base['archive_sha256']=sha256(path.read_bytes());b.store.put('packages',base['id'],base)
            apps.append((project,base))
        project,base=apps[0]
        peer=None;native=None
        if autonomy=='manual':
            from fire_backend.models import SessionStart
            from fire_backend.evolution_contract import EXTENSION
            from test_repair_target import Peer
            peer=Peer()
            native=await b.start(SessionStart(device_id='fire-01',target='device',protocol_version='0.2',boot_id='boot-cohort',
                app_mode='update',project_id=project['id'],base_package_id=base['id'],capabilities={**CAPS,'evolution':EXTENSION}),peer,'fire-01')
        await configure(b,project,autonomy)
        ev=prepare_evaluation(b,'fire-01',project['id'],base['id'],goal={'kind':'metric','metric':'max_callback_operations','minimum_improvement_percent':5})
        b.store.put('evolution_evaluations',ev['id'],ev)
        strategy=Strategies(b.store).archive_candidate('fire-01',project['id'],components={'guidance':'Bevar funksjonene, fjern redundant tegning.'},
            evaluation=ev,comparison={'status':'improved','independent_checks_passed':True,'context_sha256':ev['context_sha256'],
                'training_ids':['training-fixture'],'holdout_ids':['holdout-fixture']})
        with pytest.raises(ValueError,match='tre'):
            await b.evolution.prepare('fire-01',project['id'],'strategy_owner',{'strategy_id':strategy['id']},1)
        proposal=await b.evolution.prepare('fire-01',project['id'],'strategy_owner',{'strategy_id':strategy['id'],
            'project_ids':[a['id'] for a,_ in apps],'limits':{'max_builds':3}},1)
        assert len(proposal['cohort'])==3 and not p.calls
        result=await b.evolution.confirm('fire-01',project['id'],proposal['id'],1)
        assert b.evolution.active_project(apps[1][0]['id'])
        if native:
            from fire_backend.models import DeviceEvent
            from fire_backend.protocol import dispatch
            seen=set()
            for entry in proposal['cohort']:
                async with asyncio.timeout(15):
                    while True:
                        messages=[e for e in peer.events if e['type']=='build_proposal' and e['proposal_id'] not in seen]
                        if messages:break
                        await asyncio.sleep(.02)
                current=messages[-1];seen.add(current['proposal_id'])
                assert current['project_id']==entry['project_id']==native.project_id
                assert current['app_name']==b.store.get('projects',entry['project_id'])['name']
                assert current['evolution_job_id']==result['job_id']
                assert current['context_id']==native.development_context_id
                await dispatch(b,native,DeviceEvent(device_id='fire-01',event='build_confirm',protocol_version='0.2',
                    event_id='confirm-'+str(len(seen)),session_id=native.id,boot_id=native.boot_id,proposal_id=current['proposal_id']))
                await asyncio.wait_for(asyncio.shield(native.task),30)
            assert len(seen)==3
        await asyncio.wait_for(asyncio.shield(b.evolution.tasks[result['job_id']]),45)
        job=b.store.get('evolution_jobs',result['job_id'])
        assert job['state']=='awaiting_strategy_approval',job
        assert len(p.calls)==3 and len(job['owner_result']['multi_app_evaluations'])==3
        for original,package in apps:
            current=b.store.get('projects',original['id'])
            assert current['latest_package']==package['id'] and current['name']==original['name']
            assert current['next_version']==3
        assert Strategies(b.store).active('fire-01',apps[1][0]['id'])['id']=='strategy-base'
        owner_proposal=await b.evolution.prepare('fire-01',project['id'],'strategy_owner',{'strategy_id':job['strategy_candidate_id']},1)
        await b.evolution.confirm('fire-01',project['id'],owner_proposal['id'],1)
        assert Strategies(b.store).active('fire-01',apps[1][0]['id'])['id']==job['strategy_candidate_id']
        assert not b.store.list('commands')
    finally:await b.close()

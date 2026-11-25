"""Actual capability defaults, execution evidence and immutable SDK delivery gates."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from fire_backend.api_registry import API_CONTRACT, generation_contract, preview_capabilities, service_closure
from fire_backend.app_sdk import SDK_CONTRACT, SDK_VERSION, contract as canonical_sdk
from fire_backend.lua_worker import simulate
from fire_backend.quality import require_deliverable
from fire_backend.sdk_standards import contract, verify, require_passed, context_with_contract, MARKER
from fire_backend.storage import canonical


def request(body, **extra):
    return dict(main_lua='function init() end function update(dt) '+body+' end',
                required_services=['display'],api_version=SDK_VERSION,api_contract=SDK_CONTRACT,
                max_memory=131072,max_runtime_ms=0,preview_duration_ms=1000,
                profile='idle',native_host_policy='fire-native-host-v1',**extra)


@pytest.mark.parametrize('summary', ['Lag Snake.','Lag Tetris.','Lag et bilspill.',
    'Lag et eventyrspill.','Lag et space shooter-spill.','Lag et plattformspill.', 'Lag prikkjakt.'])
def test_game_scope_and_actual_capabilities_cannot_be_reduced_by_candidate(summary):
    c=contract(preview_capabilities(),summary)
    assert c['game_requested'] and c['audio_required'] and c['rgb_required']
    with pytest.raises(ValueError,match='BOTH'):
        require_passed(verify(c,['display'],{'profiles':[{'profile':'idle'}]},'a'*64))


@pytest.mark.parametrize('summary,rgb,audio',[
    ('Lag Snake uten RGB og uten lyd.',False,False),
    ('Create Snake without RGB and without music.',False,False),
    ('Lag Snake med lyd av/på.',True,True),
    ('Lag Snake uten lyd fra start, med av/på i menyen.',True,True),
    ('Create Snake with no sound by default.',True,True),
    ('Lag Snake uten RGB, med lyd av/på.',False,True),
    ('Lag Snake uten spilllyd, men RGB av/på.',True,False),
    ('Lag en stoppeklokke.',True,False),
    ('Lag en melodiapp.',True,True),
])
def test_permanent_user_exceptions_are_distinct_from_initial_mute_and_settings(summary,rgb,audio):
    c=contract(preview_capabilities(),summary)
    assert c['rgb_required']==rgb and c['audio_required']==audio


def test_missing_real_services_are_not_synthesized_and_legacy_is_unchanged():
    caps=preview_capabilities();caps['services']=['display','buttons']
    c=contract(caps,'Lag Snake')
    assert not c['rgb_available'] and not c['audio_available']
    assert not c['rgb_required'] and not c['audio_required']
    caps.pop('app_sdk')
    assert contract(caps,'Lag Snake') is None


@pytest.mark.parametrize('mode,passes', [('none',False),('clear',False),('left',False),('both',True)])
def test_rgb_telemetry_measures_both_sides_beyond_truncated_trace(mode,passes):
    code='local step=0\nfunction init() end\nfunction update(dt) fire.display.pixel(10,10,1);step=step+1;'
    # 240 earlier pixel events exhaust the diagnostic trace before the RGB starts.
    code+='if step>245 and step<=255 then fire.rgb.set(step-246,'+('0' if mode=='clear' else '20')+',0,0) end;' if mode in {'both','clear'} else ''
    if mode=='left':code+='if step==246 then fire.rgb.set(0,20,0,0) end;'
    code+='end'
    r=request('');r.update(main_lua=code,required_services=['display','rgb'],preview_duration_ms=5000)
    result=simulate(r)
    assert len(result['trace'])==240 and not any(t[0]=='rgb' for t in result['trace'])
    proof=verify(contract(preview_capabilities(),'Lag klokke'),r['required_services'],result,'a'*64)
    assert proof['passed']==passes and proof['rgb']['left_nonzero']==(mode in {'left','both'})
    if mode=='both':assert result['rgb_feedback']['nonzero_indices']==list(range(10))


def test_fault_only_activity_and_stop_only_audio_are_not_feature_coverage():
    c=contract(preview_capabilities(),'Lag Snake')
    rgb={'left_nonzero':True,'right_nonzero':True,'writes':10}
    v={'profiles':[{'profile':'io_error','rgb_feedback':rgb,'jobs_started':{'speaker.tone':1}},
                   {'profile':'idle','jobs_started':{'speaker.stop':1}}]}
    assert not verify(c,['display','rgb','speaker','jobs'],v,'a'*64)['passed']
    v['profiles'][1].update(rgb_feedback=rgb,jobs_started={'speaker.tone':1})
    proof=verify(c,['display','rgb','speaker','jobs'],v,'a'*64)
    assert proof['passed'] and proof['audio']['speaker_jobs_started']==1
    assert not verify(c,['display','rgb'],v,'a'*64)['passed']
    v['io_coverage_missing']=['uart']
    assert not verify(c,['display','rgb','speaker','jobs'],v,'a'*64)['passed']


def test_real_speaker_job_is_exercised_by_enabling_initially_muted_audio():
    source='''local enabled=false;local started=false;local job=nil;local led=0
    function init() end
    function on_button(b,e) if b=="B" and e=="pressed" then enabled=true end end
    function update(dt)
      fire.display.pixel(10,10,31)
      if led<10 then fire.rgb.set(led,0,40,100);led=led+1 end
      if enabled and not started then job=fire.speaker.tone(440,100,255);started=true end
      if job then local state=fire.jobs.poll(job);if state.done then local result=fire.jobs.result(job);fire.jobs.close(job);job=nil end end
    end'''
    r=request('');r.update(main_lua=source,required_services=service_closure(['display','buttons','rgb','speaker'],SDK_VERSION))
    c=contract(preview_capabilities(),'Lag Snake med lyd av/på')
    muted=simulate(r)
    assert not verify(c,r['required_services'],muted,'a'*64)['passed']
    played=simulate({**r,'button_sequence':['B'],'interval_ms':250})
    proof=verify(c,r['required_services'],played,'a'*64)
    assert proof['passed'] and proof['audio']['speaker_jobs_started']==1


def test_rgb_aggregate_and_capture_modes_do_not_inflate_app_memory():
    source='local led=0;function init() end function update(dt) fire.ui.screen("RGB");if led<10 then fire.rgb.set(led,0,40,100);led=led+1 end end'
    r=request('');r.update(main_lua=source,required_services=['display','rgb'])
    plain=simulate(r);captured=simulate({**r,'capture_at_ms':[16,500,1000]})
    assert plain['app_memory_peak']==captured['app_memory_peak']
    assert plain['rgb_feedback']==captured['rgb_feedback']


def test_standard_context_is_single_authoritative_record_and_scope_bound():
    a=contract(preview_capabilities(),'Lag Snake');b=contract(preview_capabilities(),'Lag klokke uten RGB')
    context=context_with_contract(context_with_contract('actual context',a),b)
    assert context.count(MARKER)==1 and json.loads(context.split(MARKER)[1])==b
    assert a['request_sha256']!=b['request_sha256']
    assert 'actual context' in context and not b['physical_verified']


@pytest.mark.parametrize('newline',['\n','\r\n'])
def test_resume_recovers_core_tested_standard_baseline_not_later_broken_candidate(tmp_path,newline):
    from fire_backend.build_strategy import retained_standard_core
    source=newline.join(['function init() end','function update(dt) fire.ui.screen("CORE") end'])
    digest=hashlib.sha256(source.encode()).hexdigest()
    (tmp_path/'attempt-1.lua').write_bytes(source.encode('utf-8'))
    (tmp_path/'attempt-2.lua').write_text('broken syntax',encoding='utf-8')
    (tmp_path/'validation-1.json').write_text(json.dumps({'source_sha256':digest,'local_checks_passed':True}),encoding='utf-8')
    (tmp_path/'standard-verification-1.json').write_text(json.dumps({'source_sha256':digest,'passed':False}),encoding='utf-8')
    assert retained_standard_core(tmp_path,digest,2)==source
    assert retained_standard_core(tmp_path,'b'*64,2) is None
    (tmp_path/'attempt-1.lua').write_bytes((source+'--changed').encode('utf-8'))
    assert retained_standard_core(tmp_path,digest,2) is None


def test_delivery_proof_is_bound_to_source_scope_and_sdk_only():
    expected=contract(preview_capabilities(),'Lag klokke uten RGB')
    proof=verify(expected,['display'],{'profile':'idle'},'a'*64)
    package={'mode':'openai','manifest':{'api_version':SDK_VERSION,'checksum':'a'*64},
             'validation':{'suite':'release-v4','standard_contract':expected,'standard_verification':proof}}
    require_deliverable(package)
    for field in ('source','scope','proof'):
        bad=copy.deepcopy(package)
        if field=='source':bad['manifest']['checksum']='b'*64
        elif field=='scope':bad['validation']['standard_contract']['rgb_required']=True
        else:bad['validation'].pop('standard_verification')
        with pytest.raises(ValueError,match='standardkrav'):require_deliverable(bad)
    legacy=copy.deepcopy(package);legacy['manifest']['api_version']='fire-lua-0.2';legacy['validation'].pop('standard_verification')
    require_deliverable(legacy)


def test_delivery_grid_policy_matches_negotiated_sdk_and_preserves_legacy():
    p={'mode':'mock','manifest':{'api_version':SDK_VERSION},'validation':{'suite':'release-v4',
        'native_host_policy':'fire-native-host-v1','profiles':[{'max_callback_rgb_calls':1,'max_callback_grid_cells':200}]}}
    require_deliverable(p)
    p['manifest']['api_version']='fire-lua-0.2'
    with pytest.raises(ValueError,match='grid'):require_deliverable(p)


@pytest.mark.parametrize('body',[
    'fire.display.circle(0,120,8,31)',
    'fire.display.fill_circle(319,239,8,31)',
    'fire.display.rect(315,235,30,30,31)',
    'fire.display.fill_rect(315,235,30,30,31)',
    'fire.display.grid(318,238,8,8,1,1,{1},{0,31})',
    'fire.display.text(318,238,"clipped",31)',
])
def test_sdk_native_valid_edge_clipping_does_not_inherit_legacy_design_rejection(body):
    assert simulate(request(body))['ok']
    legacy=request(body);legacy.update(api_version='fire-lua-0.2',api_contract=API_CONTRACT)
    with pytest.raises(Exception,match='clipped'):simulate(legacy)


def test_actual_sdk_particles_accepts_native_valid_center_at_screen_edge():
    code='local p={{x=0,y=120,vx=0,vy=0,age=0,color=31}}; function init() end function update(dt) fire.ui.particles(p,0) end'
    r=request('');r['main_lua']=code
    assert simulate(r)['ok']


@pytest.mark.parametrize('body',[
    'fire.display.fill_circle(-1,120,2,31)', 'fire.display.circle(10,10,161,31)',
    'fire.display.fill_rect(0,0,321,2,31)', 'fire.display.rect(320,0,1,1,31)',
    'fire.display.grid(0,0,33,1,1,1,{1},{0,31})',
])
def test_sdk_edge_clipping_does_not_relax_native_input_bounds(body):
    with pytest.raises(Exception):simulate(request(body))


def test_sdk_empty_rectangle_is_not_a_complete_visible_scene():
    with pytest.raises(Exception,match='blank|visible|empty'):simulate(request('fire.display.rect(10,10,0,20,31)'))


def test_sdk_display_semantics_are_canonical_once_without_duplicate_methods():
    detail=generation_contract(SDK_VERSION,['display'])
    expected={k:v for k,v in canonical_sdk()['registry']['display'].items() if k!='methods'}
    assert detail['display_semantics']==expected and 'methods' not in detail['display_semantics']
    assert not generation_contract('fire-lua-0.2',['display']).get('display_semantics')


async def test_real_builder_retains_core_for_targeted_standard_repair_before_review(tmp_path,monkeypatch):
    from scripts import benchmark_app_sdk as benchmark
    from fire_backend.models import GeneratedApp
    from fire_backend.app_quality import FireAppReview
    from test_pre_delivery import approve
    calls=[];reviewed=[]
    original='function init() end function update(dt) fire.ui.screen("CORE") end'
    fixed=original+'\nlocal update_core=update;local led=0;function update(dt) update_core(dt);if led<10 then fire.rgb.set(led,0,40,100);led=led+1 end end'
    class Provider(benchmark.BenchmarkProvider):
        async def generate(self,summary,context,error=None,previous=None):
            calls.append((context,error,previous))
            assert json.loads(context.split(MARKER)[1])['rgb_required']
            return GeneratedApp(name='Klokke',required_services=['display']+(['rgb'] if len(calls)>1 else []),main_lua=fixed if len(calls)>1 else original)
        async def review(self,summary,context,generated,validation):
            reviewed.append(generated.main_lua)
            assert validation['standard_verification']['passed']
            return FireAppReview(**approve().model_dump(),kind='app',**{n:True for n in FireAppReview.fire_checks()})
        async def close(self):pass
    monkeypatch.setattr(benchmark,'BenchmarkProvider',Provider)
    result=await benchmark.run_case(tmp_path,SimpleNamespace(code_model='gpt-6-luna',review_model='gpt-6-luna'),
        'fake-key-only','clock','Lag en klokke.','sdk')
    assert result['status']=='ready',result['error']
    assert len(calls)==2 and reviewed==[fixed] and calls[1][2]==original
    assert 'BOTH' in calls[1][1] and result['commands_created']==0
    folder=tmp_path/'clock-sdk'/'builds'/result['build_id']
    strategy=json.loads((folder/'strategy-1.json').read_text(encoding='utf-8'))
    assert strategy['candidate_selected_as_baseline']
    assert strategy['repair_baseline_sha256']==hashlib.sha256(original.encode()).hexdigest()
    from fire_backend.storage import Store
    from fire_backend.security import Redactor
    from fire_backend.revalidation import revalidate_package
    store=Store(tmp_path/'clock-sdk',Redactor('fake-key-only'),128*1024*1024)
    assert (await revalidate_package(store,result['build_id'],apply=True))['status']=='passed'
    package=store.get('packages',result['build_id'])
    assert package['validation']['standard_verification']['passed']
    require_deliverable(package)

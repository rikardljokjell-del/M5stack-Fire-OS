import pytest

from fire_backend.app_quality import UX_POLICY_VERSION
from fire_backend.builds import validate_release
from fire_backend.lua_worker import simulate
from fire_backend.rendering import NATIVE_HOST_POLICY


def request(source):
    return dict(main_lua=source,required_services=['display','rgb'],api_version='fire-lua-0.2',
                max_memory=131072,max_runtime_ms=1000,profile='idle',native_host_policy=NATIVE_HOST_POLICY)


def test_rgb_aliases_and_first_frame_burst_are_rejected_before_delivery():
    source='''local leds=fire.rgb
function init() end
function update(dt)
 fire.display.text(0,0,'Level',65535)
 for i=0,3 do leds.set(i,0,10,42) end
end'''
    with pytest.raises(Exception,match='Native host RGB budget'):simulate(request(source))


def test_changed_led_queue_keeps_complete_frames_and_reaches_both_bars():
    source='''local i=0
function init() end
function update(dt)
 if i<10 then fire.rgb.set(i,0,10,42) i=i+1 end
 fire.display.text(0,0,'Level',65535)
end'''
    result=simulate({**request(source),'required_services':['display','rgb','imu'],'profile':'imu_flat'})
    assert result['max_callback_rgb_calls']==1
    assert result['min_update_draws']==1
    assert result['imu_scenes'][0]['leds']==[2602]*10
    assert len([c for c in result['trace'] if c[0]=='rgb'])==10


def test_grid_cell_cost_is_cumulative_even_for_tiny_black_cells():
    source='''local c={}
function init() for i=1,70 do c[i]=0 end end
function update(dt)
 fire.display.grid(0,0,1,1,14,5,c,{0})
 fire.display.grid(20,0,1,1,14,5,c,{0})
 fire.display.text(0,10,'Level',65535)
end'''
    with pytest.raises(Exception,match='Native host grid cell budget'):simulate(request(source))


async def test_live_release_enforces_host_guard_without_model_opt_in():
    class Log:
        def log(self,*args):pass
    app=request('function init() end function update(dt) fire.rgb.set(0,0,1,2) fire.rgb.set(9,0,1,2) end')
    app.pop('native_host_policy')
    app['experience_policy_version']=UX_POLICY_VERSION
    with pytest.raises(ValueError,match='Native host RGB budget'):
        await validate_release(app,Log(),'build-native-cost')


async def test_live_builder_repairs_burst_before_packaging_and_keeps_guard_at_delivery(tmp_path):
    import copy
    from fire_backend.ai import MockProvider
    from fire_backend.app_quality import FireAppReview
    from fire_backend.models import GeneratedApp,SessionStart
    from fire_backend.quality import require_deliverable
    from fire_backend.service import Backend
    from test_device_protocol import configured
    class Provider(MockProvider):
        attempts=0
        async def generate(self,summary,context,error=None,previous=None):
            self.attempts+=1
            if self.attempts>1:assert 'Native host RGB budget' in error
            extra='fire.rgb.set(9,0,10,42)' if self.attempts==1 else ''
            return GeneratedApp(name='Status',required_services=['display','rgb'],main_lua=
                'function init() end function update(dt) fire.rgb.set(0,0,10,42) '+extra+
                ' fire.display.text(0,0,"Status",65535) end')
        async def review(self,*args):
            return FireAppReview(requirements_met=True,runtime_safe=True,visual_quality_ok=True,issues=[],kind='app',
                                 **{name:True for name in FireAppReview.fire_checks()})
    provider=Provider();backend=Backend(configured(tmp_path).model_copy(update={'fire_ai_mode':'openai'}),provider)
    try:
        session=await backend.start(SessionStart());await backend.text(session,'Lag en sirkel')
        session.capabilities={'services':['display','rgb'],'api_version':'fire-lua-0.2','max_memory':131072,'max_runtime_ms':1000}
        await backend.confirm_build(session,session.proposal_id);await session.task
        package=backend.store.get('packages',session.package_id)
        assert provider.attempts==2 and len(backend.store.list('packages'))==1
        assert package['validation']['native_host_policy']==NATIVE_HOST_POLICY
        require_deliverable(package)
        for change in ({'max_callback_rgb_calls':2},{'max_callback_grid_cells':129},{'max_callback_rgb_calls':None}):
            bad=copy.deepcopy(package);bad['validation']['profiles'][0].update(change)
            with pytest.raises(ValueError,match='native RGB'):require_deliverable(bad)
        assert not backend.store.list('commands')
    finally:await backend.close()

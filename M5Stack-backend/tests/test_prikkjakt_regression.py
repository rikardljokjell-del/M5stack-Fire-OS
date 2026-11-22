import pytest
from fire_backend.lua_worker import simulate
from fire_backend.app_quality import APP_QUALITY_POLICY,experience_contract


def req(source,profile='start_b_idle'):
    return dict(main_lua=source,required_services=['display','buttons'],api_version='fire-lua-0.2',
                max_memory=131072,max_runtime_ms=1000,profile=profile)


def grid_source(height):
    return '''local started=false local cells={}
function init() for i=1,60 do cells[i]=0 end end
function on_button(b,a) if b=='B' then started=true end end
function update(dt)
 if started then fire.display.grid(16,36,24,HEIGHT,12,5,cells,{2016})
 else fire.display.text(8,8,'Menu',2016) end
end'''.replace('HEIGHT',str(height))


def test_start_b_reaches_heavy_gameplay_which_menu_only_profile_misses():
    assert simulate(req(grid_source(32),'idle'))['max_callback_grid_pixels']==0
    with pytest.raises(Exception,match='grid raster budget'):simulate(req(grid_source(32)))
    assert simulate(req(grid_source(20)))['max_callback_grid_pixels']==28800


def test_grid_budget_is_cumulative_not_just_per_call():
    source='function init() end function update(dt) '
    source+="local c={} for i=1,60 do c[i]=0 end fire.display.grid(0,0,24,20,12,5,c,{2016}) fire.display.grid(0,0,24,20,12,5,c,{2016}) end"
    with pytest.raises(Exception,match='grid raster budget'):simulate(req(source))


def test_apps_cannot_override_os_backlight_even_through_alias():
    r=req("local p=fire.power function init() p.brightness(255) end function update(dt) end")
    r['required_services']=['power']
    with pytest.raises(Exception,match='OS backlight'):simulate(r)


def test_rgb_music_and_master_settings_are_permanent_requirements():
    for phrase in ['BOTH','indices0..9','red=error/disconnected','blue=good/connected','melodic','OS master volume','backlight']:
        assert phrase in APP_QUALITY_POLICY
    c=experience_contract({'services':['display','rgb'],'audio_output':True})
    assert c['game_audio_required'] and not c['game_audio_available']
    assert 'OS master' in c['os_settings']['volume']


async def test_silent_game_is_not_delivered_when_firmware_lacks_game_audio(tmp_path):
    from fire_backend.ai import MockProvider
    from fire_backend.app_quality import FireAppReview
    from fire_backend.models import SessionStart
    from fire_backend.service import Backend
    from test_device_protocol import configured
    class Provider(MockProvider):
        async def review(self,*args):
            return FireAppReview(requirements_met=True,runtime_safe=True,visual_quality_ok=True,issues=[],kind='game',
                **{name:True for name in FireAppReview.fire_checks()})
    b=Backend(configured(tmp_path).model_copy(update={'fire_ai_mode':'openai'}),Provider())
    try:
        s=await b.start(SessionStart());await b.text(s,'Lag en sirkel')
        s.capabilities={'services':['display','buttons','rgb'],'max_memory':131072,'max_runtime_ms':16,'audio_output':True}
        await b.confirm_build(s,s.proposal_id);await s.task
        assert not s.package_id and not b.store.list('packages') and not b.store.list('commands')
        assert b.store.get('builds',s.build_id)['attempts']==1
    finally:await b.close()

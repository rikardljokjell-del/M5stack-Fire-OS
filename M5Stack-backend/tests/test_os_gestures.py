"""Synthetic gesture ownership and bounded ten-minute PC soak, not physical proof."""
import pytest

from fire_backend.builds import simulate as isolated_simulate
from fire_backend.lua_worker import simulate
from fire_backend.security import Redactor
from fire_backend.storage import Store


COUNTERS = '''
local clicks,raw=0,0
function init() end
function on_button(button,action)
  if action=='pressed' then clicks=clicks+1 end
end
function update(dt)
  if fire.buttons.pressed('A') or fire.buttons.pressed('B') or fire.buttons.pressed('C') then raw=raw+1 end
  fire.display.text(8,8,tostring(clicks),65535)
  fire.display.text(8,30,tostring(raw),65535)
end
'''


def request(profile,**extra):
    return dict(main_lua=COUNTERS,required_services=['display','buttons'],
                max_memory=131072,max_runtime_ms=0,profile=profile,test_horizon_ms=2000,**extra)


def counter_values(result,y):
    return [int(c[3]) for c in result['trace'] if c[0]=='text' and c[2]==y]


@pytest.mark.parametrize('profile,navigation,exited',[
    ('os_long_a','home',True),('os_long_b','quick_settings',False),('os_long_c','back',True),
])
def test_reserved_long_press_never_turns_into_app_short_press(profile,navigation,exited):
    result=simulate(request(profile))
    assert set(counter_values(result,8))=={0}
    assert max(counter_values(result,30))>0 # Raw down-state can exist before OS ownership.
    assert result['os_reserved_callbacks_suppressed']==1
    assert result['os_navigation']==navigation and result['os_exited'] is exited
    assert result['os_gesture_simulated'] is True
    if exited:
        assert 640<=result['elapsed_ms']<700 and result['frames']==40
    else:
        assert result['elapsed_ms']==2000 and result['os_updates_suspended']>0
        assert result['frames']<125 and result['update_count']==result['frames']


def test_os_double_click_suppresses_both_callbacks_and_pauses_for_shortcut():
    result=simulate(request('os_double'))
    assert set(counter_values(result,8))=={0}
    assert max(counter_values(result,30))>0
    assert result['os_reserved_callbacks_suppressed']==2
    assert result['os_navigation']=='configured_double_shortcut'
    assert result['os_updates_suspended']>0 and not result['os_exited']
    assert result['elapsed_ms']==2000


def test_existing_cycle_and_synthetic_hold_behaviour_is_preserved():
    cycle=simulate(request('cycle'))
    assert max(counter_values(cycle,8))>=3
    assert cycle['os_reserved_callbacks_suppressed']==0
    assert cycle['os_gesture_simulated'] is False
    held=simulate(request('hold_a'))
    assert set(counter_values(held,8))=={1}
    assert held['frames']==125 and held['os_reserved_callbacks_suppressed']==0
    assert not held['os_exited']


@pytest.mark.parametrize('horizon',[-1,0,999,600001,True,False,1000.0,'600000',[],{}])
def test_invalid_or_unbounded_test_horizons_are_rejected(horizon):
    data=request('idle');data['test_horizon_ms']=horizon
    with pytest.raises(ValueError,match='Test horizon'):simulate(data)


def test_positive_device_lifetime_cannot_be_extended_by_test_horizon():
    data=request('idle');data['max_runtime_ms']=1000
    with pytest.raises(ValueError,match='until-exit'):simulate(data)


def test_extended_soak_has_a_bounded_ten_minute_horizon():
    data=request('long_session');data.pop('test_horizon_ms')
    result=simulate(data)
    assert result['elapsed_ms']==600000 and result['frames']==37500
    assert len(result['trace'])<=240
    assert not result['os_gesture_simulated']


def test_late_failure_after_nine_minutes_is_detected():
    data=request('long_session');data['test_horizon_ms']=600000
    data['main_lua']='''
      local elapsed=0
      function init() end
      function update(dt)
        elapsed=elapsed+dt
        fire.display.circle(40,40,5,2016)
        if elapsed>540000 then fire.display.circle(999,40,5,2016) end
      end
    '''
    with pytest.raises(Exception,match='bounds'):simulate(data)
    data['test_horizon_ms']=60000
    assert simulate(data)['elapsed_ms']==60000 # The existing horizon cannot expose this path.


async def test_ten_minute_soak_runs_through_existing_isolated_worker(tmp_path):
    data=request('long_session');data['test_horizon_ms']=600000
    result=await isolated_simulate(data,Store(tmp_path,Redactor(),10_000_000),'build-long-session')
    assert result['ok'] and result['elapsed_ms']==600000

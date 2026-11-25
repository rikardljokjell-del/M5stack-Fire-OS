import json

import pytest

from fire_backend.builds import validate_release
from fire_backend.lua_worker import simulate


def app(source):
    return dict(main_lua='function init() end\n'+source, required_services=['display', 'buttons', 'rgb', 'imu'],
                api_version='fire-lua-0.2', max_memory=131072, max_runtime_ms=8000)


def test_ordinary_imu_vector_has_unit_gravity_and_valid_measurement_path():
    result = simulate({**app('''function update(dt)
 local v=fire.imu.accel() local g=v.x*v.x+v.y*v.y+v.z*v.z
 if math.abs(g-1)>0.0001 then error('invalid gravity fixture') end
 fire.display.grid(0,0,2,2,1,1,{1},{0,65535})
end'''), 'profile': 'idle'})
    assert result['imu_reads'] == result['frames']
    assert result['max_callback_grid_pixels'] == 4


@pytest.mark.parametrize('profile,expected', [
    ('imu_flat', ['0,0,10']*5),
    ('imu_tilt', ['-5,5,7']*5),
    ('imu_vertical', ['10,0,0']*5),
    ('imu_zero', ['0,0,0']*5),
    ('imu_recovery', ['-5,5,7','-5,5,7','0,0,0','10,0,0','-5,5,7']),
    ('imu_motion', ['0,0,10','0,0,10','-5,5,7','5,-5,7','0,0,10']),
])
def test_sensor_profiles_capture_actual_output_and_both_led_bars(profile, expected):
    result = simulate({**app('''function update(dt)
 local v=fire.imu.accel()
 fire.display.text(0,0,tostring(math.floor(v.x*10+0.5))..','..tostring(math.floor(v.y*10+0.5))..','..tostring(math.floor(v.z*10+0.5)),65535)
 fire.display.grid(0,10,2,2,2,1,{0,1},{0,65535})
 fire.display.fill_circle(25,25,3,65535)
 fire.rgb.set(0,1,2,3) fire.rgb.set(9,3,2,1)
end'''), 'profile': profile})
    scenes=result['imu_scenes']
    assert [s['texts'][0] for s in scenes] == expected
    assert scenes[0]['grids'][0]['cells'] == '01'
    assert scenes[0]['circles'] == [dict(x=25,y=25,r=3)]
    assert scenes[-1]['leds'] == [66051]+[0]*8+[197121]
    assert len(json.dumps(result)) < 40000


@pytest.mark.parametrize('profile,expected', [
    ('imu_calibration', ['','B','B','B','B']),
    ('imu_recovery', ['','B','BB','BBB','BBB']),
    ('imu_tolerance', ['','A','AC','ACC','ACC']),
    ('imu_flat', ['']*5),
    ('imu_motion', ['']*5),
])
def test_imu_buttons_are_timed_and_do_not_receive_generic_cycle_input(profile, expected):
    result=simulate({**app('''local seen=''
function on_button(b,a) if a=='pressed' then seen=seen..b end end
function update(dt) fire.display.text(0,0,'Seen:'..seen,65535) end'''), 'profile':profile})
    assert [s['texts'][0].removeprefix('Seen:') for s in result['imu_scenes']] == expected


async def test_every_imu_release_includes_sensor_profiles_and_keeps_physical_unverified(tmp_path):
    from fire_backend.storage import Store
    from fire_backend.security import Redactor
    # Release validation now persists real source-bound screenshots as well as
    # logs, so use the actual bounded store instead of a log-only stub.
    store=Store(tmp_path,Redactor('test-key-only'),16*1024*1024)
    result=await validate_release(app('function update(dt) fire.imu.accel() fire.display.text(0,0,"Level",65535) end'),store,'build-imu')
    sensor={r['profile']:r for r in result['profiles'] if r['profile'].startswith('imu_')}
    assert set(sensor)=={'imu_flat','imu_tilt','imu_vertical','imu_zero','imu_calibration','imu_recovery','imu_tolerance','imu_motion'}
    assert all(len(r['imu_scenes'])==5 for r in sensor.values())
    assert result['physical_verified'] is False

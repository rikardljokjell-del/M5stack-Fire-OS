"""Negotiated hardware SDK tests. None touches actual radios, pins or files."""
import copy
from importlib.resources import files

import pytest

from fire_backend.api_registry import API_CONTRACT, BASE_API, HARDWARE_API, REGISTRY, package_compatibility, preview_capabilities
from fire_backend.app_sdk import SDK_VERSION,SDK_CONTRACT
from fire_backend.builds import validate_release
from fire_backend.hardware_requests import hardware_goal
from fire_backend.lua_worker import simulate
from fire_backend.models import Capabilities, DialogReply, GeneratedApp
from fire_backend.service import Backend
from test_device_protocol import CAPS, configured
from test_repair_target import session


def request(source, **overrides):
    caps=preview_capabilities()
    # This helper deliberately tests the unchanged hardware0.2 profile, not
    # optional SDK-only services advertised alongside it by PC preview.
    return dict(main_lua=source,required_services=sorted(set(caps['services'])&set(REGISTRY['services'])),api_version=HARDWARE_API,
                hardware=caps['hardware'],max_memory=131072,max_runtime_ms=1000,profile='idle',**overrides)


def program(init='',update=''):
    return 'function init() '+init+' end function update(dt) '+update+" fire.display.text(4,4,'Test',2016) end"


def test_capabilities_require_exact_version_contract_and_bounded_resources():
    caps=preview_capabilities()
    assert Capabilities.model_validate(caps).api_contract==API_CONTRACT
    for change in ({'api_contract':'0'*64},{'api_version':BASE_API},{'hardware':None},{'services':['invented']}):
        with pytest.raises(ValueError):Capabilities.model_validate({**caps,**change})
    for kind,values in [('gpio_write',[36]),('gpio_read',[16]),('gpio_write',[6]),('pwm',[True]),('uart',[0]),('i2c',[0,0])]:
        bad=copy.deepcopy(caps);bad['hardware'][kind]=values
        with pytest.raises(ValueError):Capabilities.model_validate(bad)


def test_every_registry_method_has_arguments_and_explicit_result_contract():
    assert len(REGISTRY['services'])==20
    for service,spec in REGISTRY['services'].items():
        for method,definition in spec['methods'].items():
            assert isinstance(definition['args'],list),(service,method)
            assert definition['since'] in {BASE_API,HARDWARE_API}
            assert definition['returns']
            if definition['returns']=='job':assert definition['result'] and 'jobs' in definition['requires']


@pytest.mark.parametrize('body',[
    'fire.i2c.scan(5)', 'fire.i2c.write(0,104,{1})', 'fire.gpio.mode(16,"output")',
    'fire.gpio.mode(36,"input_pullup")', 'fire.pwm.configure(26,20000,12)',
    'fire.pwm.configure(26,1000,8);fire.pwm.write(26,256)',
    'fire.uart.open(0,9600,36,26,"8N1")', 'fire.uart.open(2,9600,26,26,"8N1")',
    'fire.sd.read("../other/key",0,8)', 'fire.sd.write("/firmware/a.bin","x",false)',
    'fire.wifi.request("GET","file:///private"," ")',
    'fire.wifi.request("GET","https://user:secret@example.org","")',
    'fire.spi.transfer(2,{256})', 'fire.i2c.read(0,64,-1,129)',
    'local s=("x")["rep"]("x",1000000)', 'local s=string.rep("x",1000000)',
    'local f=fire.i2c;f.missing(0)',
    'for i=1,65 do fire.mic.level() end',
])
def test_malformed_unsafe_or_excessive_hardware_calls_rejected(body):
    with pytest.raises(Exception):simulate(request(program(body)))


def test_pin_broker_does_not_steal_uart_or_pwm_resources():
    # Fail the test via a deliberately absent global if a required invariant fails.
    code='''
      if not fire.gpio.mode(26,'output') then bad() end
      local ok,err=fire.pwm.configure(26,1000,8)
      if ok or err~='busy' then bad() end
      fire.gpio.release(26)
      if not fire.pwm.configure(26,1000,8) then bad() end
      ok,err=fire.uart.open(2,9600,36,26,'8N1')
      if ok or err~='busy' then bad() end
      fire.pwm.stop(26)
      if not fire.uart.open(2,9600,36,26,'8N1') then bad() end
      fire.uart.close(2)
      if not fire.gpio.mode(26,'output') then bad() end
    '''
    r=simulate(request(program(code)))
    assert r['resources_used']=={'gpio_write':[26],'pwm':[26],'uart':[2],'gpio_read':[36]}


def test_job_backpressure_cancellation_close_and_no_side_effect_from_cancel():
    code='''
      local ids={}
      for i=1,4 do ids[i]=fire.sd.write('never.txt','x',true) end
      local id,err=fire.i2c.scan(0)
      if id or err~='busy' then bad() end
      for i=1,4 do
        fire.jobs.cancel(ids[i])
        local s=fire.jobs.poll(ids[i]);local r=fire.jobs.result(ids[i])
        if s.state~='cancelled' or r.ok then bad() end
        fire.jobs.close(ids[i])
      end
      if not fire.i2c.scan(0) then bad() end
    '''
    r=simulate(request(program(code)))
    assert r['max_jobs']==4


@pytest.mark.parametrize('profile,expected',[('idle','ready'),('io_error','failed'),('io_disconnect','failed'),('io_timeout','failed')])
def test_async_jobs_complete_with_typed_success_or_fault(profile,expected):
    source='''
      local id,done=nil,false
      function init() id=fire.i2c.scan(0) end
      function update(dt)
        if id then
          local status=fire.jobs.poll(id)
          if status.done then
            if status.state~='EXPECTED' then bad() end
            local r=fire.jobs.result(id)
            if status.state=='ready' and (not r.ok or r.addresses[1]~=64) then bad() end
            if status.state=='failed' and (r.ok or r.error_code=='') then bad() end
            fire.jobs.close(id);id=nil;done=true
          end
        end
        if fire.time.millis()>64000 and not done then bad() end
        fire.display.text(4,4,'I2C',2016)
      end
    '''.replace('EXPECTED',expected)
    r=request(source);r.update(profile=profile,max_runtime_ms=5000)
    assert simulate(r)['ok']


@pytest.mark.parametrize('body',[
    "local r=fire.imu.gyro();if r.x~=0 then bad() end;fire.imu.temperature()",
    "fire.gpio.mode(26,'output');fire.gpio.write(26,1);fire.gpio.read(26);fire.gpio.release(26)",
    "fire.adc.read(36);fire.dac.write(26,128);fire.dac.stop(26)",
    "fire.pwm.configure(26,1000,8);fire.pwm.write(26,128);fire.pwm.stop(26)",
    "fire.uart.open(2,9600,36,26,'8N1');fire.uart.write(2,'hello');fire.uart.read(2,16);fire.uart.close(2)",
    "fire.i2c.read(0,64,0,16);fire.i2c.write(0,64,{1,2})",
    "fire.wifi.status();fire.wifi.scan();fire.wifi.connect('saved');fire.wifi.request('GET','https://example.org','');fire.wifi.disconnect()",
    "fire.bluetooth.scan('ble');fire.bluetooth.read_gatt('addr','service','char');fire.bluetooth.write_gatt('addr','service','char',{1})",
    "fire.mic.level();fire.mic.record('test.wav',1000,16000);fire.speaker.tone(440,100,50);fire.speaker.play('test.wav',50);fire.speaker.stop()",
    "fire.sd.mkdir('logs');fire.sd.list('');fire.sd.write('a.txt','x',false);fire.sd.read('a.txt',0,16);fire.sd.remove('a.txt')",
    "fire.power.status();fire.power.sleep(100);fire.rtc.now();fire.rtc.set(1795305600)",
    "local t={1,2};table.insert(t,3);table.remove(t);if table.concat(t,',')~='1,2' or ('AB'):sub(1,1)~='A' then bad() end",
])
def test_hardware_service_smokes_are_synthetic_and_bounded(body):
    assert simulate(request(program(body)))['hardware_simulated']


def test_new_rendering_methods_and_spi_with_explicit_free_pin_profile():
    r=request(program("fire.spi.open(2,18,19,23,27,1000000,0);fire.spi.transfer(2,{1,2});fire.spi.close(2)",
        "fire.display.fill_rect(10,10,20,20,2016);fire.display.fill_circle(60,60,8,2016);fire.display.pixel(90,90,2016);fire.display.grid(100,100,4,4,2,2,{0,1,1,0},{0,2016})"))
    r['hardware'].update(gpio_read=[19],gpio_write=[18,23,27],spi=[2])
    assert simulate(r)['resources_used']['spi']==[2]


def test_full_sdk_fits_pc_host_but_app_allocations_still_have_a_limit():
    assert simulate(request(program()))['app_memory_peak']<131072
    body='local t={} function init() end function update(dt) for i=1,300 do t[#t+1]={1,2,3,4} end fire.display.text(4,4,"Test",2016) end'
    with pytest.raises(Exception,match='memory|Memory'):simulate(request(body))


def test_tetris_text_heavy_frame_is_rejected_but_compact_rows_pass():
    def rows(width):
        return program('',f"for y=1,16 do fire.display.text(16,y*10,'{'|'+'  |'*10 if width==31 else '.'*10}',65535) end")
    with pytest.raises(Exception,match='text budget'):simulate(request(rows(31)))
    assert simulate(request(rows(10)))['max_callback_text_bytes']<256


async def test_toolbox_runs_all_ten_release_profiles_and_tracks_resources(tmp_path):
    backend=Backend(configured(tmp_path))
    try:
        code=files('fire_backend').joinpath('data/toolbox.lua').read_text(encoding='utf-8')
        r=request(code);r['required_services']=['display','buttons','jobs','i2c','gpio','pwm','uart']
        result=await validate_release(r,backend.store,'build-toolbox')
        assert result['suite']=='release-v4' and len(result['profiles'])==10
        assert result['physical_verified'] is False
        assert 26 in result['resources_used']['gpio_write']
    finally:await backend.close()


async def test_missing_firmware_keeps_exact_goal_and_never_substitutes_demo(tmp_path):
    backend=Backend(configured(tmp_path))
    try:
        s,peer=await session(backend)
        text='Lag en electronics toolbox med I2C-scanner, GPIO-tester, PWM og UART-terminal.'
        await backend.text(s,text)
        project=backend.store.get('projects',s.project_id)
        assert project['pending_hardware_request']['request']==text
        assert set(project['pending_hardware_request']['required_services'])=={'i2c','gpio','pwm','uart','jobs'}
        assert not s.proposal_id and not backend.store.list('builds')
        assert any(e['type']=='capability_required' for e in peer.events)
        assert 'IMU' not in s.history[-1]['content']
        await backend.text(s,'Lag appen.')
        assert not s.proposal_id and backend.store.get('projects',s.project_id)['pending_hardware_request']['request']==text
    finally:await backend.close()


async def test_negotiated_sdk_builds_versioned_package_and_legacy_device_cannot_install(tmp_path):
    backend=Backend(configured(tmp_path))
    class Provider:
        async def connect_dialog(self,context):return None,None
        async def close(self):pass
        async def dialog(self,history,context,connection):
            assert 'fire-lua-0.2' in context and 'PC hardware preview' in context
            return DialogReply(message='I2C-skanner med ikke-blokkerende status.',build_summary='Lag I2C-skanner',clarification_needed=False)
        async def generate(self,*args):
            return GeneratedApp(name='I2C skanner',main_lua=program('fire.i2c.scan(0)'),required_services=['display','i2c','jobs'])
    backend.provider=Provider();backend.builder.provider=backend.provider
    try:
        pc=await backend.desktop_conversation('fire-01',hardware_preview=True)
        await backend.text(pc,'Lag en I2C-skanner')
        assert pc.proposal_id and not backend.store.list('packages')
        await backend.confirm_build(pc,pc.proposal_id);await pc.task
        package=backend.store.get('packages',pc.package_id)
        # Explicit PC hardware preview now also advertises the optional App SDK;
        # the hardware wire contract itself remains 0.2 and unchanged.
        assert package['manifest']['api_version']==SDK_VERSION and package['manifest']['api_contract']==SDK_CONTRACT
        assert package['validation']['hardware_simulated']
        assert package_compatibility(package,CAPS)
        assert not package_compatibility(package,preview_capabilities())
        bad=preview_capabilities();bad['hardware']['i2c']=[]
        assert package_compatibility(package,bad)
        assert not backend.store.list('commands')
    finally:await backend.close()


def test_followups_retain_requirements_without_inventing_built_in_gps():
    first=hardware_goal('Lag I2C-scanner og GPS-tester')
    assert set(first['required_services'])=={'i2c','uart','jobs'}
    second=hardware_goal('Legg til PWM tester',first)
    assert set(second['required_services'])=={'i2c','uart','pwm','jobs'}

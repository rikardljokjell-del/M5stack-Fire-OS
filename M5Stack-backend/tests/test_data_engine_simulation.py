import pytest

from fire_backend.api_registry import methods_for, service_closure, generation_contract
from fire_backend.app_sdk import SDK_VERSION, SDK_CONTRACT
from fire_backend.data_contract import EXTENSION
from fire_backend.lua_worker import simulate


def run(source, services=None, **changes):
    return simulate({'main_lua':source,'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT,
        'data_engine':EXTENSION,'required_services':services or ['display','buttons','data','sd','jobs'],
        'profile':'idle','preview_duration_ms':1500,'native_host_policy':'fire-native-host-v1',**changes})


def test_data_create_append_seal_read_share_existing_jobs_and_keep_simulation_label():
    source='''local job,id,step=nil,nil,0
function init() fire.ui.set_theme('modern_dark') end
function update(dt)
 if job then
  local status=fire.jobs.poll(job)
  if status.done then
   local r=fire.jobs.result(job);fire.jobs.close(job);job=nil
   if not r.ok then error('Data fixture failed') end
   if step==1 then id=r.dataset_id
   elseif step==4 then if r.bytes[1]~=65 or r.bytes[2]~=0 or r.bytes[3]~=255 then error('Raw bytes changed') end end
  end
 elseif step==0 then job=fire.data.create('Signal','binary','{}');step=1
 elseif step==1 then job=fire.data.append(id,{65,0,255});step=2
 elseif step==2 then job=fire.data.seal(id);step=3
 elseif step==3 then job=fire.data.read(id,0,3);step=4 end
 fire.ui.screen('DATA','PC fixture')
end'''
    result=run(source)
    assert result['ok'] and result['data_engine_simulated'] and not result['native_timing_measured']
    assert result['max_jobs']==1 and result['jobs_started']['data.read']==1


def test_develop_only_from_actual_button_and_data_payload_bound_is_enforced():
    source='''function init() end
function update(dt)
 if fire.data.develop('update','Improve') then error('Update cannot invent a user click') end
 fire.ui.screen('DATA','PC fixture')
end
function on_button(b,a) if a=='pressed' then fire.data.develop('feedback','Measured result') end end'''
    assert run(source)['ok']
    bad='''function init() end
function update(dt) fire.data.append('data-one',string.char(1,2,3)) fire.ui.screen('DATA','PC') end'''
    # No permissive source-side string/loader capability is introduced.
    assert run(bad)['ok']  # Invalid handle is a normal recoverable job admission failure.


def test_optional_raw_ble_does_not_change_old_bluetooth_closure_and_validates_tlv():
    old=service_closure(['display','bluetooth'],SDK_VERSION)
    assert 'data' not in old
    assert 'advertise_raw' not in methods_for(SDK_VERSION,old)['bluetooth']
    services=service_closure(['display','bluetooth','data'],SDK_VERSION)
    assert {'data','jobs','sd'}<=set(services)
    assert 'advertise_raw' in generation_contract(SDK_VERSION,services)['services']['bluetooth']
    source='''local sent=false
function init() end
function update(dt)
 if not sent then sent=true;fire.bluetooth.advertise_raw({2,1,6,3,3,171,205},100) end
 fire.ui.screen('BLE','PC fixture')
end'''
    assert run(source,services)['jobs_started']['bluetooth.advertise_raw']==1
    with pytest.raises(Exception,match='TLV'):
        run(source.replace('{2,1,6,3,3,171,205}','{5,1,6}'),services)
    with pytest.raises(ValueError,match='undeclared'):
        run(source,old)


def test_data_extension_exact_hash_and_storage_dependencies_required():
    source='function init() end function update(dt) fire.ui.screen("DATA","PC") end'
    with pytest.raises(ValueError,match='Data Engine'):
        run(source,data_engine={'version':EXTENSION['version'],'contract':'0'*64})
    with pytest.raises(ValueError,match='Data Engine'):
        run(source,['display','data','jobs'])


def test_actual_radio_methods_modes_and_legacy_absence_are_enforced():
    from fire_backend.api_registry import package_compatibility, preview_capabilities
    services=service_closure(['display','bluetooth'],SDK_VERSION)
    source='''local started=false
function init() end
function update(dt) if not started then started=true;fire.bluetooth.scan('ble') end fire.ui.screen('BLE') end'''
    methods={'bluetooth':['scan','read_gatt','write_gatt','advertise','close']}
    modes={'bluetooth.scan':['ble']}
    result=run(source,services,service_methods=methods,service_modes=modes)
    assert result['service_modes_used']==modes
    with pytest.raises(Exception,match='argument|enum|mode'):
        run(source.replace("'ble'","'classic'"),services,service_methods=methods,service_modes=modes)
    with pytest.raises(ValueError,match='undeclared'):
        run(source.replace("fire.bluetooth.scan('ble')","fire.bluetooth.connect('address',100)"),services,service_methods=methods)
    caps=preview_capabilities();caps.update(service_methods=methods,service_modes=modes)
    manifest={'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT,'required_services':services}
    assert not package_compatibility({'manifest':manifest,'validation':result},caps)
    bad={**result,'service_modes_used':{'bluetooth.scan':['classic']}}
    assert 'modus' in package_compatibility({'manifest':manifest,'validation':bad},caps)
    assert not package_compatibility({'manifest':manifest,'validation':bad},preview_capabilities())


def test_capture_rejects_unannounced_sources_and_outside_actual_rate_bounds():
    source='''local done=false
function init() end
function update(dt)
 if not done then done=true;local id,e=fire.data.record('imu','{"duration_ms":1000,"sample_rate_hz":200}');if id or e~='invalid_argument' then error('rate guard') end end
 fire.ui.screen('IMU')
end'''
    capture={'capture_sources':['imu'],'capture_limits':{'imu':{'duration_ms_max':60000,'sample_rates_hz':[50,100]}}}
    assert run(source,['display','data','sd','jobs','imu'],data_capture=capture)['ok']


@pytest.mark.parametrize('capture_source,service,kind,rate,samples',[
    ('imu','imu','csv',100,200),('mic','mic','audio',8000,16000),
    ('ble.advertisements','bluetooth','text',None,2)])
def test_record_fixture_metadata_reaches_actual_sampling_branches_without_large_raw_tables(capture_source,service,kind,rate,samples):
    import json
    options={'duration_ms':2000}
    bounds={'duration_ms_max':10000}
    if rate:options['sample_rate_hz']=rate;bounds['sample_rates_hz']=[rate]
    else:bounds['max_records']=100
    source='''local job,done=nil,false
function init() end
function update(dt)
 if not job and not done then job=fire.data.record(SOURCE,OPTIONS)
 elseif job and fire.jobs.poll(job).done then
  local result=fire.jobs.result(job);fire.jobs.close(job);job=nil;done=true
  if not result.ok or result.kind~=KIND or result.samples~=SAMPLES then error('capture metadata') end
 end
 fire.ui.screen('Capture')
end'''.replace('SOURCE',json.dumps(capture_source)).replace('OPTIONS',"'"+json.dumps(options)+"'").replace('KIND',json.dumps(kind)).replace('SAMPLES',str(samples))
    capture={'capture_sources':[capture_source],'capture_limits':{capture_source:bounds}}
    result=run(source,['display','data','sd','jobs',service],data_capture=capture)
    assert result['ok'] and result['data_engine_simulated'] and result['jobs_started']['data.record']==1

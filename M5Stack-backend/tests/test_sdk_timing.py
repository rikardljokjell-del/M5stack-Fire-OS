"""Native phase declarations stay distinct from PC guards and measured evidence."""
import copy

import pytest

from fire_backend.app_sdk import SDK_VERSION,SDK_CONTRACT,callback_budgets,contract
from fire_backend.api_registry import API_CONTRACT,REGISTRY,generation_contract,preview_capabilities
from fire_backend.app_quality import experience_contract
from fire_backend.lua_worker import simulate
from fire_backend.models import Capabilities,Manifest


@pytest.mark.parametrize('sdk',[False,True])
def test_canonical_phase_facts_propagate_without_changing_legacy_hardware(sdk):
    api=SDK_VERSION if sdk else 'fire-lua-0.2'
    expected={'callback_ms':12,'init_callback_ms':250}
    if sdk:expected['sdk_update_callback_ms']=24
    assert callback_budgets(api)==expected
    caps=preview_capabilities()
    if not sdk:caps.pop('app_sdk')
    limits=experience_contract(caps)['limits']
    assert {key:limits[key] for key in expected}==expected
    assert ('sdk_update_callback_ms' in limits)==sdk
    original=copy.deepcopy(REGISTRY)
    generated=generation_contract(api,['display'])['limits']
    assert REGISTRY==original and generated['io_calls_per_callback']==64
    assert generated['io_bytes_per_callback']==2048 and generated['text_bytes_per_callback']==256
    if sdk:assert {key:generated[key] for key in expected}==expected
    else:assert generated==REGISTRY['limits']
    result=simulate(dict(main_lua='function init() end function update(dt) fire.display.pixel(0,0,1) end',
        required_services=['display'],api_version=api,api_contract=SDK_CONTRACT if sdk else API_CONTRACT,
        max_memory=131072,max_runtime_ms=32,profile='idle',native_host_policy='fire-native-host-v1'))
    assert result['native_callback_budgets']==expected
    assert result['native_timing_measured'] is False


@pytest.mark.parametrize('phase',['init','update','on_button'])
def test_update_time_calibration_does_not_relax_pc_instruction_guard(phase):
    bodies={'init':'','update':'fire.display.pixel(0,0,1)','on_button':''}
    bodies[phase]='while true do local x=1 end'
    source='function init() '+bodies['init']+' end function update(dt) '+bodies['update']+' end function on_button(b,e) '+bodies['on_button']+' end'
    with pytest.raises(Exception,match='Instruction budget exceeded'):
        simulate(dict(main_lua=source,required_services=['display','buttons'],api_version=SDK_VERSION,
            api_contract=SDK_CONTRACT,max_memory=131072,max_runtime_ms=256,profile='idle',
            button_sequence=['B'],interval_ms=100,native_host_policy='fire-native-host-v1'))
    budgets=contract()['registry']['budgets']
    assert budgets['callback_instructions']==200000 and budgets['lua_memory_bytes']==131072
    assert budgets['sdk_grid_cells_per_callback']==384 and budgets['sdk_grid_pixels_per_callback']==32768


@pytest.mark.parametrize('old',[
    '83310c217698dd968f3773842f7f3fa05bc73b487a7c7f1cffefa33acec40667',
    '64d1f826d3ac1af5fa041a7aaf1a82a8af6dd1f57ea30ae1020421db34f67857',
])
def test_intermediate_experimental_contracts_are_not_live_compatible(old):
    caps=preview_capabilities();caps['app_sdk']['contract']=old
    with pytest.raises(ValueError):Capabilities.model_validate(caps)
    with pytest.raises(ValueError):Manifest.model_validate(dict(id='timing-test',name='Test',version='0.1.1',
        api_version=SDK_VERSION,api_contract=old,required_services=['display'],permissions=['fire.display'],checksum='a'*64))

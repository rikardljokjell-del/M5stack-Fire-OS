"""Canonical per-VM SDK background, one-shot clear reuse and actual PNGs."""
import json
from io import BytesIO

from PIL import Image
import pytest

from fire_backend.api_registry import API_CONTRACT,preview_capabilities,generation_contract
from fire_backend.app_sdk import SDK_VERSION,SDK_CONTRACT,contract
from fire_backend.lua_worker import simulate
from fire_backend.models import Manifest,Capabilities
from fire_backend.security import Redactor
from fire_backend.storage import Store
from fire_backend.visual_preview import save_screenshots
from fire_backend.visual_simulator import render_frame,rgb565
from fire_backend.sdk_context import normalize,POLICY,VERSION,MARKER


def app(update,init='',button='',**extra):
    source='function init() '+init+' end\nfunction update(dt) '+update+' end\n'
    if button:source+='function on_button(b,e) '+button+' end'
    return dict(main_lua=source,required_services=['display'],api_version=SDK_VERSION,api_contract=SDK_CONTRACT,
        max_memory=131072,max_runtime_ms=0,preview_duration_ms=32,profile='idle',capture_at_ms=[16,32],
        native_host_policy='fire-native-host-v1',**extra)


def png(frame):return Image.open(BytesIO(render_frame(frame).png)).convert('RGB')


def test_init_config_prepares_first_frame_without_becoming_a_paint_call():
    r=simulate(app('fire.display.clear(31);fire.display.pixel(0,0,65535)','fire.display.set_background(31)'))
    assert r['elided_clears']==2 and r['real_clears']==0 and r['max_io_calls']==2
    assert r['io_calls']['display.set_background']==1
    assert r['max_callback_display_work']==0  # legacy pixel proxy is zero; OS fill not app work
    for frame in r['visual_frames']:
        assert frame['frame_background']==31 and len(frame['ops'])==2
        image=png(frame);assert image.getpixel((2,2))==rgb565(31) and image.getpixel((0,0))==rgb565(65535)


def test_default_first_frame_and_each_new_vm_are_black():
    blue=simulate(app('fire.display.pixel(0,0,65535)','fire.display.set_background(31)'))
    black=simulate(app('fire.display.pixel(0,0,65535)'))
    assert blue['visual_frames'][0]['frame_background']==31
    assert black['visual_frames'][0]['frame_background']==0 and black['next_background']==0


def test_update_configuration_latches_only_on_following_frame():
    r=simulate(app('fire.display.set_background(31);fire.display.clear(31);fire.display.pixel(0,0,65535)'))
    assert [f['frame_background'] for f in r['visual_frames']]==[0,31]
    assert r['real_clears']==1 and r['elided_clears']==1
    assert png(r['visual_frames'][0]).getpixel((2,2))==rgb565(31)
    assert png(r['visual_frames'][1]).getpixel((2,2))==rgb565(31)


def test_pending_different_background_does_not_dirty_current_pristine_frame():
    result=simulate(app('fire.display.set_background(2016);fire.display.clear(31);fire.display.pixel(0,0,65535)',
                        'fire.display.set_background(31)'))
    assert [f['frame_background'] for f in result['visual_frames']]==[31,2016]
    assert result['elided_clears']==1 and result['real_clears']==1


def test_config_is_not_visible_output_or_a_hidden_first_ui_background():
    with pytest.raises(Exception,match='no visible output'):
        simulate(app('fire.display.set_background(31)'))
    unprimed=simulate(app('fire.ui.screen("UNPRIMED")'))
    assert unprimed['next_background']==0 and unprimed['real_clears']==2 and unprimed['elided_clears']==0


def test_button_configuration_is_allowed_and_latched_before_same_next_update():
    r=app('fire.display.clear(31);fire.display.pixel(0,0,65535)',button='fire.display.set_background(31)')
    r.update(required_services=['display','buttons'],button_sequence=['B'])
    result=simulate(r)
    assert result['visual_frames'][0]['frame_background']==31 and result['elided_clears']==2


@pytest.mark.parametrize('update,elided,real',[
    ('fire.display.clear(31);fire.display.clear(31);fire.display.pixel(2,2,1)',1,1),
    ('fire.display.clear(2016);fire.display.pixel(2,2,1)',0,1),
    ('fire.display.pixel(0,0,65535);fire.display.clear(31);fire.display.pixel(2,2,1)',0,1),
    ('fire.display.clear(2016);fire.display.clear(31);fire.display.pixel(2,2,1)',0,2),
])
def test_later_mismatch_and_after_paint_clear_really_erase(update,elided,real):
    r=app(update,'fire.display.set_background(31)');r['preview_duration_ms']=16;r['capture_at_ms']=[16]
    result=simulate(r)
    assert result['elided_clears']==elided and result['real_clears']==real
    expected=2016 if 'clear(2016)' in update and 'clear(31)' not in update else 31
    assert png(result['visual_frames'][0]).getpixel((0,0))==rgb565(expected)


PAINTS=[
 'fire.display.circle(20,20,2,31)', 'fire.display.rect(0,0,0,1,31)',
 'fire.display.line(0,0,1,1,31)','fire.display.text(0,0,"",31)',
 'fire.display.fill_rect(0,0,1,1,31)','fire.display.fill_circle(0,0,0,31)',
 'fire.display.pixel(0,0,31)','fire.display.grid(0,0,1,1,1,1,{0},{31})',
 'fire.display.text_style(0,0,"",31)',
 'fire.display.asset(-100,-100,"icon.timer")','fire.display.round_rect(0,0,1,1,0,31)',
 'fire.display.triangle(0,0,1,0,1,1,31)','fire.display.polyline({0,0,1,1},31)',
 'fire.display.polygon({0,0,1,0,1,1},31)','fire.display.gradient_rect(0,0,1,1,31,31)',
 'fire.display.arc(0,0,1,0,0,31)',
]


@pytest.mark.parametrize('paint',PAINTS)
def test_all_canonical_paint_methods_invalidate_even_if_clipped_empty_or_same_color(paint):
    r=app(paint+';fire.display.clear(31);fire.display.pixel(2,2,1)','fire.display.set_background(31)')
    r['preview_duration_ms']=16;r['capture_at_ms']=[16]
    result=simulate(r)
    assert result['elided_clears']==0 and result['real_clears']==1


def test_measurement_queries_rgb_and_configuration_do_not_dirty_or_paint():
    r=app('fire.display.measure_text("x");fire.display.set_background(31);fire.time.millis();fire.imu.accel();fire.buttons.pressed("A");fire.rgb.set(0,1,2,3);fire.display.clear(31);fire.display.pixel(2,2,1)',
          'fire.display.set_background(31)')
    r['required_services']=['display','time','imu','buttons','rgb']
    result=simulate(r)
    assert result['elided_clears']==2 and result['real_clears']==0 and result['max_io_calls']==8
    assert all(op[0]!='set_background' for f in result['visual_frames'] for op in f['ops'])


@pytest.mark.parametrize('value',['-1','65536','0.5','true','0/0'])
def test_configuration_keeps_strict_native_input_bounds(value):
    with pytest.raises(Exception):simulate(app('fire.display.set_background('+value+');fire.display.pixel(0,0,1)'))


def test_config_and_elided_clears_still_use_combined64_io_and_logical_bytes():
    result=simulate(app('for i=1,63 do fire.display.set_background(0) end;fire.display.pixel(0,0,1)'))
    assert result['max_io_calls']==64 and result['max_io_bytes']==64
    with pytest.raises(Exception,match='I/O budget'):
        simulate(app('for i=1,64 do fire.display.set_background(0) end;fire.display.pixel(0,0,1)'))
    with pytest.raises(Exception,match='I/O budget'):
        simulate(app('for i=1,64 do fire.display.clear(0) end;fire.display.pixel(0,0,1)'))


def test_init_clear_does_not_acknowledge_or_set_next_os_background():
    result=simulate(app('fire.display.clear(31);fire.display.pixel(0,0,1)','fire.display.clear(31)'))
    assert result['elided_clears']==0 and result['real_clears']==3 and result['next_background']==0


def test_legacy_api_black_prefill_and_conservative_clear_order_are_unchanged():
    simulate(app('fire.display.pixel(0,0,65535)','fire.display.set_background(31)'))
    r=app('fire.display.pixel(0,0,31)');r.update(api_version='fire-lua-0.2',api_contract=API_CONTRACT)
    assert simulate(r)['visual_frames'][0]['frame_background']==0
    r['main_lua']='function init() end function update(dt) fire.display.set_background(31);fire.display.pixel(0,0,1) end'
    with pytest.raises(ValueError,match='Unknown'):simulate(r)
    r['main_lua']='function init() end function update(dt) fire.display.pixel(0,0,31);fire.display.clear(0);fire.display.pixel(1,1,1) end'
    with pytest.raises(Exception,match='clear at most once'):simulate(r)


def test_background_configuration_never_grants_undeclared_display_permission():
    request=app('fire.display.set_background(31)');request['required_services']=['buttons']
    with pytest.raises(ValueError,match='display permission'):simulate(request)


def test_actual_png_background_and_dedup_include_host_color_without_extra_ops(tmp_path):
    ops=[['pixel',0,0,65535]]
    a={'frame_background':31,'ops':ops};b={'frame_background':2016,'ops':ops}
    assert png(a).getpixel((2,2))==rgb565(31) and png(b).getpixel((2,2))==rgb565(2016)
    assert png({'ops':ops}).getpixel((2,2))==rgb565(0)
    store=Store(tmp_path,Redactor(''),4*1024*1024)
    evidence=save_screenshots([a,b],store,'test-prefill','a'*64)
    assert len(evidence['frames'])==2
    assert {f['frame_background'] for f in evidence['frames']}=={31,2016}


def test_new_canonical_method_hash_capability_and_manifest_are_explicit():
    assert 'set_background' in generation_contract(SDK_VERSION,['display'])['services']['display']
    assert contract()['registry']['display']['frame_preparation']['default_background']==0
    caps=preview_capabilities();Capabilities.model_validate(caps)
    m=dict(id='sdk-test',name='SDK',version='0.1.1',api_version=SDK_VERSION,api_contract=SDK_CONTRACT,
        required_services=['display'],permissions=['fire.display'],checksum='a'*64)
    Manifest.model_validate(m)
    old='e6972ef535053a898babec4b532be7418941d6adc00c5fd477828bb0b9940e57'
    with pytest.raises(ValueError):Manifest.model_validate({**m,'api_contract':old})
    caps['app_sdk']['contract']=old
    with pytest.raises(ValueError):Capabilities.model_validate(caps)


@pytest.mark.parametrize('version',[3,4])
def test_retained_context_is_replaced_by_one_v6_policy(version):
    old=f'\nFIRE App SDK development and acceptance policy, version{version}:\nobsolete old policy\n'+MARKER+json.dumps({'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT})+'\nProject: preserved'
    result=normalize(old,capabilities=preview_capabilities(),summary='Lag klokke')
    assert result.count(POLICY)==1 and 'obsolete old policy' not in result and 'Project: preserved' in result
    assert VERSION.endswith('v6') and 'function init() fire.ui.set_theme("modern_dark") end' in result

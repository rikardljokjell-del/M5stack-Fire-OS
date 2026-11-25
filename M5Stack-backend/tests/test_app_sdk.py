"""Real shared SDK fixtures and independent contract/raster/sandbox checks."""
import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from fire_backend.app_sdk import DATA, SDK_VERSION, SDK_CONTRACT, assets, data_fingerprint, selected_context
from fire_backend.api_registry import API_CONTRACT, package_compatibility, preview_capabilities
from fire_backend.builds import validate_release, write_archive, sha256
from fire_backend.lua_worker import simulate
from fire_backend.models import Capabilities, Manifest
from fire_backend.security import Redactor
from fire_backend.storage import Store
from fire_backend.visual_simulator import render_frame, asset_image, fonts, text_size, rgb565
from fire_backend.visual_preview import save_screenshots, image_inputs


def app(source=None, **extra):
    return dict(main_lua=source or 'function init() end function update(dt) fire.ui.screen("TEST","SDK") end',
                required_services=['display','buttons'], api_version=SDK_VERSION, api_contract=SDK_CONTRACT,
                max_memory=131072, max_runtime_ms=0, profile='idle', preview_duration_ms=2000,
                capture_at_ms=[2000], native_host_policy='fire-native-host-v1', **extra)


@pytest.mark.parametrize('name,buttons', [('gallery', ['C']*i) for i in range(6)] +
    [('stopwatch', []), ('stopwatch', ['B']), ('stopwatch', ['B','C','B']),
     ('racing', []), ('racing', ['B']), ('racing', ['B','B'])])
def test_actual_shared_ui_and_examples_fit_unchanged_budgets(name, buttons):
    r=simulate(app((DATA/(name+'.lua')).read_text(encoding='utf-8'), button_sequence=buttons, interval_ms=250))
    assert r['app_memory_peak'] <= 131072
    assert r['max_io_calls'] <= 64 and r['max_io_bytes'] <= 2048
    assert r['max_callback_text_bytes'] <= 256
    frame=r['visual_frames'][-1]
    assert frame['input_count']==len(buttons)
    image=render_frame(frame)
    assert image.metrics['unique_colors']>3 and image.metrics['font_data_exact']
    assert not image.metrics['native_raster_exact'] and not image.metrics['physical_verified']


def test_gallery_pages_are_distinct_complete_frames_and_allow_more_than_24_calls():
    hashes=[]
    for page in range(6):
        r=simulate(app((DATA/'gallery.lua').read_text(encoding='utf-8'), button_sequence=['C']*page, interval_ms=250))
        hashes.append(render_frame(r['visual_frames'][-1]).pixel_sha256)
        if page==0:
            assert r['max_callback_operations']>24 and r['elided_clears']>0
            assert r['max_callback_display_work']+76800>120000  # old redundant full clear is now reused
    assert len(set(hashes))==6


def test_sdk_cannot_bypass_display_permission_or_old_api_negotiation():
    for changes in ({'required_services':['buttons']}, {'api_contract':'0'*64}, {'api_version':'fire-lua-0.2'}):
        request=app();request.update(changes)
        with pytest.raises(Exception): simulate(request)
    caps=preview_capabilities()
    manifest=Manifest(id='sdk-test',name='SDK',version='0.1.1',api_version=SDK_VERSION,
        api_contract=SDK_CONTRACT,required_services=['display'],permissions=['fire.display'],checksum='a'*64)
    assert not package_compatibility({'manifest':manifest.model_dump()},caps)
    old=copy.deepcopy(caps);old.pop('app_sdk')
    assert package_compatibility({'manifest':manifest.model_dump()},old)
    with pytest.raises(ValueError):Capabilities.model_validate({**caps,'app_sdk':{'version':SDK_VERSION,'contract':'0'*64}})
    assert 'app_sdk' not in Capabilities.model_validate(old).model_dump()


@pytest.mark.parametrize('body', [
    'fire.display.asset(0,0,"knight")',
    'fire.display.text_style(0,0,"x",65535,"not-a-font")',
    'fire.display.text_style(0,0,"x",65535,"ui12","left",0)',
    'fire.display.round_rect(0,0,8,8,5,1,true)',
    'fire.display.arc(0,0,5,20,10,1)',
    'fire.display.arc(0,0,5,0,360,1,6)',
    'fire.display.polyline({1,2,3},1)',
    'fire.display.gradient_rect(0/0,0,10,10,1,2)',
    'for i=1,65 do fire.display.measure_text("","ui12") end',
    'for i=1,4 do fire.display.measure_text("12345678901234567890123456789012345678901234567890123456789012345678901234567890") end',
    'local t={} for i=1,10000 do t[i]={1,2,3,4,5,6,7,8} end',
    'local f=fire.ui; f["require"]("os")',
    'local x=string.rep("x",1000000)',
])
def test_sdk_keeps_input_io_text_memory_and_sandbox_guards(body):
    source='function init() end function update(dt) '+body+' fire.display.pixel(0,0,1) end'
    with pytest.raises(Exception):simulate(app(source))


def test_sdk_200_cell_board_and_legacy_policy_remain_separate():
    source='local cells={} for i=1,200 do cells[i]=1 end function init() end function update(dt) fire.display.grid(0,0,8,8,10,20,cells,{0,2016}) end'
    assert simulate(app(source))['max_callback_grid_cells']==200
    request=app(source);request['api_version']='fire-lua-0.2';request['api_contract']=API_CONTRACT
    with pytest.raises(Exception,match='grid cell budget'):simulate(request)


@pytest.mark.parametrize('service,method,arguments',[('time','millis',''),('imu','accel',''),('buttons','pressed','"A"')])
def test_sdk_counts_base_queries_in_combined_native_io_quota(service,method,arguments):
    request=app('function init() end function update(dt) for i=1,65 do fire.'+service+'.'+method+'('+arguments+') end fire.display.pixel(0,0,1) end')
    request['required_services']=list(set(['display','buttons',service]))
    with pytest.raises(Exception,match='I/O budget'):simulate(request)


def test_sdk_valid_frames_do_not_hit_old_global_32_calls_per_frame_proxy():
    request=app('function init() end function update(dt) for x=1,40 do fire.display.pixel(x,0,31) end end')
    request['preview_duration_ms']=10000
    result=simulate(request)
    assert result['api_operations']==625*40 and result['max_io_calls']==40


def test_capture_diagnostics_do_not_consume_app_heap_or_raise_app_quota():
    source=(DATA/'gallery.lua').read_text(encoding='utf-8')
    peaks=[];host=[]
    for times in ([],[16],[16,1000,2000,3000,4000,5000,5900,6000]):
        request=app(source);request.update(preview_duration_ms=6000,capture_at_ms=times)
        r=simulate(request);peaks.append(r['app_memory_peak']);host.append(r['diagnostic_memory_bytes'])
    assert max(peaks)-min(peaks)<=64 and peaks[0]>50000  # actual UI remains charged
    assert host[0]<host[1]<host[2]
    bloated='local retained={} function init() for i=1,12000 do retained[i]=i end end function update(dt) fire.ui.screen("Heap") end'
    for times in ([],[16,32,48]):
        request=app(bloated);request['capture_at_ms']=times
        with pytest.raises(Exception,match='memory|Memory'):simulate(request)


@pytest.mark.parametrize('sdk',[False,True])
def test_standalone_compatibility_checks_missing_services_for_legacy_and_sdk(sdk):
    from fire_backend.api_registry import API_CONTRACT
    caps=preview_capabilities();caps['services'].remove('wifi')
    package={'manifest':{'api_version':SDK_VERSION if sdk else 'fire-lua-0.2',
        'api_contract':SDK_CONTRACT if sdk else API_CONTRACT,
        'required_services':['display','wifi','jobs']}}
    assert package_compatibility(package,caps)


def test_shared_bitmap_metrics_alignment_clipping_and_transparency():
    text='æøåÆØÅ°';width,height=text_size(text,'ui16')
    expected=sum(fonts()['ui16']['glyphs'][str(ord(c))]['advance'] for c in text)
    assert width==expected and height==fonts()['ui16']['line_height']
    r=render_frame({'ops':[['clear',31], ['text_style',10,10,text,65535,'ui16','right',15]]})
    image=Image.open(BytesIO(r.png))
    assert image.getpixel((9,10))==rgb565(31) and image.getpixel((25,10))==rgb565(31)
    assert r.metrics['text_boxes'][0]['clipped']
    assert text_size('☃','ui12')==text_size('?','ui12')


def test_font_evidence_distinguishes_sdk_from_unverified_legacy_font_settings():
    old=render_frame({'ops':[['text',0,0,'Legacy',65535]]})
    sdk=render_frame({'ops':[['text_style',0,0,'SDK',65535,'ui12','left',100]]})
    assert old.metrics['font_mode']=='legacy_reference' and old.metrics['font_data_exact']
    assert old.metrics['legacy_font_settings_verified'] is False
    assert sdk.metrics['font_mode']=='shared_sdk' and sdk.metrics['font_data_exact']
    assert not old.metrics['native_raster_exact'] and not sdk.metrics['native_raster_exact']


def test_unknown_font_diagnostic_identifies_actual_id_and_canonical_choices():
    source='function init() end function update(dt) fire.ui.label(10,10,"Test",{font="ui16b"}) end'
    with pytest.raises(Exception) as found:simulate(app(source))
    assert "'ui16b'" in str(found.value)
    assert all(name in str(found.value) for name in fonts())


def test_assets_use_real_rle_transparency_and_ignore_tint_on_colored_assets():
    colored=next(a for a in assets().values() if not a.get('tintable'))
    assert asset_image(colored['id'],63488).tobytes()==asset_image(colored['id']).tobytes()
    request=app('function init() end function update(dt) fire.display.asset(2,2,"'+colored['id']+'",1,63488) end')
    frame=simulate(request)['visual_frames'][0]
    assert frame['ops'][0][5]==-1
    img=asset_image('icon.heart',2016)
    assert any(p[3]==0 for p in img.getdata()) and any(p==(0,255,0,255) for p in img.getdata())


def test_gradient_endpoints_channel_rounding_and_single_dimension():
    image=Image.open(BytesIO(render_frame({'ops':[['gradient_rect',0,0,1,3,0,65535,True],['gradient_rect',2,0,1,1,31,2016,False]]}).png))
    assert image.getpixel((0,0))==(0,0,0) and image.getpixel((0,2))==(255,255,255)
    assert image.getpixel((0,1))==rgb565((16<<11)|(32<<5)|16)
    assert image.getpixel((2,0))==rgb565(31)


def test_context_is_selected_from_canonical_signatures_and_not_whole_assets():
    caps=preview_capabilities();context=selected_context('Lag racing bilspill',caps)
    v=json.loads(context.split('\n')[-1]);canonical=json.loads((DATA/'sdk.json').read_text(encoding='utf-8'))
    assert len(v['assets'])<=12 and len(context)<12000
    assert all(a['id'] in assets() and 'runs_b64' not in a for a in v['assets'])
    assert all(signature==canonical['ui_signatures'][name] for name,signature in v['ui'].items())
    assert v['suggested_theme'] in canonical['themes'] and v['suggested_layout'] in canonical['layouts']
    caps.pop('app_sdk');assert selected_context('Lag racing',caps)==''


def test_evidence_rejects_changed_sdk_data_even_for_same_source(tmp_path,monkeypatch):
    import fire_backend.visual_preview as preview
    store=Store(tmp_path,Redactor('test-key-only'),16*1024*1024)
    source='a'*64;evidence=save_screenshots([{'ops':[['pixel',1,1,31]]}],store,'build-sdk',source)
    assert evidence['sdk_data_sha256']==data_fingerprint()
    monkeypatch.setattr(preview,'data_fingerprint',lambda:'0'*64)
    with pytest.raises(ValueError):image_inputs(evidence,store,'build-sdk',source)


async def test_sdk_release_uses_real_worker_and_binds_screenshots(tmp_path):
    store=Store(tmp_path,Redactor('test-key-only'),16*1024*1024)
    request=app((DATA/'racing.lua').read_text(encoding='utf-8'));request.pop('profile');request.pop('preview_duration_ms');request.pop('capture_at_ms')
    request['max_runtime_ms']=1000
    result=await validate_release(request,store,'build-sdk')
    assert result['suite']=='release-v4' and not result['physical_verified']
    assert len(result['profiles'])>=7 and result['visual_evidence']['frames']
    assert image_inputs(result['visual_evidence'],store,'build-sdk',sha256(request['main_lua'].encode()))

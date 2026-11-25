import base64
import copy
import hashlib
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from fire_backend.ai import OpenAIProvider
from fire_backend.app_quality import FireAppReview
from fire_backend.lua_worker import simulate
from fire_backend.security import Redactor
from fire_backend.storage import Store
from fire_backend.visual_preview import image_inputs, save_screenshots, preview_folder
from fire_backend.visual_simulator import render_frame
from test_device_protocol import configured
from test_pre_delivery import approve


SOURCE = '''local n=0
function init() end
function update(dt)
 n=n+1
 fire.display.grid(0,0,8,8,1,1,{n%2},{63488,2016})
end'''


def app(**extra):
    return {'main_lua': SOURCE, 'required_services': ['display'],
            'api_version': 'fire-lua-0.2', 'max_memory': 131072,
            'max_runtime_ms': 10000, 'profile': 'idle', **extra}


def test_full_frame_capture_is_independent_of_truncated_trace_and_copies_grid_data():
    result = simulate(app(capture_at_ms=[16, 32, 9000]))
    assert len(result['trace']) == 240
    frames = result['visual_frames']
    assert len(frames) == 3 and frames[-1]['at_ms'] >= 9000
    assert frames[0]['ops'][0][-2:] == [[1], [63488, 2016]]
    assert frames[1]['ops'][0][-2:] == [[0], [63488, 2016]]
    pixels = [Image.open(BytesIO(render_frame(f).png)).getpixel((0, 0)) for f in frames[:2]]
    assert pixels == [(0, 255, 0), (255, 0, 0)]


def test_new_black_frame_draw_order_and_rgb565_are_rendered_deterministically():
    frame = {'ops': [['fill_rect', 0, 0, 30, 30, 63488],
                     ['fill_rect', 5, 5, 5, 5, 2016], ['pixel', 6, 6, 31]]}
    first = render_frame(frame)
    image = Image.open(BytesIO(first.png))
    assert image.size == (320, 240)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((5, 5)) == (0, 255, 0)
    assert image.getpixel((6, 6)) == (0, 0, 255)
    assert image.getpixel((100, 100)) == (0, 0, 0)
    assert first.png == render_frame(frame).png
    assert Image.open(BytesIO(render_frame({'ops': [['pixel', 100, 100, 31]]}).png)).getpixel((0, 0)) == (0, 0, 0)


@pytest.mark.parametrize('changes', [
    {'capture_at_ms': [32, 16]}, {'capture_at_ms': [16] * 9},
    {'capture_at_ms': [float('nan')]}, {'preview_duration_ms': 12001},
    {'button_sequence': ['HOME']}, {'button_sequence': ['B'] * 33},
])
def test_preview_inputs_cannot_escape_bounded_sandbox(changes):
    with pytest.raises(ValueError):
        simulate(app(**changes))


def test_virtual_buttons_execute_real_short_press_path():
    source = '''local selected=false function init() end
function on_button(b,action) if b=='B' and action=='pressed' then selected=true end end
function update(dt) fire.display.fill_rect(0,0,16,16,selected and 2016 or 63488) end'''
    idle = simulate(app(main_lua=source, preview_duration_ms=500, capture_at_ms=[500]))
    pressed = simulate(app(main_lua=source, button_sequence=['B'], preview_duration_ms=500, capture_at_ms=[500]))
    assert idle['visual_frames'][0]['ops'] != pressed['visual_frames'][0]['ops']
    assert pressed['visual_frames'][0]['button'] == 'B'
    assert pressed['visual_frames'][0]['input_count'] == 1


def test_evidence_is_bounded_deduplicated_and_source_and_byte_bound(tmp_path):
    store = Store(tmp_path, Redactor('test-api-key-only'), 16 * 1024 * 1024)
    digest = hashlib.sha256(SOURCE.encode()).hexdigest()
    candidates = [{'profile': 'idle', 'at_ms': n, 'ops': [['pixel', n % 12, 0, 31]]} for n in range(30)]
    evidence = save_screenshots(candidates, store, 'build-test', digest)
    assert len(evidence['frames']) == 8 and evidence['physical_verified'] is False
    images = image_inputs(evidence, store, 'build-test', digest)
    assert len(images) == 6 and all(i['image_url'].startswith('data:image/png;base64,') for i in images)
    with pytest.raises(ValueError, match='another source'):
        image_inputs(evidence, store, 'build-test', 'a' * 64)
    path = preview_folder(store,'build-test',digest) / (evidence['frames'][0]['png_sha256'][:24] + '.png')
    path.write_bytes(path.read_bytes() + b'tampered')
    with pytest.raises(ValueError, match='checksum mismatch'):
        image_inputs(evidence, store, 'build-test', digest)


async def test_existing_review_request_includes_verified_images_without_extra_ai_call(tmp_path):
    from fire_backend.models import GeneratedApp
    settings = configured(tmp_path, openai_api_key='test-api-key-only')
    provider = OpenAIProvider(settings)
    calls = []
    review = FireAppReview(**approve().model_dump(), kind='app', **{n: True for n in FireAppReview.fire_checks()})
    class Responses:
        async def parse(self, **values):
            calls.append(values)
            return SimpleNamespace(status='completed', output_parsed=review)
    provider.client = SimpleNamespace(responses=Responses())
    store = Store(tmp_path, Redactor('test-api-key-only'), 16 * 1024 * 1024)
    checksum = hashlib.sha256(SOURCE.encode()).hexdigest()
    evidence = save_screenshots([{'profile': 'idle', 'at_ms': 16, 'ops': [['pixel', 0, 0, 31]]}], store, 'build-test', checksum)
    images = image_inputs(evidence, store, 'build-test', checksum)
    generated = GeneratedApp(name='Test', main_lua=SOURCE, required_services=['display'])
    result = await provider.review('Test', 'API', generated, {'ok': True, 'visual_evidence': evidence, '_visual_review_images': images})
    assert result.approved and len(calls) == 1 and calls[0]['store'] is False
    content = calls[0]['input'][1]['content']
    assert sum(p['type'] == 'input_image' for p in content) == 1
    assert content[-1]['detail'] == 'low'
    assert 'data:image' not in content[0]['text']
    assert 'test-api-key-only' not in json.dumps(calls,default=str)
    assert 'Representative 320x240 screenshots are attached' in str(calls[0]['input'][0]['content'])
    stale = copy.deepcopy(images)
    stale[0]['source_sha256'] = 'a' * 64
    with pytest.raises(ValueError, match='source mismatch'):
        await provider.review('Test', 'API', generated, {'_visual_review_images': stale})
    assert len(calls) == 1

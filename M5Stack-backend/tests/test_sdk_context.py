import json
from types import SimpleNamespace
import pytest

from fire_backend.ai import OpenAIProvider
from fire_backend.app_quality import APP_QUALITY_POLICY,FireAppReview
from fire_backend.app_sdk import DATA,SDK_VERSION,SDK_CONTRACT,selected_context
from fire_backend.api_registry import preview_capabilities
from fire_backend.build_strategy import POLICY as DEVELOPMENT_POLICY,scoped_review_context
from fire_backend.models import GeneratedApp
from fire_backend.rendering import VISUAL_POLICY
from fire_backend.sdk_context import normalize,from_context,POLICY,VERSION,detailed_services
from test_device_protocol import configured
from test_pre_delivery import approve


@pytest.mark.parametrize('brief,layout,theme,asset',[
    ('Lag en stoppeklokke.','clock','modern_dark','icon.timer'),
    ('Lag en værapp.','dashboard','nature','icon.cloud-rain'),
    ('Lag en kalkulator.','calculator','minimal','icon.calculator'),
    ('Lag et sensordashboard.','sensor_monitor','professional_instrument','icon.activity'),
    ('Lag et teknisk måleinstrument.','instrument','professional_instrument','icon.gauge'),
    ('Lag Snake.','puzzle','retro_arcade','one-bit.coin'),
    ('Lag Tetris.','puzzle','retro_arcade','one-bit.coin'),
    ('Lag et bilspill.','racing','neon','one-bit.car-top'),
    ('Lag et space shooter-spill.','arcade','sci_fi','one-bit.ufo'),
    ('Lag et plattformspill.','platformer','pixel_art','pixel-platformer.026'),
    ('Lag et eventyrspill.','adventure','adventure','tiny-dungeon.096'),
    ('Create a stopwatch app','clock','modern_dark','icon.timer'),
    ('Make a weather app','dashboard','nature','icon.cloud-rain'),
    ('Create a calculator','calculator','minimal','icon.calculator'),
    ('Build a sensor dashboard','sensor_monitor','professional_instrument','icon.activity'),
    ('Create a technical measuring instrument','instrument','professional_instrument','icon.gauge'),
    ('Make a car racing game','racing','neon','one-bit.car-top'),
    ('Create a platform game','platformer','pixel_art','pixel-platformer.026'),
    ('Create an adventure game','adventure','adventure','tiny-dungeon.096'),
])
def test_real_compound_requests_choose_actual_layout_theme_and_relevant_assets(brief,layout,theme,asset):
    value=json.loads(selected_context(brief,preview_capabilities()).split('\n')[-1])
    assert value['suggested_layout']==layout and value['suggested_theme']==theme
    assert asset in {a['id'] for a in value['assets']}


def test_selected_input_example_is_valid_lua_with_actual_navigation_behavior():
    from fire_backend.lua_worker import simulate
    payload=json.loads(selected_context('Lag et bilspill',preview_capabilities()).split('\n')[-1])
    source=payload['examples']['input']+'\nfunction init() end\nfunction update(dt) fire.ui.screen(tostring(mode)) end'
    result=simulate(dict(main_lua=source,required_services=['display','buttons'],api_version=SDK_VERSION,
        api_contract=SDK_CONTRACT,max_memory=131072,max_runtime_ms=1000,profile='idle',
        capture_at_ms=[1000],button_sequence=['C','B'],interval_ms=250))
    assert any(op[0]=='text_style' and op[3]=='2' for op in result['visual_frames'][0]['ops'])


def raw_context():
    return ((DATA.parent/'FIRE_DEVICE_CONTEXT.md').read_text(encoding='utf-8')+APP_QUALITY_POLICY+
        VISUAL_POLICY+DEVELOPMENT_POLICY+selected_context('Lag en stoppeklokke.',preview_capabilities(),include_native=False))


def test_sdk_replaces_legacy_instructions_and_selects_only_relevant_api_details():
    original=raw_context();caps=preview_capabilities()
    context=normalize(original,capabilities=caps,summary='Lag en stoppeklokke.')
    assert len(context)<len(original)*.6
    for legacy in ('at most 128 total','No app sprite','120000','<=12 display','fixed textSize1'):
        assert legacy not in context
    assert context.count(POLICY)==1 and from_context(context)
    assert SDK_CONTRACT in scoped_review_context(context)
    assert normalize('legacy context')=='legacy context'
    assert detailed_services('Lag stoppeklokke',caps)==['buttons','display','rgb','time']
    assert {'i2c','jobs'}<=set(detailed_services('Lag I2C-skanner',caps))
    assert 'uart' in detailed_services('Endre fargen',caps,{'required_services':['display','jobs','uart']} )


def test_canonical_ui_help_options_and_real_palette_are_selected():
    payload=json.loads(selected_context('Lag stoppeklokke',preview_capabilities()).split('\n')[-1])
    metadata=json.loads((DATA/'sdk.json').read_text(encoding='utf-8'))
    assert payload['ui_help']['navigate']==metadata['ui_help']['navigate']
    assert payload['ui_options']['label']==metadata['ui_options']['label']
    assert set(payload['palette'])=={'bg','panel','fg','muted','accent','good','bad','border'}
    assert payload['palette']['bg']<=65535 and len(payload['ui_help'])<len(metadata['ui_help'])


async def test_real_generate_and_review_requests_preserve_sdk_without_late_legacy_append(tmp_path):
    app=GeneratedApp(name='Klokke',required_services=['display'],main_lua='function init() end function update(dt) fire.ui.screen("KLOKKE") end')
    review=FireAppReview(**approve().model_dump(),kind='app',**{k:True for k in FireAppReview.fire_checks()})
    calls=[]
    class Responses:
        async def parse(self,**request):
            calls.append(request)
            return SimpleNamespace(status='completed',output_parsed=app if request['text_format'] is GeneratedApp else review)
    provider=OpenAIProvider(configured(tmp_path,openai_api_key='test-key-only'))
    provider.client=SimpleNamespace(responses=Responses())
    context=normalize(raw_context(),capabilities=preview_capabilities(),summary='Lag stoppeklokke')
    await provider.generate('Lag stoppeklokke',context)
    await provider.review('Lag stoppeklokke',context,app,{'negotiated_contract':{'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT}})
    assert len(calls)==2
    for request in calls:
        developer=str(request['input'][0]['content'])
        assert SDK_VERSION in developer and SDK_CONTRACT in developer and VERSION in developer
        for legacy in ('No app sprite','at most 128 total','120000','<=12 display'):
            assert legacy not in developer
        assert 'text_style(10,85' in developer and 'PHYSICAL left/middle/right' in developer
    payload=json.loads(calls[1]['input'][1]['content'])
    assert payload['pc_validation']['negotiated_contract']['api_contract']==SDK_CONTRACT

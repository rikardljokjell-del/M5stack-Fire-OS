import json
from types import SimpleNamespace

import pytest

from fire_backend.ai import OpenAIProvider
from fire_backend.api_registry import preview_capabilities
from fire_backend.app_quality import FireAppReview
from fire_backend.app_sdk import SDK_VERSION, SDK_CONTRACT
from fire_backend.data_contract import CONTRACT
from fire_backend.models import GeneratedApp
from fire_backend.sdk_context import normalize
from test_device_protocol import configured
from test_sdk_context import raw_context, approve


@pytest.mark.parametrize('brief',[
    'Lag en app som registrerer Bluetooth-signaler og sammenligner lysknappetrykk.',
    'Lag elektronikkdiagnose med registrering og analyse av UART-signaler.',
    'Lag IMU-vibrasjonsmåling med frekvensanalyse og sammenligning.',
])
async def test_actual_generate_and_review_requests_keep_selected_data_contract_and_real_method_bounds(tmp_path,brief):
    calls=[]
    app=GeneratedApp(name='Test',required_services=['display'],main_lua='function init() end function update(dt) fire.ui.screen("TEST") end')
    review=FireAppReview(**approve().model_dump(),kind='app',**{k:True for k in FireAppReview.fire_checks()})
    class Responses:
        async def parse(self,**request):
            calls.append(request)
            return SimpleNamespace(status='completed',output_parsed=app if request['text_format'] is GeneratedApp else review)
    provider=OpenAIProvider(configured(tmp_path,openai_api_key='test-only-key'))
    provider.client=SimpleNamespace(responses=Responses())
    caps=preview_capabilities()
    caps['service_methods']={'bluetooth':['scan','read_gatt','write_gatt','advertise','advertise_raw','close'], 'wifi':['status','scan']}
    caps['service_modes']={'bluetooth.scan':['ble']}
    context=normalize(raw_context(),capabilities=caps,summary=brief)
    await provider.generate(brief,context)
    await provider.review(brief,context,app,{'negotiated_contract':{'api_version':SDK_VERSION,'api_contract':SDK_CONTRACT}})
    assert len(calls)==2
    for request in calls:
        parts=request['input'][0]['content']
        content='\n'.join(p['text'] for p in parts) if isinstance(parts,list) else parts
        assert CONTRACT in content and '"data"' in content and '"develop"' in content
        assert 'metadata_json' in content and 'append_bytes' in content and '768' in content
        assert 'binary' in content and 'user' in content and 'immutable' in content
        if 'Bluetooth' in brief:
            marker='Exact negotiated host contract (arguments, returns, dependencies, units and bounds):\n'
            contract=json.JSONDecoder().raw_decode(content.split(marker,1)[1])[0]
            bluetooth=contract['services']['bluetooth']
            assert 'advertise_raw' in bluetooth and 'close' in bluetooth and 'connect' not in bluetooth
            assert bluetooth['scan']['args'][0]['values']==['ble']


def test_simple_clock_omits_data_and_legacy_context_unchanged():
    caps=preview_capabilities()
    clock=normalize(raw_context(),capabilities=caps,summary='Lag en enkel klokke')
    assert CONTRACT not in clock and '"data_engine"' not in clock
    assert normalize('Original legacy context',capabilities={'services':['display']})=='Original legacy context'

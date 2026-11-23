"""Model selection and migration tests; no network or paid requests."""
import json
import os

import pytest

from fire_backend.config import Settings
from fire_backend.desktop_config import DesktopStore, COST_PROFILE_VERSION
from fire_backend.model_catalog import CODE_MODELS, ROLE_MODELS, choice_label, price_detail
from test_desktop import MemoryVault
from test_usage import ledger


def test_previous_economy_profile_moves_code_and_review_to_luna_once(tmp_path):
    store=DesktopStore(tmp_path,MemoryVault())
    store.save(store.config,api_key='sk-private-model-migration')
    credentials=dict(store.vault.values)
    raw=store.config.model_dump()
    raw.update(cost_profile_version=1,code_model='gpt-6.2-sol',review_model='gpt-6.2-sol',
        dialog_model='gpt-realtime-2.1',port=9876,daily_budget_usd=1)
    store.path.write_text(json.dumps(raw),encoding='utf-8')
    restored=DesktopStore(tmp_path,store.vault)
    assert restored.migrate_cost_profile()
    assert not restored.migrate_cost_profile()
    assert restored.config.cost_profile_version==COST_PROFILE_VERSION
    assert restored.config.code_model==restored.config.review_model=='gpt-6-luna'
    assert restored.config.dialog_model=='gpt-realtime-2.1'  # deliberate current choice
    assert restored.config.port==9876 and restored.config.daily_budget_usd==1
    assert restored.vault.values==credentials
    settings=restored.settings()
    assert settings.openai_code_model==settings.openai_review_model=='gpt-6-luna'
    assert Settings(_env_file=None).openai_code_model=='gpt-6-luna'


@pytest.mark.parametrize('model',CODE_MODELS)
def test_each_picker_code_model_has_usable_budgeted_pricing(tmp_path,model):
    meter=ledger(tmp_path,fire_request_budget_usd=20,fire_daily_budget_usd=100,fire_build_budget_usd=100)
    item=meter.begin('generate',model,300000,1000)
    result=meter.finish(item,{'input_tokens':300000,'output_tokens':1000})
    from fire_backend.model_catalog import PRICES
    p=PRICES[model]
    assert result['estimated_usd']==pytest.approx((300000*p.text_in*2+1000*p.text_out*1.5)/1e6)
    assert result['cache_write_ttl']=='30m'


def test_prices_show_correct_units_and_fractional_cache_prices():
    assert '$0.10 / ut $0.50' in choice_label('code_model','gpt-6-luna')
    assert '$0.125' in price_detail('code_model','gpt-6-luna')
    assert '$0.0045/min' in choice_label('transcribe_model','gpt-transcribe')
    assert 'inkludert' in price_detail('transcribe_model','gpt-transcribe')
    assert 'lyd ut $20.00' in choice_label('speech_model','gpt-realtime-2.1-mini')
    assert '1 mill. lydtokens' in price_detail('speech_model','gpt-realtime-2.1-mini')
    assert not set(ROLE_MODELS['dialog_model']) & set(CODE_MODELS)
    assert ROLE_MODELS['transcribe_model']==('gpt-transcribe',)


@pytest.mark.skipif(os.name!='nt',reason='Windows Tk picker')
def test_dropdown_selection_prices_profile_and_reload_keep_model_ids(tmp_path,monkeypatch):
    import tkinter as tk
    from fire_backend.desktop_ui import DesktopUI
    monkeypatch.setattr('fire_backend.desktop_ui.threading.Thread.start',lambda _:None)
    monkeypatch.setattr('fire_backend.desktop_ui.lan_addresses',lambda:['127.0.0.1'])
    root=tk.Tk();root.withdraw()
    store=DesktopStore(tmp_path,MemoryVault())
    try:
        ui=DesktopUI(root,store)
        for role,models in ROLE_MODELS.items():
            picker=ui.model_pickers[role]
            assert str(picker.cget('state'))=='readonly'
            for i,model in enumerate(models):
                picker.current(i)
                picker.event_generate('<<ComboboxSelected>>')
                assert ui.models[role].get()==model
                assert ui.collect().model_dump()[role]==model
                assert ui.model_price_labels[role].cget('text')==price_detail(role,model)
        # Restoring the economy preset must also refresh labels and prices.
        ui.economy_profile()
        assert ui.models['code_model'].get()=='gpt-6-luna'
        assert '$0.50' in ui.model_labels['code_model'].get()
        store.save(ui.collect())
        restored=DesktopStore(tmp_path,store.vault)
        assert restored.config.code_model=='gpt-6-luna'
        assert restored.settings().openai_review_model=='gpt-6-luna'
        # Previously saved private/custom names survive opening and saving.
        ui.models['review_model'].set('my-private-model')
        assert 'utenfor' in ui.model_labels['review_model'].get()
        assert ui.collect().review_model=='my-private-model'
    finally:
        root.destroy()

import json
from unittest.mock import Mock

import pytest

from fire_backend.desktop_config import DesktopConfig,DesktopStore,ECONOMY_MODELS,COST_PROFILE_VERSION
from fire_backend.desktop_runtime import DesktopRuntime
from fire_backend.desktop_ui import usage_task_name,usage_status_name
from test_desktop import MemoryVault


def test_legacy_economy_migration_preserves_credentials_network_and_own_models(tmp_path):
    vault=MemoryVault();store=DesktopStore(tmp_path,vault)
    store.save(store.config,api_key="sk-test-private-preserved")
    before=dict(vault.values);raw=store.config.model_dump()
    raw.pop("cost_profile_version");raw.pop("review_model")
    raw.update(code_model="gpt-6.2-astra",dialog_model="gpt-realtime-2.1",transcribe_model="gpt-transcribe",
               speech_model="my-saved-voice-model",port=8787,max_workspace_mb=1024)
    store.path.write_text(json.dumps(raw),encoding="utf-8")
    restored=DesktopStore(tmp_path,vault)
    assert restored.config.cost_profile_version==0
    assert restored.migrate_cost_profile()
    assert not restored.migrate_cost_profile()
    cfg=restored.config
    assert cfg.cost_profile_version==COST_PROFILE_VERSION
    assert cfg.code_model==cfg.review_model=="gpt-6.2-sol"
    assert cfg.dialog_model=="gpt-realtime-2.1-mini"
    assert cfg.transcribe_model=="gpt-transcribe" and cfg.speech_model=="my-saved-voice-model"
    assert cfg.port==8787 and cfg.max_workspace_mb==1024
    assert vault.values==before
    assert all(secret not in restored.path.read_text() for secret in before.values())


def test_migration_keeps_custom_codegen_and_dialogue_models(tmp_path):
    store=DesktopStore(tmp_path,MemoryVault())
    raw=store.config.model_dump();raw.pop("cost_profile_version")
    raw.update(code_model="custom-code",dialog_model="custom-dialog",daily_budget_usd=3,request_budget_usd=.1)
    store.path.write_text(json.dumps(raw),encoding="utf-8")
    store=DesktopStore(tmp_path,store.vault);store.migrate_cost_profile()
    assert store.config.code_model=="custom-code" and store.config.dialog_model=="custom-dialog"
    assert store.config.daily_budget_usd==3 and store.config.request_budget_usd==.1


def test_desktop_budget_and_review_fields_reach_backend_settings(tmp_path):
    store=DesktopStore(tmp_path,MemoryVault())
    store.save(store.config.model_copy(update={"daily_budget_usd":1.5,"build_budget_usd":.4,"request_budget_usd":.12,
        "max_corrections":0,"review_model":"my-review"}))
    settings=store.settings()
    assert settings.openai_code_model=="gpt-6.2-sol" and settings.openai_review_model=="my-review"
    assert settings.fire_daily_budget_usd==1.5 and settings.fire_build_budget_usd==.4
    assert settings.fire_request_budget_usd==.12 and settings.fire_max_corrections==0
    assert settings.openai_transcribe_model=="gpt-transcribe"


@pytest.mark.parametrize("field,value",[("daily_budget_usd",0),("build_budget_usd",-1),("request_budget_usd",float('inf')),("max_corrections",4)])
def test_cost_settings_cannot_disable_guards_with_invalid_values(field,value):
    with pytest.raises(ValueError):DesktopConfig(**{field:value})


def test_usage_controls_only_call_local_admin_endpoints():
    runtime=DesktopRuntime();runtime.request=Mock(return_value={"currency":"USD"})
    assert runtime.usage()=={"currency":"USD"}
    runtime.request.assert_called_with("GET","/desktop/usage")
    runtime.reset_usage();runtime.request.assert_called_with("POST","/desktop/usage/reset",json={})
    assert usage_task_name('review')=='Kodekontroll'
    assert usage_status_name({'status':'completed','usage_source':'provider'})=='Fullført'
    assert 'anslag' in usage_status_name({'status':'cancelled','usage_source':'reservation'})


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows Tk smoke')
def test_usage_screen_renders_reported_and_uncertain_requests_without_paid_calls(tmp_path,monkeypatch):
    import tkinter as tk
    from fire_backend.desktop_ui import DesktopUI
    monkeypatch.setattr('fire_backend.desktop_ui.threading.Thread.start',lambda _:None)
    monkeypatch.setattr('fire_backend.desktop_ui.lan_addresses',lambda:['127.0.0.1'])
    root=tk.Tk();root.withdraw()
    try:
        ui=DesktopUI(root,DesktopStore(tmp_path,MemoryVault()))
        ui.usage_snapshot={'pricing_date':'2026-11-23','since_reset':{'requests':2,'estimated_usd':.08,'audio_seconds':3,'cached_tokens':200,'unknown_usage_requests':1},
            'today':{'requests':2,'estimated_usd':.08},'lifetime':{'requests':4,'estimated_usd':.1},
            'limits':{'daily_usd':2,'daily_remaining_usd':1.92},
            'by_operation':[{'operation':'generate','requests':1,'input_tokens':300,'output_tokens':200,'estimated_usd':.02}],
            'recent':[{'id':'usage-one','model':'gpt-6.2-sol','operation':'generate','status':'completed','usage_source':'provider','input_tokens':300,'output_tokens':200,'cached_tokens':100,'estimated_usd':.02,'started_at':1795420000},
                      {'id':'usage-two','model':'gpt-realtime-2.1-mini','operation':'speech','status':'cancelled','usage_source':'reservation','input_tokens':200,'output_tokens':0,'estimated_usd':.06,'started_at':1795420001}]}
        ui.render_usage()
        assert '$0.0800' in ui.usage_totals['since_reset'].cget('text')
        assert len(ui.usage_recent.get_children())==2
        assert 'Kodebygging' in str(ui.usage_groups['by_operation'].item(ui.usage_groups['by_operation'].get_children()[0])['values'])
        ui.usage_recent.selection_set('usage-two');ui.render_usage_detail()
        assert 'reserve beholdes' in ui.usage_detail.cget('text')
        ui.economy_profile();assert ui.models['review_model'].get()=='gpt-6.2-sol'
        assert ui.collect().daily_budget_usd==2
    finally:root.destroy()

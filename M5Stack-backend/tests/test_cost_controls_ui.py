import os

import pytest

from fire_backend.desktop_config import DesktopStore
from test_desktop import MemoryVault


@pytest.mark.skipif(os.name!='nt',reason='Windows Tk controls')
def test_zero_defaults_independent_switches_lifetime_cost_column_and_reload(tmp_path,monkeypatch,ui_root):
    import tkinter as tk
    from fire_backend.desktop_ui import DesktopUI
    monkeypatch.setattr('fire_backend.desktop_ui.threading.Thread.start',lambda _:None)
    monkeypatch.setattr('fire_backend.desktop_ui.lan_addresses',lambda:['127.0.0.1'])
    root=ui_root;store=DesktopStore(tmp_path,MemoryVault())
    try:
        ui=DesktopUI(root,store)
        assert all(float(v.get())==0 for v in ui.cost_limits.values())
        assert not ui.cost_limits_enabled.get() and not ui.output_limits_enabled.get()
        assert all(str(f.cget('state'))=='disabled' for f in ui.budget_fields)
        ui.cost_limits_enabled.set(True);ui.sync_cost_controls()
        assert all(str(f.cget('state'))=='normal' for f in ui.budget_fields)
        ui.cost_limits['build_budget_usd'].set('.4');ui.cost_limits['max_corrections'].set('5')
        ui.output_limits_enabled.set(True);ui.speech_enabled.set(False)
        saved=ui.collect();store.save(saved)
        loaded=DesktopStore(tmp_path,store.vault).settings()
        assert loaded.fire_build_budget_usd==.4 and loaded.fire_max_corrections==5
        assert loaded.fire_cost_limits_enabled and loaded.fire_output_limits_enabled
        assert not loaded.fire_speech_enabled and loaded.fire_audio_enabled
        assert ui.apps_table.heading('cost')['text']=='Cost (USD)'
        ui.usage_snapshot={'limits':{'enabled':False,'daily_usd':0,'daily_remaining_usd':None}}
        ui.render_usage();assert 'Kostnadsgrenser er av' in ui.usage_info.cget('text')
        ui.economy_profile()
        assert all(float(v.get())==0 for v in ui.cost_limits.values())
        assert not ui.cost_limits_enabled.get() and not ui.output_limits_enabled.get()
    finally:root.destroy()

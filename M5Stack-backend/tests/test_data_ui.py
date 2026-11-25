import pytest


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows Tk smoke')
def test_data_page_renders_raw_provenance_confirmation_and_ordinary_context_open(tmp_path,monkeypatch,ui_root):
    from unittest.mock import Mock
    from fire_backend.desktop_ui import DesktopUI
    from fire_backend.desktop_config import DesktopStore
    from test_desktop_costs import MemoryVault
    monkeypatch.setattr('fire_backend.desktop_ui.threading.Thread.start',lambda _:None)
    monkeypatch.setattr('fire_backend.desktop_ui.lan_addresses',lambda:['127.0.0.1'])
    ui=DesktopUI(ui_root,DesktopStore(tmp_path,MemoryVault()))
    ui.snapshot['data_engine']={'datasets':[{'id':'dataset-one','label':'Måling æøå','kind':'binary','state':'sealed',
        'device_id':'fire-one','acquisition':'app_recorded','evidence':'device_uploaded_app_data'}],
        'contexts':[{'id':'context-one','device_id':'fire-one','app_id':'signal-tool','mode':'update',
            'user_confirmation':'confirm','source_sha256':'test-source'}],
        'results':[{'id':'result-one','evidence':'ai_assessment','result':{'status':'unknown'}}]}
    ui.render_data()
    assert len(ui.data_table.get_children())==3
    ui.data_table.selection_set('contexts:context-one');ui.render_data_detail()
    assert 'Observasjon bekreftet' in str(ui.data_table.item('contexts:context-one')['values'])
    assert 'test-source' in ui.data_detail.get('1.0','end')
    ui.runtime.desktop_conversation=Mock(return_value={})
    ui.work=lambda action,**kwargs:action()
    ui.open_data_context()
    ui.runtime.desktop_conversation.assert_called_once_with('fire-one',development_context_id='context-one')

from fire_backend.service import Backend
from test_device_protocol import configured
from test_repair_target import saved_app
from test_device_app_manager import version


async def test_updated_app_precedes_newer_named_app_independently_of_selected_version(tmp_path,monkeypatch,ui_root):
    b=Backend(configured(tmp_path/'backend'))
    try:
        first,old=saved_app(b,'Zulu',slug='zulu');second,other=saved_app(b,'Alfa',slug='alfa')
        revised=version(b,old,2)
        for package,stamp in [(old,100),(other,200),(revised,300)]:
            package['created_at']=stamp;b.store.put('packages',package['id'],package)
        rows=b.app_library()
        assert [r['package_id'] for r in rows]==[revised['id'],other['id'],old['id']]
        from fire_backend.desktop_ui import DesktopUI
        from fire_backend.desktop_config import DesktopStore
        from test_desktop import MemoryVault
        monkeypatch.setattr('fire_backend.desktop_ui.threading.Thread.start',lambda _:None)
        monkeypatch.setattr('fire_backend.desktop_ui.lan_addresses',lambda:['127.0.0.1'])
        ui=DesktopUI(ui_root,DesktopStore(tmp_path/'ui',MemoryVault()))
        ui.snapshot['apps']=rows;ui.render_status()
        assert ui.apps_table.get_children()==(first['id'],second['id'])
        ui.version_selection[first['id']]=old['id'];ui.render_app_detail();ui.render_status()
        assert ui.apps_table.get_children()==(first['id'],second['id'])
    finally:await b.close()

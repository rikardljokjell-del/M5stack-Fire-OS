"""Command deployment failures retain evidence without poisoning tested Lua."""
from fastapi.testclient import TestClient
import pytest

from fire_backend.app import create_app
from fire_backend.failure_learning import deployment_case,source_guard_eligible
from fire_backend.quality import require_deliverable
from fire_backend.service import Backend
from test_device_protocol import configured,Device,headers,ADMIN
from test_repair_target import saved_app


@pytest.mark.parametrize('code',['not_installed','archive_mismatch','expired_command'])
def test_failed_run_remains_failed_but_same_tested_source_can_be_reinstalled(code,tmp_path):
    with TestClient(create_app(configured(tmp_path,fire_desktop_enabled=True))) as client:
        with client.websocket_connect('/ws/device',headers=headers()) as socket:
            device=Device(socket);device.start();offer,_=device.build();device.install(offer)
            backend=client.app.state.backend;package_id=offer['package_id']
            checksum=backend.store.get('packages',package_id)['manifest']['checksum']
            run,_=device.run(package_id)
            event=device.send('app_failed',package_id=package_id,run_id=run['run_id'],error_code=code,message='Rejected before Lua execution')
            device.ack(event)
            assert backend.store.get('commands',run['run_id'])['status']=='failed'
            assert backend.store.get('devices',device.device_id)['runtime_status']=='failed'
            package=backend.store.get('packages',package_id)
            case=backend.quality.cases(package['project_id'])[0]
            assert case['failure_scope']=='deployment' and case['category']=='installation'
            assert case['error_code']==code and case['failure_evidence']['latest_feedback']['run_id']==run['run_id']
            assert deployment_case({'provenance':'device_receipt','failure_evidence':case['failure_evidence']})
            assert not source_guard_eligible('device_receipt',{'mode':'openai'},'Lua update: callback budget exceeded',code)
            assert backend.store.get('feedback',event['event_id'])['event']=='app_failed'
            assert not package.get('quality',{}).get('blocked')
            backend.quality.reject_known_failure(package['project_id'],checksum);require_deliverable(package)
            # Ordinary reinstall plus the device's real protocol receipt, not a
            # changed source/version or fabricated successful run in production.
            response=client.post('/desktop/sessions/'+device.session_id+'/install',headers=headers(ADMIN),json={'package_id':package_id})
            assert response.status_code==200,response.text
            second=device.until('install_request');device.install(second)
            new_run,_=device.run(package_id);device.healthy(new_run)
            assert backend.store.get('commands',new_run['run_id'])['status']=='healthy'
            assert backend.store.get('commands',run['run_id'])['status']=='failed'
            assert backend.store.get('packages',package_id)['manifest']['checksum']==checksum
            assert backend.store.get('quality',case['id'])['error_code']==code


@pytest.mark.parametrize('code,message',[
    ('runtime_error','app callback time budget exceeded'),
    ('init_error','Lua init: nil value'),
    ('load_error','Lua syntax: unexpected symbol'),
    ('runtime_error','Lua update: forbidden sandbox API'),
])
async def test_real_callback_init_load_and_sandbox_failures_still_block(code,message,tmp_path):
    backend=Backend(configured(tmp_path))
    try:
        project,package=saved_app(backend,'Test')
        backend.quality.record(project_id=project['id'],package_id=package['id'],message=message,provenance='device_receipt',error_code=code)
        saved=backend.store.get('packages',package['id'])
        assert saved['quality']['blocked']
        assert not deployment_case({'provenance':'device_receipt','error_code':code})
        with pytest.raises(ValueError,match='sperret'):require_deliverable(saved)
        with pytest.raises(ValueError,match='identical'):backend.quality.reject_known_failure(project['id'],package['manifest']['checksum'])
    finally:await backend.close()


async def test_later_deployment_failure_never_clears_independent_real_source_failure(tmp_path):
    backend=Backend(configured(tmp_path))
    try:
        project,package=saved_app(backend,'Test')
        original=backend.quality.record(project_id=project['id'],package_id=package['id'],message='Lua update: callback budget exceeded',provenance='device_receipt',error_code='runtime_error')
        deploy=backend.quality.record(project_id=project['id'],package_id=package['id'],message='not_installed: missing mapping',provenance='device_receipt',error_code='not_installed')
        assert deploy['id']!=original['id'] and deploy['failure_scope']=='deployment'
        assert backend.store.get('packages',package['id'])['quality']['case_id']==original['id']
        assert backend.store.get('quality',original['id'])['message']==original['message']
        with pytest.raises(ValueError,match='identical'):backend.quality.reject_known_failure(project['id'],package['manifest']['checksum'])
    finally:await backend.close()

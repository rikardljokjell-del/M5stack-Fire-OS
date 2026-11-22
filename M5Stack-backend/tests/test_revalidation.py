from fire_backend.builds import sha256,write_archive
from fire_backend.revalidation import revalidate_package
from fire_backend.service import Backend
from test_device_protocol import configured
from test_repair_target import saved_app


async def test_revalidation_preserves_source_archive_versions_and_known_failure_block(tmp_path):
    backend=Backend(configured(tmp_path))
    try:
        project,p=saved_app(backend,'Sirkel',slug='sirkel')
        source=b'function init() end function update(dt) fire.display.circle(20,20,5,2016) end'
        p['manifest']['checksum']=sha256(source);p['validation']={'suite':'release-v3'}
        path=backend.store.path('packages',p['id'],'.zip');write_archive(path,p['manifest'],source)
        p['archive_sha256']=sha256(path.read_bytes());backend.store.put('packages',p['id'],p)
        before=path.read_bytes()
        assert (await revalidate_package(backend.store,p['id']))['status']=='passed'
        assert backend.store.get('packages',p['id'])['validation']['suite']=='release-v3'
        assert (await revalidate_package(backend.store,p['id'],apply=True))['status']=='passed'
        assert path.read_bytes()==before
        assert backend.store.get('packages',p['id'])['manifest']==p['manifest']
        assert backend.store.get('projects',project['id'])==project
        backend.quality.record(project_id=project['id'],package_id=p['id'],message='native failure',provenance='test')
        assert (await revalidate_package(backend.store,p['id'],apply=True))['status']=='skipped_known_failure'
        assert backend.store.get('packages',p['id'])['quality']['blocked']
        assert not backend.store.list('commands')
    finally:await backend.close()


async def test_failed_revalidation_blocks_only_when_explicitly_applied(tmp_path):
    backend=Backend(configured(tmp_path))
    try:
        _,p=saved_app(backend,'Blank') # This fixture has a blank update.
        assert (await revalidate_package(backend.store,p['id']))['status']=='failed'
        assert not backend.store.get('packages',p['id']).get('quality')
        assert (await revalidate_package(backend.store,p['id'],apply=True))['status']=='failed'
        assert backend.store.get('packages',p['id'])['quality']['blocked']
    finally:await backend.close()

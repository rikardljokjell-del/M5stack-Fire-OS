"""Offline lifecycle regression. Fixture receipts are not physical evidence."""
import asyncio
import copy
import hashlib

import pytest

from fire_backend.models import SessionStart
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from test_background_repairs import RepairProvider, event, finished, prepare
from test_device_protocol import CAPS, configured
from test_repair_target import Peer, saved_app, session


class CountedProvider(RepairProvider):
    def __init__(self):
        super().__init__()
        self.operations = []

    async def dialog(self, *args, **kwargs):
        self.operations.append('dialog')
        return await super().dialog(*args, **kwargs)

    async def generate(self, *args, **kwargs):
        self.operations.append('generate')
        return await super().generate(*args, **kwargs)

    async def review(self, *args, **kwargs):
        self.operations.append('review')
        return await super().review(*args, **kwargs)


async def ready_background_job(backend, provider, kind):
    current, peer = await session(backend)
    repair_id = None
    original = None
    if kind == 'repair':
        _, original = saved_app(backend, 'Vater', slug='vater')
        proposal = await prepare(backend, current, original)
        repair_id = proposal['repair_id']
        await dispatch(backend, current, event(current, 'build_confirm',
            repair_id=repair_id, proposal_id=proposal['proposal_id']))
        task = backend.repairs.tasks[repair_id]
    else:
        await backend.text(current, 'Lag en sirkel')
        build = await backend.confirm_build(current, current.proposal_id)
        task = current.task
    await asyncio.wait_for(provider.entered.wait(), 3)
    if repair_id:
        build_id = backend.store.get('repairs', repair_id)['build_id']
        target = {'repair_id': repair_id}
    else:
        build_id = build['id']
        target = {'build_id': build_id}
    await dispatch(backend, current, event(current, 'job_control', job_action='background', **target))
    await dispatch(backend, current, event(current, 'app_select', app_mode='new'))
    unrelated_project = current.project_id
    provider.release.set()
    await asyncio.wait_for(task, 15)
    if repair_id:
        assert (await finished(backend, repair_id))['status'] == 'ready'
    build = backend.store.get('builds', build_id)
    assert build['status'] == 'ready'
    package = backend.store.get('packages', build['package_id'])
    assert unrelated_project != package['project_id'] == build['project_id']
    assert not backend.store.list('commands')
    if original:
        # Actual normal inventory handler supplies the older installed-side
        # identity; the new tested repair remains the recommended candidate.
        await dispatch(backend, current, event(current, 'app_inventory', storage_ready=True, complete=True,
            apps=[{'app_id': original['manifest']['id'], 'package_id': original['id'],
                   'version': original['manifest']['version'], 'checksum': original['manifest']['checksum']}]))
    return current, peer, build, package, repair_id, original


@pytest.mark.parametrize('kind', ['normal', 'repair'])
async def test_minimized_ready_job_reopens_readonly_then_delivers_only_after_explicit_choice(tmp_path, kind):
    provider = CountedProvider()
    provider.release.clear()
    backend = Backend(configured(tmp_path), provider)
    try:
        current, peer, build, package, repair_id, original = await ready_background_job(backend, provider, kind)
        archive = backend.store.path('packages', package['id'], '.zip')
        archive_bytes = archive.read_bytes()
        manifest = copy.deepcopy(package['manifest'])
        operations = list(provider.operations)
        usage = backend.usage.records()
        build_count = len(backend.store.list('builds'))
        selected_project = current.project_id
        selected_history = copy.deepcopy(current.history)

        await dispatch(backend, current, event(current, 'build_jobs'))
        catalog = next(m for m in reversed(peer.events) if m['type'] == 'build_jobs')
        row = next(r for r in catalog['jobs'] if r.get('build_id') == build['id'])
        assert row['status'] == 'ready' and row['can_open'] is True and row['can_resume'] is False
        assert (row['project_id'], row['package_id'], row['name'], row['version']) == (
            package['project_id'], package['id'], manifest['name'], manifest['version'])
        assert row['repair_id'] == repair_id
        if repair_id:
            repair = await dispatch(backend, current, event(current, 'app_repair_status', repair_id=repair_id))
            assert repair['status'] == 'ready'
            assert (repair['package_id'], repair['version'], repair['project_id']) == (
                package['id'], manifest['version'], package['project_id'])

        await dispatch(backend, current, event(current, 'app_list'))
        apps = next(m for m in reversed(peer.events) if m['type'] == 'app_catalog')['apps']
        app = next(a for a in apps if a['project_id'] == package['project_id'])
        assert app['latest_package_id'] == package['id'] and app['latest_version'] == manifest['version']
        assert app['downloadable'] is True and app['download_block_reason'] == ''
        assert 'recommended_package_id' not in app and 'installed_version' not in app
        if original:
            assert app['base_package_id'] == original['id']
            assert original['manifest']['version'] != app['latest_version']

        # Local Open consumes these authoritative views, never build_resume:
        # merely viewing must not install, run, switch app or regenerate.
        assert current.project_id == selected_project and current.history == selected_history
        assert provider.operations == operations and backend.usage.records() == usage
        assert len(backend.store.list('builds')) == build_count and not backend.store.list('commands')
        assert archive.read_bytes() == archive_bytes

        other = await backend.start(SessionStart(device_id='fire-02', target='device', protocol_version='0.2',
            boot_id='boot-other', capabilities=CAPS), Peer(), 'fire-02')
        with pytest.raises(PermissionError):
            await dispatch(backend, other, event(other, 'app_download',
                project_id=package['project_id'], package_id=package['id']))
        if repair_id:
            with pytest.raises(PermissionError):
                await dispatch(backend, other, event(other, 'app_repair_status', repair_id=repair_id))
        assert not backend.app_catalog('fire-02', other)
        with pytest.raises(PermissionError):
            await dispatch(backend, current, event(current, 'app_download',
                project_id=selected_project, package_id=package['id']))
        with pytest.raises(FileNotFoundError):
            await dispatch(backend, current, event(current, 'app_download',
                project_id=package['project_id'], package_id='build-missing'))
        assert current.project_id == selected_project and not backend.store.list('commands')

        # Explicit Download/Kjor is the first operation permitted to rehome the
        # current unrelated authoring session and issue an install command.
        offer = await dispatch(backend, current, event(current, 'app_download',
            project_id=package['project_id'], package_id=package['id']))
        install = backend.store.get('commands', offer['install_id'])
        assert install['status'] == 'pending' and install['kind'] == 'install'
        assert (install['package_id'], install['project_id'], install['session_id'], install['boot_id']) == (
            package['id'], package['project_id'], current.id, current.boot_id)
        assert install['archive_sha256'] == hashlib.sha256(archive_bytes).hexdigest()
        assert install['download_url'] == f"/packages/{package['id']}/download"
        assert current.project_id == package['project_id'] and current.package_id == package['id']
        with pytest.raises(ValueError):
            await dispatch(backend, current, event(current, 'run_confirm', package_id=package['id']))
        with pytest.raises(ValueError):
            await dispatch(backend, current, event(current, 'device_install_result', install_id=install['id'],
                package_id=package['id'], status='ok', archive_sha256='0'*64))
        await dispatch(backend, current, event(current, 'device_install_result', install_id=install['id'],
            package_id=package['id'], status='ok', archive_sha256=package['archive_sha256']))
        assert backend.store.get('commands', install['id'])['status'] == 'completed'
        assert not any(c['kind'] == 'run' for c in backend.store.list('commands'))
        with pytest.raises((ValueError, FileNotFoundError)):
            await dispatch(backend, current, event(current, 'run_confirm', package_id='build-untested'))
        started = await dispatch(backend, current, event(current, 'run_confirm', package_id=package['id']))
        run = backend.store.get('commands', started['run_id'])
        assert (run['package_id'], run['boot_id'], run['session_id']) == (package['id'], current.boot_id, current.id)
        assert run['source_sha256'] == manifest['checksum'] and run['archive_sha256'] == package['archive_sha256']
        await dispatch(backend, current, event(current, 'app_started', run_id=run['id'],
            package_id=package['id'], source_sha256=manifest['checksum']))
        assert backend.store.get('commands', run['id'])['status'] == 'started'
        assert provider.operations == operations and backend.usage.records() == usage
        assert len(backend.store.list('builds')) == build_count
        assert len(backend.store.list('commands')) == 2
        assert archive.read_bytes() == archive_bytes
        assert backend.store.get('packages', package['id'])['manifest'] == manifest
    finally:
        await backend.close()

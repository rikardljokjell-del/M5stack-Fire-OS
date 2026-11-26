"""Catalog reads share metadata only within one request, never action grants."""
from collections import Counter

import pytest

from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from test_background_repairs import event
from test_device_protocol import configured
from test_repair_target import saved_app, session


async def test_catalog_page_reads_each_history_once_and_only_checks_visible_rows(tmp_path, monkeypatch):
    backend = Backend(configured(tmp_path))
    try:
        current, peer = await session(backend)
        packages = [saved_app(backend, name, slug='app-'+str(i))[1]
                    for i, name in enumerate(['Åpen', 'Delta', 'Bravo', 'Charlie', 'Alpha', 'Echo'])]
        saved_app(backend, 'Foreign', owner='fire-02', slug='foreign')
        _, failed = saved_app(backend, 'Failed', slug='failed')
        build = backend.store.get('builds', failed['build_id'])
        build['status'] = 'failed'
        backend.store.put('builds', build['id'], build)
        full = backend.app_catalog(current.device_id, current)
        assert [row['name'] for row in full] == ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Åpen']
        assert {row['latest_package_id'] for row in full} == {p['id'] for p in packages}
        assert all(row['downloadable'] and row['version_count'] == 1 for row in full)

        counts = Counter()
        checked = []
        original_list, original_check = backend.store.list, backend.app_download_check

        def counted(group):
            counts[group] += 1
            return original_list(group)

        def checked_download(package, capabilities=None):
            checked.append(package['id'])
            return original_check(package, capabilities)

        monkeypatch.setattr(backend.store, 'list', counted)
        monkeypatch.setattr(backend, 'app_download_check', checked_download)
        rows = []
        for offset, next_offset in [(0, 4), (4, None), (100, None)]:
            counts.clear(); checked.clear()
            sent = event(current, 'app_list', offset=offset)
            await dispatch(backend, current, sent)
            page = next(e for e in reversed(peer.events) if e['type'] == 'app_catalog')
            assert page['offset'] == offset and page['next_offset'] == next_offset
            assert page['request_event_id'] == sent.event_id
            assert page['apps'] == full[offset:offset+4]
            assert len(checked) == len(page['apps'])
            for group in ['projects', 'builds', 'packages', 'repairs', 'commands', 'evolution_jobs']:
                assert counts[group] == 1
            rows += page['apps']
        assert rows == full
        assert not backend.store.list('commands') and not backend.usage.records()
    finally:
        await backend.close()


async def test_catalog_has_no_cross_request_delivery_or_owner_grant(tmp_path):
    backend = Backend(configured(tmp_path))
    try:
        current, peer = await session(backend)
        project, package = saved_app(backend, 'Timer', slug='timer')
        assert backend.app_catalog('fire-01', current)[0]['downloadable'] is True
        # A cached eligible row must not authorize delivery of a newly blocked source.
        package['quality'] = {'blocked': True}
        backend.store.put('packages', package['id'], package)
        assert backend.app_catalog('fire-01', current)[0]['downloadable'] is False
        with pytest.raises(ValueError):
            await dispatch(backend, current, event(current, 'app_download',
                project_id=project['id'], package_id=package['id']))
        assert not backend.store.list('commands')
        project['owner_device_id'] = 'fire-02'
        backend.store.put('projects', project['id'], project)
        assert backend.app_catalog('fire-01', current) == []
        with pytest.raises(PermissionError):
            await dispatch(backend, current, event(current, 'app_download',
                project_id=project['id'], package_id=package['id']))
        assert not backend.store.list('commands') and not backend.usage.records()
    finally:
        await backend.close()


async def test_foreign_malformed_packages_do_not_break_another_owners_catalog(tmp_path):
    backend = Backend(configured(tmp_path))
    try:
        current, _ = await session(backend)
        saved_app(backend, 'Timer', slug='timer')
        expected = backend.app_catalog('fire-01', current)
        for i, missing in enumerate([False, True]):
            _, foreign = saved_app(backend, 'Foreign', owner='fire-02', slug='foreign-'+str(i))
            foreign['manifest']['version'] = 'invalid.version'
            if missing: foreign.pop('build_id')
            backend.store.put('packages', foreign['id'], foreign)
        assert backend.app_catalog('fire-01', current) == expected
        assert backend.app_catalog_page('fire-01', current, 0) == (expected, 1)
    finally:
        await backend.close()

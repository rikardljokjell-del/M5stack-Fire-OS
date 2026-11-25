import hashlib
import json

import pytest

from fire_backend.data_engine import DataError
from test_data_engine import running, event, descriptor, finish


async def frozen_fork(backend, session):
    raw=b'ax\n1\n2\n'
    await backend.data_engine.request(session,event(session,operation='develop',mode='fork',
        instruction='Reuse the measured signal',options_json='{}',datasets=[descriptor(raw)]))
    for part,body in [('data',raw),('index',b''),('events',b'')]:
        await backend.data_engine.upload(session,'request-data','capture-one',0,body,hashlib.sha256(body).hexdigest(),part)
    context_id=(await finish(backend))['public_result']['context_id']
    return backend.data_engine.context(session.device_id,context_id)


async def test_fork_reads_only_frozen_parent_refs_without_copy_or_write_grants(tmp_path):
    backend,s,_,_=await running(tmp_path)
    try:
        context=await frozen_fork(backend,s)
        project=backend.new_project(s.device_id,'device')
        grant={'context_id':context['id'],'snapshot_sha256':context['snapshot_sha256'],'readonly':True,'proposal_id':'proposal-test'}
        project['parent_context_grant']=grant
        backend.store.put('projects',project['id'],project)
        record=backend.data_engine.dataset(s.device_id,project['id'],'capture-one',sealed=True)
        assert record['project_id']==s.project_id and record['state']=='sealed'
        with pytest.raises(DataError,match='not_found'):
            backend.data_engine.repo.get(s.device_id,project['id'],'capture-one')
        with pytest.raises(DataError,match='permission_denied'):
            backend.data_engine.dataset(s.device_id,project['id'],'ungranted-data',sealed=True)
        project['parent_context_grant']['snapshot_sha256']='0'*64
        backend.store.put('projects',project['id'],project)
        with pytest.raises(DataError,match='permission_denied'):
            backend.data_engine.dataset(s.device_id,project['id'],'capture-one',sealed=True)
        with pytest.raises(DataError,match='permission_denied'):
            backend.data_engine.dataset('another-owner',project['id'],'capture-one')
    finally:await backend.close()


async def test_project_delete_removes_only_its_data_while_version_delete_retains_raw(tmp_path):
    backend,s,_,package=await running(tmp_path)
    try:
        context=await frozen_fork(backend,s)
        row=backend.data_engine.repo.get(s.device_id,s.project_id,'capture-one',sealed=True)
        paths=[backend.data_engine.repo.path(row,sealed=True,part=p) for p in ['data','index','events']]
        # Existing version delete operates on its archive only; data is app history.
        backend.store.delete_version_files(package)
        assert all(p.exists() for p in paths)
        assert backend.data_engine.repo.register(s.device_id,s.project_id,descriptor(b'ax\n1\n2\n'))['id']==row['id']
        with pytest.raises(DataError,match='permission_denied'):
            backend.data_engine.repo.register(s.device_id,s.project_id,{**descriptor(b'ax\n1\n2\n'),'dataset_id':'new-after-source-delete'})
        other=backend.new_project(s.device_id,'device')
        backend.store.put('data_results','result-other',{'id':'result-other','project_id':other['id']})
        backend.store.delete_project(s.project_id)
        assert all(not p.exists() for p in paths)
        assert not backend.store.list('datasets') and not backend.store.list('development_contexts')
        assert not backend.store.list('data_jobs')
        assert backend.store.get('data_results','result-other')['project_id']==other['id']
    finally:await backend.close()


async def test_data_snapshot_and_download_require_sealed_owner_scope_and_open_context_is_normal_proposal(tmp_path):
    backend,s,_,_=await running(tmp_path)
    try:
        context=await frozen_fork(backend,s)
        snapshot=backend.data_engine.snapshot()
        assert snapshot['total_datasets']==1 and snapshot['contexts'][0]['user_confirmation']=='unconfirmed'
        row=snapshot['datasets'][0]
        path=await backend.data_engine.download(row['id'],'data')
        assert path.read_bytes()==b'ax\n1\n2\n'
        import httpx
        from fire_backend.app import create_app
        app=create_app(backend.settings.model_copy(update={'fire_desktop_enabled':True}));app.state.backend=backend
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            route=f"/desktop/data/{row['id']}/data"
            assert (await client.get(route)).status_code in {401,403}
            response=await client.get(route,headers={'Authorization':'Bearer '+backend.settings.fire_backend_token.get_secret_value()})
            assert response.status_code==200 and response.content==b'ax\n1\n2\n'
            assert response.headers['content-type']=='application/octet-stream'
            assert 'attachment' in response.headers['content-disposition']
        pc=await backend.desktop_conversation(s.device_id,hardware_preview=True,development_context_id=context['id'])
        assert pc.project_id!=s.project_id and pc.development_context_id==context['id']
        assert pc.proposal_id and pc.state.value=='awaiting_build_confirmation'
        assert not backend.store.list('commands') and not backend.usage.records()
        assert 'Reuse the measured signal' in backend.context_for(pc)
        with pytest.raises(ValueError):
            await backend.desktop_conversation(s.device_id,project_id=s.project_id,development_context_id=context['id'])
    finally:await backend.close()

import asyncio
import hashlib
import json

import pytest

from fire_backend.api_registry import preview_capabilities, service_closure
from fire_backend.app_sdk import SDK_VERSION, SDK_CONTRACT
from fire_backend.data_contract import EXTENSION, LIMITS
from fire_backend.data_engine import DataError
from fire_backend.models import Capabilities, DeviceEvent, Manifest, SessionStart
from fire_backend.runtime_contract import EXTENSION as AI_EXTENSION
from fire_backend.service import Backend
from test_device_protocol import configured


SOURCE = hashlib.sha256(b'test-data-source').hexdigest()


class Socket:
    def __init__(self): self.events = []
    async def send_json(self, event): self.events.append(event)


async def running(tmp_path):
    backend = Backend(configured(tmp_path))
    socket = Socket()
    session = await backend.start(SessionStart(device_id='fire-01', target='device', protocol_version='0.2',
        boot_id='boot-data', capabilities=Capabilities(**preview_capabilities())), socket, 'fire-01')
    project = backend.store.get('projects', session.project_id)
    project['app_id'] = 'signal-tool'; backend.store.put('projects', project['id'], project)
    services = service_closure(['display', 'buttons', 'data', 'ai'], SDK_VERSION)
    manifest = Manifest(id='signal-tool', name='Signal', version='0.1.1', api_version=SDK_VERSION,
        api_contract=SDK_CONTRACT, required_services=services, permissions=['fire.' + s for s in services],
        checksum=SOURCE, max_memory=131072, max_runtime_ms=0, data_engine=EXTENSION, runtime_ai=AI_EXTENSION)
    package = {'id': 'build-data', 'build_id':'build-data', 'project_id': project['id'], 'manifest': manifest.model_dump(),
               'archive_sha256': hashlib.sha256(b'archive-data').hexdigest()}
    backend.store.put('packages', package['id'], package)
    backend.store.put('builds', package['id'], {'id': package['id'], 'project_id': project['id'], 'summary': 'Measure signal'})
    # Isolated protocol fixture only; this is not a physical installation/start ACK.
    device = backend.device_record(session)
    device.update(active_run_id='run-data', running_package_id=package['id'], runtime_status='running')
    backend.store.put('devices', device['id'], device)
    return backend, session, socket, package


def event(session, **changes):
    values = dict(event='data_request', device_id=session.device_id, protocol_version='0.2',
        session_id=session.id, boot_id=session.boot_id, event_id='event-data', request_id='request-data',
        app_id='signal-tool', package_id='build-data', source_sha256=SOURCE, run_id='run-data',
        operation='process', dataset_id='capture-one', options_json='{"operation":"stats","column":"ax"}')
    values.update(changes)
    return DeviceEvent(**values)


def descriptor(raw):
    return {'dataset_id': 'capture-one', 'kind': 'csv', 'label': 'IMU sample', 'size': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(), 'metadata_json': '{"columns":["ax"],"sample_rate_hz":100}',
        'origin_package_id': 'build-data', 'origin_source_sha256': SOURCE,
        'origin_run_id': 'run-data', 'created_ms': 100,
        'components': {'data': {'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}, **{k:{'size':0,'sha256':hashlib.sha256(b'').hexdigest()} for k in ['index','events']}}}


async def finish(backend, request_id='request-data'):
    entry = backend.data_engine.tasks.get(request_id)
    if entry and entry['task']:
        await entry['task']
    return backend.store.get('data_jobs', request_id)


async def test_transfer_resume_then_stats_runs_on_same_service_without_model_or_commands(tmp_path):
    backend, session, socket, package = await running(tmp_path)
    try:
        raw = b'ax\n1\n2\n3\n'
        request = event(session, datasets=[descriptor(raw)])
        answer = await backend.data_engine.request(session, request)
        assert answer['status'] == 'upload_required'
        assert json.loads(socket.events[-1]['result_json'])['uploads'][0]['offset'] == 0
        response = await backend.data_engine.upload(session, request.request_id, 'capture-one', 0, raw[:5], hashlib.sha256(raw[:5]).hexdigest())
        assert response == {'offset': 5, 'complete': False, 'next_upload': {'dataset_id':'capture-one','part':'data','offset':5}}
        await backend.data_engine.request(session, request)  # Replay reports offset, never duplicate processing.
        assert json.loads(socket.events[-1]['result_json'])['uploads'][0]['offset'] == 5
        await backend.data_engine.upload(session, request.request_id, 'capture-one', 5, raw[5:], hashlib.sha256(raw[5:]).hexdigest())
        for part in ['index','events']:
            if backend.store.get('data_jobs',request.request_id)['state']=='upload_required':
                await backend.data_engine.upload(session,request.request_id,'capture-one',0,b'',hashlib.sha256(b'').hexdigest(),part)
        record = await finish(backend)
        assert record['state'] == 'completed'
        result = json.loads(socket.events[-1]['result_json'])
        assert result['data']['mean'] == 2 and len(socket.events[-1]['result_json'].encode()) <= LIMITS['result_bytes']
        assert backend.data_engine.repo.verified(session.device_id, session.project_id, 'capture-one')[1].read_bytes() == raw
        assert not backend.store.list('commands') and not backend.usage.records()
    finally: await backend.close()


async def test_stale_run_and_cross_source_are_refused_before_accepting_datasets(tmp_path):
    backend, session, socket, _ = await running(tmp_path)
    try:
        raw = b'ax\n1\n'
        for changes, code in [({'run_id':'old-run'}, 'stale_run'), ({'source_sha256':'c'*64}, 'permission_denied')]:
            answer = await backend.data_engine.request(session, event(session, datasets=[descriptor(raw)], **changes))
            assert answer['status'] == 'rejected' and answer['error_code'] == code
        assert not backend.store.list('datasets') and not backend.store.list('data_jobs')
    finally: await backend.close()


async def test_develop_freezes_source_data_and_creates_no_paid_work_or_install(tmp_path):
    backend, session, socket, package = await running(tmp_path)
    try:
        raw = b'ax\n1\n2\n'
        backend.data_engine.repo.register(session.device_id, session.project_id, descriptor(raw))
        backend.data_engine.repo.upload(session.device_id, session.project_id, 'capture-one', 0, raw, hashlib.sha256(raw).hexdigest())
        for part in ['index','events']:
            backend.data_engine.repo.upload(session.device_id,session.project_id,'capture-one',0,b'',hashlib.sha256(b'').hexdigest(),part)
        request = event(session, event='app_develop_request', operation=None, dataset_id=None,
                        options_json=None, mode='update', instruction='Improve based on this measurement', dataset_ids=['capture-one'])
        await backend.data_engine.request(session, request)
        record = await finish(backend)
        assert record['state'] == 'completed'
        ready = next(e for e in socket.events if e['type'] == 'app_develop_ready')
        frozen = backend.store.get('development_contexts', ready['context_id'])
        assert frozen['base_package_id'] == package['id'] and frozen['source_sha256'] == SOURCE
        assert frozen['dataset_refs'][0]['sha256'] == hashlib.sha256(raw).hexdigest()
        assert frozen['user_observation_confirmed'] is False and not frozen['physical_solution_verified']
        assert not backend.store.list('commands') and not backend.usage.records()
    finally: await backend.close()


async def test_runtime_refs_are_bounded_and_old_capture_source_is_not_current_run_identity(tmp_path):
    backend, session, socket, package = await running(tmp_path)
    try:
        raw = b'ax\n1\n2\n3\n'
        backend.data_engine.repo.register(session.device_id, session.project_id, descriptor(raw))
        backend.data_engine.repo.upload(session.device_id, session.project_id, 'capture-one', 0, raw, hashlib.sha256(raw).hexdigest())
        for part in ['index','events']:
            backend.data_engine.repo.upload(session.device_id,session.project_id,'capture-one',0,b'',hashlib.sha256(b'').hexdigest(),part)
        schema = {'type':'object','properties':{'value':{'type':'number'}},'required':['value'],'additionalProperties':False}
        identity = {k:getattr(event(session), k) for k in ('request_id','app_id','package_id','source_sha256','run_id','boot_id')}
        identity['timeout_ms'] = 30000
        resolved, refs = await backend.data_engine.resolve_ai_refs(session, identity, 'Assess signal', {'dataset_refs':['capture-one']}, schema)
        assert 'dataset_refs' not in resolved and resolved['datasets'][0]['mean'] == 2
        assert len(json.dumps(resolved, separators=(',', ':')).encode()) <= 768
        backend.data_engine.check_ai_refs(session, identity, refs)
        assert refs[0]['sha256'] == hashlib.sha256(raw).hexdigest()
        with pytest.raises(DataError, match='permission_denied'):
            await backend.data_engine.resolve_ai_refs(session, {**identity,'source_sha256':'f'*64}, 'Assess', {'dataset_refs':['capture-one']}, schema)
    finally: await backend.close()


async def test_http_zero_byte_components_have_exact_length_and_finish_on_same_backend(tmp_path):
    import httpx
    from fire_backend.app import create_app
    backend, session, socket, _ = await running(tmp_path)
    try:
        raw = b'ax\n1\n2\n'
        await backend.data_engine.request(session, event(session, datasets=[descriptor(raw)]))
        app = create_app(backend.settings)
        app.state.backend = backend  # Existing test instance; no extra server/lifespan.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            for part,body in [('data',raw),('index',b''),('events',b'')]:
                response = await client.post(f'/sessions/{session.id}/data/request-data/capture-one',content=body,
                    headers={'Authorization':'Bearer '+backend.settings.device_tokens()[session.device_id],
                        'Content-Type':'application/octet-stream','X-Data-Offset':'0','X-Data-Part':part,
                        'X-Data-SHA256':hashlib.sha256(body).hexdigest()})
                assert response.status_code == 200, response.text
                assert response.json()['complete'] is True
                assert int(response.headers['content-length']) == len(response.content)
                assert any(name==b'Content-Length' for name,value in response.headers.raw)
        assert (await finish(backend))['state']=='completed'
    finally: await backend.close()


async def test_cancelled_http_worker_keeps_dataset_lock_until_actual_write_finishes(tmp_path):
    import threading
    backend, session, socket, _ = await running(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = backend.data_engine.repo.write_chunk
    call_order = []
    def blocked(*args):
        call_order.append(args[1])
        if len(call_order)==1:
            entered.set(); release.wait(3)
        return original(*args)
    try:
        raw=b'ax\n1\n2\n'
        await backend.data_engine.request(session,event(session,datasets=[descriptor(raw)]))
        backend.data_engine.repo.write_chunk=blocked
        first=asyncio.create_task(backend.data_engine.upload(session,'request-data','capture-one',0,raw[:3],hashlib.sha256(raw[:3]).hexdigest()))
        assert await asyncio.to_thread(entered.wait,2)
        first.cancel()
        second=asyncio.create_task(backend.data_engine.upload(session,'request-data','capture-one',3,raw[3:],hashlib.sha256(raw[3:]).hexdigest()))
        await asyncio.sleep(.02)
        assert call_order==[0] and not first.done() and not second.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):await first
        assert (await second)['complete']
        assert call_order==[0,3]
    finally:
        release.set();await backend.close()


async def test_os_observation_confirmation_is_separate_source_bound_and_reject_is_retained(tmp_path):
    from fire_backend.protocol import dispatch
    backend,session,socket,_=await running(tmp_path)
    try:
        request=event(session,event='app_develop_request',operation=None,dataset_id=None,options_json=None,
                      mode='feedback',instruction='The observed result changed')
        await backend.data_engine.request(session,request);record=await finish(backend)
        context_id=record['public_result']['context_id']
        before=backend.store.get('development_contexts',context_id)
        for choice in ['confirm','reject']:
            await dispatch(backend,session,event(session,event='app_observation_confirm',event_id='observe-'+choice,
                operation=None,dataset_id=None,options_json=None,context_id=context_id,observation_action=choice))
        feedback=[r for r in backend.store.list('feedback') if r.get('event')=='user_confirmation']
        assert {r['observation_action'] for r in feedback}=={'confirm','reject'}
        assert all(r['context_snapshot_sha256']==before['snapshot_sha256'] for r in feedback)
        assert all(r['run_id']==before['run_id'] and r['boot_id']==before['boot_id'] for r in feedback)
        assert all(r['provenance']=='os_user_confirmation' and not r['physical_solution_verified'] for r in feedback)
        assert backend.store.get('development_contexts',context_id)==before
        assert not backend.usage.records()
    finally:await backend.close()


async def test_cancel_before_first_processing_turn_clears_job_without_losing_partial_raw(tmp_path):
    backend,s,_,_=await running(tmp_path)
    try:
        await backend.data_engine.request(s,event(s,event='app_develop_request',mode='feedback',
            operation=None,dataset_id=None,options_json=None,instruction='Observed result'))
        assert backend.data_engine.tasks['request-data']['task']
        await backend.data_engine.cancel('request-data')
        assert not backend.data_engine.tasks
        assert backend.store.get('data_jobs','request-data')['state']=='cancelled'
        assert not backend.store.list('development_contexts') and not backend.usage.records()
    finally:await backend.close()

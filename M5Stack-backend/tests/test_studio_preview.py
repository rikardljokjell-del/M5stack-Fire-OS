"""Authenticated Studio preview, immutable bytes and no physical actions."""
import hashlib

from fire_backend.app_sdk import DATA, SDK_VERSION, SDK_CONTRACT
from fire_backend.builds import write_archive
from fire_backend.models import Manifest
from test_browser_access import web


def ready_package(backend):
    source=(DATA/'stopwatch.lua').read_bytes()
    manifest=Manifest(id='stopwatch',name='Stoppeklokke',version='0.1.1',api_version=SDK_VERSION,
        api_contract=SDK_CONTRACT,required_services=['display','buttons'],permissions=['fire.display','fire.buttons'],
        max_runtime_ms=0,max_memory=131072,checksum=hashlib.sha256(source).hexdigest()).model_dump()
    key='build-preview'
    folder=backend.store.path('builds',key,'');folder.mkdir(parents=True)
    archive=backend.store.path('packages',key,'.zip');write_archive(archive,manifest,source)
    package=dict(id=key,build_id=key,project_id='project-preview',manifest=manifest,
                 archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    backend.store.put('builds',key,dict(id=key,status='ready'))
    backend.store.put('packages',key,package)
    return key,archive


def test_preview_requires_browser_authority_and_csrf_then_replays_without_device_commands(web):
    client,app,_,_=web
    key,archive=ready_package(app.state.backend)
    url=f'/web/packages/{key}/preview'
    assert client.post(url,json={},headers={'X-Fire-CSRF':''}).status_code==403
    assert client.post(url,json={'buttons':['HOME']}).status_code==422
    assert client.post(url,json={'elapsed_ms':12001}).status_code==422
    response=client.post(url,json={'buttons':['B'],'elapsed_ms':1500})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['physical_verified'] is False and result['images']
    assert all(i['source_sha256']==result['source_sha256'] and i['sdk_contract']==SDK_CONTRACT for i in result['images'])
    assert not app.state.backend.store.list('commands')
    archive.write_bytes(archive.read_bytes()+b'bad')
    assert client.post(url,json={}).status_code==400


def test_preview_never_marks_a_failed_package_deliverable(web):
    client,app,_,_=web
    key,_=ready_package(app.state.backend)
    package=app.state.backend.store.get('packages',key)
    package['quality']={'blocked':True,'reason':'physical runtime failure'}
    app.state.backend.store.put('packages',key,package)
    assert client.post(f'/web/packages/{key}/preview',json={}).status_code==200
    assert app.state.backend.store.get('packages',key)['quality']['blocked']
    build=app.state.backend.store.get('builds',key);build['status']='failed'
    app.state.backend.store.put('builds',key,build)
    assert client.post(f'/web/packages/{key}/preview',json={}).status_code==400

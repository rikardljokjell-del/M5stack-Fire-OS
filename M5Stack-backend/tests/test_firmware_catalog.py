import base64
import json

import httpx
import pytest

from fire_backend import firmware_catalog as f


def index(version="fire-os-1.1"):
    return {"schema":1,"repository":f.REPOSITORY,"target":"m5stack-fire",
            "files":[{"name":version+'.bin',"version":version}]}


def signed(version="1.2.0-rc1"):
    payload={**index(version),"schema":2,"layout":"fire-ab-recovery-v1","min_recovery":1}
    return {"schema":2,"algorithm":"ecdsa-p256-sha256","key_id":"test-only","signature":"unverified-metadata",
            "payload":base64.b64encode(json.dumps(payload).encode()).decode()}


def transport(monkeypatch, values):
    calls=[];client=httpx.AsyncClient
    def request(req):
        calls.append(str(req.url))
        assert req.headers.get('authorization') is None
        assert not req.url.path.endswith('.bin')
        value=values[str(req.url)]
        return httpx.Response(value) if type(value) is int else httpx.Response(200,json=value)
    def factory(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return client(transport=httpx.MockTransport(request),**kwargs)
    monkeypatch.setattr(f.httpx,'AsyncClient',factory)
    return calls


async def test_current_legacy_and_releases_merge_cached_without_binary_download(monkeypatch):
    current=signed();legacy=index()
    legacy['files'].append({'name':'older-duplicate.bin','version':'1.2.0-rc1'})
    calls=transport(monkeypatch,{f.INDEX:current,f.LEGACY_INDEX:legacy,
        f.RELEASES:[{'tag_name':'fire-os-1.1','name':'release-duplicate'},
                    {'tag_name':'1.1.5','name':'Extra release','body':'Kort info'}]})
    catalog=f.FirmwareCatalog();result=await catalog.get()
    rows=result['releases']
    assert [r['version'] for r in rows]==['1.2.0-rc1','fire-os-1.1','1.1.5']
    assert rows[0]['signed'] and rows[0]['signature_verified'] is False
    assert rows[0]['source']=='firmware/index.json'
    assert rows[1]['legacy_unsigned'] and rows[1]['source']=='firmware/legacy-index-v1.json'
    assert 'Ikke for den nye recovery-layouten' in rows[1]['compatibility']
    assert not result['error']
    assert (await catalog.get())==result and len(calls)==3


@pytest.mark.parametrize('legacy',[404,{'unexpected':'data'},None])
async def test_missing_or_invalid_legacy_archive_never_breaks_current(monkeypatch,legacy):
    transport(monkeypatch,{f.INDEX:signed(),f.LEGACY_INDEX:legacy,f.RELEASES:[]})
    result=await f.FirmwareCatalog().get()
    assert len(result['releases'])==1 and not result['error']


async def test_total_failure_preserves_previous_metadata_and_reports_error(monkeypatch):
    transport(monkeypatch,{f.INDEX:503,f.LEGACY_INDEX:404,f.RELEASES:403})
    catalog=f.FirmwareCatalog();catalog.cached=[{'version':'previous'}]
    result=await catalog.get()
    assert result['releases']==[{'version':'previous'}] and result['error']

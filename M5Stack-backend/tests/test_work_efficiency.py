import json

import pytest

from fire_backend.ai import MockProvider
from fire_backend.generation_errors import GenerationResponseError
from fire_backend.models import GeneratedApp
from fire_backend.service import Backend
from test_device_protocol import configured
from test_pre_delivery import build


class ReviewInterrupted(MockProvider):
    def __init__(self):self.generations=0;self.reviews=0
    async def generate(self,*args):
        self.generations+=1
        return await super().generate(*args)
    async def review(self,*args):
        self.reviews+=1
        if self.reviews==1:raise GenerationResponseError('ai_incomplete','AI-svaret ble avbrutt')
        return await super().review(*args)


@pytest.mark.parametrize('change',[None,'summary','source'])
async def test_resume_reuses_locally_validated_source_only_when_identity_and_requirements_match(tmp_path,change):
    p=ReviewInterrupted();b=Backend(configured(tmp_path),p)
    try:
        first=await build(b);old=b.store.get('builds',first.build_id)
        assert old['status']=='failed' and old['attempts']==1
        assert not b.store.list('quality')  # API failure is not a Lua-source defect.
        if change=='source':
            (b.store.path('builds',old['id'],'')/'attempt-1.lua').write_text('tampered',encoding='utf-8')
        elif change=='summary':
            old['summary']+=' Endre fargen.'
            old['resume_context']['summary']=old['summary'];b.store.put('builds',old['id'],old)
        result=await b.jobs.resume(old['id']);current=b.session(result['session_id'])
        assert p.generations==1 and current.proposal_id
        await b.confirm_build(current,current.proposal_id);await current.task
        ready=b.store.get('builds',current.build_id)
        assert ready['status']=='ready' and p.reviews==2
        assert p.generations==(1 if change is None else 2)
        assert bool(ready.get('reused_candidate_from'))==(change is None)
        assert b.store.get('packages',ready['id'])['validation']['suite']=='release-v4'
    finally:await b.close()


class Progressing(MockProvider):
    def __init__(self,stuck=False):self.calls=0;self.stuck=stuck
    async def generate(self,*args):
        self.calls+=1
        if self.calls==1 or self.stuck:
            return GeneratedApp(name='Test',main_lua='function init( end',required_services=[])
        if self.calls==2:
            return GeneratedApp(name='Test',main_lua="function init() end function update(dt) error('different failure') end",required_services=[])
        return await super().generate(*args)


@pytest.mark.parametrize('stuck',[False,True])
async def test_zero_means_adaptive_corrections_with_progress_not_an_endless_paid_loop(tmp_path,stuck):
    p=Progressing(stuck);b=Backend(configured(tmp_path,fire_max_corrections=0),p)
    try:
        s=await build(b);row=b.store.get('builds',s.build_id)
        assert row['max_attempts'] is None
        if stuck:
            assert row['status']=='failed' and p.calls==2 and row['error_code']=='ai_no_progress'
            assert not b.store.list('packages')
        else:
            assert row['status']=='ready' and p.calls==3
    finally:await b.close()

import copy

import pytest

from fire_backend.ai import MockProvider,OpenAIProvider
from fire_backend.app_quality import APP_QUALITY_POLICY,AppReview,ReviewIssue
from fire_backend.models import GeneratedApp
from fire_backend.quality import require_deliverable
from fire_backend.revalidation import revalidate_package
from fire_backend.service import Backend
from test_device_protocol import configured


def approve():
    return AppReview(requirements_met=True,runtime_safe=True,visual_quality_ok=True,issues=[])


class ReviewedProvider(MockProvider):
    def __init__(self,always_reject=False):
        self.generated=[];self.reviewed=[];self.always_reject=always_reject

    async def generate(self,summary,context,error=None,previous=None):
        self.generated.append((context,error,previous))
        assert APP_QUALITY_POLICY in context
        if len(self.generated)>1:
            assert 'Pre-delivery review rejected' in error and 'status area' in error
        return GeneratedApp(name='Sirkel',required_services=['display'],main_lua=
            "function init() end function update(dt) fire.display.circle(80,80,12,2016) "
            +( "fire.display.text(8,8,'Sirkel',65535) " if len(self.generated)>1 else '')+'end')

    async def review(self,summary,context,generated,validation):
        self.reviewed.append(generated.main_lua)
        assert validation['suite']=='release-v4'
        if len(self.reviewed)==1 or self.always_reject:
            return AppReview(requirements_met=True,runtime_safe=True,visual_quality_ok=False,
                issues=[ReviewIssue(category='design',description='Missing readable title/status area; add a compact status area without hiding the animation.')])
        return approve()


async def build(service):
    session=await service.desktop_conversation('fire-01')
    await service.text(session,'Lag en sirkel')
    await service.confirm_build(session,session.proposal_id);await session.task
    return session


async def test_passing_runtime_candidate_is_corrected_before_first_delivery(tmp_path):
    provider=ReviewedProvider();service=Backend(configured(tmp_path),provider)
    try:
        # Learned native precautions must already reach the FIRST generation.
        service.quality.record(project_id='app-earlier',message='native callback budget exceeded',provenance='test')
        s=await build(service)
        p=service.store.get('packages',s.package_id)
        assert len(provider.generated)==len(provider.reviewed)==2
        assert 'Cache text/rotation' in provider.generated[0][0]
        assert 'Sirkel' in provider.reviewed[-1] and provider.generated[1][2]==provider.reviewed[0]
        assert len(service.store.list('packages'))==1 and len(service.store.list('builds'))==1
        assert p['manifest']['version']=='0.1.1' # Corrections stay internal, not new deliveries.
        review=p['validation']['pre_delivery_review']
        assert review['approved'] and review['source_sha256']==p['manifest']['checksum']
        assert review['mode']=='mock_fixture' and review['physical_verified'] is False
        require_deliverable(p)
        assert not service.store.list('commands')
        await revalidate_package(service.store,p['id'],apply=True)
        assert service.store.get('packages',p['id'])['validation']['pre_delivery_review']==review
    finally:await service.close()


async def test_persistent_design_defect_is_never_packaged(tmp_path):
    provider=ReviewedProvider(always_reject=True);service=Backend(configured(tmp_path),provider)
    try:
        s=await build(service)
        assert len(provider.generated)==4 and len(provider.reviewed)==4
        assert s.package_id is None and not service.store.list('packages')
        assert not list((service.store.root/'packages').glob('*.zip'))
        assert not service.store.list('commands')
        assert any(c['category']=='design' for c in service.store.list('quality'))
    finally:await service.close()


async def test_delivery_rejects_missing_stale_or_mock_review_for_live_package(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        s=await build(service);p=service.store.get('packages',s.package_id)
        require_deliverable(p)
        for mutate in ('missing','different_source','rejected_checks','mock_live'):
            bad=copy.deepcopy(p)
            if mutate=='missing':bad['validation'].pop('pre_delivery_review')
            if mutate=='different_source':bad['validation']['pre_delivery_review']['source_sha256']='0'*64
            if mutate=='rejected_checks':bad['validation']['pre_delivery_review']['checks']['runtime_safe']=False
            if mutate=='mock_live':bad['mode']='openai'
            with pytest.raises(ValueError,match='designkontroll'):require_deliverable(bad)
    finally:await service.close()


async def test_live_provider_uses_separate_structured_review_without_executing_code(tmp_path):
    from types import SimpleNamespace
    from fire_backend.lua_worker import simulate
    calls=[]
    class Responses:
        async def parse(self,**values):
            calls.append(values)
            return SimpleNamespace(status='completed',output_parsed=approve())
    settings=configured(tmp_path,openai_api_key='test-only-key');provider=OpenAIProvider(settings)
    provider.client=SimpleNamespace(responses=Responses())
    app=GeneratedApp(name='Sirkel',main_lua="function init() end function update(dt) fire.display.circle(20,20,5,2016) end",required_services=['display'])
    review=await provider.review('Lag en sirkel','negotiated API',app,simulate({'main_lua':app.main_lua,'required_services':['display']}))
    assert review.approved and calls[0]['text_format'] is AppReview and calls[0]['store'] is False
    assert calls[0]['model']==settings.openai_code_model
    assert APP_QUALITY_POLICY in calls[0]['instructions'] and 'main_lua' in calls[0]['input']

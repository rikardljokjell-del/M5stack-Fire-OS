import pytest
from fire_backend.api_registry import service_closure,preview_capabilities,API_CONTRACT,package_compatibility
from fire_backend.models import Manifest,GeneratedApp
from fire_backend.ai import MockProvider
from fire_backend.service import Backend
from test_device_protocol import configured


def test_speaker_permissions_include_transitive_sd_jobs_even_for_tone_only():
    assert service_closure(['speaker'])==['jobs','sd','speaker']
    assert service_closure(['speaker','jobs'])==['jobs','sd','speaker']
    assert service_closure(['uart','i2c','sd'])==['i2c','jobs','sd','uart']
    assert service_closure(['display'],'fire-lua-0.1')==['display']


def test_missing_dependency_is_rejected_before_archive_or_device_delivery():
    m=dict(id='melodi',name='Melodi',version='0.1.1',api_version='fire-lua-0.2',api_contract=API_CONTRACT,
           required_services=['speaker','jobs'],permissions=['fire.speaker','fire.jobs'],checksum='a'*64)
    with pytest.raises(ValueError,match='dependencies invalid'):Manifest.model_validate(m)
    assert 'avhengigheter' in package_compatibility({'manifest':m},preview_capabilities())
    m.update(required_services=service_closure(m['required_services']),permissions=['fire.'+s for s in service_closure(m['required_services'])])
    assert Manifest.model_validate(m)


@pytest.mark.parametrize('sdk',[False,True])
async def test_builder_supplies_dependencies_without_changing_melody_source(tmp_path,sdk):
    from fire_backend.app_quality import FireAppReview
    code="local j=nil function init() j=fire.speaker.tone(440,100,40) end function update(dt) if j and fire.jobs.poll(j).done then fire.jobs.close(j) j=nil end fire.display.text(4,4,'Melodi',2016) end"
    class Provider(MockProvider):
        async def generate(self,*args):return GeneratedApp(name='Melodi',main_lua=code,required_services=['display','speaker','jobs'])
        async def review(self,*args):return FireAppReview(requirements_met=True,runtime_safe=True,visual_quality_ok=True,issues=[],kind='app',**{name:True for name in FireAppReview.fire_checks()})
    b=Backend(configured(tmp_path).model_copy(update={'fire_ai_mode':'openai'}),Provider())
    try:
        s=await b.desktop_conversation('fire-01',hardware_preview=True)
        # This fixture isolates transitive speaker permissions, not experience
        # defaults. Exercise legacy plus a legitimate SDK profile without RGB;
        # mandatory RGB on advertised devices has its own real-builder tests.
        if sdk:s.capabilities['services'].remove('rgb')
        else:s.capabilities.pop('app_sdk')
        await b.text(s,'Lag en sirkel');await b.confirm_build(s,s.proposal_id);await s.task
        p=b.store.get('packages',s.package_id)
        assert {'speaker','sd','jobs'}<=set(p['manifest']['required_services'])
        assert 'fire.sd' in p['manifest']['permissions']
        assert p['validation']['jobs_started']['speaker.tone']>0
        assert not any(k.startswith('sd.') for k in p['validation']['io_calls'])
        assert not b.store.list('commands')
    finally:await b.close()

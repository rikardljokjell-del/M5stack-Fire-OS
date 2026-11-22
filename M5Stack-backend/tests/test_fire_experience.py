import copy

import pytest

from fire_backend.app_quality import AppReview,FireAppReview,UX_POLICY_VERSION,experience_contract
from fire_backend.ai import MockProvider
from fire_backend.builds import validate_release
from fire_backend.models import SessionStart
from fire_backend.quality import require_deliverable
from fire_backend.service import Backend
from test_device_protocol import configured


def fire_review(**changes):
    values=dict(requirements_met=True,runtime_safe=True,visual_quality_ok=True,issues=[],kind='game',
                **{name:True for name in FireAppReview.fire_checks()})
    return FireAppReview(**{**values,**changes})


def test_device_contract_has_fixed_navigation_and_truthful_audio():
    contract=experience_contract({'services':['display','rgb','jobs'],'audio_output':True})
    assert contract['navigation']=={'A':'previous/up','B':'select/confirm','C':'next/down'}
    assert contract['screen']=={'width':320,'height':240,'os_insets':0}
    assert contract['reserved']['long']=={'A':'home','B':'quick_settings','C':'back'}
    assert contract['reserved']['long_ms']==650
    assert contract['game_audio_available'] is False and 'unavailable' in contract['game_menu']['sound']
    assert contract['game_menu']['rgb']=='toggle'
    assert experience_contract({'services':['speaker','jobs']})['game_audio_available']
    assert not experience_contract({'services':['speaker']})['game_audio_available']
    assert experience_contract({'services':[]})['game_menu']['rgb']=='unavailable'


@pytest.mark.parametrize('field',FireAppReview.fire_checks())
def test_each_device_experience_check_is_a_release_condition(field):
    r=fire_review(**{field:False})
    assert not r.approved and field in r.correction()
    with pytest.raises(ValueError):fire_review(**{field:'yes'})


async def test_new_review_flags_and_policy_version_are_required_at_delivery(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        s=await service.start(SessionStart());await service.text(s,'Lag en sirkel')
        await service.confirm_build(s,s.proposal_id);await s.task
        p=service.store.get('packages',s.package_id);require_deliverable(p)
        review=p['validation']['pre_delivery_review']
        assert review['experience_policy_version']==UX_POLICY_VERSION
        for field in FireAppReview.fire_checks():
            bad=copy.deepcopy(p);bad['validation']['pre_delivery_review']['checks'][field]=False
            with pytest.raises(ValueError,match='designkontroll'):require_deliverable(bad)
        bad=copy.deepcopy(p);bad['validation']['pre_delivery_review']['experience_policy_version']='unknown'
        with pytest.raises(ValueError):require_deliverable(bad)
        bad=copy.deepcopy(p);bad['validation']['pre_delivery_review']['checks'].pop('controls_ok')
        with pytest.raises(ValueError):require_deliverable(bad)
    finally:await service.close()


async def test_explicit_os_and_ten_minute_profiles_are_in_new_live_gate(tmp_path):
    service=Backend(configured(tmp_path))
    try:
        result=await validate_release({'main_lua':"function init() end function update(dt) fire.display.circle(40,40,8,2016) end",
            'required_services':['display'],'max_memory':131072,'max_runtime_ms':0,
            'experience_policy_version':UX_POLICY_VERSION},service.store,'build-ux-gate')
        profiles={p['profile']:p for p in result['profiles']}
        assert len(profiles)==12 and profiles['long_session']['elapsed_ms']==600000
        assert profiles['os_long_a']['os_exited']
        assert profiles['os_long_b']['os_updates_suspended']>0
        assert profiles['os_double']['os_reserved_callbacks_suppressed']==2
        assert result['physical_verified'] is False
    finally:await service.close()


async def test_live_build_cannot_fall_back_to_old_three_flag_review(tmp_path):
    class OldReviewer(MockProvider):
        async def review(self,*args):
            return AppReview(requirements_met=True,runtime_safe=True,visual_quality_ok=True,issues=[])
    service=Backend(configured(tmp_path).model_copy(update={'fire_ai_mode':'openai'}),OldReviewer())
    try:
        s=await service.start(SessionStart());await service.text(s,'Lag en sirkel')
        # Make the fixture quick; no secret/API/network call is used by this provider.
        s.capabilities={'services':['display','buttons','rgb','imu','time'],'max_memory':131072,'max_runtime_ms':16}
        await service.confirm_build(s,s.proposal_id);await s.task
        assert s.package_id is None and not service.store.list('packages')
        assert service.store.get('builds',s.build_id)['attempts']==4
    finally:await service.close()

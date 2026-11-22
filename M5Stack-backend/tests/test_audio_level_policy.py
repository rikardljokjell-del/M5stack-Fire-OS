import pytest
from fire_backend.app_quality import experience_contract,APP_QUALITY_POLICY,FireAppReview


def test_default_audio_gain_is_full_relative_gain_under_os_master():
    policy=experience_contract({'services':['speaker','jobs','sd']})
    assert policy['audio_gain']['default']==255
    assert policy['audio_gain']['maximum']==255 and policy['audio_gain']['master_zero']=='silent'
    assert 'gain MUST be 255/255' in APP_QUALITY_POLICY
    assert 'never raise the OS volume' in APP_QUALITY_POLICY


def test_audio_level_is_an_independent_release_review_check():
    fields=dict(requirements_met=True,runtime_safe=True,visual_quality_ok=True,issues=[],kind='app',
                **{name:True for name in FireAppReview.fire_checks()})
    assert FireAppReview(**fields).approved
    fields['audio_level_ok']=False
    review=FireAppReview(**fields)
    assert not review.approved and 'audio_level_ok' in review.correction()
    fields['audio_level_ok']='yes'
    with pytest.raises(ValueError):FireAppReview(**fields)


async def test_low_gain_failure_has_a_persistent_fixed_regression_rule(tmp_path):
    from fire_backend.service import Backend
    from test_device_protocol import configured
    b=Backend(configured(tmp_path))
    try:
        case=b.quality.record(project_id='app-audio',message='audio gain44 nearly inaudible',provenance='user_report')
        assert case['category']=='audio_level'
        assert '255/255' in b.quality.policy()
        assert case['regression']['rule_id'].endswith('/audio_level')
    finally:await b.close()

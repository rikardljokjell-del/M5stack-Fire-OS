from fire_backend.build_strategy import RepairBaseline,source_hash
from fire_backend.app_quality import FireAppReview,ReviewIssue
from fire_backend.prompt_context import normalized_repair_summary
from fire_backend.sdk_standards import contract
from fire_backend.api_registry import preview_capabilities
from test_pre_delivery import approve


def review_failure():
    return FireAppReview(**{**approve().model_dump(),'runtime_safe':False,'kind':'game',
        **{k:False for k in FireAppReview.fire_checks()},'issues':[ReviewIssue(category='runtime',description='Fix audio cleanup')]})


def test_standard_pass_with_review_findings_beats_earlier_missing_audio_candidate():
    baseline=RepairBaseline()
    baseline.failure('core','Missing audio',local_passed=True,standard_passed=False)
    result=baseline.failure('complete core','Fix audio cleanup',local_passed=True,standard_passed=True,review=review_failure())
    assert result['candidate_selected_as_baseline'] and baseline.source=='complete core'
    assert result['repair_baseline_sha256']==source_hash('complete core')
    regressed=baseline.failure('broken menu','nil button',local_passed=False)
    assert not regressed['candidate_selected_as_baseline'] and baseline.source=='complete core'
    assert regressed['baseline_findings']['source_sha256']==source_hash('complete core')


def test_nested_repair_boilerplate_and_mojibake_are_normalized_only_in_view():
    original='Reparer eksisterende app. Opprinnelige krav: '*4+'Lag en blÃ¥ klokke.'
    assert normalized_repair_summary(original)=='Lag en blå klokke.'
    assert original.startswith('Reparer') and 'Ã¥' in original


def test_current_visual_scope_can_defer_new_audio_but_not_existing_audio():
    text='Oppgrader Prikkjakt visuelt. Om lyd er aktivert senere skal den ha meny; nå visuell oppgradering.'
    a=contract(preview_capabilities(),text)
    assert a['audio_deferred_for_scope'] and not a['audio_required']
    b=contract(preview_capabilities(),text,{'required_services':['display','speaker','jobs','sd']})
    assert not b['audio_deferred_for_scope'] and b['audio_required']

"""Retest immutable archived Lua without AI, version changes or device actions."""
import time
import zipfile
import json
import re

from .builds import validate_release, verify_archive
from .quality import Quality


def sdk_revalidation_input(store,package,build,source):
    """Recover confirmed scope/capabilities and exact candidate test sequences.

    No fresh model interpretation and no capability inference from the manifest.
    This helper is also used by isolated offline audits of retained candidates.
    """
    from .sdk_standards import contract
    from .lua_worker import without_literals
    folder=store.path('builds',build['id'],'')
    request_path=folder/'request.json'
    if request_path.stat().st_size>256000:raise ValueError('SDK revalidation request exceeds bound')
    original=json.loads(request_path.read_text(encoding='utf-8'))
    capabilities=original.get('capabilities') or {}
    expected=contract(capabilities,build.get('effective_summary') or original['summary'])
    if not expected:raise ValueError('SDK revalidation needs the original actual SDK capabilities')
    attempt=build.get('attempts',0)
    if type(attempt) is not int or not 1<=attempt<=10000:raise ValueError('Missing SDK candidate identity')
    meta_path=folder/f'candidate-{attempt}.json';plan_path=folder/f'test-plan-{attempt}.json'
    if meta_path.stat().st_size>24000 or plan_path.stat().st_size>24000:raise ValueError('SDK candidate metadata exceeds bound')
    if json.loads(meta_path.read_text(encoding='utf-8'))['source_sha256']!=package['manifest']['checksum']:
        raise ValueError('SDK revalidation candidate checksum mismatch')
    coverage=set(package['manifest']['required_services'])
    if 'speaker' in coverage and not re.search(r'\bfire\s*\.\s*sd\b',without_literals(source)):coverage.discard('sd')
    return expected,dict(hardware=capabilities.get('hardware') or {},
        test_sequences=json.loads(plan_path.read_text(encoding='utf-8')),
        require_io_coverage=True,defer_io_coverage=True,coverage_services=sorted(coverage))


async def revalidate_package(store,package_id,*,apply=False):
    # Caller must hold the workspace lock, with the normal server stopped.
    package=store.get('packages',package_id)
    if package.get('quality',{}).get('blocked'):
        return {'package_id':package_id,'status':'skipped_known_failure'}
    build=store.get('builds',package['build_id'])
    if build['status']!='ready':raise ValueError('Package build is not ready')
    manifest=package['manifest'];path=store.path('packages',package_id,'.zip')
    verify_archive(path,manifest,package['archive_sha256'])
    with zipfile.ZipFile(path) as archive:
        source=archive.read(f"apps/{manifest['id']}/main.lua").decode('utf-8')
    try:
        from .app_quality import UX_POLICY_VERSION
        from .app_sdk import SDK_VERSION
        from .sdk_standards import verify,require_passed
        standard=None;extra={}
        if manifest['api_version']==SDK_VERSION and package.get('mode')=='openai':
            standard,extra=sdk_revalidation_input(store,package,build,source)
        validation=await validate_release({'main_lua':source,'required_services':manifest['required_services'],
            **({'experience_policy_version':UX_POLICY_VERSION} if package.get('mode')=='openai' else {}),
            'api_version':manifest['api_version'],'api_contract':manifest.get('api_contract'),'max_memory':manifest['max_memory'],
            'max_runtime_ms':manifest['max_runtime_ms'],'hardware':package.get('validation',{}).get('resources_used',{}),**extra},store,package_id)
        if standard:
            validation['standard_contract']=standard
            validation['standard_verification']=verify(standard,manifest['required_services'],validation,manifest['checksum'])
            require_passed(validation['standard_verification'])
    except (OSError,ValueError,KeyError) as error:
        if apply:
            Quality(store).record(project_id=package['project_id'],package_id=package_id,source_hash=manifest['checksum'],
                build_id=package['build_id'],message=str(error),provenance='release_revalidation')
        return {'package_id':package_id,'status':'failed','error':store.redactor.text(str(error))[:600]}
    verify_archive(path,manifest,package['archive_sha256'])
    # Retesting byte-identical code must never erase an independent review gate.
    for field in ('pre_delivery_review_required','pre_delivery_review'):
        if field in package.get('validation',{}):validation[field]=package['validation'][field]
    if apply:
        package['validation_history']=(package.get('validation_history',[])+[package.get('validation',{})])[-3:]
        package['validation']={**validation,'revalidated_at':time.time()}
        store.put('packages',package_id,package)
    return {'package_id':package_id,'status':'passed','suite':validation['suite'],'profiles':len(validation['profiles'])}

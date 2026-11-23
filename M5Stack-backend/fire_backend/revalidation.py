"""Retest immutable archived Lua without AI, version changes or device actions."""
import time
import zipfile

from .builds import validate_release, verify_archive
from .quality import Quality


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
        validation=await validate_release({'main_lua':source,'required_services':manifest['required_services'],
            **({'experience_policy_version':UX_POLICY_VERSION} if package.get('mode')=='openai' else {}),
            'api_version':manifest['api_version'],'max_memory':manifest['max_memory'],
            'max_runtime_ms':manifest['max_runtime_ms'],'hardware':package.get('validation',{}).get('resources_used',{})},store,package_id)
    except ValueError as error:
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

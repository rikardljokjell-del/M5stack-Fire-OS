import asyncio
import hashlib
import json
import os
import platform
import random
import re
from itertools import count
import time
from email.utils import parsedate_to_datetime
import shutil
import sys
import tempfile
import zipfile
from importlib import metadata
from pathlib import Path
from openai import APIStatusError,APIConnectionError

from .sdk_standards import contract as sdk_standard_contract,verify as verify_sdk_standard,require_passed as require_sdk_standard,context_with_contract
from .sdk_context import normalize as sdk_context_normalize,VERSION as SDK_POLICY_VERSION
from .app_sdk import SDK_VERSION,SDK_CONTRACT,package_api,selected_context
from .models import Manifest,AppTestSequence,GeneratedApp
from .storage import canonical
from .app_names import app_id_for
from .rendering import VISUAL_POLICY,NATIVE_HOST_POLICY
from .status_text import build_text
from .provider_errors import account_limit
from .metering import build_usage
from .api_registry import BASE_API,HARDWARE_API,BASE_SERVICES,API_CONTRACT,service_closure
from .app_quality import APP_QUALITY_POLICY,AppReview,FireAppReview,UX_POLICY_VERSION,experience_contract
from .capabilities import CapabilityError
from .usage import UsageBudgetError
from .jobs import apply_context,mark_context_applied,require_current_context,ContextChanged
from .data_contract import EXTENSION as DATA_EXTENSION
from .generation_errors import GenerationResponseError
from .build_strategy import POLICY as DEVELOPMENT_POLICY,VERSION as DEVELOPMENT_VERSION,RepairBaseline,evidence_for,review_conflicts,retained_baseline,retained_standard_core


def sha256(data):
    return hashlib.sha256(data).hexdigest()


RELEASE_PROFILES = ("idle", "cycle", "hold_a", "hold_b", "hold_c", "rapid", "jitter")


def worker_timeout(app):
    # A ten-minute soak evaluates 37,500 complete scenes, ten times the usual
    # until-exit horizon. Keep the same callback quotas but allow host overhead.
    return 30 if app.get("profile")=="long_session" and app.get("max_runtime_ms")==0 else 8


async def validate_release(app, store, build_id):
    """Fresh isolated VM per input/timing profile; no 180-frame release gate."""
    results, visual_candidates = [], []
    captures={'idle':[16,1400,5400], 'cycle':[1400,5400],
              'start_b_idle':[16,1400], 'play_directions':[1400,5400],
              'io_error':[1400], 'long_session':[600000]}
    if app.get("experience_policy_version")==UX_POLICY_VERSION:
        app={**app,"native_host_policy":NATIVE_HOST_POLICY}
    profiles=RELEASE_PROFILES+(("io_error","io_timeout","io_disconnect") if app.get("api_version") in {HARDWARE_API,SDK_VERSION} and set(app["required_services"])-BASE_SERVICES else ())
    if app.get("experience_policy_version")==UX_POLICY_VERSION:
        profiles+=("os_long_a","os_long_b","os_long_c","os_double","start_b_idle","play_directions","long_session")
    if 'imu' in app['required_services']:
        profiles+=("imu_flat","imu_tilt","imu_vertical","imu_zero","imu_calibration","imu_recovery","imu_tolerance","imu_motion")
    for profile in profiles:
        try:
            result = await simulate({**app, "profile": profile,
                'capture_at_ms':captures.get(profile,[]) if 'display' in app['required_services'] else [],
                **({"test_horizon_ms":600000} if profile=="long_session" and app.get("max_runtime_ms")==0 else {})}, store, build_id)
        except (ValueError, asyncio.TimeoutError) as error:
            raise ValueError(f"Release profile {profile}: {str(error) or 'worker timeout'}") from error
        visual_candidates.extend({'profile':profile,**frame} for frame in result.pop('visual_frames',[]))
        results.append({"profile": profile, **{k:v for k,v in result.items() if k != "trace"}})
    for raw in app.get("test_sequences",[]):
        scenario=AppTestSequence.model_validate(raw)
        for fault in ("idle","io_error","io_timeout","io_disconnect"):
            try:
                result=await simulate({**app,"profile":fault,"button_sequence":scenario.buttons,
                    'capture_at_ms':[min(60000,16+(len(scenario.buttons)-1)*scenario.interval_ms+500)]
                        if fault in {'idle','io_error'} and 'display' in app['required_services'] else [],
                    "interval_ms":scenario.interval_ms},store,build_id)
            except (ValueError,asyncio.TimeoutError) as error:
                raise ValueError(f"Scenario {scenario.name}/{fault}: {str(error) or 'worker timeout'}") from error
            visual_candidates.extend({'profile':fault,'scenario':scenario.name,**frame} for frame in result.pop('visual_frames',[]))
            results.append({"profile":fault,"scenario":scenario.name,**{k:v for k,v in result.items() if k!="trace"}})
    calls,jobs,modes={},{},{}
    missing=set()
    for result in results:
        for key,value in result.get("io_calls",{}).items():calls[key]=calls.get(key,0)+value
        for key,value in result.get("jobs_started",{}).items():jobs[key]=jobs.get(key,0)+value
        for key,values in result.get('service_modes_used',{}).items():modes[key]=sorted(set(modes.get(key,[]))|set(values))
    if app.get("require_io_coverage"):
        asynchronous={"i2c","uart","spi","sd","mic","speaker","bluetooth","ai","data"}
        synchronous={"gpio","pwm","adc","dac","rtc","wifi","power"}
        active={k.split('.')[0] for k in calls if k.split('.')[-1] not in {"close","stop","release"}}
        active.update(k.split('.')[0] for k in jobs)
        coverage=set(app.get('coverage_services',app['required_services']))
        missing=(coverage&synchronous)-active
        missing|=(coverage&asynchronous)-{k.split('.')[0] for k in jobs}
        if 'ai' in missing:raise ValueError('I/O coverage missing for ai. Init cannot start Runtime AI; test a real update/button trigger after run binding with a responsive local fallback.')
        if missing and not app.get("defer_io_coverage"):raise ValueError("I/O coverage missing for "+", ".join(sorted(missing))+". Add/correct test_sequences that navigate menus and START these operations; keep the app features.")
    if {"display", "rgb"}.intersection(app["required_services"]) and not sum(p["api_operations"] for p in results):
        raise ValueError("Release suite: app declares display/RGB but produces no visible output in any input profile")
    resources={}
    for result in results:
        for kind,values in result.get("resources_used",{}).items():resources[kind]=sorted(set(resources.get(kind,[]))|set(values))
    from .visual_preview import save_screenshots
    visual=await asyncio.to_thread(save_screenshots,visual_candidates,store,build_id,sha256(app['main_lua'].encode('utf-8')))
    return {**results[0], "profiles": results, "resources_used":resources,"io_calls":calls,"jobs_started":jobs,'service_modes_used':modes,"suite": "release-v4", "rendering_contract": "cleared-sprite-v1", "physical_verified": False,
            'visual_evidence':visual,'io_coverage_missing':sorted(missing),
            'negotiated_contract':{'api_version':app.get('api_version',BASE_API),'api_contract':app.get('api_contract'),
                'sdk_policy_version':SDK_POLICY_VERSION if app.get('api_version')==SDK_VERSION else None,
                'limits':experience_contract({'services':app['required_services'],'max_memory':app.get('max_memory',131072),
                    'app_sdk':{'version':SDK_VERSION,'contract':SDK_CONTRACT} if app.get('api_version')==SDK_VERSION else None})['limits']},
            "native_host_policy":app.get("native_host_policy"),
            "native_numeric_parity": False}


async def simulate(app, store, build_id):
    # No secrets, inherited credentials, PYTHONPATH or current project code in child env.
    child_env = {key: value for key, value in os.environ.items()
                 if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    if getattr(sys, "frozen", False):
        return await simulate_bundled(app, store, build_id, child_env)
    worker = Path(__file__).with_name("lua_worker.py").resolve()
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(worker),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=child_env, cwd=worker.parent,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(canonical(app)), timeout=worker_timeout(app))
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if len(stdout)>262144:
        raise ValueError('Lua worker output exceeds bound')
    store.log(build_id, "stderr: " + stderr.decode("utf-8", errors="replace"))
    result = json.loads(stdout)
    store.log(build_id, "stdout: " + json.dumps({k:v for k,v in result.items() if k!='visual_frames'},ensure_ascii=True))
    if process.returncode != 0 or not result.get("ok"):
        raise ValueError(result.get("error", "Lua worker failed"))
    return result


async def simulate_bundled(app, store, build_id, child_env):
    # Windowed executables have no Python stdin/stdout. Use bounded temporary
    # files in this workspace for the isolated worker, then always remove them.
    with tempfile.TemporaryDirectory(prefix="lua-worker-", dir=store.root) as temporary:
        request = Path(temporary) / "input.json"
        response = Path(temporary) / "output.json"
        payload = canonical(app)
        if len(payload) > 220000:
            raise ValueError("Lua worker input exceeds limit")
        store.reserve(len(payload) + 262144)
        request.write_bytes(payload)
        child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        flags = {"creationflags": 0x08000000} if os.name == "nt" else {}
        process = await asyncio.create_subprocess_exec(sys.executable, "--lua-worker", str(request), str(response),
                    env=child_env, cwd=temporary, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **flags)
        try:
            await asyncio.wait_for(process.wait(), timeout=worker_timeout(app))
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if not response.exists() or response.stat().st_size > 262144:
            raise ValueError("Lua worker did not return a bounded result")
        result = json.loads(response.read_text(encoding="utf-8"))
        store.log(build_id, "Bundled Lua worker: " + json.dumps({k:v for k,v in result.items() if k!='visual_frames'}, ensure_ascii=True))
        if process.returncode != 0 or not result.get("ok"):
            raise ValueError(result.get("error", "Lua worker failed"))
        return result


def verify_archive(path, expected_manifest, archive_hash=None):
    if archive_hash and sha256(path.read_bytes()) != archive_hash:
        raise ValueError("Archive checksum mismatch")
    prefix = f"apps/{expected_manifest['id']}/"
    expected_names = {prefix + n for n in ("manifest.json", "main.lua", "assets/", "appdata/")}
    with zipfile.ZipFile(path) as archive:
        if set(archive.namelist()) != expected_names or len(archive.namelist()) != 4:
            raise ValueError("Invalid package layout")
        if archive.testzip() is not None:
            raise ValueError("Package CRC test failed")
        manifest = Manifest.model_validate_json(archive.read(prefix + "manifest.json"))
        if manifest.model_dump() != expected_manifest:
            raise ValueError("Manifest mismatch")
        if sha256(archive.read(prefix + "main.lua")) != manifest.checksum:
            raise ValueError("Payload checksum mismatch")
    return True


def write_archive(path, manifest, payload):
    prefix = f"apps/{manifest['id']}/"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, content in (("manifest.json", canonical(manifest)), ("main.lua", payload), ("assets/", b""), ("appdata/", b"")):
            info = zipfile.ZipInfo(prefix + name, date_time=(2020, 1, 1, 0, 0, 0))
            info.external_attr = (0o40755 if name.endswith("/") else 0o100644) << 16
            archive.writestr(info, content)


class Builder:
    def __init__(self, settings, store, provider, context):
        self.settings, self.store, self.provider, self.context = settings, store, provider, context

    def reusable_candidate(self,build,request,summary):
        """Reuse generated source after an interrupted review, never a package verdict.

        Scope, source checksum, full context/capabilities, original base and
        effective user requirements must match. Local tests and review run again.
        """
        old_id=build['id'] if build.get('resume_checkpoint') else build.get('retry_of')
        if not old_id:return None
        try:
            old=self.store.get('builds',old_id)
            checkpoint=build.get('resume_checkpoint') if old_id==build['id'] else old
            if old['project_id']!=build['project_id'] or checkpoint['status']!='failed':return None
            folder=self.store.path('builds',old_id,'')
            source_attempt=checkpoint.get('attempts',0)
            meta_path=folder/f"candidate-{source_attempt}.json"
            if meta_path.stat().st_size>8192:return None
            meta=json.loads(meta_path.read_text(encoding='utf-8'))
            if (not meta.get('local_validated') or meta['context_sha256']!=request['context_sha256'] or
                    meta['summary_sha256']!=sha256(summary.encode('utf-8')) or
                    meta['capabilities_sha256']!=sha256(canonical(request['capabilities'])) or
                    meta['base_package_id']!=request['base_package_id'] or meta['mode']!=request['mode']):return None
            source_path=folder/f"attempt-{source_attempt}.lua"
            if source_path.stat().st_size>100000:return None
            source=source_path.read_bytes()
            if sha256(source)!=meta['source_sha256']:return None
            plan_path=folder/f"test-plan-{source_attempt}.json"
            if plan_path.stat().st_size>24000:return None
            return GeneratedApp(name=meta['name'],main_lua=source.decode('utf-8'),required_services=meta['required_services'],
                                test_sequences=json.loads(plan_path.read_text(encoding='utf-8')))
        except (OSError,ValueError,KeyError,TypeError):return None

    @build_usage
    async def provider_call(self,build,phase,progress,call,*args):
        """Retry the SAME generation/review, without spending a Lua correction.

        SDK retries are disabled in OpenAIProvider. Honor server delay hints;
        never replay billing/auth/quota failures or log provider response bodies.
        The enclosing build timeout and cancellation remain authoritative.
        """
        waited=0
        for retry in range(5):
            try:return await call(*args)
            except (APIStatusError,APIConnectionError) as error:
                if account_limit(error):raise
                if isinstance(error,APIStatusError) and error.status_code not in {408,409,429,500,502,503,504}:raise
                if retry==4:raise
                headers=error.response.headers if isinstance(error,APIStatusError) else {}
                delay=5*2**retry
                hint=headers.get('retry-after')
                if hint:
                    try:delay=max(delay,float(hint))
                    except ValueError:
                        try:delay=max(delay,parsedate_to_datetime(hint).timestamp()-time.time())
                        except (ValueError,TypeError,OverflowError):pass
                if headers.get('retry-after-ms'):
                    try:delay=max(delay,float(headers['retry-after-ms'])/1000)
                    except ValueError:pass
                if not 0<=delay<=180 or waited+delay+1>240:raise
                delay+=random.uniform(.1,.5);waited+=delay
                build.update(provider_retry=retry+1,provider_retry_phase=phase,retry_at=time.time()+delay)
                self.store.put('builds',build['id'],build)
                self.store.log(build['id'],f'AI temporary failure: {type(error).__name__}; retry {retry+1}/4 in {delay:.1f}s')
                percent=build.get('progress',10 if phase=='generating' else 75)
                await progress('api_wait',percent,build_text('api_wait'))
                await asyncio.sleep(delay)
                build.pop('retry_at',None)
                await progress(phase,percent,build_text(phase,operation=build.get('operation','new'),attempt=build.get('generation_attempt',1),progress=percent))

    async def build(self, build, project, progress, capabilities=None, context=None):
        from .prompt_context import compact_repair_evidence,dumps
        build_id = build["id"]
        folder = self.store.path("builds", build_id, "")
        continuing=bool(build.get('resume_checkpoint'))
        folder.mkdir(exist_ok=continuing)
        # Retained inputs allow revalidation/repackaging without another paid API call.
        context = context or self.context
        if VISUAL_POLICY not in context:
            context += VISUAL_POLICY
        if APP_QUALITY_POLICY not in context:
            context += APP_QUALITY_POLICY
        if DEVELOPMENT_POLICY not in context:context+=DEVELOPMENT_POLICY
        sdk_context=selected_context(build["summary"],capabilities,include_native=False)
        if sdk_context and sdk_context not in context:context+=sdk_context
        ux_contract=experience_contract(capabilities)
        context+="\nBackend-authored FIRE experience contract:\n"+json.dumps(ux_contract,ensure_ascii=False)
        from .quality import Quality
        # Also applies to direct Builder callers, new apps and the first attempt.
        learned_policy=Quality(self.store).policy()
        if learned_policy and learned_policy not in context:context+=learned_policy
        base_manifest=self.store.get('packages',project['latest_package'])['manifest'] if project.get('latest_package') else None
        fork_previous = None
        fork_context_id = build.get('resume_context',{}).get('development_context_id')
        if not project.get('latest_package') and project.get('parent_context_grant'):
            if not fork_context_id or not hasattr(self,'fork_source'):
                raise PermissionError('Fork requires an explicit frozen parent context')
            fork_base, fork_previous = self.fork_source(project['id'],project.get('owner_device_id'),fork_context_id)
            base_manifest = fork_base['manifest']
        from .runtime_contract import GENERATION_MARKER,generation_mode,generation_context,explicitly_requested,available as runtime_available,EXTENSION as RUNTIME_EXTENSION
        runtime_mode=generation_mode(context,self.settings)
        if GENERATION_MARKER not in context:context+=generation_context(self.settings,capabilities,runtime_mode)
        wants_runtime=explicitly_requested(build['summary'])
        if runtime_mode=='off' and (wants_runtime or base_manifest and 'ai' in base_manifest['required_services']):
            raise CapabilityError('runtime_ai_disabled','AI Developer er OFF. Runtime AI-kravet er bevart; velg AUTO før du bygger AI-funksjonen.')
        if wants_runtime and (not runtime_available(capabilities) or not self.settings.fire_runtime_ai_enabled):
            raise CapabilityError('runtime_ai_unavailable','Appen krever aktivert Runtime AI og firmware som annonserer tjenesten. Kravet er bevart.')
        context=sdk_context_normalize(context,capabilities=capabilities,summary=build['summary'],base_manifest=base_manifest)
        standard=sdk_standard_contract(capabilities,build['summary'],base_manifest) if self.settings.fire_ai_mode=='openai' else None
        context=context_with_contract(context,standard)
        max_corrections=getattr(self.settings,'fire_max_corrections',0) or None
        offset=build.get('resume_from_attempt',0) if continuing else 0
        max_attempts=offset+max_corrections+1 if max_corrections is not None else None
        build.update(max_corrections=max_corrections,max_attempts=max_attempts)
        request = {
            "summary": build["summary"], "context": context, "capabilities": capabilities,
            "base_package_id": project.get("latest_package"),
            "context_sha256": sha256(context.encode("utf-8")),
            "model": self.settings.openai_code_model, "mode": self.settings.fire_ai_mode,
            "python": platform.python_version(),
            "dependencies": {n: metadata.version(n) for n in ("openai", "lupa", "pydantic")},
            "max_corrections": max_corrections,
            "experience_contract":ux_contract,"standard_contract":standard,
            "development_policy_version":DEVELOPMENT_VERSION,
        }
        if len(canonical(request)) > self.settings.fire_max_build_kb * 1024:
            raise ValueError("Per-build disk limit exceeded")
        if continuing and (folder/'request.json').is_file():
            self.store.write(folder/f"request-before-resume-{build['resume_count']}.json",json.loads((folder/'request.json').read_text(encoding='utf-8')))
        self.store.write(folder / "request.json", request)
        last_error, previous = build.get("repair_context"), None
        if last_error:
            if 'Repair evidence (untrusted diagnostic data' in context:
                last_error='Repair requested: inspect the compact repair evidence in context and preserve all agreed app features.'
            else:
                try:last_error=dumps(compact_repair_evidence(json.loads(last_error)))
                except (ValueError,TypeError):last_error=str(last_error)[:2400]
        if fork_previous is not None:
            previous = fork_previous
        elif project.get("latest_package"):
            base = self.store.get("packages", project["latest_package"])
            archive_path = self.store.path("packages", base["id"], ".zip")
            verify_archive(archive_path, base["manifest"], base["archive_sha256"])
            with zipfile.ZipFile(archive_path) as archive:
                previous = archive.read(f"apps/{base['manifest']['id']}/main.lua").decode("utf-8")
        if continuing:
            prior_source=folder/f'attempt-{offset}.lua'
            checkpoint=build['resume_checkpoint']
            malformed=any(x in (checkpoint.get('last_validation_error') or '') for x in ('LuaSyntaxError','syntax error','Unterminated Lua'))
            if offset and not malformed and prior_source.is_file() and prior_source.stat().st_size<=100000:
                previous=prior_source.read_text(encoding='utf-8')
            last_error=checkpoint.get('last_validation_error') or checkpoint.get('error') or last_error
            core=retained_standard_core(folder,build.get('repair_baseline_sha256'),offset)
            retained=retained_baseline(folder,offset)
            if retained:
                previous=retained[0]
                build['repair_baseline_sha256']=sha256(previous.encode('utf-8'))
                last_error=dumps({'primary_error':last_error,'retained_source_sha256':build['repair_baseline_sha256'],
                    'historical_review_advice_not_current_evidence':retained[1].correction(),
                    'instruction':'Continue from this locally tested source. Inspect actual code; historical reviewer claims must be checked against current backend source identity and development policy.'})
            if core and not retained:
                previous=core
                last_error=dumps({'primary_error':checkpoint.get('last_validation_error') or checkpoint.get('error'),
                    'retained_source_sha256':sha256(core.encode('utf-8')),
                    'instruction':'Retain this core-tested app and make the targeted standard correction. Rerun all tests and review; core-tested is not deliverable.'})
        with tempfile.TemporaryDirectory(prefix="tmp-", dir=folder) as temp:
            work = Path(temp)
            baseline=RepairBaseline(previous,last_error)
            seen_sources=set();seen_failures=set()
            for cycle_attempt in range(max_corrections+1) if max_corrections is not None else count():
                attempt=offset+cycle_attempt
                summary,context_revision=apply_context(self.store,build,attempt+1)
                if standard:
                    standard=sdk_standard_contract(capabilities,summary,base_manifest)
                    context=context_with_contract(context,standard)
                    self.store.write(folder/f'standard-contract-r{context_revision}.json',standard)
                    if standard['game_requested'] and not standard['audio_available'] and not standard['explicit_audio_opt_out']:
                        raise CapabilityError('game_audio_unavailable','Spillet krever lydadapter i firmware. Appønsket er bevart; ingen uannonsert tjeneste eller stille erstatning er levert.')
                build['generation_attempt']=attempt+1
                operation='repair' if build.get('repair_of') or build.get('repair_job_id') else 'update' if project.get('latest_package') else 'new'
                await progress("generating", min(25,10 + attempt * 3), build_text('generating',operation=operation,attempt=attempt+1,total=max_attempts))
                generated=self.reusable_candidate(build,request,summary) if cycle_attempt==0 else None
                if generated:
                    build['reused_candidate_from']=build['id'] if continuing else build['retry_of']
                    self.store.log(build_id,'Gjenbruker appkode fra '+build['reused_candidate_from']+'. Lokale tester og AI-kontroll kjøres på nytt.')
                else:
                    generated = await self.provider_call(build,'generating',progress,self.provider.generate,summary, context, last_error, previous)
                mark_context_applied(self.store,build_id,context_revision,attempt+1)
                # Redact before persisting, validating or packaging any model output.
                generated = type(generated).model_validate(self.store.redactor.value(generated.model_dump()))
                api_version=package_api(capabilities)
                payload = generated.main_lua.encode("utf-8")
                source_hash=sha256(payload)
                candidate_key=(source_hash,sha256(canonical([s.model_dump() for s in generated.test_sequences])))
                if max_corrections is None and candidate_key in seen_sources:
                    raise GenerationResponseError('ai_no_progress','AI gjentar samme appkode uten å rette feilen. Plan og siste kontrollfunn er bevart; velg Resume for å fortsette.')
                seen_sources.add(candidate_key)
                if len(payload) > 100000:
                    raise ValueError("Generated source exceeds limit")
                self.store.reserve(len(payload) * 3 + 32768)
                existing = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
                if existing + len(payload) * 3 + 32768 > self.settings.fire_max_build_kb * 1024:
                    raise ValueError("Per-build disk limit exceeded")
                (work / "main.lua").write_bytes(payload)
                (folder / f"attempt-{attempt + 1}.lua").write_bytes(payload)
                self.store.write(folder / f"test-plan-{attempt+1}.json",[s.model_dump() for s in generated.test_sequences])
                candidate_meta={'name':generated.name,'required_services':generated.required_services,'source_sha256':source_hash,
                    'context_sha256':request['context_sha256'],'summary_sha256':sha256(summary.encode('utf-8')),
                    'capabilities_sha256':sha256(canonical(capabilities)),'base_package_id':request['base_package_id'],
                    'mode':request['mode'],'local_validated':False}
                self.store.write(folder/f'candidate-{attempt+1}.json',candidate_meta)
                build["attempts"] = attempt + 1
                self.store.put("builds", build_id, build)
                await progress("validating", 35, build_text('validating'))
                await progress("compiling", 50, build_text('compiling'))
                await progress("testing", 65, build_text('testing'))
                local_passed=False;standard_passed=False;review=None
                try:
                    require_current_context(self.store,build,context_revision)
                    if 'ai' in generated.required_services and runtime_mode=='off':raise CapabilityError('runtime_ai_disabled','AI Developer er OFF; ingen AI-app er levert.')
                    if wants_runtime and 'ai' not in generated.required_services:raise ValueError('The confirmed request explicitly needs Runtime AI; keep the core and add bounded ai/jobs with a meaningful local fallback.')
                    generated=generated.model_copy(update={'required_services':service_closure(generated.required_services,api_version)})
                    Quality(self.store).reject_known_failure(project["id"], sha256(payload))
                    if capabilities and not set(generated.required_services) <= set(capabilities["services"]):
                        raise ValueError("Generated app requests services absent from actual device capabilities")
                    budgets = {"max_memory": capabilities["max_memory"], "max_runtime_ms": capabilities["max_runtime_ms"]} if capabilities else {}
                    api_version=package_api(capabilities)
                    coverage=set(generated.required_services)
                    if 'speaker' in coverage or 'data' in coverage:
                        from .lua_worker import without_literals
                        if not re.search(r'\bfire\s*\.\s*sd\b',without_literals(generated.main_lua)):coverage.discard('sd')
                    result = await validate_release({**generated.model_dump(), **budgets,"api_version":api_version,
                        'data_capture':(capabilities or {}).get('data_engine') or {},
                        'service_methods':(capabilities or {}).get('service_methods'),
                        'service_modes':(capabilities or {}).get('service_modes'),
                        "api_contract":SDK_CONTRACT if api_version==SDK_VERSION else API_CONTRACT if api_version==HARDWARE_API else None,
                        **({'runtime_ai':RUNTIME_EXTENSION} if 'ai' in generated.required_services else {}),
                        **({'data_engine':DATA_EXTENSION} if 'data' in generated.required_services else {}),
                        "coverage_services":sorted(coverage),
                        "hardware":(capabilities or {}).get("hardware") or {},
                        "require_io_coverage":self.settings.fire_ai_mode=="openai","defer_io_coverage":bool(standard),
                        **({"experience_policy_version":UX_POLICY_VERSION} if self.settings.fire_ai_mode=="openai" else {})}, self.store, build_id)
                    local_passed=True
                    result['source_identity']=evidence_for(self.store,project['id'],generated.main_lua)
                    profiles=result.get('profiles',[])
                    self.store.write(folder/f'validation-{attempt+1}.json',{
                        'source_sha256':source_hash,'local_checks_passed':True,'physical_verified':False,
                        'profiles_run':[{k:p[k] for k in ('profile','scenario') if k in p} for p in profiles],
                        'peak_budgets':{key:max((p.get(key,0) for p in profiles),default=result.get(key,0))
                            for key in ('max_callback_operations','max_callback_text_bytes','max_callback_display_work','max_callback_rgb_calls')}})
                    if standard:
                        result['standard_contract']=standard
                        result['standard_verification']=verify_sdk_standard(standard,generated.required_services,result,source_hash)
                        self.store.write(folder/f'standard-verification-{attempt+1}.json',result['standard_verification'])
                        require_sdk_standard(result['standard_verification'])
                    standard_passed=True
                    candidate_meta['local_validated']=True
                    self.store.write(folder/f'candidate-{attempt+1}.json',candidate_meta)
                    await progress("testing",75,build_text('testing',progress=75))
                    require_current_context(self.store,build,context_revision)
                    reviewer=getattr(self.provider,"review",None)
                    if reviewer is None:
                        if self.settings.fire_ai_mode!="mock":
                            raise ValueError("Pre-delivery review is required for live generation")
                        from .ai import MockProvider
                        reviewer=MockProvider().review
                    from .visual_preview import image_inputs
                    review_input={**result,'_visual_review_images':image_inputs(result['visual_evidence'],self.store,build_id,source_hash)}
                    review=await self.provider_call(build,'testing',progress,reviewer,summary,context,generated,review_input)
                    conflicts=review_conflicts(review,result['source_identity'],require_source=self.settings.fire_ai_mode=='openai')
                    if conflicts:
                        self.store.write(folder/f'review-{attempt+1}-evidence-conflict.json',{'review':review.model_dump(),'conflicts':conflicts})
                        result['review_correction']={'conflicts':conflicts,'instruction':'Re-evaluate THIS SAME candidate against backend source_identity. Different-source device history is not a failure of this candidate. Keep all concrete source/local-test defects; place unmeasured physical timing in verification_notes.'}
                        review=await self.provider_call(build,'testing',progress,reviewer,summary,context,generated,
                            {**review_input,'review_correction':result['review_correction']})
                        if review_conflicts(review,result['source_identity'],require_source=self.settings.fire_ai_mode=='openai'):
                            raise GenerationResponseError('ai_review_evidence','Kodekontrollen blander kildeversjoner. Den lokalt testede koden er bevart; ingen ny omskriving eller utestet levering er gjort. Velg Resume for å fortsette kodekontrollen.')
                    review_data=self.store.redactor.value(review.model_dump())
                    if self.settings.fire_ai_mode=="mock" and not isinstance(review,FireAppReview):
                        # Limited offline fixtures are explicitly identified; no live UX claim.
                        review_data.update(kind="app",**{name:True for name in FireAppReview.fire_checks()})
                    review=FireAppReview.model_validate(review_data)
                    if (self.settings.fire_ai_mode=="openai" and review.kind=="game" and not ux_contract["game_audio_available"] and not (standard and standard["explicit_audio_opt_out"])):
                        raise CapabilityError("game_audio_unavailable","Spill med lyd/melodier krever Lua speaker/jobs i firmware. AI-talesvar gir ikke spilllyd. Ingen stille erstatningspakke er levert.")
                    review_record={"source_sha256":sha256(payload),"approved":review.approved,
                        "experience_policy_version":UX_POLICY_VERSION,
                        "mode":"openai_source_review" if self.settings.fire_ai_mode=="openai" else "mock_fixture",
                        "checks":review.model_dump(),"physical_verified":False}
                    self.store.write(folder / f"review-{attempt+1}.json",review_record)
                    require_current_context(self.store,build,context_revision)
                    if not review.approved:raise ValueError(review.correction())
                    result.update(pre_delivery_review_required=True,pre_delivery_review=review_record)
                    break
                except ContextChanged as error:
                    seen_sources.discard(candidate_key)
                    previous=generated.main_lua;last_error=str(error)
                    self.store.log(build_id,last_error)
                    if cycle_attempt==max_corrections:raise ValueError('Ny kontekst venter, men rettingsgrensen er nådd. Fortsett i Aktivitet med konteksten.') from error
                except (CapabilityError,UsageBudgetError,GenerationResponseError):
                    raise  # Regenerating Lua cannot implement a missing native driver.
                except (ValueError, asyncio.TimeoutError) as error:
                    # A rejected candidate must not be reused as though only
                    # its remote review was interrupted.
                    candidate_meta['local_validated']=False
                    self.store.write(folder/f'candidate-{attempt+1}.json',candidate_meta)
                    failure=str(error) or "Lua worker timeout"
                    feedback=baseline.failure(generated.main_lua,failure,local_passed=local_passed,standard_passed=standard_passed,review=review)
                    if 'I/O coverage missing' in failure:
                        feedback['test_sequences']=[s.model_dump() for s in generated.test_sequences]
                        feedback['instruction']='Preserve working previous_code. Correct the bounded test sequences to START and exercise the missing operations; do not remove app features.'
                    previous=baseline.source
                    last_error=dumps(feedback)
                    self.store.write(folder/f'strategy-{attempt+1}.json',feedback)
                    build['repair_baseline_sha256']=feedback['repair_baseline_sha256']
                    build["last_validation_error"]=self.store.redactor.text(failure)[:2400]
                    self.store.put("builds",build_id,build)
                    Quality(self.store).record_validation(build, generated.main_lua, failure)
                    self.store.log(build_id, f"Attempt {attempt + 1} failed: {failure}")
                    fingerprint=re.sub(r'\b\d+\b','#',' '.join(failure.casefold().split()))
                    if max_corrections is None and fingerprint in seen_failures:
                        raise GenerationResponseError('ai_no_progress','AI løser ikke det samme kontrollfunnet etter retting. Ingen utestet app er levert. Plan og feil er bevart; velg Resume.') from error
                    seen_failures.add(fingerprint)
                    if cycle_attempt == max_corrections:
                        raise ValueError(f"Build failed after {max_corrections} corrections: " + failure) from error
            await progress("packaging", 85, build_text('packaging'))
            version = project.get("next_version", 1)
            manifest = Manifest(
                id=app_id_for(generated.name, project, self.store), name=generated.name, version=f"0.1.{version}",
                api_version=api_version,
                api_contract=SDK_CONTRACT if api_version==SDK_VERSION else API_CONTRACT if api_version==HARDWARE_API else None,
                required_services=generated.required_services,
                **budgets,
                permissions=[f"fire.{s}" for s in generated.required_services], checksum=sha256(payload),
                **({'runtime_ai':RUNTIME_EXTENSION} if 'ai' in generated.required_services else {}),
                **({'data_engine':DATA_EXTENSION} if 'data' in generated.required_services else {}),
            ).model_dump()
            archive_path = work / "app.zip"
            write_archive(archive_path, manifest, payload)
            if sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) > self.settings.fire_max_build_kb * 1024:
                raise ValueError("Per-build disk limit exceeded")
            verify_archive(archive_path, manifest)
            package = {
                "id": build_id, "project_id": project["id"], "build_id": build_id,
                "created_at":time.time(),
                "manifest": manifest, "archive_sha256": sha256(archive_path.read_bytes()),
                "size_bytes": archive_path.stat().st_size,
                "validation": {k: v for k, v in result.items() if k != "trace"},
                "mode": self.settings.fire_ai_mode,
            }
            self.store.write(folder / "simulation.json", result)
            (folder / "main.lua").write_bytes(payload)
            self.store.write(folder / "build-manifest.json", package)
            if sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) > self.settings.fire_max_build_kb * 1024:
                raise ValueError("Per-build disk limit exceeded")
            self.store.reserve(package["size_bytes"] + len(canonical(package)))
            destination = self.store.path("packages", build_id, ".zip")
            staged = destination.with_suffix(".zip.tmp")
            try:
                shutil.copyfile(archive_path, staged)
                os.replace(staged, destination)
            finally:
                staged.unlink(missing_ok=True)
            self.store.put("packages", build_id, package)
            Quality(self.store).validated_build(build_id,build_id)
            self.store.log(build_id, f"Package tests passed. SHA256={package['archive_sha256']}")
            return package

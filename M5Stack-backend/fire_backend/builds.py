import asyncio
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import zipfile
from importlib import metadata
from pathlib import Path

from .models import Manifest
from .storage import canonical
from .app_names import app_id_for
from .rendering import VISUAL_POLICY
from .api_registry import BASE_API,HARDWARE_API,BASE_SERVICES,API_CONTRACT
from .app_quality import APP_QUALITY_POLICY,AppReview


def sha256(data):
    return hashlib.sha256(data).hexdigest()


RELEASE_PROFILES = ("idle", "cycle", "hold_a", "hold_b", "hold_c", "rapid", "jitter")


async def validate_release(app, store, build_id):
    """Fresh isolated VM per input/timing profile; no 180-frame release gate."""
    results = []
    profiles=RELEASE_PROFILES+(("io_error","io_timeout","io_disconnect") if app.get("api_version")==HARDWARE_API and set(app["required_services"])-BASE_SERVICES else ())
    for profile in profiles:
        try:
            result = await simulate({**app, "profile": profile}, store, build_id)
        except (ValueError, asyncio.TimeoutError) as error:
            raise ValueError(f"Release profile {profile}: {str(error) or 'worker timeout'}") from error
        results.append({"profile": profile, **{k:v for k,v in result.items() if k != "trace"}})
    if {"display", "rgb"}.intersection(app["required_services"]) and not sum(p["api_operations"] for p in results):
        raise ValueError("Release suite: app declares display/RGB but produces no visible output in any input profile")
    resources={}
    for result in results:
        for kind,values in result.get("resources_used",{}).items():resources[kind]=sorted(set(resources.get(kind,[]))|set(values))
    return {**results[0], "profiles": results, "resources_used":resources,"suite": "release-v4", "rendering_contract": "cleared-sprite-v1", "physical_verified": False,
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
        stdout, stderr = await asyncio.wait_for(process.communicate(canonical(app)), timeout=8)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    store.log(build_id, "stdout: " + stdout.decode("utf-8", errors="replace"))
    store.log(build_id, "stderr: " + stderr.decode("utf-8", errors="replace"))
    result = json.loads(stdout)
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
        store.reserve(len(payload) + 40000)
        request.write_bytes(payload)
        child_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        flags = {"creationflags": 0x08000000} if os.name == "nt" else {}
        process = await asyncio.create_subprocess_exec(sys.executable, "--lua-worker", str(request), str(response),
                    env=child_env, cwd=temporary, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **flags)
        try:
            await asyncio.wait_for(process.wait(), timeout=8)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if not response.exists() or response.stat().st_size > 40000:
            raise ValueError("Lua worker did not return a bounded result")
        result = json.loads(response.read_text(encoding="utf-8"))
        store.log(build_id, "Bundled Lua worker: " + json.dumps(result, ensure_ascii=True))
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

    async def build(self, build, project, progress, capabilities=None, context=None):
        build_id = build["id"]
        folder = self.store.path("builds", build_id, "")
        folder.mkdir(exist_ok=False)
        # Retained inputs allow revalidation/repackaging without another paid API call.
        context = context or self.context
        if VISUAL_POLICY not in context:
            context += VISUAL_POLICY
        if APP_QUALITY_POLICY not in context:
            context += APP_QUALITY_POLICY
        from .quality import Quality
        # Also applies to direct Builder callers, new apps and the first attempt.
        learned_policy=Quality(self.store).policy()
        if learned_policy and learned_policy not in context:context+=learned_policy
        request = {
            "summary": build["summary"], "context": context, "capabilities": capabilities,
            "base_package_id": project.get("latest_package"),
            "context_sha256": sha256(context.encode("utf-8")),
            "model": self.settings.openai_code_model, "mode": self.settings.fire_ai_mode,
            "python": platform.python_version(),
            "dependencies": {n: metadata.version(n) for n in ("openai", "lupa", "pydantic")},
            "max_corrections": 3,
        }
        if len(canonical(request)) > self.settings.fire_max_build_kb * 1024:
            raise ValueError("Per-build disk limit exceeded")
        self.store.write(folder / "request.json", request)
        last_error, previous = build.get("repair_context"), None
        if project.get("latest_package"):
            base = self.store.get("packages", project["latest_package"])
            archive_path = self.store.path("packages", base["id"], ".zip")
            verify_archive(archive_path, base["manifest"], base["archive_sha256"])
            with zipfile.ZipFile(archive_path) as archive:
                previous = archive.read(f"apps/{base['manifest']['id']}/main.lua").decode("utf-8")
        with tempfile.TemporaryDirectory(prefix="tmp-", dir=folder) as temp:
            work = Path(temp)
            for attempt in range(4):  # initial generation plus at most THREE corrections
                await progress("generating", 10 + attempt * 3, f"Genererer Lua, forsøk {attempt + 1}")
                generated = await self.provider.generate(build["summary"], context, last_error, previous)
                # Redact before persisting, validating or packaging any model output.
                generated = type(generated).model_validate(self.store.redactor.value(generated.model_dump()))
                payload = generated.main_lua.encode("utf-8")
                if len(payload) > 100000:
                    raise ValueError("Generated source exceeds limit")
                self.store.reserve(len(payload) * 3 + 32768)
                existing = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
                if existing + len(payload) * 3 + 32768 > self.settings.fire_max_build_kb * 1024:
                    raise ValueError("Per-build disk limit exceeded")
                (work / "main.lua").write_bytes(payload)
                (folder / f"attempt-{attempt + 1}.lua").write_bytes(payload)
                build["attempts"] = attempt + 1
                self.store.put("builds", build_id, build)
                await progress("validating", 35, "Validerer syntaks og tillatte API-er")
                await progress("compiling", 50, "Kontrollerer Lua 5.4; ingen firmwarekompilering")
                await progress("testing", 65, "Tester hele kjøretiden med sju knapp-/tidsprofiler")
                try:
                    Quality(self.store).reject_known_failure(project["id"], sha256(payload))
                    if capabilities and not set(generated.required_services) <= set(capabilities["services"]):
                        raise ValueError("Generated app requests services absent from actual device capabilities")
                    budgets = {"max_memory": capabilities["max_memory"], "max_runtime_ms": capabilities["max_runtime_ms"]} if capabilities else {}
                    api_version=(capabilities or {}).get("api_version",BASE_API)
                    result = await validate_release({**generated.model_dump(), **budgets,"api_version":api_version,
                        "hardware":(capabilities or {}).get("hardware") or {}}, self.store, build_id)
                    await progress("testing",75,"Kontrollerer funksjoner, stabilitet og grafisk utforming før levering")
                    reviewer=getattr(self.provider,"review",None)
                    if reviewer is None:
                        if self.settings.fire_ai_mode!="mock":
                            raise ValueError("Pre-delivery review is required for live generation")
                        from .ai import MockProvider
                        reviewer=MockProvider().review
                    review=await reviewer(build["summary"],context,generated,result)
                    review=AppReview.model_validate(self.store.redactor.value(review.model_dump()))
                    review_record={"source_sha256":sha256(payload),"approved":review.approved,
                        "mode":"openai_source_review" if self.settings.fire_ai_mode=="openai" else "mock_fixture",
                        "checks":review.model_dump(),"physical_verified":False}
                    self.store.write(folder / f"review-{attempt+1}.json",review_record)
                    if not review.approved:raise ValueError(review.correction())
                    result.update(pre_delivery_review_required=True,pre_delivery_review=review_record)
                    break
                except (ValueError, asyncio.TimeoutError) as error:
                    last_error, previous = str(error) or "Lua worker timeout", generated.main_lua
                    Quality(self.store).record_validation(build, generated.main_lua, last_error)
                    self.store.log(build_id, f"Attempt {attempt + 1} failed: {last_error}")
                    if attempt == 3:
                        raise ValueError("Build failed after 3 corrections: " + last_error) from error
            await progress("packaging", 85, "Pakker validert app med SHA256")
            version = project.get("next_version", 1)
            manifest = Manifest(
                id=app_id_for(generated.name, project, self.store), name=generated.name, version=f"0.1.{version}",
                api_version=api_version,
                api_contract=API_CONTRACT if api_version==HARDWARE_API else None,
                required_services=generated.required_services,
                **budgets,
                permissions=[f"fire.{s}" for s in generated.required_services], checksum=sha256(payload),
            ).model_dump()
            archive_path = work / "app.zip"
            write_archive(archive_path, manifest, payload)
            if sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) > self.settings.fire_max_build_kb * 1024:
                raise ValueError("Per-build disk limit exceeded")
            verify_archive(archive_path, manifest)
            package = {
                "id": build_id, "project_id": project["id"], "build_id": build_id,
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
            self.store.log(build_id, f"Package tests passed. SHA256={package['archive_sha256']}")
            return package

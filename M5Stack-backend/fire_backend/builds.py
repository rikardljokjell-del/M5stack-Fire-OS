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


def sha256(data):
    return hashlib.sha256(data).hexdigest()


async def simulate(app, store, build_id):
    # No secrets, inherited credentials, PYTHONPATH or current project code in child env.
    child_env = {key: value for key, value in os.environ.items()
                 if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
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

    async def build(self, build, project, progress):
        build_id = build["id"]
        folder = self.store.path("builds", build_id, "")
        folder.mkdir(exist_ok=False)
        # Retained inputs allow revalidation/repackaging without another paid API call.
        self.store.write(folder / "request.json", {
            "summary": build["summary"], "context": self.context,
            "context_sha256": sha256(self.context.encode("utf-8")),
            "model": self.settings.openai_code_model, "mode": self.settings.fire_ai_mode,
            "python": platform.python_version(),
            "dependencies": {n: metadata.version(n) for n in ("openai", "lupa", "pydantic")},
            "max_corrections": 3,
        })
        last_error, previous = None, None
        with tempfile.TemporaryDirectory(prefix="tmp-", dir=folder) as temp:
            work = Path(temp)
            for attempt in range(4):  # initial generation plus at most THREE corrections
                await progress("generating", 10 + attempt * 3, f"Genererer Lua, forsøk {attempt + 1}")
                generated = await self.provider.generate(build["summary"], self.context, last_error, previous)
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
                await progress("testing", 65, "Tester 180 frames i begrenset PC-simulering")
                try:
                    result = await simulate(generated.model_dump(), self.store, build_id)
                    break
                except (ValueError, asyncio.TimeoutError) as error:
                    last_error, previous = str(error) or "Lua worker timeout", generated.main_lua
                    self.store.log(build_id, f"Attempt {attempt + 1} failed: {last_error}")
                    if attempt == 3:
                        raise ValueError("Build failed after 3 corrections: " + last_error) from error
            await progress("packaging", 85, "Pakker validert app med SHA256")
            version = project.get("next_version", 1)
            manifest = Manifest(
                id=project["id"], name=generated.name, version=f"0.1.{version}",
                required_services=generated.required_services,
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
            self.store.reserve(package["size_bytes"] + len(canonical(package)))
            destination = self.store.path("packages", build_id, ".zip")
            shutil.copyfile(archive_path, destination)
            self.store.put("packages", build_id, package)
            self.store.log(build_id, f"Package tests passed. SHA256={package['archive_sha256']}")
            return package

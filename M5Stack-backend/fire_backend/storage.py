import json
import os
import re
import shutil
import uuid
from pathlib import Path


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ValueError("Invalid identifier")
    return value


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Store:
    def __init__(self, root: Path, redactor, max_bytes: int):
        self.root = root.resolve()
        self.redactor = redactor
        self.max_bytes = max_bytes
        self.failure_reserve = min(65536, max_bytes // 8)
        for name in ("projects", "builds", "packages", "logs", "context", "templates", "sessions", "devices", "commands", "events", "audio", "quality", "feedback"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def path(self, group: str, item_id: str, suffix=".json") -> Path:
        return self.root / group / (identifier(item_id) + suffix)

    def size(self):
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())

    def reserve(self, count: int, critical=False):
        limit = self.max_bytes if critical else self.max_bytes - self.failure_reserve
        if self.size() + count > limit:
            raise ValueError("Workspace disk limit reached; archive or delete old projects")

    def write(self, path: Path, value, critical=False):
        payload = canonical(self.redactor.value(value))
        self.reserve(len(payload), critical=critical)
        temp = path.with_name(path.name + ".tmp")
        try:
            temp.write_bytes(payload)
            with temp.open("r+b") as handle:
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def put(self, group, item_id, value, critical=False):
        self.write(self.path(group, item_id), value, critical=critical)

    def get(self, group, item_id):
        return json.loads(self.path(group, item_id).read_text(encoding="utf-8"))

    def list(self, group):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((self.root / group).glob("*.json"))]

    def log(self, build_id, message, critical=False):
        line = self.redactor.text(message)[:24000] + "\n"
        self.reserve(len(line.encode("utf-8")), critical=critical)
        with self.path("logs", build_id, ".log").open("a", encoding="utf-8") as f:
            f.write(line)

    def delete_project(self, project_id):
        self.get("projects", project_id)
        # Check every recursive target before deleting any metadata. Generated
        # paths must remain in this workspace, including after symlink resolution.
        for build in self.list("builds"):
            if build["project_id"] == project_id:
                folder = self.path("builds", build["id"], "").resolve()
                if folder == self.root:
                    raise ValueError("Unsafe build directory")
                folder.relative_to(self.root)
        for build in self.list("builds"):
            if build["project_id"] == project_id:
                build_id = build["id"]
                self.path("builds", build_id).unlink(missing_ok=True)
                self.path("logs", build_id, ".log").unlink(missing_ok=True)
                folder = self.path("builds", build_id, "")
                if folder.exists():
                    shutil.rmtree(folder)
        for package in self.list("packages"):
            if package["project_id"] == project_id:
                self.path("packages", package["id"]).unlink(missing_ok=True)
                self.path("packages", package["id"], ".zip").unlink(missing_ok=True)
        self.path("projects", project_id).unlink()
        for case in self.list("quality"):
            if case.get("project_id") == project_id:
                self.path("quality", case["id"]).unlink(missing_ok=True)
        for report in self.list("feedback"):
            if report.get("project_id") == project_id:
                self.path("feedback",report["id"]).unlink(missing_ok=True)

    def recover(self):
        for project in self.list("projects"):
            if project.get("schema_version", 1) < 2:
                project.update(last_simulated_package_id=project.get("current"),
                               simulated_previous=project.get("previous"), simulated_backup=project.get("backup"),
                               current=None, previous=None, backup=None, schema_version=2)
                self.put("projects", project["id"], project, critical=True)
        for session in self.list("sessions"):
            if session.get("protocol_version") != "0.2" and session["state"] != "idle":
                session.update(state="idle", proposal_id=None, package_id=None)
                self.put("sessions", session["session_id"], session, critical=True)
        for device in self.list("devices"):
            device.update(online=False, runtime_status="unknown")
            self.put("devices", device["id"], device, critical=True)
        for build in self.list("builds"):
            if build["status"] not in {"ready", "failed"}:
                build.update(status="failed", phase="failed", error="Backend restarted during build")
                self.put("builds", build["id"], build, critical=True)
        for project in self.list("projects"):
            if project.get("candidate"):
                project["candidate"] = None
                self.put("projects", project["id"], project)
        # Temporary folders contain only generated files, never firmware source.
        for folder in (self.root / "builds").glob("*/tmp-*"):
            if folder.is_dir():
                shutil.rmtree(folder)
        for path in (self.root / "packages").glob("*.zip.tmp"):
            path.unlink(missing_ok=True)

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field, replace
from importlib.resources import files

from .ai import MockProvider, OpenAIProvider
from .builds import Builder, simulate, verify_archive
from openai import APIStatusError
from .models import State
from .devices import DeviceLifecycle
from .app_lifecycle import AppLifecycle
from .capabilities import generation_policy, policy, status as capability_status
from .security import Redactor
from .storage import Store, new_id


class Conflict(ValueError):
    pass


def bounded_history(history):
    kept, size = [], 0
    for item in reversed(history[-32:]):
        amount = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        if size + amount > 24000:
            break
        kept.append(item)
        size += amount
    return list(reversed(kept))


@dataclass
class Session:
    id: str
    device_id: str
    project_id: str
    state: State = State.listening
    proposal_id: str | None = None
    summary: str = ""
    package_id: str | None = None
    build_id: str | None = None
    history: list = field(default_factory=list)
    sockets: set = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    operation_task: asyncio.Task | None = None
    dialog_manager: object = None
    dialog_connection: object = None
    stopped: bool = False
    sequence: int = 0
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    progress: dict = field(default_factory=dict)
    protocol_version: str = "0.1"
    target: str = "pc_simulation"
    boot_id: str | None = None
    capabilities: dict | None = None
    last_seen: float = field(default_factory=time.time)
    disconnected_at: float | None = None
    activity: str = "idle"
    turn_id: str | None = None
    audio_id: str | None = None
    input_task: asyncio.Task | None = None
    speech_task: asyncio.Task | None = None
    last_error: str = ""
    app_mode: str = "new"
    base_package_id: str | None = None
    app_revision: int = 0
    install_permitted: bool = True
    audio_status: dict = field(default_factory=dict)
    recording_started_at: float | None = None


class Backend(DeviceLifecycle, AppLifecycle):
    def __init__(self, settings, provider=None):
        self.settings = settings
        self.redactor = Redactor(settings.openai_api_key.get_secret_value(), settings.fire_backend_token.get_secret_value(), *settings.device_tokens().values())
        self.store = Store(settings.fire_workspace, self.redactor, settings.fire_max_workspace_mb * 1024 * 1024)
        self.context = files("fire_backend").joinpath("data/FIRE_DEVICE_CONTEXT.md").read_text(encoding="utf-8")
        self.store.reserve(len(self.context.encode("utf-8")))
        (self.store.root / "context" / "FIRE_DEVICE_CONTEXT.md").write_text(self.context, encoding="utf-8")
        self.provider = provider or (MockProvider() if settings.fire_ai_mode == "mock" else OpenAIProvider(settings))
        self.builder = Builder(settings, self.store, self.provider, self.context)
        self.sessions = {}
        self.build_lock = asyncio.Lock()
        self.active_build_id = None
        self.active_downloads = {}
        self.store.recover()
        for command in self.store.list("commands"):
            if command["status"] in {"pending", "started", "healthy"}:
                self.finish_command(command, "unknown")
        self.maintenance_task = None

    def session(self, session_id):
        session = self.sessions.get(session_id)
        if session is None or session.stopped:
            raise KeyError("Session not found")
        return session

    def app_library(self):
        """Saved packages and correlated device receipts, never a fabricated SD scan."""
        projects = {p["id"]: p for p in self.store.list("projects")}
        devices = {d["id"]: d for d in self.store.list("devices")}
        installed = {(c["device_id"], c["package_id"]) for c in self.store.list("commands")
                     if c["kind"] == "install" and c["status"] == "completed"}
        apps = []
        for package in self.store.list("packages"):
            project = projects.get(package["project_id"], {})
            device_id = project.get("owner_device_id")
            device = devices.get(device_id, {})
            manifest = package["manifest"]
            presence = self.app_presence(device, manifest["id"])
            absent = presence.get("state") in {"deleted", "missing"}
            can_delete, block_reason = self.backend_delete_check(project) if project else (False, "Prosjektet finnes ikke.")
            apps.append({"app_id": manifest["id"], "name": manifest["name"], "version": manifest["version"],
                         "project_id": package["project_id"], "package_id": package["id"], "mode": package["mode"], "device_id": device_id,
                         "device_presence": presence.get("state", "unknown"), "can_delete_backend": can_delete,
                         "delete_block_reason": block_reason,
                         "sd_path": f"/apps/{manifest['id']}/", "installed_receipt": bool(not absent and device.get("online")
                             and device.get("installed_package_id") == package["id"] and (device_id, package["id"]) in installed),
                         "had_install_receipt": (device_id, package["id"]) in installed,
                         "current_healthy": not absent and device.get("projects", {}).get(package["project_id"], {}).get("current") == package["id"],
                         "running": bool(not absent and device.get("online") and device.get("runtime_status") == "running"
                                         and device.get("running_package_id") == package["id"]),
                         "physical_verified": False})
        return apps

    async def install_saved(self, session, package_id):
        """Explicit local UI selection reuses a tested package after reboot.

        This neither generates code nor authorizes running the app. Validate
        ownership, archive and current capabilities before changing the project.
        """
        if (session.target != "device" or not session.sockets or session.stopped or session.lock.locked()
                or session.operation_task or (session.input_task and not session.input_task.done())
                or session.activity in {"listening", "processing", "speaking"}
                or session.state in {State.building, State.testing, State.processing, State.running,
                                     State.starting, State.stopping, State.rollback_pending}):
            raise Conflict("FIRE må være tilkoblet og ledig før installasjon.")
        device = self.device_record(session)
        if device.get("active_run_id") or device.get("pending_run_id"):
            raise Conflict("Stopp forrige app før ny installasjon.")
        package = self.store.get("packages", package_id)
        project = self.store.get("projects", package["project_id"])
        if project.get("owner_device_id") != session.device_id:
            raise PermissionError("Pakken tilhører en annen enhet.")
        self.verify_package(replace(session, project_id=project["id"]), package_id)
        # Reserve before the first await so concurrent confirmations/text cannot
        # race a project switch. Existing install offers are superseded below.
        async with session.lock:
            await self.close_dialog(session)
            if session.stopped or not session.sockets:
                raise Conflict("FIRE ble frakoblet før installasjonen.")
            if hasattr(self, "audio"):
                self.audio.cancel(session)
            prior = [s for s in self.store.list("sessions") if s["project_id"] == project["id"]]
            session.history = bounded_history(max(prior, key=lambda s: s.get("last_seen", 0)).get("history", [])) if prior else []
            session.project_id, session.package_id, session.build_id = project["id"], package_id, package["build_id"]
            session.app_mode, session.base_package_id = "update", package_id
            session.install_permitted, session.app_revision = True, device.get("app_change_counter", 0)
            session.proposal_id, session.turn_id, session.last_error = None, None, ""
            session.audio_status, session.recording_started_at = {}, None
            session.summary = project.get("last_confirmed_summary", "")
            versions = device.get("projects", {}).get(project["id"], {})
            device.update(project_id=project["id"], **{key: versions.get(key) for key in ("current", "previous", "backup")})
            self.store.put("devices", device["id"], device)
            await self.activity(session, "idle")
            command = await self.offer_install(session, package)
            return {"status": "awaiting_device_install", "install_id": command["id"], "package_id": package_id}

    def snapshot(self, session):
        return {"session_id": session.id, "device_id": session.device_id,
                "project_id": session.project_id, "state": session.state,
                "proposal_id": session.proposal_id, "package_id": session.package_id,
                "build_id": session.build_id, "mode": self.settings.fire_ai_mode,
                "protocol_version": session.protocol_version, "target": session.target,
                "boot_id": session.boot_id, "capabilities": session.capabilities,
                "activity": session.activity, "turn_id": session.turn_id, "server_time": int(time.time()),
                "last_error": session.last_error,
                "app_mode": session.app_mode, "base_package_id": session.base_package_id,
                "app_revision": session.app_revision, "install_permitted": session.install_permitted,
                "audio_status": session.audio_status,
                "effective_capabilities": policy(self.settings, session.target, session.capabilities),
                "physical_verified": False}

    def persist(self, session):
        session.history = bounded_history(session.history)
        self.store.put("sessions", session.id, {**self.snapshot(session), "history": session.history[-32:],
                       "summary": session.summary, "sequence": session.sequence, "stopped": session.stopped,
                       "last_seen": session.last_seen, "disconnected_at": session.disconnected_at,
                       "progress": session.progress}, critical=session.state in {State.failed, State.idle})

    async def emit(self, session, event):
        async with session.send_lock:
            session.sequence += 1
            self.persist(session)
            message = self.redactor.value({**event, "session_id": session.id, "seq": session.sequence,
                                           "protocol_version": session.protocol_version})
            if len(json.dumps(message, ensure_ascii=False).encode("utf-8")) > 8192:
                raise ValueError("Outbound control event exceeds 8192 bytes")
            for socket in tuple(session.sockets):
                try:
                    await asyncio.wait_for(socket.send_json(message), timeout=2)
                except Exception:
                    session.sockets.discard(socket)

    async def state(self, session, state):
        session.state = state
        self.persist(session)
        await self.emit(session, {"type": "ui_event", "event": "assistant_state", "state": state})

    async def activity(self, session, activity):
        session.activity = activity
        self.persist(session)
        await self.emit(session, {"type": "ui_event", "event": "assistant_activity", "activity": activity})

    def context_for(self, session):
        context = self.context
        if session.capabilities:
            context += "\nActual device capabilities (never exceed):\n" + json.dumps(session.capabilities)
        project = self.store.get("projects", session.project_id)
        selected_base = session.base_package_id or project.get("latest_package")
        summary = self.store.get("builds", selected_base).get("summary", "") if selected_base else ""
        context += "\nProject: " + json.dumps({"id": project["id"], "name": project["name"],
            "app_mode": session.app_mode, "base_package_id": selected_base, "last_confirmed_summary": summary})
        if selected_base:
            latest = self.store.get("packages", selected_base)
            context += "\nCurrent app manifest: " + json.dumps(latest["manifest"])
        context += generation_policy(self.settings, session)
        return context

    async def report_capabilities(self, session):
        if session.target == "device":
            report = capability_status(self.settings, session)
            await self.emit(session, report)
            # Current native UI understands assistant_message, but does not yet
            # render capability_status. This is text only; never synthesize it.
            if not report["effective_capabilities"]["conversation_audio"]["input_enabled"]:
                await self.emit(session, {"type": "assistant_message", "text": report["message"], "audio": False})

    async def start(self, request, socket=None, principal="admin"):
        if request.target == "device" and principal != request.device_id:
            raise PermissionError("Physical sessions require the token scoped to this device")
        if principal != "admin" and (request.device_id != principal or request.target != "device"):
            raise PermissionError("Device credential scope mismatch")
        if request.target == "device" and (request.project_id or request.app_id):
            project = self.app_project(request.device_id, request.project_id, request.app_id)
            request = request.model_copy(update={"project_id": project["id"]})
            if request.base_package_id and not any(p["id"] == request.base_package_id for p in self.app_versions(project)):
                raise ValueError("Basisversjonen tilhører ikke den valgte appen.")
        await self.expire_sessions()
        if request.resume_session_id:
            return await self.resume(request, socket, principal)
        # Current FIRE firmware reconnects with session_start and the same boot
        # ID, without a resume hint. Reattach only an offline, matching peer;
        # never take over a live connection or reuse commands across boots.
        if request.target == "device" and request.app_mode is None:
            candidates = [s for s in self.sessions.values() if s.device_id == request.device_id
                          and s.boot_id == request.boot_id and not s.sockets and not s.stopped
                          and (not request.project_id or s.project_id == request.project_id)]
            if not candidates:
                for saved in self.store.list("sessions"):
                    if (saved.get("target") == "device" and saved["device_id"] == request.device_id
                            and saved.get("boot_id") == request.boot_id and not saved.get("stopped")
                            and (not request.project_id or saved["project_id"] == request.project_id)
                            and time.time() - (saved.get("disconnected_at") or saved.get("last_seen", 0)) <= self.settings.fire_session_resume_seconds):
                        request = request.model_copy(update={"resume_session_id": saved["session_id"]})
                        return await self.resume(request, socket, principal)
            if candidates:
                request = request.model_copy(update={"resume_session_id": candidates[0].id})
                return await self.resume(request, socket, principal)
        for existing in list(self.sessions.values()):
            if (existing.device_id == request.device_id and existing.target == "device"
                    and (existing.boot_id != request.boot_id or not existing.sockets and
                         (request.app_mode in {"new", "update"} or request.project_id and request.project_id != existing.project_id))):
                await self.stop(existing)
                for command in self.store.list("commands"):
                    if command["device_id"] == request.device_id and command["status"] in {"pending", "started", "healthy"}:
                        self.finish_command(command, "unknown")
        if len(self.sessions) >= self.settings.fire_max_sessions:
            raise Conflict("Maximum active sessions reached")
        if any(s.device_id == request.device_id for s in self.sessions.values()):
            raise Conflict("Device already has an active session")
        if request.project_id:
            project = self.store.get("projects", request.project_id)
            if project.get("owner_device_id") != (request.device_id if request.target == "device" else None):
                raise PermissionError("Project belongs to another device")
        else:
            project = self.new_project(request.device_id, request.target)
        session = Session(new_id("session"), request.device_id, project["id"])
        session.app_mode = "update" if request.project_id else "new"
        session.base_package_id = request.base_package_id or project.get("latest_package")
        if request.project_id:
            prior = [saved for saved in self.store.list("sessions") if saved["project_id"] == project["id"]]
            if prior:
                session.history = max(prior, key=lambda saved: saved.get("last_seen", 0)).get("history", [])[-32:]
        session.protocol_version, session.target, session.boot_id = request.protocol_version, request.target, request.boot_id
        session.capabilities = self.redactor.value(request.capabilities.model_dump()) if request.capabilities else None
        if session.target == "device":
            # Native FIRE interprets listening as an ACTIVE microphone capture.
            # Readiness is idle; only listen_start can transition to listening.
            session.state = State.idle
        if session.target == "device":
            try:
                device = self.store.get("devices", session.device_id)
            except FileNotFoundError:
                device = {"id": session.device_id, "current": None, "previous": None, "backup": None,
                          "installed_package_id": None, "running_package_id": None}
            if request.project_id and not request.base_package_id and project.get("latest_package"):
                session.base_package_id = self.update_base(project, device)["id"]
            if session.base_package_id:
                self.verify_package(session, session.base_package_id)
                if session.base_package_id != project.get("latest_package"):
                    session.history = []
            versions = device.setdefault("projects", {})
            if device.get("project_id") and device["project_id"] not in versions:
                versions[device["project_id"]] = {key: device.get(key) for key in ("current", "previous", "backup")}
            selected_versions = versions.get(session.project_id, {})
            device.update(project_id=session.project_id, **{key: selected_versions.get(key) for key in ("current", "previous", "backup")})
            if device.get("boot_id") != session.boot_id:
                device.update(active_run_id=None, pending_run_id=None, running_package_id=None,
                              installed_package_id=None, runtime_status="unknown")
            device.update(boot_id=session.boot_id, online=True, capabilities=session.capabilities, physical_verified=False)
            device["connection_epoch"] = device.get("connection_epoch", 0) + 1
            session.app_revision = device.get("app_change_counter", 0)
            self.store.put("devices", device["id"], device)
        if socket:
            session.sockets.add(socket)
        self.sessions[session.id] = session
        self.persist(session)
        await self.emit(session, {"type": "session_started", **self.snapshot(session)})
        await self.state(session, session.state)
        await self.report_capabilities(session)
        return session

    async def resume(self, request, socket, principal):
        session = self.sessions.get(request.resume_session_id)
        if session is None:
            saved = self.store.get("sessions", request.resume_session_id)
            if saved.get("stopped") or saved.get("protocol_version") != "0.2":
                raise Conflict("Session cannot be resumed")
            session = Session(saved["session_id"], saved["device_id"], saved["project_id"])
            for name in ("state", "proposal_id", "package_id", "build_id", "history", "summary", "protocol_version",
                         "target", "boot_id", "capabilities", "last_seen", "disconnected_at", "progress", "turn_id", "last_error",
                         "app_mode", "base_package_id", "app_revision", "install_permitted", "audio_status"):
                if name in saved:
                    setattr(session, name, saved[name])
            session.sequence = saved.get("sequence", 0)
            if session.state in {State.building, State.testing, State.processing, State.starting, State.stopping, State.rollback_pending}:
                session.state, session.proposal_id = State.failed, None
        if (session.device_id != request.device_id or session.target != request.target
                or session.boot_id != request.boot_id or session.capabilities != (self.redactor.value(request.capabilities.model_dump()) if request.capabilities else None)
                or (request.project_id and request.project_id != session.project_id)
                or (request.base_package_id and request.base_package_id != session.base_package_id)
                or session.protocol_version != request.protocol_version or session.sockets
                or time.time() - (session.disconnected_at or session.last_seen) > self.settings.fire_session_resume_seconds):
            raise Conflict("Resume identity, capabilities or expiry mismatch")
        if len(self.sessions) >= self.settings.fire_max_sessions and session.id not in self.sessions:
            raise Conflict("Maximum active sessions reached")
        if any(other.device_id == session.device_id and other.id != session.id for other in self.sessions.values()):
            raise Conflict("Device already has another active session")
        device = self.device_record(session) if session.target == "device" else None
        if device and device["boot_id"] != session.boot_id:
            raise Conflict("Resume from previous boot rejected")
        self.sessions[session.id] = session
        session.disconnected_at = None
        session.last_seen = time.time()
        if socket:
            session.sockets.add(socket)
        if session.target == "device":
            device["online"] = True
            device["connection_epoch"] = device.get("connection_epoch", 0) + 1
            self.store.put("devices", device["id"], device)
            if not session.install_permitted:
                session.state = State.failed
            elif session.package_id and session.state == State.idle:
                session.state = State.installed if device.get("installed_package_id") == session.package_id else State.awaiting_install
        self.persist(session)
        await self.emit(session, {"type": "session_started", **self.snapshot(session)})
        await self.session_snapshot(session)
        await self.report_capabilities(session)
        if session.target == "device" and session.package_id and session.install_permitted and session.state == State.awaiting_install and not self.pending_commands(session):
            await self.offer_install(session, self.verify_package(session, session.package_id))
        return session

    async def session_snapshot(self, session):
        await self.emit(session, {"type": "session_snapshot", **self.snapshot(session), "progress": session.progress,
                                  "summary": session.summary, "pending_commands": [self.command_message(c) for c in self.pending_commands(session)],
                                  "device": self.device_view(session) if session.target == "device" else None})

    async def detach(self, session, socket):
        session.sockets.discard(socket)
        if session.protocol_version == "0.1":
            await self.stop(session)
            return
        session.disconnected_at = session.last_seen = time.time()
        await self.close_dialog(session)
        if session.target == "device":
            device = self.device_record(session)
            device.update(online=False, runtime_status="unknown")
            self.store.put("devices", device["id"], device, critical=True)
        self.persist(session)

    async def expire_sessions(self):
        for session in list(self.sessions.values()):
            if session.disconnected_at and time.time() - session.disconnected_at > self.settings.fire_session_resume_seconds:
                await self.stop(session)

    async def maintenance(self):
        while True:
            await asyncio.sleep(1)
            await self.expire_sessions()
            if hasattr(self, "audio"):
                self.audio.cleanup()
                await self.audio.expire_waiting()
            for command in self.store.list("commands"):
                if command["status"] == "pending" and command["expires_at"] <= time.time():
                    self.finish_command(command, "unknown")
                    session = self.sessions.get(command["session_id"])
                    if session and not session.stopped:
                        if command["kind"] == "run":
                            device = self.device_record(session)
                            device["runtime_status"] = "unknown"
                            self.store.put("devices", device["id"], device, critical=True)
                        await self.state(session, State.failed)
                        await self.emit(session, {"type": "error", "code": "command_timeout", "message": "Device command expired; physical result unknown"})

    async def close_dialog(self, session):
        if session.dialog_manager:
            manager = session.dialog_manager
            session.dialog_manager = session.dialog_connection = None
            with contextlib.suppress(Exception):
                await asyncio.wait_for(manager.__aexit__(None, None, None), timeout=3)

    async def stop(self, session):
        # Mark before cancellation so new confirmations cannot race shutdown.
        session.stopped = True
        if session.input_task and session.input_task is not asyncio.current_task() and not session.input_task.done():
            session.input_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.input_task
        if hasattr(self, "audio"):
            self.audio.cancel(session)
        if session.speech_task and not session.speech_task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await session.speech_task
        operation = session.operation_task
        if operation and operation is not asyncio.current_task() and not operation.done():
            operation.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await operation
        if session.task and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.task
        # A task cancelled before its first instruction never enters its finally block.
        if session.build_id and self.active_build_id == session.build_id:
            build = self.store.get("builds", session.build_id)
            build.update(status="failed", phase="failed", error="Build cancelled before startup")
            self.store.put("builds", session.build_id, build, critical=True)
            self.active_build_id = None
            self.build_lock.release()
        await self.close_dialog(session)
        if session.target == "device":
            device = self.device_record(session)
            device.update(online=False, runtime_status="unknown")
            self.store.put("devices", device["id"], device, critical=True)
        session.proposal_id = None
        await self.state(session, State.idle)
        self.sessions.pop(session.id, None)

    async def close(self):
        if self.maintenance_task:
            self.maintenance_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.maintenance_task
        for session in list(self.sessions.values()):
            preserve = session.protocol_version == "0.2"
            await self.stop(session)
            if preserve:
                saved = self.store.get("sessions", session.id)
                saved.update(stopped=False, disconnected_at=time.time(), last_seen=time.time())
                self.store.put("sessions", session.id, saved, critical=True)
        await self.provider.close()

    async def text(self, session, text):
        task = asyncio.current_task()
        if session.operation_task and session.operation_task is not task:
            raise Conflict("Session is busy")
        session.operation_task = task
        try:
            return await self._text(session, text)
        finally:
            if session.operation_task is task:
                session.operation_task = None

    async def _text(self, session, text):
        if not session.install_permitted:
            raise Conflict("Appen er borte fra FIRE. Velg Ny app eller Endre app før en ny bestilling.")
        if session.stopped or session.lock.locked() or session.state in {State.building, State.testing, State.running}:
            raise Conflict("Session is busy")
        if not text or not text.strip():
            raise ValueError("Text is required")
        async with session.lock:
            session.proposal_id = None  # any new text invalidates prior authorization
            session.last_error = ""
            session.summary = ""
            session.package_id = None
            await self.state(session, State.processing)
            await self.activity(session, "processing")
            session.history.append({"role": "user", "content": self.redactor.text(text)})
            session.history = session.history[-32:]
            try:
                async with asyncio.timeout(self.settings.fire_ai_timeout_seconds):
                    if session.dialog_connection is None:
                        session.dialog_manager, session.dialog_connection = await self.provider.connect_dialog(self.context_for(session))
                    reply = await self.provider.dialog(session.history, self.context_for(session), session.dialog_connection)
                reply = type(reply).model_validate(self.redactor.value(reply.model_dump()))
                session.history.append({"role": "assistant", "content": reply.message})
                await self.emit(session, {"type": "assistant_message", "text": reply.message})
                if reply.clarification_needed or not reply.build_summary.strip():
                    await self.state(session, State.clarification_needed)
                else:
                    session.summary = reply.build_summary
                    session.proposal_id = new_id("proposal")
                    await self.state(session, State.awaiting_build_confirmation)
                    await self.emit(session, {"type": "build_proposal", "proposal_id": session.proposal_id,
                                              "summary": session.summary, "project_id": session.project_id})
                if session.turn_id:
                    session.audio_status = {**session.audio_status, "phase": "text_ready", "turn_id": session.turn_id}
                await self.activity(session, "idle")
                if self.settings.fire_audio_enabled and session.turn_id and hasattr(self, "audio"):
                    session.speech_task = asyncio.create_task(self.audio.speak(session, reply.message))
            except Exception as error:
                await self.close_dialog(session)
                await self.failure(session, error)

    async def failure(self, session, error):
        # SDK exceptions are deliberately reduced to their type, without provider bodies.
        if isinstance(error, APIStatusError):
            safe = f"OpenAI HTTP {error.status_code}: {type(error).__name__}; request_id={error.request_id}"
        else:
            safe = str(error) if isinstance(error, (ValueError, Conflict)) else type(error).__name__
        safe = self.redactor.text(safe or "Operation timed out")[:6000]
        safe = safe.encode("utf-8")[:6000].decode("utf-8", errors="ignore")
        self.store.log(session.id, "Operation failed: " + safe, critical=True)
        session.last_error = safe[:240]
        await self.activity(session, "idle")
        await self.state(session, State.failed)
        await self.emit(session, {"type": "error", "code": "operation_failed", "message": safe[:240]})
        return safe

    async def confirm_build(self, session, proposal_id):
        if (session.stopped or not session.install_permitted or session.lock.locked() or self.build_lock.locked()
                or session.state != State.awaiting_build_confirmation
                or not proposal_id or proposal_id != session.proposal_id):
            raise Conflict("No matching build proposal or builder busy")
        # Reserve synchronously before yielding. Consumed confirmations cannot be replayed.
        await self.build_lock.acquire()
        build_id = new_id("build")
        build = {"id": build_id, "project_id": session.project_id, "session_id": session.id,
                 "status": "building", "phase": "preparing", "progress": 0,
                 "summary": session.summary, "confirmed_proposal_id": proposal_id, "attempts": 0}
        if session.target == "device":
            session.app_revision = self.device_record(session).get("app_change_counter", 0)
        try:
            if hasattr(self, "audio"):
                self.audio.cancel(session)
            self.store.put("builds", build_id, build)
            session.build_id = build_id
            session.proposal_id = None
            session.state = State.building
            self.persist(session)
            self.active_build_id = build_id
            session.task = asyncio.create_task(self.build_job(session, build))
        except BaseException:
            self.build_lock.release()
            raise
        return build

    async def build_job(self, session, build):
        async def progress(phase, percent, message):
            session.progress = {"type": "build_progress", "build_id": build["id"], "phase": phase,
                                "progress": percent, "message": message, "eta_seconds": None}
            build.update(phase=phase, progress=percent)
            self.store.put("builds", build["id"], build, critical=phase == "failed")
            if phase == "testing":
                await self.state(session, State.testing)
            elif phase in {"generating", "validating", "compiling", "packaging"}:
                if session.state != State.building:
                    await self.state(session, State.building)
            await self.emit(session, session.progress)

        async def heartbeat():
            while True:
                await asyncio.sleep(self.settings.fire_progress_interval_seconds)
                if session.progress:
                    await self.emit(session, session.progress)

        pulse = asyncio.create_task(heartbeat())
        build_completed = False
        project_before = None
        try:
            await self.state(session, State.building)
            await progress("preparing", 1, "Oppretter isolert arbeidsmappe")
            async with asyncio.timeout(self.settings.fire_build_timeout_seconds):
                project = self.store.get("projects", session.project_id)
                project_before = dict(project)
                build_project = {**project, "latest_package": session.base_package_id or project.get("latest_package")}
                package = await self.builder.build(build, build_project, progress, capabilities=session.capabilities,
                                                   context=self.context_for(session))
            project.update(name=package["manifest"]["name"], app_id=package["manifest"]["id"], latest_package=package["id"],
                           next_version=project["next_version"] + 1, last_confirmed_summary=build["summary"])
            self.store.put("projects", project["id"], project)
            session.package_id = package["id"]
            session.base_package_id = package["id"]
            build.update(status="ready", package_id=package["id"])
            await progress("ready", 100, "Pakken er testet. Sender til FIRE for installasjon." if session.target == "device"
                           else "Pakken er testet. Venter på eksplisitt kjørebekreftelse.")
            await self.state(session, State.ready_to_run)
            build_completed = True
            await self.emit(session, {"type": "package_ready", "package_id": package["id"],
                                      "manifest": package["manifest"], "archive_sha256": package["archive_sha256"],
                                      "project_id": session.project_id, "size_bytes": package["size_bytes"],
                                      "download_url": f"/packages/{package['id']}/download"})
            if session.target == "device":
                await self.offer_install(session, package)
        except BaseException as error:
            if not isinstance(error, (Exception, asyncio.CancelledError)):
                raise
            message = "Build cancelled" if isinstance(error, asyncio.CancelledError) else await self.failure(session, error)
            if build_completed:
                # A delivery/connection failure cannot revoke an already tested,
                # published immutable package or pretend its compilation failed.
                build["delivery_error"] = message
                self.store.put("builds", build["id"], build, critical=True)
                self.store.log(build["id"], "Delivery failed: " + message, critical=True)
                return
            # Never leave a usable package record when any final build step failed.
            self.store.path("packages", build["id"]).unlink(missing_ok=True)
            self.store.path("packages", build["id"], ".zip").unlink(missing_ok=True)
            if project_before:
                current_project = self.store.get("projects", session.project_id)
                if current_project.get("latest_package") == build["id"]:
                    self.store.put("projects", session.project_id, project_before, critical=True)
            session.package_id = None
            build.update(status="failed", error=message)
            self.store.log(build["id"], message, critical=True)
            await progress("failed", 0, message[:240])
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse
            if self.active_build_id == build["id"]:
                self.active_build_id = None
                self.build_lock.release()

    async def confirm_run(self, session, package_id):
        task = asyncio.current_task()
        if session.operation_task and session.operation_task is not task:
            raise Conflict("Session is busy")
        session.operation_task = task
        try:
            return await self._confirm_run(session, package_id)
        finally:
            if session.operation_task is task:
                session.operation_task = None

    async def _confirm_run(self, session, package_id):
        if session.target == "device":
            if session.stopped or session.lock.locked():
                raise Conflict("Session is busy")
            return await self.device_run(session, package_id)
        if (session.stopped or session.lock.locked() or session.state != State.ready_to_run
                or not package_id or package_id != session.package_id):
            raise Conflict("No matching tested package awaiting run confirmation")
        async with session.lock:
            package = self.store.get("packages", package_id)
            if package["project_id"] != session.project_id:
                raise Conflict("Package belongs to another project")
            if self.store.get("builds", package_id)["status"] != "ready":
                raise Conflict("Build has not passed")
            try:
                path = self.store.path("packages", package_id, ".zip")
                verify_archive(path, package["manifest"], package["archive_sha256"])
                import zipfile
                with zipfile.ZipFile(path) as archive:
                    source = archive.read(f"apps/{package['manifest']['id']}/main.lua").decode("utf-8")
                await self.state(session, State.running)
                result = await simulate({"main_lua": source, **package["manifest"]}, self.store, package_id)
                project = self.store.get("projects", session.project_id)
                if project.get("last_simulated_package_id") != package_id:
                    project.update(simulated_backup=project.get("simulated_previous"),
                                   simulated_previous=project.get("last_simulated_package_id"), last_simulated_package_id=package_id)
                    self.store.put("projects", project["id"], project)
                await self.emit(session, {"type": "run_result", "package_id": package_id,
                                          "target": "pc_simulation", "status": "completed",
                                          "frames": result["frames"], "api_operations": result["api_operations"]})
                await self.state(session, State.ready_to_run)
                return {"status": "completed", "target": "pc_simulation", "package_id": package_id}
            except Exception as error:
                await self.failure(session, error)
                raise Conflict("Package run failed; previous current retained") from None

    async def device_failed(self, session, package_id):
        raise Conflict("Physical failures require protocol 0.2 and a correlated run_id receipt")

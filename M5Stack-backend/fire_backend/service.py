import asyncio
import contextlib
from dataclasses import dataclass, field
from importlib.resources import files

from .ai import MockProvider, OpenAIProvider
from .builds import Builder, simulate, verify_archive
from openai import APIStatusError
from .models import State
from .security import Redactor
from .storage import Store, new_id


class Conflict(ValueError):
    pass


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


class Backend:
    def __init__(self, settings, provider=None):
        self.settings = settings
        self.redactor = Redactor(settings.openai_api_key.get_secret_value(), settings.fire_backend_token.get_secret_value())
        self.store = Store(settings.fire_workspace, self.redactor, settings.fire_max_workspace_mb * 1024 * 1024)
        self.context = files("fire_backend").joinpath("data/FIRE_DEVICE_CONTEXT.md").read_text(encoding="utf-8")
        self.store.reserve(len(self.context.encode("utf-8")))
        (self.store.root / "context" / "FIRE_DEVICE_CONTEXT.md").write_text(self.context, encoding="utf-8")
        self.provider = provider or (MockProvider() if settings.fire_ai_mode == "mock" else OpenAIProvider(settings))
        self.builder = Builder(settings, self.store, self.provider, self.context)
        self.sessions = {}
        self.build_lock = asyncio.Lock()
        self.active_build_id = None
        self.store.recover()

    def session(self, session_id):
        session = self.sessions.get(session_id)
        if session is None or session.stopped:
            raise KeyError("Session not found")
        return session

    def snapshot(self, session):
        return {"session_id": session.id, "device_id": session.device_id,
                "project_id": session.project_id, "state": session.state,
                "proposal_id": session.proposal_id, "package_id": session.package_id,
                "build_id": session.build_id, "mode": self.settings.fire_ai_mode}

    def persist(self, session):
        self.store.put("sessions", session.id, self.snapshot(session), critical=session.state in {State.failed, State.idle})

    async def emit(self, session, event):
        async with session.send_lock:
            session.sequence += 1
            message = self.redactor.value({**event, "session_id": session.id, "seq": session.sequence})
            for socket in tuple(session.sockets):
                try:
                    await asyncio.wait_for(socket.send_json(message), timeout=2)
                except Exception:
                    session.sockets.discard(socket)

    async def state(self, session, state):
        session.state = state
        self.persist(session)
        await self.emit(session, {"type": "ui_event", "event": "assistant_state", "state": state})

    async def start(self, request, socket=None):
        if len(self.sessions) >= self.settings.fire_max_sessions:
            raise Conflict("Maximum active sessions reached")
        if any(s.device_id == request.device_id for s in self.sessions.values()):
            raise Conflict("Device already has an active session")
        if request.project_id:
            project = self.store.get("projects", request.project_id)
        else:
            project = {"id": new_id("app"), "name": "Ny app", "current": None,
                       "previous": None, "backup": None, "candidate": None,
                       "latest_package": None, "next_version": 1}
            self.store.put("projects", project["id"], project)
        session = Session(new_id("session"), request.device_id, project["id"])
        if socket:
            session.sockets.add(socket)
        self.sessions[session.id] = session
        self.persist(session)
        await self.emit(session, {"type": "session_started", **self.snapshot(session)})
        await self.state(session, State.listening)
        return session

    async def close_dialog(self, session):
        if session.dialog_manager:
            manager = session.dialog_manager
            session.dialog_manager = session.dialog_connection = None
            with contextlib.suppress(Exception):
                await asyncio.wait_for(manager.__aexit__(None, None, None), timeout=3)

    async def stop(self, session):
        # Mark before cancellation so new confirmations cannot race shutdown.
        session.stopped = True
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
        session.proposal_id = None
        await self.state(session, State.idle)
        self.sessions.pop(session.id, None)

    async def close(self):
        for session in list(self.sessions.values()):
            await self.stop(session)
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
        if session.stopped or session.lock.locked() or session.state in {State.building, State.testing, State.running}:
            raise Conflict("Session is busy")
        if not text or not text.strip():
            raise ValueError("Text is required")
        async with session.lock:
            session.proposal_id = None  # any new text invalidates prior authorization
            session.summary = ""
            session.package_id = None
            await self.state(session, State.processing)
            session.history.append({"role": "user", "content": self.redactor.text(text)})
            session.history = session.history[-32:]
            try:
                async with asyncio.timeout(self.settings.fire_ai_timeout_seconds):
                    if session.dialog_connection is None:
                        session.dialog_manager, session.dialog_connection = await self.provider.connect_dialog(self.context)
                    reply = await self.provider.dialog(session.history, self.context, session.dialog_connection)
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
        self.store.log(session.id, "Operation failed: " + safe, critical=True)
        await self.state(session, State.failed)
        await self.emit(session, {"type": "error", "code": "operation_failed", "message": safe[:240]})
        return safe

    async def confirm_build(self, session, proposal_id):
        if (session.stopped or session.lock.locked() or self.build_lock.locked()
                or session.state != State.awaiting_build_confirmation
                or not proposal_id or proposal_id != session.proposal_id):
            raise Conflict("No matching build proposal or builder busy")
        # Reserve synchronously before yielding. Consumed confirmations cannot be replayed.
        await self.build_lock.acquire()
        build_id = new_id("build")
        build = {"id": build_id, "project_id": session.project_id, "session_id": session.id,
                 "status": "building", "phase": "preparing", "progress": 0,
                 "summary": session.summary, "confirmed_proposal_id": proposal_id, "attempts": 0}
        try:
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
        try:
            await self.state(session, State.building)
            await progress("preparing", 1, "Oppretter isolert arbeidsmappe")
            async with asyncio.timeout(self.settings.fire_build_timeout_seconds):
                project = self.store.get("projects", session.project_id)
                package = await self.builder.build(build, project, progress)
            project.update(name=package["manifest"]["name"], latest_package=package["id"],
                           next_version=project["next_version"] + 1)
            self.store.put("projects", project["id"], project)
            session.package_id = package["id"]
            build.update(status="ready", package_id=package["id"])
            await progress("ready", 100, "Pakken er testet. Venter på eksplisitt kjørebekreftelse.")
            await self.state(session, State.ready_to_run)
            await self.emit(session, {"type": "package_ready", "package_id": package["id"],
                                      "manifest": package["manifest"], "archive_sha256": package["archive_sha256"],
                                      "download_url": f"/packages/{package['id']}/download"})
        except BaseException as error:
            if not isinstance(error, (Exception, asyncio.CancelledError)):
                raise
            message = "Build cancelled" if isinstance(error, asyncio.CancelledError) else await self.failure(session, error)
            # Never leave a usable package record when any final build step failed.
            self.store.path("packages", build["id"]).unlink(missing_ok=True)
            self.store.path("packages", build["id"], ".zip").unlink(missing_ok=True)
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
                    source = archive.read(f"apps/{session.project_id}/main.lua").decode("utf-8")
                await self.state(session, State.running)
                result = await simulate({"main_lua": source, **package["manifest"]}, self.store, package_id)
                project = self.store.get("projects", session.project_id)
                if project["current"] != package_id:
                    project.update(backup=project["previous"], previous=project["current"], current=package_id)
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
        if session.lock.locked() or session.state in {State.building, State.testing, State.running}:
            raise Conflict("Session is busy")
        if not package_id:
            raise Conflict("A failed package_id is required")
        project = self.store.get("projects", session.project_id)
        if project["current"] != package_id:
            raise Conflict("Failure does not match the current app")
        project.update(current=project["previous"], previous=project["backup"], backup=None)
        self.store.put("projects", project["id"], project)
        session.package_id = None
        await self.state(session, State.failed)
        await self.emit(session, {"type": "rollback", "stopped_package_id": package_id, "current": project["current"],
                                  "message": "Forrige pakke er beholdt; ingen app startes automatisk."})

import asyncio
import contextlib
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import ValidationError

from .audio import AudioManager
from .auth import authorize_project, authorize_session, principal
from .config import Settings
from .models import BuildConfirm, DeviceEvent, RunConfirm, SessionAction, SessionStart
from .protocol import begin_event, dispatch, finish_event
from .security import SecretFilter
from .service import Backend, Conflict


def create_app(settings=None, provider=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        service = Backend(settings, provider)
        service.audio = AudioManager(service)
        service.maintenance_task = asyncio.create_task(service.maintenance())
        app.state.backend = service
        filters = []
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
            for handler in logging.getLogger(name).handlers:
                filter_ = SecretFilter(service.redactor)
                handler.addFilter(filter_)
                filters.append((handler, filter_))
        for name in ("openai", "httpx", "httpcore", "websockets"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        try:
            yield
        finally:
            await service.close()
            for handler, filter_ in filters:
                handler.removeFilter(filter_)

    app = FastAPI(title="FIRE OS AI Developer", version="0.2.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def backend(request: Request):
        return request.app.state.backend

    async def auth(request: Request):
        try:
            return principal(settings, request.headers.get("authorization"))
        except PermissionError:
            raise HTTPException(401, "Authentication required") from None

    @app.exception_handler(Conflict)
    async def conflict_handler(request, error):
        return PlainTextResponse(request.app.state.backend.redactor.text(str(error)), status_code=409)

    @app.exception_handler(KeyError)
    @app.exception_handler(FileNotFoundError)
    async def missing_handler(request, error):
        return PlainTextResponse("Not found", status_code=404)

    @app.exception_handler(PermissionError)
    async def permission_handler(request, error):
        return PlainTextResponse("Credential scope does not allow this action", status_code=403)

    @app.exception_handler(ValueError)
    async def value_handler(request, error):
        return PlainTextResponse(request.app.state.backend.redactor.text(str(error))[:1000], status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return PlainTextResponse("Invalid request schema", status_code=422)

    @app.middleware("http")
    async def request_limits(request, call_next):
        audio_upload = request.method == "POST" and re.fullmatch(r"/sessions/[a-z0-9_-]{1,64}/audio/[a-z0-9_-]{1,64}", request.url.path)
        if audio_upload:
            # Authenticate BEFORE reading a large/chunked body. Only this exact
            # route bypasses the ordinary 8 KiB control-message limit.
            try:
                principal(settings, request.headers.get("authorization"))
            except PermissionError:
                return PlainTextResponse("Authentication required", status_code=401)
            if request.headers.get("content-type", "").split(";")[0].strip().lower() != "audio/wav":
                return PlainTextResponse("Expected Content-Type audio/wav", status_code=415)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return PlainTextResponse("Invalid Content-Length", status_code=400)
            if length < 0 or length > settings.fire_audio_max_input_bytes:
                return PlainTextResponse("Audio too large", status_code=413)
        elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            size, chunks = 0, []
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 8192:
                            return PlainTextResponse("Request too large", status_code=413)
                        chunks.append(chunk)
            except asyncio.TimeoutError:
                return PlainTextResponse("Request timed out", status_code=408)
            request._body = b"".join(chunks)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "0.2.0", "protocol_versions": ["0.1", "0.2"],
                "mode": settings.fire_ai_mode, "openai_configured": bool(settings.openai_api_key.get_secret_value()),
                "device_integration": "backend_contract_ready_unverified_on_hardware", "audio_enabled": settings.fire_audio_enabled}

    @app.get("/device/context")
    async def context(identity=Depends(auth), service: Backend = Depends(backend)):
        return {"api_version": "fire-lua-0.1", "context": service.context, "source_verified": True,
                "firmware_runtime_verified": False}

    @app.post("/session/start")
    async def start(body: SessionStart, identity=Depends(auth), service: Backend = Depends(backend)):
        return service.snapshot(await service.start(body, principal=identity))

    @app.get("/sessions/{session_id}")
    async def session_status(session_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        session = authorize_session(service, session_id, identity)
        return {**service.snapshot(session), "progress": session.progress,
                "device": service.device_record(session) if session.target == "device" else None}

    @app.post("/session/stop")
    async def stop(body: SessionAction, identity=Depends(auth), service: Backend = Depends(backend)):
        await service.stop(authorize_session(service, body.session_id, identity))
        return {"status": "stopped"}

    async def confirmed(body, name, identity, service):
        session = authorize_session(service, body.session_id, identity)
        if body.event_id:
            values = body.model_dump(exclude={"session_id", "event_id"})
            event = DeviceEvent(event=name, device_id=session.device_id, protocol_version=session.protocol_version,
                                event_id=body.event_id, session_id=session.id, boot_id=session.boot_id, **values)
            return await dispatch(service, session, event)
        if session.protocol_version == "0.2":
            raise ValueError("Protocol 0.2 confirmations require event_id")
        if name == "build_confirm":
            return await service.confirm_build(session, body.proposal_id)
        return await service.confirm_run(session, body.package_id)

    @app.post("/build/confirm", status_code=202)
    async def confirm_build(body: BuildConfirm, identity=Depends(auth), service: Backend = Depends(backend)):
        return await confirmed(body, "build_confirm", identity, service)

    @app.post("/run/confirm")
    async def confirm_run(body: RunConfirm, identity=Depends(auth), service: Backend = Depends(backend)):
        return await confirmed(body, "run_confirm", identity, service)

    @app.post("/device/events")
    async def receipt(body: DeviceEvent, identity=Depends(auth), service: Backend = Depends(backend)):
        if body.event == "session_start" or not body.session_id:
            raise ValueError("Use WebSocket/session start first")
        return await dispatch(service, authorize_session(service, body.session_id, identity), body)

    @app.get("/devices/{device_id}")
    async def device_status(device_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        if identity != "admin" and identity != device_id:
            raise PermissionError("Device mismatch")
        return service.store.get("devices", device_id)

    @app.post("/sessions/{session_id}/audio/{turn_id}", status_code=202)
    async def audio_input(session_id: str, turn_id: str, request: Request, identity=Depends(auth), service: Backend = Depends(backend)):
        session = authorize_session(service, session_id, identity)
        try:
            return await service.audio.receive(session, turn_id, request.stream())
        except asyncio.TimeoutError:
            raise HTTPException(408, "Audio upload timed out") from None
        except ValueError as error:
            raise HTTPException(413 if "size limit" in str(error) else 400, service.redactor.text(str(error))) from None

    @app.get("/audio/{audio_id}")
    async def audio_output(audio_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        item, path = service.audio.clip(audio_id, identity)
        return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": "private, no-store", "X-Audio-Format": "pcm_s16le", "X-Audio-Sample-Rate": "24000"})

    @app.get("/projects")
    async def projects(identity=Depends(auth), service: Backend = Depends(backend)):
        return [p for p in service.store.list("projects") if identity == "admin" or p.get("owner_device_id") == identity]

    @app.get("/projects/{item_id}")
    async def project(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        return authorize_project(service.store, item_id, identity)

    @app.delete("/projects/{item_id}")
    async def delete(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        authorize_project(service.store, item_id, identity)
        if any(s.project_id == item_id for s in service.sessions.values()):
            raise Conflict("Stop project sessions before deleting")
        package_ids = {p["id"] for p in service.store.list("packages") if p["project_id"] == item_id}
        for device in service.store.list("devices"):
            if any(device.get("projects", {}).get(item_id, {}).values()):
                raise Conflict("Project has retained device versions; cannot delete")
            if any(device.get(k) in package_ids for k in ("current", "previous", "backup", "installed_package_id", "running_package_id")):
                raise Conflict("Project has retained device versions; cannot delete")
        service.store.delete_project(item_id)
        return {"status": "deleted"}

    def scoped_build(service, item_id, identity):
        build = service.store.get("builds", item_id)
        authorize_project(service.store, build["project_id"], identity)
        return build

    @app.get("/builds/{item_id}")
    async def build(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        return scoped_build(service, item_id, identity)

    @app.get("/builds/{item_id}/log", response_class=PlainTextResponse)
    async def log(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        scoped_build(service, item_id, identity)
        return service.store.path("logs", item_id, ".log").read_text(encoding="utf-8")

    def scoped_package(service, item_id, identity):
        package = service.store.get("packages", item_id)
        authorize_project(service.store, package["project_id"], identity)
        return package

    @app.get("/packages/{item_id}")
    async def package(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        return scoped_package(service, item_id, identity)

    @app.get("/packages/{item_id}/download")
    async def download(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        package = scoped_package(service, item_id, identity)
        if service.store.get("builds", package["build_id"])["status"] != "ready":
            raise Conflict("Package build has not passed")
        from .builds import verify_archive
        path = service.store.path("packages", item_id, ".zip")
        verify_archive(path, package["manifest"], package["archive_sha256"])
        return FileResponse(path, media_type="application/zip", filename=f"{item_id}.zip", headers={"Cache-Control": "private, no-cache"})

    @app.websocket("/ws/device")
    async def device(socket: WebSocket):
        try:
            identity = principal(settings, socket.headers.get("authorization"))
            if socket.headers.get("origin"):
                raise PermissionError("Browser Origin is not supported")
        except PermissionError:
            await socket.close(code=1008)
            return
        await socket.accept()
        service, session = socket.app.state.backend, None
        try:
            while True:
                packet = await socket.receive()
                if packet["type"] == "websocket.disconnect":
                    break
                raw = packet.get("text")
                if raw is None:
                    await socket.close(code=1003)
                    break
                if len(raw.encode("utf-8")) > 8192:
                    await socket.close(code=1009)
                    break
                try:
                    event = DeviceEvent.model_validate_json(raw)
                    if event.event == "session_start":
                        if identity != "admin" and event.device_id != identity:
                            raise PermissionError("Device identity mismatch")
                        record, duplicate = begin_event(service, event)
                        if duplicate:
                            await (service.emit(session, duplicate) if session else socket.send_json(duplicate))
                            continue
                        if session:
                            raise Conflict("Session already started")
                        try:
                            request = SessionStart(**{k: getattr(event, k) for k in SessionStart.model_fields})
                            session = await service.start(request, socket, identity)
                        except (ValueError, KeyError, PermissionError, FileNotFoundError) as error:
                            finish_event(service, record, {"error": type(error).__name__})
                            raise
                        ack = finish_event(service, record, service.snapshot(session))
                        if ack:
                            await service.emit(session, ack)
                    else:
                        if session is None:
                            raise Conflict("Start a session first")
                        await dispatch(service, session, event)
                        if session.stopped:
                            session = None
                except ValidationError:
                    error_event = {"type": "error", "code": "invalid_event", "message": "Invalid event schema"}
                    await (service.emit(session, error_event) if session else socket.send_json(error_event))
                except (ValueError, KeyError, PermissionError, FileNotFoundError) as error:
                    message = "Referenced item not found" if isinstance(error, FileNotFoundError) else service.redactor.text(str(error))[:240]
                    error_event = {"type": "error", "code": "event_rejected", "message": message}
                    await (service.emit(session, error_event) if session else socket.send_json(error_event))
        except WebSocketDisconnect:
            pass
        finally:
            if session and not session.stopped:
                await service.detach(session, socket)

    return app

import asyncio
import contextlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from .config import Settings
from .models import BuildConfirm, DeviceEvent, RunConfirm, SessionAction, SessionStart, State
from .security import SecretFilter
from .service import Backend, Conflict


def create_app(settings=None, provider=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        backend = Backend(settings, provider)
        app.state.backend = backend
        filters = []
        for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
            for handler in logging.getLogger(name).handlers:
                filter_ = SecretFilter(backend.redactor)
                handler.addFilter(filter_)
                filters.append((handler, filter_))
        # SDK HTTP logging can include provider response details when debug is set externally.
        for name in ("openai", "httpx", "httpcore", "websockets"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        try:
            yield
        finally:
            await backend.close()
            for handler, filter_ in filters:
                handler.removeFilter(filter_)

    app = FastAPI(title="FIRE OS AI Developer", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def backend(request: Request):
        return request.app.state.backend

    def authorized(authorization):
        expected = settings.fire_backend_token.get_secret_value()
        return not expected or hmac.compare_digest(authorization or "", "Bearer " + expected)

    async def auth(request: Request):
        if not authorized(request.headers.get("authorization")):
            raise HTTPException(401, "Authentication required")

    @app.exception_handler(Conflict)
    async def conflict_handler(request, error):
        return PlainTextResponse(request.app.state.backend.redactor.text(str(error)), status_code=409)

    @app.exception_handler(KeyError)
    @app.exception_handler(FileNotFoundError)
    async def missing_handler(request, error):
        return PlainTextResponse("Not found", status_code=404)

    @app.exception_handler(ValueError)
    async def value_handler(request, error):
        return PlainTextResponse(request.app.state.backend.redactor.text(str(error))[:1000], status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        # Default validation responses echo input, which may contain a pasted secret.
        return PlainTextResponse("Invalid request schema", status_code=422)

    @app.middleware("http")
    async def request_limits(request, call_next):
        # Restrict request bodies before JSON decoding (including chunked requests).
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 8192:
                    return PlainTextResponse("Request too large", status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        return await call_next(request)

    protected = [Depends(auth)]

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": settings.fire_ai_mode,
                "openai_configured": bool(settings.openai_api_key.get_secret_value()),
                "device_integration": False, "audio_enabled": False}

    @app.get("/device/context", dependencies=protected)
    async def context(service: Backend = Depends(backend)):
        return {"api_version": "fire-lua-0.1", "context": service.context, "source_verified": False}

    @app.post("/session/start", dependencies=protected)
    async def start(body: SessionStart, service: Backend = Depends(backend)):
        return service.snapshot(await service.start(body))

    @app.post("/session/stop", dependencies=protected)
    async def stop(body: SessionAction, service: Backend = Depends(backend)):
        await service.stop(service.session(body.session_id))
        return {"status": "stopped"}

    @app.post("/build/confirm", dependencies=protected, status_code=202)
    async def confirm_build(body: BuildConfirm, service: Backend = Depends(backend)):
        return await service.confirm_build(service.session(body.session_id), body.proposal_id)

    @app.post("/run/confirm", dependencies=protected)
    async def confirm_run(body: RunConfirm, service: Backend = Depends(backend)):
        return await service.confirm_run(service.session(body.session_id), body.package_id)

    @app.get("/projects", dependencies=protected)
    async def projects(service: Backend = Depends(backend)):
        return service.store.list("projects")

    @app.get("/projects/{item_id}", dependencies=protected)
    async def project(item_id: str, service: Backend = Depends(backend)):
        return service.store.get("projects", item_id)

    @app.delete("/projects/{item_id}", dependencies=protected)
    async def delete(item_id: str, service: Backend = Depends(backend)):
        if any(s.project_id == item_id for s in service.sessions.values()):
            raise Conflict("Stop project sessions before deleting")
        service.store.delete_project(item_id)
        return {"status": "deleted"}

    @app.get("/builds/{item_id}", dependencies=protected)
    async def build(item_id: str, service: Backend = Depends(backend)):
        return service.store.get("builds", item_id)

    @app.get("/builds/{item_id}/log", dependencies=protected, response_class=PlainTextResponse)
    async def log(item_id: str, service: Backend = Depends(backend)):
        return service.store.path("logs", item_id, ".log").read_text(encoding="utf-8")

    @app.get("/packages/{item_id}", dependencies=protected)
    async def package(item_id: str, service: Backend = Depends(backend)):
        return service.store.get("packages", item_id)

    @app.get("/packages/{item_id}/download", dependencies=protected)
    async def download(item_id: str, service: Backend = Depends(backend)):
        package = service.store.get("packages", item_id)
        if service.store.get("builds", package["build_id"])["status"] != "ready":
            raise Conflict("Package build has not passed")
        from .builds import verify_archive
        path = service.store.path("packages", item_id, ".zip")
        verify_archive(path, package["manifest"], package["archive_sha256"])
        return FileResponse(path, media_type="application/zip", filename=f"{item_id}.zip")

    @app.websocket("/ws/device")
    async def device(socket: WebSocket):
        if not authorized(socket.headers.get("authorization")) or socket.headers.get("origin"):
            await socket.close(code=1008)
            return
        await socket.accept()
        service = socket.app.state.backend
        session = None
        work = None

        async def send_error(code, message):
            event = {"type": "error", "code": code, "message": service.redactor.text(message)[:240]}
            if session:
                await service.emit(session, event)
            else:
                await socket.send_json(event)

        try:
            while True:
                raw = await socket.receive_text()
                if len(raw.encode("utf-8")) > 8192:
                    await socket.close(code=1009)
                    break
                try:
                    event = DeviceEvent.model_validate_json(raw)
                    if event.event == "session_start":
                        if session:
                            raise Conflict("Session already started")
                        session = await service.start(SessionStart(device_id=event.device_id, project_id=event.project_id), socket)
                        continue
                    if session is None or event.device_id != session.device_id:
                        raise Conflict("Start a session with this device_id first")
                    if event.event == "ping":
                        await service.emit(session, {"type": "pong", **service.snapshot(session)})
                    elif event.event == "session_stop":
                        if work and not work.done():
                            work.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await work
                        await service.stop(session)
                        session = None
                        await socket.send_json({"type": "session_stopped"})
                    elif work and not work.done():
                        raise Conflict("Session is busy")
                    elif event.event == "text":
                        if not event.text or not event.text.strip():
                            raise ValueError("Text is required")
                        # Keep receive loop free so stop/disconnect can interrupt a stalled API call.
                        work = asyncio.create_task(text_in_background(service, session, event.text))
                    elif event.event == "build_confirm":
                        await service.confirm_build(session, event.proposal_id)
                    elif event.event == "run_confirm":
                        work = asyncio.create_task(run_in_background(service, session, event.package_id))
                    elif event.event == "app_failed":
                        await service.device_failed(session, event.package_id)
                    elif event.event == "app_stopped":
                        raise Conflict("No device runtime attached; use session_stop to stop this PC session")
                    elif event.event == "button":
                        if not event.button or not event.action:
                            raise ValueError("button and action are required")
                        # Buttons never substitute for explicit build_confirm/run_confirm events.
                        await service.emit(session, {"type": "ui_event", "event": "button_received",
                                                     "button": event.button, "action": event.action})
                except ValidationError:
                    await send_error("invalid_event", "Invalid event schema")
                except (ValueError, KeyError) as error:
                    await send_error("conflict" if isinstance(error, Conflict) else "invalid_event", str(error))
        except WebSocketDisconnect:
            pass
        finally:
            if work:
                work.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await work
            if session and not session.stopped:
                await service.stop(session)

    return app


async def run_in_background(service, session, package_id):
    try:
        await service.confirm_run(session, package_id)
    except (ValueError, KeyError) as error:
        await service.emit(session, {"type": "error", "code": "run_rejected", "message": str(error)[:240]})


async def text_in_background(service, session, text):
    try:
        await service.text(session, text)
    except (ValueError, KeyError) as error:
        await service.emit(session, {"type": "error", "code": "text_rejected", "message": str(error)[:240]})

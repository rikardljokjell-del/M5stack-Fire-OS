import asyncio
import contextlib
import logging
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from pydantic import ValidationError

from .audio import AudioManager
from .auth import authorize_project, authorize_session, principal
from .config import Settings
from .capabilities import CapabilityError, FIRMWARE_SOURCE_REVISION, FIRMWARE_IMPLEMENTED_LUA_SERVICES, HANDOFF_PATH
from .models import BuildConfirm, DeviceEvent, RunConfirm, SessionAction, SessionStart
from .status_text import display_event
from .protocol import begin_event, dispatch, finish_event
from .storage import new_id
from .security import SecretFilter
from .service import Backend, Conflict, SessionStartRejected
from .reverse_tcp import ReverseTCP
from .device_http import DeviceFileResponse


def create_app(settings=None, provider=None, *, config_store=None, restart_callback=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        service = Backend(settings, provider)
        service.backend_settings.config_store=config_store
        service.audio = AudioManager(service)
        service.reverse_tcp = ReverseTCP(settings)
        await service.reverse_tcp.start()
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
            await service.reverse_tcp.close()
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

    @app.exception_handler(CapabilityError)
    async def capability_handler(request, error):
        return JSONResponse({"code": error.code, "message": str(error)}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return PlainTextResponse("Invalid request schema", status_code=422)

    @app.middleware("http")
    async def request_limits(request, call_next):
        audio_upload = request.method == "POST" and re.fullmatch(r"/sessions/[a-z0-9_-]{1,64}/audio/[a-z0-9_-]{1,64}", request.url.path)
        firmware_upload = request.method=="POST" and request.url.path=="/desktop/firmware"
        if firmware_upload:
            try:identity=principal(settings,request.headers.get("authorization"))
            except PermissionError:return PlainTextResponse("Authentication required",status_code=401)
            if (not settings.fire_desktop_enabled or identity!="admin" or not request.client or request.client.host not in {"127.0.0.1","::1","testclient"} or request.headers.get("origin")):
                return PlainTextResponse("Local desktop only",status_code=403)
            if request.headers.get("content-type","").split(";")[0]!="application/octet-stream":
                return PlainTextResponse("Expected binary firmware",status_code=415)
            from .firmware import MAX_FIRMWARE_BYTES
            try:length=int(request.headers.get("content-length","0"))
            except ValueError:return PlainTextResponse("Invalid Content-Length",status_code=400)
            if length<0 or length>MAX_FIRMWARE_BYTES:return PlainTextResponse("Firmware too large",status_code=413)
        elif audio_upload:
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
        from .api_registry import API_CONTRACT,REGISTRY
        return {"api_version": "fire-lua-0.1", "context": service.context, "source_verified": True,
                "hardware_api_version":"fire-lua-0.2","hardware_api_contract":API_CONTRACT,"hardware_api":REGISTRY,
                "firmware_extended_runtime_implemented_in_inspected_source":True,
                "firmware_implemented_lua_services":FIRMWARE_IMPLEMENTED_LUA_SERVICES,
                "firmware_source_revision": FIRMWARE_SOURCE_REVISION, "handoff_path": HANDOFF_PATH,
                "firmware_runtime_implemented_in_source": True,
                "firmware_runtime_verified": False, "physical_verified": False}

    async def desktop_auth(request: Request, identity=Depends(auth)):
        if (not settings.fire_desktop_enabled or identity != "admin" or not request.client
                or request.client.host not in {"127.0.0.1", "::1", "testclient"}
                or request.headers.get("origin")):
            raise HTTPException(403, "Local desktop only")

    from .evolution_http import install as install_evolution
    install_evolution(app,backend,desktop_auth,'/desktop')

    @app.get("/desktop/status", dependencies=[Depends(desktop_auth)])
    async def desktop_status(service: Backend = Depends(backend)):
        sessions = [{**service.snapshot(s), "summary": s.summary, "online": bool(s.sockets),
                     "history": s.history[-12:], "progress": s.progress} for s in service.sessions.values() if not s.stopped]
        builds = service.store.list("builds")
        return {"sessions": sessions, "devices": service.store.list("devices"),
                "builds": builds[-20:], "apps": service.app_library(),
                "repairs":[service.repairs.public(j) for j in sorted(service.store.list('repairs'),key=lambda j:j['updated_at'],reverse=True)[:16]],
                "firmware":service.firmware.catalog(),
                "physical_verified": False, "transport": service.reverse_tcp.status(),"runtime_ai":service.runtime_ai.snapshot(),
                "data_engine":service.data_engine.snapshot()}

    @app.get('/desktop/usage', dependencies=[Depends(desktop_auth)])
    async def desktop_usage(service: Backend = Depends(backend)):
        return service.usage.snapshot()

    @app.get('/desktop/data/{dataset_key}/{part}',dependencies=[Depends(desktop_auth)])
    async def desktop_data_download(dataset_key:str,part:str,service:Backend=Depends(backend)):
        path=await service.data_engine.download(dataset_key,part)
        return FileResponse(path,media_type='application/octet-stream',filename=dataset_key+'.'+part)

    @app.get('/desktop/jobs', dependencies=[Depends(desktop_auth)])
    async def desktop_jobs(service: Backend = Depends(backend)):
        return service.jobs.snapshot()

    @app.get('/desktop/runtime-ai',dependencies=[Depends(desktop_auth)])
    async def runtime_ai_status(service:Backend=Depends(backend)):
        return service.runtime_ai.snapshot()

    @app.patch('/desktop/runtime-ai',dependencies=[Depends(desktop_auth)])
    async def runtime_ai_global(request:Request,service:Backend=Depends(backend)):
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={'enabled'}:raise HTTPException(422,'Expected enabled')
        return await service.runtime_ai.set_global_enabled(body['enabled'],config_store)

    @app.patch('/desktop/apps/{project_id}/runtime-ai',dependencies=[Depends(desktop_auth)])
    async def runtime_ai_app(project_id:str,request:Request,service:Backend=Depends(backend)):
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={'enabled'}:raise HTTPException(422,'Expected enabled')
        return await service.runtime_ai.set_app_enabled(project_id,body['enabled'])

    @app.post('/desktop/jobs/{build_id}/context', dependencies=[Depends(desktop_auth)])
    async def job_context(build_id: str,request: Request,service: Backend = Depends(backend)):
        data=await request.json()
        if not isinstance(data,dict) or set(data)!={'text'}:raise HTTPException(422,'Expected text')
        return service.jobs.context(build_id,data['text'])

    @app.post('/desktop/jobs/{build_id}/resume', dependencies=[Depends(desktop_auth)])
    async def resume_job(build_id: str,request: Request,service: Backend = Depends(backend)):
        if await request.json()!={}:raise HTTPException(422,'Expected empty request')
        return await service.jobs.resume(build_id)

    @app.post('/desktop/usage/reset', dependencies=[Depends(desktop_auth)])
    async def reset_desktop_usage(request: Request, service: Backend = Depends(backend)):
        body = await request.body()
        if body and body.strip() != b'{}':
            raise HTTPException(422, 'Expected empty request')
        return service.usage.reset()

    @app.post("/desktop/sessions/{session_id}/text", dependencies=[Depends(desktop_auth)])
    async def desktop_text(session_id: str, request: Request, service: Backend = Depends(backend)):
        session = service.session(session_id)
        if not session.desktop_device_id and (session.target != "device" or not session.sockets):
            raise Conflict("M5Stack må være tilkoblet før du sender tekst.")
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {"text"}:
            raise HTTPException(422, "Expected text")
        if not isinstance(data["text"],str) or not 1<=len(data["text"].strip())<=4000:
            raise HTTPException(422,"Skriv 1–4000 tegn.")
        if session.desktop_device_id:
            if session.operation_task and not session.operation_task.done():raise Conflict("PC-samtalen behandler forrige melding.")
            from .protocol import text_task
            session.operation_task=asyncio.create_task(text_task(service,session,data["text"]))
            return {"status":"accepted"}
        event = DeviceEvent(device_id=session.device_id, protocol_version=session.protocol_version,
                            event="text", event_id=new_id("desktop"), session_id=session.id,
                            boot_id=session.boot_id, text=data["text"])
        return await dispatch(service, session, event)

    @app.post("/desktop/conversations", dependencies=[Depends(desktop_auth)])
    async def desktop_conversation(request: Request, service: Backend = Depends(backend)):
        data=await request.json()
        if (not isinstance(data,dict) or "device_id" not in data or set(data)-{"device_id","project_id","base_package_id","hardware_preview","runtime_ai_mode","development_context_id"}
                or ("hardware_preview" in data and type(data["hardware_preview"]) is not bool)
                or any(v is not None and (not isinstance(v,str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}",v)) for k,v in data.items() if k!="hardware_preview")):
            raise HTTPException(422,"Expected device_id and optional project/base version")
        return service.snapshot(await service.desktop_conversation(**data))

    @app.post("/desktop/firmware",dependencies=[Depends(desktop_auth)])
    async def firmware_upload(request: Request,service: Backend=Depends(backend)):
        if settings.fire_public_enabled:
            raise HTTPException(410, "Firmware hentes direkte fra GitHub på FIRE.")
        async with asyncio.timeout(60):
            return await service.firmware.upload(request.stream(),request.headers.get("x-firmware-name"),request.headers.get("x-firmware-version"))

    @app.post("/desktop/firmware/{firmware_id}/send",dependencies=[Depends(desktop_auth)])
    async def firmware_send(firmware_id: str,request: Request,service: Backend=Depends(backend)):
        if settings.fire_public_enabled:
            raise HTTPException(410, "Firmware hentes direkte fra GitHub på FIRE.")
        data=await request.json()
        if not isinstance(data,dict) or set(data)!={"device_id"}:raise HTTPException(422,"Expected device_id")
        return await service.firmware.send(firmware_id,data["device_id"])

    @app.get("/firmware/{firmware_id}/download")
    async def firmware_download(firmware_id: str,transfer_id: str,identity=Depends(auth),service: Backend=Depends(backend)):
        path=service.firmware.download(firmware_id,transfer_id,identity)
        return DeviceFileResponse(path,media_type="application/octet-stream",headers={"Cache-Control":"private, no-store"})

    @app.post("/desktop/sessions/{session_id}/install", dependencies=[Depends(desktop_auth)])
    async def desktop_install(session_id: str, request: Request, service: Backend = Depends(backend)):
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {"package_id"} or not isinstance(data["package_id"], str):
            raise HTTPException(422, "Expected package_id")
        return await service.install_saved(service.session(session_id), data["package_id"])

    @app.post("/desktop/sessions/{session_id}/conversation", dependencies=[Depends(desktop_auth)])
    async def desktop_conversation(session_id: str, request: Request, service: Backend = Depends(backend)):
        data = await request.json()
        if not isinstance(data, dict) or set(data) not in ({"conversation_mode"}, {"action"}, {'runtime_ai_mode'}):
            raise HTTPException(422, "Expected conversation_mode or action")
        if "action" in data and data["action"] != "cancel":
            raise HTTPException(422, "Expected cancel action")
        session = service.session(session_id)
        event = DeviceEvent(device_id=session.device_id, protocol_version=session.protocol_version,
                            event="cancel_turn" if "action" in data else "mode_select", event_id=new_id("desktop"),
                            session_id=session.id, boot_id=session.boot_id,
                            **({"conversation_mode": data["conversation_mode"]} if "conversation_mode" in data else {}),
                            **({'runtime_ai_mode':data['runtime_ai_mode']} if 'runtime_ai_mode' in data else {}))
        return await dispatch(service, session, event)

    @app.post("/desktop/sessions/{session_id}/voice", dependencies=[Depends(desktop_auth)])
    async def desktop_voice(session_id: str, request: Request, service: Backend = Depends(backend)):
        data=await request.json()
        if not isinstance(data,dict) or set(data)!={"test"} or type(data["test"]) is not bool:
            raise HTTPException(422,"Expected test boolean")
        return await service.audio.replay(service.session(session_id),test=data["test"])

    @app.post("/desktop/sessions/{session_id}/app", dependencies=[Depends(desktop_auth)])
    async def desktop_app(session_id: str, request: Request, service: Backend = Depends(backend)):
        data = await request.json()
        if not isinstance(data, dict) or not data or set(data) - {"app_mode", "project_id", "app_id", "base_package_id"}:
            raise HTTPException(422, "Expected app selection")
        session = service.session(session_id)
        event = DeviceEvent(device_id=session.device_id, protocol_version=session.protocol_version, event="app_select",
                            event_id=new_id("desktop"), session_id=session.id, boot_id=session.boot_id, **data)
        return await dispatch(service, session, event)

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

    @app.post('/sessions/{session_id}/data/{request_id}/{dataset_id}')
    async def data_upload(session_id: str, request_id: str, dataset_id: str, request: Request,
                          identity=Depends(auth), service: Backend = Depends(backend)):
        from .data_engine import DataError
        session = authorize_session(service, session_id, identity)
        limit = service.data_engine.limits['http_chunk_bytes']
        if request.headers.get('content-type','').split(';',1)[0].strip().lower() != 'application/octet-stream':
            raise HTTPException(415, 'invalid_format')
        try:
            offset = int(request.headers.get('x-data-offset', '-1'))
        except ValueError:
            raise HTTPException(400, 'offset_mismatch') from None
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, 'quota_exceeded')
            chunks.append(chunk)
        try:
            result = await service.data_engine.upload(session, request_id, dataset_id, offset,
                b''.join(chunks), request.headers.get('x-data-sha256', ''), request.headers.get('x-data-part', 'data'))
            response = JSONResponse(result)
            response.raw_headers = [(b'Content-Length' if name.lower()==b'content-length' else name, value)
                                    for name,value in response.raw_headers]
            return response
        except DataError as error:
            raise HTTPException(400, error.code) from None

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

    @app.get("/devices/{device_id}/apps")
    async def device_apps(device_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        if identity not in {"admin", device_id}:
            raise PermissionError("Device mismatch")
        return service.app_catalog(device_id)

    @app.get("/projects/{item_id}/versions")
    async def project_versions(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        project = authorize_project(service.store, item_id, identity)
        return [{"package_id": p["id"], "version": p["manifest"]["version"], "manifest": p["manifest"],
                 "archive_sha256": p["archive_sha256"]} for p in service.app_versions(project)]

    @app.post("/sessions/{session_id}/audio/{turn_id}", status_code=202)
    async def audio_input(session_id: str, turn_id: str, request: Request, identity=Depends(auth), service: Backend = Depends(backend)):
        session = authorize_session(service, session_id, identity)
        try:
            return await service.audio.receive(session, turn_id, request.stream())
        except CapabilityError:
            raise
        except asyncio.TimeoutError:
            raise HTTPException(408, "Audio upload timed out") from None
        except ValueError as error:
            raise HTTPException(413 if "size limit" in str(error) else 400, service.redactor.text(str(error))) from None

    @app.get("/audio/{audio_id}")
    async def audio_output(audio_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        item, path = service.audio.clip(audio_id, identity)
        return DeviceFileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": "private, no-store", "X-Audio-Format": "pcm_s16le", "X-Audio-Sample-Rate": "24000"},
                                  completed=lambda stats:service.audio.download_result(audio_id,stats))

    @app.get("/projects")
    async def projects(identity=Depends(auth), service: Backend = Depends(backend)):
        return [p for p in service.store.list("projects") if identity == "admin" or p.get("owner_device_id") == identity]

    @app.get("/projects/{item_id}")
    async def project(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        return authorize_project(service.store, item_id, identity)

    @app.get("/projects/{item_id}/quality")
    async def project_quality(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        authorize_project(service.store, item_id, identity)
        return service.quality.cases(item_id)

    @app.get("/projects/{item_id}/feedback")
    async def project_feedback(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        authorize_project(service.store,item_id,identity)
        return [r for r in service.store.list("feedback") if r["project_id"]==item_id]

    @app.delete("/projects/{item_id}")
    async def delete(item_id: str, identity=Depends(auth), service: Backend = Depends(backend)):
        project = authorize_project(service.store, item_id, identity)
        if project.get("owner_device_id") and identity != "admin":
            raise PermissionError("Backendhistorikk slettes fra PC-programmet.")
        allowed, reason = service.backend_delete_check(project)
        if not allowed:
            raise Conflict(reason)
        service.delete_app_history(project)
        return {"status": "deleted"}

    @app.delete("/projects/{item_id}/versions/{package_id}",dependencies=[Depends(desktop_auth)])
    async def delete_version(item_id: str,package_id: str,service: Backend=Depends(backend)):
        project=service.store.get("projects",item_id)
        service.delete_app_version(project,package_id)
        return {"status":"deleted","package_id":package_id}

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
        from .quality import require_deliverable
        require_deliverable(package)
        service.evolution.require_delivery(package)
        if service.store.get("builds", package["build_id"])["status"] != "ready":
            raise Conflict("Package build has not passed")
        from .builds import verify_archive
        path = service.store.path("packages", item_id, ".zip")
        verify_archive(path, package["manifest"], package["archive_sha256"])
        manifest = package["manifest"]
        def transfer(delta):
            count = service.active_downloads.get(item_id, 0) + delta
            if count:
                service.active_downloads[item_id] = count
            else:
                service.active_downloads.pop(item_id, None)
        return DeviceFileResponse(path, media_type="application/zip", filename=f"{manifest['id']}-v{manifest['version']}.zip",
                                  headers={"Cache-Control": "private, no-cache"}, transfer=transfer)

    @app.websocket("/ws/device")
    async def device(socket: WebSocket):
        try:
            identity = principal(settings, socket.headers.get("authorization"))
            if getattr(socket.app.state, "restart_pending", False):
                raise PermissionError("Backend is restarting")
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
                if session and socket not in session.sockets:
                    await socket.close(code=1000)
                    break  # A replacement connection now owns this session.
                raw = packet.get("text")
                if raw is None:
                    await socket.close(code=1003)
                    break
                if len(raw.encode("utf-8")) > 8192:
                    await socket.close(code=1009)
                    break
                try:
                    if getattr(socket.app.state, "restart_pending", False):
                        await socket.close(code=1012)
                        break
                    event = DeviceEvent.model_validate_json(raw)
                    if event.event == "session_start":
                        if identity != "admin" and event.device_id != identity:
                            raise PermissionError("Device identity mismatch")
                        record, duplicate = begin_event(service, event)
                        if duplicate:
                            # A lost session_started may cause an exact retry on
                            # a new socket. Dedup acknowledges the action, but
                            # the transport must still attach to that session.
                            prior_id = (duplicate.get("result") or {}).get("session_id")
                            if not prior_id and (duplicate.get('result') or {}).get('error'):
                                raise SessionStartRejected('prior_start_rejected')
                            if prior_id:
                                request = SessionStart(**{k: getattr(event, k) for k in SessionStart.model_fields})
                                if session is None:
                                    request = request.model_copy(update={"resume_session_id": prior_id})
                                    session = await service.start(request, socket, identity)
                                elif session.id != prior_id:
                                    raise Conflict("Session start belongs to another session")
                                else:
                                    await service.emit(session, {"type": "session_started", **service.snapshot(session)})
                                    await service.session_snapshot(session)
                                duplicate = {**duplicate, "result": service.snapshot(session)}
                            await (service.emit(session, duplicate) if session else socket.send_json(duplicate))
                            continue
                        if session:
                            raise Conflict("Session already started")
                        try:
                            request = SessionStart(**{k: getattr(event, k) for k in SessionStart.model_fields})
                            session = await service.start(request, socket, identity)
                        except (ValueError, KeyError, PermissionError, FileNotFoundError) as error:
                            reason = (error.reason_code if isinstance(error, SessionStartRejected) else
                                      'identity_mismatch' if isinstance(error, PermissionError) else
                                      'reference_unavailable' if isinstance(error, (KeyError, FileNotFoundError)) else
                                      'session_conflict' if isinstance(error, Conflict) else 'invalid_start')
                            finish_event(service, record, {"error": type(error).__name__, 'reason_code': reason})
                            raise
                        result = service.snapshot(session)
                        if getattr(session, 'recovery_reason_code', None):
                            result['recovery_reason_code'] = session.recovery_reason_code
                        ack = finish_event(service, record, result)
                        if ack:
                            await service.emit(session, ack)
                    else:
                        if session is None:
                            raise Conflict("Start a session first")
                        await dispatch(service, session, event)
                        if session.stopped:
                            session = None
                except ValidationError as error:
                    # Never include input values or arbitrary extra field names.
                    known = {"session_id required after session_start": "session_id", "Protocol 0.2 requires event_id": "event_id",
                             "Missing event-specific fields": "event_fields",
                             "Device sessions require protocol 0.2, boot_id and capabilities": "boot_id/capabilities"}
                    fields = sorted({str(e["loc"][0]) if e["loc"] and e["loc"][0] in DeviceEvent.model_fields else
                                     known.get(str(e.get("ctx", {}).get("error", "")), "event") if not e["loc"] else "extra_fields"
                                     for e in error.errors()})
                    safe = "Ugyldig melding fra FIRE: " + ", ".join(fields)
                    logging.getLogger("uvicorn.error").warning(safe)
                    error_event = {"type": "error", "code": "invalid_event", "message": safe[:240]}
                    if session is None:
                        error_event.update(code='session_start_rejected', retryable=False)
                    await (service.emit(session, error_event) if session else socket.send_json(display_event(error_event)))
                    if session is None:
                        await socket.close(code=1008)
                        break
                except (ValueError, KeyError, PermissionError, FileNotFoundError) as error:
                    message = "Referenced item not found" if isinstance(error, FileNotFoundError) else service.redactor.text(str(error))[:240]
                    error_event = {"type": "error", "code": error.code if isinstance(error, CapabilityError) else "event_rejected", "message": message}
                    if session is None:
                        error_event.update(code='session_start_rejected', retryable=False,
                            message='Tilkobling avvist. Kontroller valgt app og samtalemodus.')
                    await (service.emit(session, error_event) if session else socket.send_json(display_event(error_event)))
                    if session is None:
                        await socket.close(code=1008)
                        break
        except WebSocketDisconnect:
            pass
        finally:
            if session and not session.stopped:
                await service.detach(session, socket)

    from .browser_api import install_browser
    install_browser(app, settings, config_store, restart_callback)
    return app

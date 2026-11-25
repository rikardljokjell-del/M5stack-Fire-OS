"""Same-process browser UI using the existing backend/configuration/job stores."""
import asyncio
import contextlib
import hmac
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .auth import principal
from .browser_auth import BrowserAuth, COOKIE, LOCAL_HOSTS, SurfaceBoundary, digest, host_of
from .desktop_config import DesktopConfig
from .firmware_catalog import FirmwareCatalog
from .quality import require_deliverable
from .service import Conflict, Session
from .models import State


class StartConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    project_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    base_package_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    conversation_mode: str = Field(default="develop", pattern=r"^(develop|chat)$")
    runtime_ai_mode: Literal['auto','off'] | None = None


class Text(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    buttons: list[Literal['A','B','C']] = Field(default_factory=list,max_length=32)
    elapsed_ms: int = Field(default=1000,ge=16,le=12000,strict=True)


def busy(service):
    return bool(service.device_builds or service.build_lock.locked() or service.repairs.tasks or service.active_downloads or service.runtime_ai.tasks
                or getattr(service,'preview_service',None) and service.preview_service.lock.locked()
                or any(s.lock.locked() or any(t and not t.done() for t in
                       (s.task, s.operation_task, s.input_task, s.speech_task)) for s in service.sessions.values()))


def install_browser(app, settings, config_store=None, restart_callback=None):
    auth = BrowserAuth(settings)
    firmware = FirmwareCatalog()
    app.state.browser_auth = auth
    app.state.config_store = config_store
    app.state.firmware_catalog = firmware
    app.state.restart_pending = False
    app.state.restart_message = ""
    app.add_middleware(SurfaceBoundary, settings=settings)

    @app.middleware("http")
    async def browser_headers(request, call_next):
        if app.state.restart_pending and request.method not in {"GET", "HEAD", "OPTIONS"}:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Backend starter på nytt. Arbeid kan startes når den er klar."}, status_code=503)
        response = await call_next(request)
        if request.url.path.startswith(("/web", "/ui")) or request.url.path == "/":
            response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    def backend(request: Request):
        return request.app.state.backend

    async def signed_in(request: Request):
        return await auth.require(request)

    def store():
        if config_store is None:
            raise HTTPException(409, "Åpne fra Windows-programmet for å endre innstillinger.")
        return config_store

    @app.get("/")
    async def root():
        return RedirectResponse("/ui/")

    @app.get("/ui/")
    async def index():
        return FileResponse(Path(__file__).parent / "web" / "index.html")

    app.mount("/ui/assets", StaticFiles(directory=Path(__file__).parent / "web"), name="web-assets")

    @app.get("/web/auth")
    async def auth_status(request: Request):
        try:
            session = await auth.require(request)
            return {"signed_in": True, "csrf": session.csrf, "expires_at": session.expires}
        except HTTPException:
            return {"signed_in": False, "remote": auth.origin(request).startswith("https:")}

    @app.post("/web/login")
    async def access_login(request: Request, response: Response):
        auth.origin_check(request)
        if auth.origin(request) != settings.fire_web_origin:
            raise HTTPException(403, "Use local sign-in")
        claims = await auth.verify_access(request.headers.get("cf-access-jwt-assertion"))
        return auth.create(response, claims["sub"], auth.origin(request), claims["exp"], remote=True)

    @app.post("/desktop/web-login")
    async def desktop_link(request: Request):
        if (not settings.fire_desktop_enabled or request.headers.get("origin")
                or not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}
                or principal(settings, request.headers.get("authorization")) != "admin"
                or not settings.fire_backend_token.get_secret_value()):
            raise HTTPException(403, "Desktop credential required")
        return {"path": "/ui/#signin=" + auth.bootstrap(), "expires_in": 60}

    @app.post("/web/local-login")
    async def local_login(request: Request, response: Response):
        auth.origin_check(request)
        if host_of(request.headers.get("host", "")) not in LOCAL_HOSTS or not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(403, "Local sign-in only")
        bucket = int(time.time() // 60)
        auth.failures = {k: v for k, v in auth.failures.items() if k == bucket}
        auth.failures[bucket] = auth.failures.get(bucket, 0) + 1
        if auth.failures[bucket] > 10:
            raise HTTPException(429, "Vent ett minutt før neste innlogging.")
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {"code"}:
            raise HTTPException(422, "Use the one-time link from the Windows program")
        auth.consume(data["code"])
        return auth.create(response, "local-desktop", auth.origin(request))

    @app.post("/web/logout", dependencies=[Depends(signed_in)])
    async def logout(request: Request, response: Response):
        auth.sessions.pop(digest(request.cookies.get(COOKIE, "")), None)
        response.delete_cookie(COOKIE, path="/")
        return {"signed_in": False}

    @app.get("/web/status", dependencies=[Depends(signed_in)])
    async def status(service=Depends(backend)):
        sessions = [{**service.snapshot(s), "history": s.history, "summary": s.summary,
                     "progress": s.progress, "online": bool(s.sockets)} for s in service.sessions.values() if not s.stopped]
        active = {s["session_id"] for s in sessions}
        saved = sorted(service.store.list("sessions"), key=lambda s: s.get("last_seen", 0), reverse=True)
        archived = [{k: s.get(k) for k in ("session_id", "project_id", "desktop_device_id", "summary", "last_seen", "state")}
                    for s in saved if s.get("desktop_device_id") in settings.device_tokens() and s["session_id"] not in active][:24]
        return {"mode": settings.fire_ai_mode, "sessions": sessions, "saved_conversations": archived,
                "devices": service.store.list("devices"), "configured_devices": list(settings.device_tokens()),
                "jobs": service.jobs.snapshot(), "apps": service.app_library(), "usage": service.usage.snapshot(),
                "physical_verified": False, "restart_available": bool(restart_callback),
                "runtime_ai":service.runtime_ai.snapshot(),
                "restart_pending": app.state.restart_pending, "restart_message": app.state.restart_message}

    @app.get("/web/models", dependencies=[Depends(signed_in)])
    async def models():
        from .model_catalog import ROLE_MODELS, choice_label, price_detail
        return {role: [{"id": name, "label": choice_label(role, name), "detail": price_detail(role, name)}
                       for name in names] for role, names in ROLE_MODELS.items()}

    @app.patch('/web/runtime-ai',dependencies=[Depends(signed_in)])
    async def runtime_global(request:Request,service=Depends(backend)):
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={'enabled'}:raise HTTPException(422,'Expected enabled')
        return await service.runtime_ai.set_global_enabled(body['enabled'],config_store)

    @app.patch('/web/apps/{project_id}/runtime-ai',dependencies=[Depends(signed_in)])
    async def runtime_app(project_id:str,request:Request,service=Depends(backend)):
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={'enabled'}:raise HTTPException(422,'Expected enabled')
        return await service.runtime_ai.set_app_enabled(project_id,body['enabled'])

    @app.get("/web/settings", dependencies=[Depends(signed_in)])
    async def get_settings():
        current = store()
        # Admin/device credentials and namespace never leave the vault.
        values = current.config.model_dump(exclude={"credential_namespace"})
        return {"values": values, "openai_configured": bool(current.secret("openai")),
                "apply_requires_restart": True}

    @app.patch("/web/settings", dependencies=[Depends(signed_in)])
    async def save_settings(request: Request, service=Depends(backend)):
        if busy(service):
            raise Conflict("La den aktive jobben bli ferdig før du endrer innstillinger.")
        data = await request.json()
        if not isinstance(data, dict) or set(data) - {"values", "openai_api_key"} or not isinstance(data.get("values", {}), dict):
            raise HTTPException(422, "Expected settings values")
        current = store()
        allowed = set(DesktopConfig.model_fields) - {"credential_namespace", "schema_version", "cost_profile_version", "workspace", "device_ids"}
        if set(data.get("values", {})) - allowed:
            raise HTTPException(422, "This setting is managed in the Windows program")
        api_key = data.get("openai_api_key")
        if api_key is not None and (not isinstance(api_key, str) or len(api_key) > 1000 or any(c.isspace() for c in api_key)):
            raise HTTPException(422, "Invalid API credential")
        config = DesktopConfig.model_validate({**current.config.model_dump(), **data.get("values", {})})
        current.save(config, api_key=api_key)
        return {"saved": True, "restart_required": True, "message": "Lagret. Velg Bruk innstillinger for kontrollert omstart."}

    @app.post("/web/settings/apply", dependencies=[Depends(signed_in)])
    async def apply_settings(service=Depends(backend)):
        if busy(service):
            raise Conflict("En jobb pågår. Innstillingene kan brukes når den er ferdig.")
        if not restart_callback:
            raise HTTPException(409, "Start backend på nytt fra Windows-programmet.")
        next_settings = store().settings()  # Validate before scheduling anything.
        if next_settings.fire_ai_mode == "openai" and not next_settings.openai_api_key.get_secret_value():
            raise Conflict("Legg inn OpenAI API-nøkkel før du aktiverer OpenAI-modus.")
        app.state.restart_pending = True
        app.state.restart_message = "Backend starter på nytt."
        # Block all new HTTP and WS work during the response-drain interval.
        # Recheck on this event loop: an already admitted request may have won
        # the race just before the gate closed. Never stop its new work.
        def restart_if_idle():
            if busy(service):
                app.state.restart_pending = False
                app.state.restart_message = "Ny jobb startet før omstart. Jobben fortsetter; bruk innstillingene når den er ferdig."
                return
            restart_callback()
        asyncio.get_running_loop().call_later(1, restart_if_idle)
        return {"status": "restarting", "message": "Backend starter på nytt. Logg inn igjen etterpå."}

    @app.get("/web/firmware", dependencies=[Depends(signed_in)])
    async def firmware_list(service=Depends(backend)):
        result = await firmware.get()
        return {**result, "devices": [{"id": d["id"], "firmware_version": (d.get("capabilities") or {}).get("firmware_version"),
                                      "online": d.get("online", False), "last_seen": d.get("last_seen")}
                                     for d in service.store.list("devices")]}

    @app.get("/desktop/firmware-catalog")
    async def desktop_firmware(request: Request):
        if (not settings.fire_desktop_enabled or request.headers.get("origin") or not request.client
                or request.client.host not in {"127.0.0.1", "::1", "testclient"}
                or principal(settings, request.headers.get("authorization")) != "admin"):
            raise HTTPException(403, "Desktop credential required")
        return await firmware.get()

    @app.post("/web/conversations", dependencies=[Depends(signed_in)])
    async def conversation(body: StartConversation, service=Depends(backend)):
        s = await service.desktop_conversation(body.device_id, body.project_id, body.base_package_id,runtime_ai_mode=body.runtime_ai_mode)
        s.conversation_mode = body.conversation_mode
        service.persist(s)
        return service.snapshot(s)

    @app.post('/web/conversations/{session_id}/mode',dependencies=[Depends(signed_in)])
    async def runtime_generation_mode(session_id:str,request:Request,service=Depends(backend)):
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={'runtime_ai_mode'}:raise HTTPException(422,'Expected runtime_ai_mode')
        from .models import DeviceEvent
        from .protocol import dispatch
        from .storage import new_id
        s=service.session(session_id)
        return await dispatch(service,s,DeviceEvent(device_id=s.device_id,session_id=s.id,boot_id=s.boot_id,
            protocol_version=s.protocol_version,event_id=new_id('mode'),event='mode_select',runtime_ai_mode=body['runtime_ai_mode']))

    @app.post("/web/conversations/{session_id}/resume", dependencies=[Depends(signed_in)])
    async def resume_conversation(session_id: str, service=Depends(backend)):
        if session_id in service.sessions:
            s = service.session(session_id)
        else:
            saved = service.store.get("sessions", session_id)
            owner = saved.get("desktop_device_id")
            if not owner or owner not in settings.device_tokens():
                raise PermissionError
            s = Session(session_id, saved["device_id"], saved["project_id"], desktop_device_id=owner)
            for key in ("history", "summary", "capabilities", "base_package_id", "app_mode", "conversation_mode",
                        "proposal_id", "package_id", "build_id", "progress", "resumed_from_build_id"):
                if key in saved:
                    setattr(s, key, saved[key])
            s.state = State.awaiting_build_confirmation if s.proposal_id else State.idle
            service.sessions[s.id] = s
            service.persist(s)
        return {**service.snapshot(s), "history": s.history, "summary": s.summary}

    @app.post("/web/conversations/{session_id}/text", dependencies=[Depends(signed_in)])
    async def text(session_id: str, body: Text, service=Depends(backend)):
        s = service.session(session_id)
        if not s.desktop_device_id:
            raise Conflict("Velg en PC-samtale.")
        if s.operation_task and not s.operation_task.done():
            raise Conflict("Forrige melding behandles. Du kan avbryte svaret.")
        from .protocol import text_task
        s.operation_task = asyncio.create_task(text_task(service, s, body.text))
        return {"status": "accepted"}

    @app.post("/web/conversations/{session_id}/cancel", dependencies=[Depends(signed_in)])
    async def cancel_turn(session_id: str, service=Depends(backend)):
        s = service.session(session_id)
        if not s.desktop_device_id:
            raise Conflict("Velg en PC-samtale.")
        from .protocol import cancel_turn as cancel
        await cancel(service, s)
        service.persist(s)
        return {"status": "cancelled"}

    @app.post("/web/conversations/{session_id}/build", dependencies=[Depends(signed_in)])
    async def build_confirm(session_id: str, request: Request, service=Depends(backend)):
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {"proposal_id"} or not isinstance(data["proposal_id"], str):
            raise HTTPException(422, "Confirm the current proposal")
        return await service.confirm_build(service.session(session_id), data["proposal_id"])

    @app.post("/web/conversations/{session_id}/run", dependencies=[Depends(signed_in)])
    async def run_confirm(session_id: str, request: Request, service=Depends(backend)):
        data = await request.json()
        if not isinstance(data, dict) or set(data) != {"package_id"} or not isinstance(data["package_id"], str):
            raise HTTPException(422, "Confirm the tested package")
        s = service.session(session_id)
        if s.target != "device" or not s.sockets:
            raise Conflict("Koble til FIRE og installer pakken før du velger Kjør.")
        return await service.confirm_run(s, data["package_id"])

    @app.post("/web/jobs/{build_id}/context", dependencies=[Depends(signed_in)])
    async def context(build_id: str, body: Text, service=Depends(backend)):
        return service.jobs.context(build_id, body.text)

    @app.post("/web/jobs/{build_id}/resume", dependencies=[Depends(signed_in)])
    async def resume_job(build_id: str, service=Depends(backend)):
        return await service.jobs.resume(build_id)

    @app.post("/web/jobs/{build_id}/cancel", dependencies=[Depends(signed_in)])
    async def cancel_job(build_id: str, service=Depends(backend)):
        build = service.store.get("builds", build_id)
        owner = service.store.get("projects", build["project_id"]).get("owner_device_id")
        if owner not in settings.device_tokens():
            raise PermissionError
        # Admin action uses existing ownership/cancellation code without creating
        # a fake connection or a physical installation receipt.
        proxy = Session("web-cancel", owner, build["project_id"], target="device", protocol_version="0.2")
        return await service.build_event(proxy, SimpleNamespace(event="build_cancel", build_id=build_id))

    @app.post("/web/usage/reset", dependencies=[Depends(signed_in)])
    async def reset_usage(service=Depends(backend)):
        return service.usage.reset()

    @app.get("/web/packages/{package_id}/download", dependencies=[Depends(signed_in)])
    async def download(package_id: str, service=Depends(backend)):
        p = service.store.get("packages", package_id)
        require_deliverable(p)
        if service.store.get("builds", p["build_id"])["status"] != "ready":
            raise Conflict("Package build has not passed")
        from .builds import verify_archive
        path = service.store.path("packages", package_id, ".zip")
        verify_archive(path, p["manifest"], p["archive_sha256"])
        from .device_http import DeviceFileResponse
        def transfer(delta):
            count = service.active_downloads.get(package_id, 0) + delta
            if count: service.active_downloads[package_id] = count
            else: service.active_downloads.pop(package_id, None)
        return DeviceFileResponse(path, transfer=transfer,
                            filename=p["manifest"]["id"] + "-" + p["manifest"]["version"] + ".zip",
                            media_type="application/zip")

    @app.post("/web/packages/{package_id}/install", dependencies=[Depends(signed_in)])
    async def install(package_id: str, service=Depends(backend)):
        p = service.store.get("packages", package_id)
        owner = service.store.get("projects", p["project_id"]).get("owner_device_id")
        s = next((s for s in service.sessions.values() if s.target == "device" and s.device_id == owner and s.sockets and not s.stopped), None)
        if not s:
            raise Conflict("Koble til FIRE før installasjon. Pakken er lagret i biblioteket.")
        return await service.install_saved(s, package_id)

    @app.post('/web/packages/{package_id}/preview',dependencies=[Depends(signed_in)])
    async def package_preview(package_id:str,body:PreviewInput,service=Depends(backend)):
        from .visual_preview import PreviewService
        if not hasattr(service,'preview_service'):
            service.preview_service=PreviewService(service)
        return await service.preview_service.package(package_id,body.buttons,body.elapsed_ms)

    @app.delete("/web/apps/{project_id}", dependencies=[Depends(signed_in)])
    async def delete_app(project_id: str, service=Depends(backend)):
        service.delete_app_history(service.store.get("projects", project_id))
        return {"status": "deleted"}

    @app.delete("/web/apps/{project_id}/versions/{package_id}", dependencies=[Depends(signed_in)])
    async def delete_version(project_id: str, package_id: str, service=Depends(backend)):
        service.delete_app_version(service.store.get("projects", project_id), package_id)
        return {"status": "deleted"}

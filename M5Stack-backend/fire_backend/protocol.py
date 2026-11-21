"""Durable event deduplication and the single device-control dispatch path."""
import asyncio
import contextlib
import hashlib
import time

from .models import State
from .capabilities import policy, require_audio_input
from .storage import canonical, new_id


def begin_event(service, event):
    if event.protocol_version != "0.2":
        return None, None
    digest = hashlib.sha256(canonical(event.model_dump())).hexdigest()
    try:
        saved = service.store.get("events", event.event_id)
    except FileNotFoundError:
        saved = None
    if saved:
        if saved["device_id"] != event.device_id or saved["digest"] != digest:
            raise ValueError("event_id reused with different identity or payload")
        status = "duplicate" if saved["status"] == "completed" else "unknown"
        return None, {"type": "event_ack", "event_id": event.event_id, "status": status, "result": saved.get("result")}
    record = {"id": event.event_id, "device_id": event.device_id, "digest": digest,
              "status": "processing", "created_at": time.time()}
    service.store.put("events", record["id"], record)
    return record, None


def finish_event(service, record, result):
    if record is None:
        return None
    record.update(status="completed", result=result)
    service.store.put("events", record["id"], record, critical=True)
    return {"type": "event_ack", "event_id": record["id"], "status": "accepted", "result": result}


async def cancel_turn(service, session):
    for task in (session.input_task, session.operation_task):
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    await service.close_dialog(session)
    if hasattr(service, "audio"):
        service.audio.cancel(session)
    if session.speech_task and not session.speech_task.done():
        with contextlib.suppress(asyncio.CancelledError):
            await session.speech_task
    session.proposal_id, session.summary, session.turn_id = None, "", None
    if session.state not in {State.building, State.testing, State.running}:
        ready = policy(service.settings, session.target, session.capabilities)["conversation_audio"]["input_enabled"]
        await service.state(session, State.listening if ready else State.idle)
    await service.activity(session, "idle")


async def text_task(service, session, text):
    try:
        await service.text(session, text)
    except (ValueError, KeyError) as error:
        await service.emit(session, {"type": "error", "code": "text_rejected", "message": str(error)[:240]})


async def run_task(service, session, package_id):
    try:
        await service.confirm_run(session, package_id)
    except (ValueError, KeyError) as error:
        await service.emit(session, {"type": "error", "code": "run_rejected", "message": str(error)[:240]})


async def dispatch(service, session, event):
    if session.stopped:
        raise ValueError("Session was stopped")
    if event.device_id != session.device_id or event.protocol_version != session.protocol_version:
        raise ValueError("Session identity or protocol mismatch")
    if session.protocol_version == "0.2" and event.session_id != session.id:
        raise ValueError("session_id mismatch")
    if session.target == "device" and event.boot_id != session.boot_id:
        raise ValueError("boot_id mismatch")
    session.last_seen = time.time()
    record, duplicate = begin_event(service, event)
    if duplicate:
        await service.emit(session, duplicate)
        return duplicate
    try:
        result = await handle(service, session, event)
    except (ValueError, KeyError, PermissionError, FileNotFoundError) as error:
        if record:
            finish_event(service, record, {"error": type(error).__name__, "message": str(error)[:240]})
        raise
    ack = finish_event(service, record, result)
    if ack:
        await service.emit(session, ack)
    return result


async def handle(service, session, event):
    name = event.event
    if name == "ping":
        await service.emit(session, {"type": "pong", **service.snapshot(session)})
        if session.protocol_version == "0.2":
            await service.session_snapshot(session)
        return {"status": "ok"}
    if name == "session_stop":
        await service.stop(session)
        await service.emit(session, {"type": "session_stopped"})
        return {"status": "stopped"}
    if name == "cancel_turn":
        await cancel_turn(service, session)
        return {"status": "cancelled"}
    if name == "app_stop":
        return {"stop_id": (await service.request_app_stop(session))["id"]}
    if name == "install_retry":
        if session.state not in {State.awaiting_install, State.failed, State.installed} or event.package_id != session.package_id:
            raise ValueError("No matching package awaiting installation retry")
        package = service.verify_package(session, event.package_id)
        return {"install_id": (await service.offer_install(session, package))["id"]}
    if name in {"device_install_result", "app_started", "app_healthy", "app_failed", "app_stopped", "rollback_result"}:
        return await service.device_receipt(session, event)
    if name in {"audio_playback_started", "audio_playback_finished"}:
        await service.audio.playback(session, event)
        return {"status": "recorded"}
    if name == "button":
        if not event.button or not event.action:
            raise ValueError("button and action are required")
        await service.emit(session, {"type": "ui_event", "event": "button_received", "button": event.button, "action": event.action})
        return {"status": "received"}
    if session.input_task and not session.input_task.done():
        raise ValueError("Session is busy")
    if name in {"text", "listen_start", "listen_stop"}:
        if session.lock.locked() or session.state in {State.building, State.testing, State.running, State.starting, State.stopping, State.rollback_pending}:
            raise ValueError("Session is busy")
        if name == "text":
            if not event.text or not event.text.strip():
                raise ValueError("Text is required")
            if hasattr(service, "audio"):
                service.audio.cancel(session)
            session.turn_id = event.turn_id or new_id("turn")
            session.proposal_id, session.summary = None, ""
            service.persist(session)
            session.input_task = asyncio.create_task(text_task(service, session, event.text))
            return {"status": "queued", "turn_id": session.turn_id}
        require_audio_input(service.settings, session)
        if not event.turn_id:
            raise ValueError("turn_id is required")
        if name == "listen_start":
            service.audio.cancel(session)
            session.proposal_id, session.summary, session.turn_id = None, "", event.turn_id
            await service.state(session, State.listening)
            await service.activity(session, "listening")
        else:
            if session.turn_id != event.turn_id or session.activity != "listening":
                raise ValueError("No matching recording")
            await service.activity(session, "processing")
        return {"turn_id": session.turn_id}
    if name == "build_confirm":
        build = await service.confirm_build(session, event.proposal_id)
        return {"build_id": build["id"]}
    if name == "run_confirm":
        if session.target == "device":
            return await service.confirm_run(session, event.package_id)
        session.input_task = asyncio.create_task(run_task(service, session, event.package_id))
        return {"status": "queued", "target": "pc_simulation"}
    raise ValueError("Unsupported event")

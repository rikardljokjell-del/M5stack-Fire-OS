"""Durable event deduplication and the single device-control dispatch path."""
import asyncio
import contextlib
import hashlib
import time

from .models import State, APP_EVENT_DEFAULTS, CAPABILITY_DEFAULTS
from .capabilities import require_audio_input
from .storage import canonical, new_id


def begin_event(service, event):
    if event.protocol_version != "0.2":
        return None, None
    payload = event.model_dump()
    if payload.get("capabilities"):
        for name,default in CAPABILITY_DEFAULTS.items():
            if payload["capabilities"].get(name)==default:payload["capabilities"].pop(name,None)
    for name, default in APP_EVENT_DEFAULTS.items():
        if payload.get(name) == default:
            payload.pop(name, None)
    digest = hashlib.sha256(canonical(payload)).hexdigest()
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
    old_turn = session.turn_id
    if old_turn:
        session.retired_turns = (session.retired_turns + [old_turn])[-32:]
    session.turn_id = None  # invalidate old work BEFORE yielding to cancellation
    if hasattr(service, "audio"):
        service.audio.cancel(session)
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
    session.recording_started_at = None
    session.last_error = ""
    if session.state not in {State.building, State.testing, State.running}:
        await service.state(session, State.idle if session.target == "device" else State.listening)
    await service.activity(session, "idle")
    if old_turn:
        await service.emit(session, {"type": "turn_cancelled", "turn_id": old_turn})


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


async def repair_after_stop(service, session, text):
    try:
        async with asyncio.timeout(service.settings.fire_command_timeout_seconds + 1):
            while session.state in {State.running, State.stopping, State.starting, State.rollback_pending} and not session.stopped:
                await asyncio.sleep(0.05)
        if not session.stopped:
            await service.text(session, text)
    except TimeoutError:
        await service.failure(session, ValueError("Appen svarte ikke på stopp. Reparasjonen er ikke startet; prøv igjen når FIRE er tilkoblet."))


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
        if session.target == "device" and not (isinstance(result,dict) and result.get('status')=='identity_conflict'):
            with contextlib.suppress(OSError,ValueError):
                service.quality.feedback(session,event)
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
    if name=='runtime_ai_request':return await service.runtime_ai.request(session,event)
    if name=='runtime_ai_cancel':return await service.runtime_ai.cancel_event(session,event)
    if name.startswith('backend_settings_'):return await service.backend_settings.event(session,event)
    if name.startswith('evolution_'):return await service.evolution.event(session,event)
    if name in {'data_request','app_develop_request'}:return await service.data_engine.request(session,event)
    if name=='data_cancel':return await service.data_engine.cancel_event(session,event)
    if name=='app_observation_confirm':return await service.data_engine.confirm_observation(session,event)
    if name in {'build_background','build_jobs','build_notice_ack','build_resume','build_cancel'}:
        return await service.build_event(session,event)
    if name=='app_repair_prepare':return await service.repairs.prepare(session,event)
    if name=='app_repair_status':return await service.repairs.status(session,event)
    if name=='app_repair_cancel':return await service.repairs.cancel(session,event)
    if name=='build_confirm' and event.repair_id:return await service.repairs.confirm(session,event)
    if name == "firmware_store_result":
        return service.firmware.receipt(session,event)
    if name in {"app_list", "app_versions", "app_select", "app_deleted", "app_inventory", "app_download", "app_backend_delete_prepare", "app_backend_delete_confirm"}:
        if session.target != "device" or session.protocol_version != "0.2":
            raise ValueError("App lifecycle requires a protocol-0.2 device session")
        return await service.app_event(session, event)
    if name == "ping":
        await service.emit(session, {"type": "pong", **service.snapshot(session)})
        if session.protocol_version == "0.2":
            await service.session_snapshot(session)
        return {"status": "ok"}
    if name == "app_diagnostic":
        package = service.store.get("packages", event.package_id)
        project = service.store.get("projects", package["project_id"])
        if session.target != "device" or project.get("owner_device_id") != session.device_id or package["manifest"]["id"] != event.app_id:
            raise PermissionError("Diagnostic package scope mismatch")
        source=service.repairs.source(package)
        if (event.sha256 and event.sha256!=package['manifest']['checksum'] or
                event.diagnostics and event.diagnostics.source_bytes is not None and event.diagnostics.source_bytes!=len(source.encode('utf-8'))):
            # Preserve the report, but never blame a different immutable source.
            report={'id':event.event_id,'device_id':session.device_id,'app_id':event.app_id,
                    'reported_package_id':event.package_id,'reported_source_sha256':event.sha256,
                    'message':event.message,'error_code':event.error_code,
                    'diagnostics':event.diagnostics.model_dump(exclude_none=True) if event.diagnostics else {},
                    'reported_at':time.time(),'status':'identity_conflict'}
            service.store.put('diagnostics',report['id'],report,critical=True)
            await service.emit(session,{'type':'repair_available','app_id':event.app_id,'package_id':None,
                'reported_package_id':event.package_id,'identity_conflict':True})
            await service.request_inventory(session)
            return {'status':'identity_conflict','report_id':event.event_id}
        case = service.quality.record(project_id=project["id"],package_id=package["id"],device_id=session.device_id,
            source_hash=package["manifest"]["checksum"],message=event.error_code+": "+(event.message or ""),provenance="device_diagnostic")
        device=service.device_record(session)
        if device.get("installed_package_id")==package["id"]:
            device.update(last_failure_package_id=package["id"],last_failure_boot_id=session.boot_id)
            service.store.put("devices",device["id"],device,critical=True)
        await service.emit(session,{"type":"repair_available","app_id":event.app_id,"package_id":package["id"],"case_id":case["id"]})
        return {"status":"recorded","case_id":case["id"]}
    if name == "session_stop":
        await service.stop(session)
        await service.emit(session, {"type": "session_stopped"})
        return {"status": "stopped"}
    if name == "cancel_turn":
        if event.turn_id and event.turn_id in session.retired_turns:
            return {"status": "ignored", "reason": "retired_turn"}
        if event.turn_id and event.turn_id != session.turn_id:
            raise ValueError("No matching turn to cancel")
        await cancel_turn(service, session)
        return {"status": "cancelled"}
    if name == "mode_select":
        if event.runtime_ai_mode:
            if session.state in {State.building,State.testing}:raise ValueError('La byggingen bli ferdig før du endrer AI-valg.')
            session.runtime_ai_mode=event.runtime_ai_mode;service.persist(session)
            from .runtime_contract import available
            await service.emit(session,{'type':'ui_event','event':'runtime_ai_policy','mode':session.runtime_ai_mode,
                'available':available(session.capabilities),'enabled':service.settings.fire_runtime_ai_enabled})
            if not event.conversation_mode:return {'runtime_ai_mode':session.runtime_ai_mode}
        await service.release_foreground(session)
        if session.state in {State.building, State.testing, State.running, State.starting, State.stopping, State.rollback_pending, State.awaiting_install}:
            raise ValueError("Fullfør eller stopp app-handlingen før du bytter samtalemodus.")
        await cancel_turn(service, session)
        session.conversation_mode = event.conversation_mode
        session.history = []
        await service.emit(session, {"type": "conversation_mode", "conversation_mode": session.conversation_mode})
        return {"conversation_mode": session.conversation_mode}
    if name == "app_stop":
        return {"stop_id": (await service.request_app_stop(session))["id"]}
    if name == "install_retry":
        if session.state not in {State.awaiting_install, State.failed, State.installed} or event.package_id != session.package_id:
            raise ValueError("No matching package awaiting installation retry")
        package = service.verify_package(session, event.package_id)
        return {"install_id": (await service.offer_install(session, package))["id"]}
    if name in {"device_install_result", "app_started", "app_healthy", "app_failed", "app_stopped", "rollback_result"}:
        result=await service.device_receipt(session, event)
        if name in {'app_stopped','app_failed'}:
            await service.runtime_ai.cancel_run(session,event.run_id)
            await service.data_engine.cancel_run(session,event.run_id)
        if name=='app_failed':await service.evolution.receipt_finding(session,event)
        return result
    if name in {"audio_playback_started", "audio_playback_finished", "audio_playback_failed"}:
        if event.turn_id in session.retired_turns:
            return {"status": "ignored", "reason": "retired_turn"}
        outcome=await service.audio.playback(session, event)
        return {"status": outcome or "recorded"}
    if name == "button":
        if not event.button or not event.action:
            raise ValueError("button and action are required")
        await service.emit(session, {"type": "ui_event", "event": "button_received", "button": event.button, "action": event.action})
        return {"status": "received"}
    if name in {"text", "listen_start", "listen_stop"}:
        if name in {'text','listen_start'}:
            service.detach_device_build(session)
        from .quality import repair_requested
        if name == "text" and session.conversation_mode == "develop" and event.text and repair_requested(event.text) and session.state == State.running:
            await service.request_app_stop(session)
            session.input_task = asyncio.create_task(repair_after_stop(service, session, event.text))
            return {"status":"stopping_for_repair"}
        if name == "text" and (not event.text or not event.text.strip()):
            raise ValueError("Text is required")
        if name == "listen_stop" and event.turn_id in session.retired_turns:
            return {"status": "ignored", "reason": "retired_turn"}
        if session.state in {State.building, State.testing, State.running, State.starting, State.stopping, State.rollback_pending}:
            raise ValueError("App-handling pågår. Vent til den er ferdig, eller stopp appen før du snakker.")
        if name in {"text", "listen_start"}:
            if name == "listen_start":
                require_audio_input(service.settings, session)
                if event.turn_id in session.retired_turns:
                    return {"status": "ignored", "reason": "retired_turn"}
                if event.turn_id == session.turn_id and session.activity == "listening":
                    return {"turn_id": session.turn_id, "status": "already_recording"}
            await cancel_turn(service, session)
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
            session.recording_started_at = time.monotonic()
            session.audio_status = {"phase": "recording", "turn_id": event.turn_id}
            session.last_error = ""
            session.proposal_id, session.summary, session.turn_id = None, "", event.turn_id
            await service.state(session, State.listening)
            await service.activity(session, "listening")
        else:
            if session.turn_id == event.turn_id and session.activity != "listening" and session.audio_status.get("phase") in {"awaiting_upload", "transcribing", "dialog", "text_ready", "generating_reply", "reply_ready", "playing", "played", "retry"}:
                return {"turn_id": session.turn_id, "status": "already_stopped"}
            if session.turn_id != event.turn_id or session.activity != "listening":
                raise ValueError("No matching recording")
            if session.recording_started_at is not None:
                session.audio_status["recording_wall_seconds"] = round(time.monotonic() - session.recording_started_at, 3)
                session.recording_started_at = None
            await service.activity(session, "processing")
            service.audio.expect_upload(session)
        return {"turn_id": session.turn_id}
    if session.input_task and not session.input_task.done():
        pending=session.input_task
        if (name!='build_confirm' or session.state!=State.awaiting_build_confirmation
                or not event.proposal_id or event.proposal_id!=session.proposal_id):
            raise ValueError("Venter på AI-svaret. Trykk B for å avbryte og snakke på nytt.")
        # The proposal may reach FIRE before this same text task finishes its
        # final activity notification. Drain only that task, without cancelling it.
        proposal,turn=session.proposal_id,session.turn_id
        try:
            await asyncio.wait_for(asyncio.shield(pending),timeout=2)
        except TimeoutError:
            raise ValueError("Venter på AI-svaret. Trykk B for å avbryte og snakke på nytt.") from None
        except asyncio.CancelledError:
            if not pending.cancelled():raise
            raise ValueError("Byggforslaget er erstattet; vent på det nye forslaget.") from None
        if (session.stopped or session.input_task is not pending or session.turn_id!=turn
                or session.proposal_id!=proposal or session.state!=State.awaiting_build_confirmation):
            raise ValueError("Byggforslaget er erstattet; vent på det nye forslaget.")
    if name == "build_confirm":
        build = await service.confirm_build(session, event.proposal_id)
        return {"build_id": build["id"]}
    if name == "run_confirm":
        if session.target == "device":
            return await service.confirm_run(session, event.package_id)
        session.input_task = asyncio.create_task(run_task(service, session, event.package_id))
        return {"status": "queued", "target": "pc_simulation"}
    raise ValueError("Unsupported event")

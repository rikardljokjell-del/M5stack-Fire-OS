"""Bounded half-duplex audio turns; raw audio never enters logs or packages."""
import array
import asyncio
import contextlib
import hashlib
import io
import math
import os
import sys
import time
import wave

from .models import State
from .capabilities import policy, require_audio_input
from .storage import identifier, new_id, canonical
from .metering import session_usage


class CaptureSignalError(ValueError):
    pass


def validate_wav(data):
    try:
        if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE" or int.from_bytes(data[4:8], "little") != len(data) - 8:
            raise ValueError("Malformed WAV size/header")
        with wave.open(io.BytesIO(data), "rb") as wav:
            count = wav.getnframes()
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, "NONE"):
                raise ValueError("Expected mono PCM16 WAV at 16000 Hz")
            if not 1600 <= count <= 240000:
                raise ValueError("Recording must be 0.1 to 15 seconds")
            samples = wav.readframes(count)
            if len(samples) != count * 2:
                raise ValueError("Truncated WAV payload")
        values = array.array("h", samples)
        if sys.byteorder != "little":
            values.byteswap()
        if max(abs(value) for value in values) < 50:
            raise CaptureSignalError("Jeg hørte ikke tale. Trykk B og prøv igjen nær mikrofonen.")
        return count
    except (wave.Error, EOFError) as error:
        raise ValueError("Invalid PCM WAV recording") from error


def prepare_recording(data):
    """Remove ADC DC bias; retain bounded gain and safe numerical diagnostics.

    Deduplication still hashes original wire bytes. No recorded content is
    written to ordinary logs, packages or permanent diagnostic files.
    """
    count = validate_wav(data)
    with wave.open(io.BytesIO(data), "rb") as wav:
        samples = array.array("h", wav.readframes(count))
    if sys.byteorder != "little":
        samples.byteswap()
    dc = sum(samples) / count
    ac_peak = max(abs(value-dc) for value in samples)
    rms = math.sqrt(sum((value-dc)**2 for value in samples) / count)
    if ac_peak < 16:
        raise CaptureSignalError("Jeg hørte ikke tydelig tale. Trykk B og prøv igjen nær mikrofonen.")
    gain = max(1.0, min(8.0, 12000 / ac_peak))
    corrected = array.array("h", (max(-32768, min(32767, round((value-dc)*gain))) for value in samples))
    if sys.byteorder != "little":
        corrected.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(corrected.tobytes())
    return output.getvalue(), {"samples": count, "duration_seconds": round(count/16000, 3),
        "dc_offset": round(dc), "ac_peak": round(ac_peak), "ac_rms": round(rms, 1), "gain": round(gain, 2),
        "clipped_fraction": round(sum(abs(x) >= 32760 for x in samples)/count, 4)}


class AudioManager:
    def __init__(self, service):
        self.service = service
        self.store, self.settings = service.store, service.settings
        self.uploads = {}
        self.awaiting = {}
        self.serial_turns = {}
        self.ready_tasks = {}
        # No audio survives a backend restart. Metadata is retained briefly only
        # for deduplication, and its previous URLs become immediately unavailable.
        for path in (self.store.root / "audio").iterdir():
            if path.suffix in {".pcm", ".wav", ".part"}:
                path.unlink(missing_ok=True)
        for item in self.store.list("audio"):
            if item["status"] in {"receiving", "processing", "ready", "staged", "committed"}:
                item.update(status="expired", expires_at=time.time())
                self.store.put("audio", item["id"], item, critical=True)

    def serial_available(self, session):
        return bool(self.settings.fire_audio_enabled and session.protocol_version == '0.2'
                    and session.target == 'device')

    @staticmethod
    def serial_scope(session):
        return {**{name: getattr(session, name) for name in ('id', 'device_id', 'boot_id', 'project_id',
            'base_package_id', 'conversation_mode', 'app_mode', 'development_context_id', 'turn_id')},
            'capabilities_sha256': hashlib.sha256(canonical(session.capabilities)).hexdigest()}

    def serial_turn(self, session, kind):
        handoff = self.serial_turns.get(session.id)
        if (not handoff or handoff['kind'] != kind or session.stopped
                or handoff['scope'] != self.serial_scope(session) or session.turn_id in session.retired_turns):
            return None
        try:
            project = self.store.get('projects', session.project_id)
        except FileNotFoundError:
            return None
        if project.get('owner_device_id') != session.device_id:
            return None
        if self.service.device_record(session).get('boot_id') != session.boot_id:
            return None
        if kind in {'input', 'output'} and (time.monotonic() >= handoff['deadline']
                or time.time() >= handoff['expires_at']):
            return None
        return handoff

    def preserve_handoff(self, session):
        # No provider work is retained merely because the transport reconnects.
        if session.lock.locked() or any(task and not task.done() for task in (session.input_task, session.operation_task, session.speech_task)):
            return False
        handoff = self.serial_turn(session, 'input') or self.serial_turn(session, 'output')
        if not handoff:
            return False
        if handoff['kind'] == 'output':
            if handoff.get('proposal_id') != session.proposal_id or session.audio_id != handoff['audio_id']:
                return False
        return True

    async def resume_handoff(self, session):
        handoff = self.serial_turn(session, 'output')
        if handoff and self.preserve_handoff(session):
            item = self.store.get('audio', handoff['audio_id'])
            if item['status'] == 'ready':
                await self.announce(session, item)

    def schedule_serial_ready(self, session, item):
        async def finished():
            try:
                # speak has finished writing immutable PCM, but its task and
                # the input task may still have harmless persistence epilogues.
                tasks = {t for t in (session.input_task, session.operation_task, session.speech_task) if t}
                if tasks:
                    await asyncio.gather(*(asyncio.shield(t) for t in tasks))
                handoff = self.serial_turn(session, 'processing')
                if not handoff or session.audio_id != item['id'] or item['status'] != 'ready':
                    return
                deadline = min(item['expires_at'], item['ready_at'] + 35)
                handoff.update(kind='output', audio_id=item['id'], proposal_id=session.proposal_id,
                    expires_at=deadline, deadline=time.monotonic() + max(0, deadline-time.time()))
                if self.serial_turn(session, 'output'):
                    await self.announce(session, item)
            except asyncio.CancelledError:
                raise
            except Exception:
                if not session.stopped and session.audio_id == item['id']:
                    await self.playback_failed(session, item, 'audio_handoff_failed',
                        'Talesvaret kunne ikke klargjøres. Tekst og forslag er beholdt.')
        task = asyncio.create_task(finished())
        self.ready_tasks[session.id] = task
        def done(completed):
            if self.ready_tasks.get(session.id) is completed:
                self.ready_tasks.pop(session.id, None)
            if not completed.cancelled():
                completed.exception()
        task.add_done_callback(done)

    def cleanup(self):
        now = time.time()
        for item in self.store.list("audio"):
            if item["expires_at"] <= now:
                for suffix in (".pcm", ".wav", ".part"):
                    self.store.path("audio", item["id"], suffix).unlink(missing_ok=True)
                # Keep compact dedup tombstones for one resume window.
                if item["expires_at"] + self.settings.fire_session_resume_seconds <= now:
                    self.store.path("audio", item["id"]).unlink(missing_ok=True)

    def cancel(self, session):
        self.serial_turns.pop(session.id, None)
        ready = self.ready_tasks.pop(session.id, None)
        if ready and ready is not asyncio.current_task() and not ready.done():
            ready.cancel()
        self.awaiting.pop(session.id, None)
        if session.audio_status.get("phase") in {"recording", "awaiting_upload", "transcribing", "generating_reply", "reply_ready", "playing"}:
            session.audio_status = {**session.audio_status, "phase": "cancelled"}
        if session.speech_task and session.speech_task is not asyncio.current_task() and not session.speech_task.done():
            session.speech_task.cancel()
        # Release reverse-pool HTTP slots as soon as a turn is retired. Waiting
        # for the next upload can deadlock a finite pool of occupied sockets.
        for key, task in list(self.uploads.items()):
            if key[0] == session.id and (session.stopped or key[1] in session.retired_turns):
                if task is not asyncio.current_task():
                    task.cancel()
                    self.uploads.pop(key, None)
        for item in self.store.list("audio"):
            if item["session_id"] == session.id and item["status"] in {"processing", "ready", "staged", "committed"}:
                item.update(status="cancelled", expires_at=time.time())
                self.store.put("audio", item["id"], item, critical=True)
                for suffix in (".pcm", ".wav", ".part"):
                    self.store.path("audio", item["id"], suffix).unlink(missing_ok=True)
        session.audio_id = None

    def expect_upload(self, session, *, serial_audio=False):
        if serial_audio and not self.serial_available(session):
            raise ValueError('Serial audio was not advertised for this device session')
        self.awaiting[session.id] = (session.turn_id, time.monotonic() + 25)
        session.audio_status = {**session.audio_status, "phase": "awaiting_upload", "turn_id": session.turn_id}
        if serial_audio:
            now = time.time()
            handoff = {'scope': self.serial_scope(session), 'kind': 'input', 'deadline': time.monotonic()+45,
                'expires_at': now+45, 'upload_expires_at': now+25}
            self.serial_turns[session.id] = handoff
            session.audio_status.update(serial_audio=True, upload_expires_at=handoff['upload_expires_at'],
                commit_expires_at=handoff['expires_at'])
            return {'serial_audio': True, 'upload_expires_at': handoff['upload_expires_at'],
                'commit_expires_at': handoff['expires_at']}
        return {}

    async def expire_waiting(self):
        for session_id, handoff in list(self.serial_turns.items()):
            if handoff['kind'] != 'input' or time.monotonic() < handoff['deadline']:
                continue
            session = self.service.sessions.get(session_id)
            if session and self.serial_turns.get(session_id) is handoff:
                self.cancel(session)
                if not session.stopped and session.turn_id == handoff['scope']['turn_id']:
                    await self.service.input_retry(session, 'Lydomgangen utløp. Ta et nytt opptak.', 'audio_upload_missing')
        for session_id, (turn_id, deadline) in list(self.awaiting.items()):
            if time.monotonic() < deadline or (session_id, turn_id) in self.uploads:
                continue
            self.awaiting.pop(session_id, None)
            session = self.service.sessions.get(session_id)
            if session and not session.stopped and session.turn_id == turn_id:
                self.serial_turns.pop(session.id, None)
                session.audio_status["phase"] = "upload_missing"
                await self.service.input_retry(session, "Lydfilen kom ikke frem. Trykk B for et nytt opptak.", "audio_upload_missing")
        for item in self.store.list("audio"):
            if item.get("status") != "ready" or "ready_at" not in item:
                continue
            session = self.service.sessions.get(item["session_id"])
            if not session or session.stopped or session.turn_id != item["turn_id"] or session.audio_id != item["id"]:
                continue
            age=time.time()-item["ready_at"]
            if session.audio_status.get("phase") == "playing":
                if age>=max(60,item["size_bytes"]/48000+35):
                    await self.playback_failed(session,item,"playback_finish_missing","FIRE kvitterte ikke for ferdig avspilling. Tekst og forslag er beholdt.")
                continue
            if age >= 35:
                await self.playback_failed(session,item,"playback_timeout","FIRE kvitterte ikke for lydsvaret. Tekst og byggeforslag er beholdt.")
            elif age >= 12 and item.get("announcements",1)<2 and not item.get("server_transfer",{}).get("finished"):
                item["announcements"]=2
                self.store.put("audio",item["id"],item)
                await self.announce(session,item)

    async def announce(self,session,item):
        keys=("turn_id","sha256","size_bytes","expires_at","sample_rate","channels","format","synthetic","mode")
        serial = {}
        if item.get('serial_audio'):
            handoff = self.serial_turn(session, 'output')
            if not handoff or handoff['audio_id'] != item['id']:
                return
            serial = {'serial_audio': True, 'fetch_expires_at': handoff['expires_at']}
        await self.service.emit(session,{"type":"audio_ready","audio_id":item["id"],"download_url":f"/audio/{item['id']}",
            **{k:item[k] for k in keys}, **serial})

    async def replay(self,session,test=False):
        if not getattr(self.settings,'fire_speech_enabled',True):
            raise ValueError('Talesvar er slått av i backend. Taleopptak og tekst fungerer fortsatt.')
        if (not session.sockets or not session.turn_id or session.activity!="idle" or session.lock.locked()
                or (session.input_task and not session.input_task.done()) or session.state not in
                {State.idle,State.clarification_needed,State.awaiting_build_confirmation,State.failed}):
            raise ValueError("Vent til FIRE er tilkoblet og taleomgangen er ferdig før lydtesten.")
        if not policy(self.settings,session.target,session.capabilities)["conversation_audio"]["output_enabled"]:
            raise ValueError("FIRE annonserer ikke støtte for talesvar.")
        text="Dette er en test av høyttaleren på FIRE." if test else next((x["content"] for x in reversed(session.history) if x["role"]=="assistant"),"")
        if not text:raise ValueError("Ingen lagret svartekst å spille av.")
        old=session.speech_task
        self.cancel(session)
        if old and not old.done():
            with contextlib.suppress(asyncio.CancelledError):await old
        session.audio_status={"phase":"generating_reply","turn_id":session.turn_id,"test_clip":test}
        session.speech_task=asyncio.create_task(self.speak(session,text))
        return {"status":"queued","turn_id":session.turn_id,"test_clip":test}

    async def restore_proposal(self,session):
        if session.state==State.awaiting_build_confirmation and session.proposal_id:
            await self.service.emit(session,{"type":"build_proposal","proposal_id":session.proposal_id,
                "project_id":session.project_id,"summary":session.summary,"turn_id":session.turn_id})

    async def playback_failed(self,session,item,code,message):
        self.serial_turns.pop(session.id, None)
        item.update(status="playback_failed",error_code=code,expires_at=time.time())
        self.store.put("audio",item["id"],item,critical=True)
        self.store.path("audio",item["id"],".pcm").unlink(missing_ok=True)
        session.audio_status.update(phase="playback_failed",audio_id=item["id"],error_code=code)
        session.audio_id=None
        await self.service.activity(session,"idle")
        await self.service.emit(session,{"type":"audio_error","turn_id":item["turn_id"],"message":message})
        await self.restore_proposal(session)

    async def receive(self, session, turn_id, stream):
        identifier(turn_id)
        require_audio_input(self.settings, session)
        upload_key = (session.id, turn_id)
        if upload_key in self.uploads:
            raise ValueError("An upload is already active")
        if turn_id in session.retired_turns:
            return {"status": "cancelled", "turn_id": turn_id, "duplicate": False}
        for key, task in list(self.uploads.items()):
            if key[0] == session.id and key[1] in session.retired_turns:
                task.cancel()
                self.uploads.pop(key, None)
        if sum(key[0] == session.id for key in self.uploads) >= 2:
            raise ValueError("Forrige lydopplasting avsluttes. Prøv igjen om et øyeblikk.")
        self.uploads[upload_key] = asyncio.current_task()
        try:
            data = bytearray()
            handoff = self.serial_turn(session, 'input') if session.audio_status.get('serial_audio') else None
            if session.audio_status.get('serial_audio') and not handoff:
                raise ValueError('Serial audio handoff is no longer current')
            if handoff and time.time() >= handoff['upload_expires_at'] and not handoff.get('input_id'):
                raise ValueError('Audio upload start deadline expired')
            timeout = min(20, max(0, handoff['deadline']-time.monotonic())) if handoff else 20
            async with asyncio.timeout(timeout):
                async for chunk in stream:
                    if len(data) + len(chunk) > self.settings.fire_audio_max_input_bytes:
                        raise ValueError("Audio input size limit exceeded")
                    data.extend(chunk)
            digest = hashlib.sha256(data).hexdigest()
            if session.stopped or turn_id in session.retired_turns:
                return {"status": "cancelled", "turn_id": turn_id, "duplicate": False}
            item_id = "input-" + hashlib.sha256((session.id + ":" + turn_id).encode()).hexdigest()[:32]
            try:
                previous = self.store.get("audio", item_id)
            except FileNotFoundError:
                previous = None
            if previous:
                if previous["sha256"] != digest:
                    raise ValueError("turn_id reused with different audio")
                if previous.get('serial_audio'):
                    if not handoff or previous['status'] != 'staged' or handoff.get('input_id') != item_id:
                        raise ValueError('Serial audio was already consumed or expired')
                    return {'status': 'staged', 'turn_id': turn_id, 'duplicate': True,
                        'sha256': digest, 'expires_at': handoff['expires_at']}
                return {"status": previous["status"], "turn_id": turn_id, "duplicate": True}
            # HTTP and control use different pool sockets. A small bounded wait
            # tolerates the final WAV bytes overtaking listen_stop on the wire;
            # it never invents a recording event or admits a different turn.
            if session.turn_id == turn_id and session.activity == "listening":
                async with asyncio.timeout(2):
                    while session.turn_id == turn_id and session.activity == "listening" and not session.stopped:
                        await asyncio.sleep(0.01)
            if session.stopped or session.turn_id != turn_id or session.activity != "processing":
                raise ValueError("Upload must follow matching listen_start/listen_stop")
            if session.lock.locked() or (session.input_task and not session.input_task.done()):
                raise ValueError("Session is busy")
            if handoff and self.serial_turn(session, 'input') is not handoff:
                raise ValueError('Serial audio handoff changed during upload')
            prepared, metrics = prepare_recording(data)
            wall = session.audio_status.get("recording_wall_seconds", 0)
            if wall:
                metrics.update(recording_wall_seconds=wall, capture_fraction=round(metrics["duration_seconds"]/max(wall, 0.001), 3),
                               capture_gap_suspected=wall > 0.5 and metrics["duration_seconds"] < wall * 0.6,
                               capture_rate_suspected=wall > 0.5 and metrics["duration_seconds"] > max(wall * 1.6, wall + 0.75))
            self.store.reserve(len(data) + 2048)
            item = {"id": item_id, "session_id": session.id, "device_id": session.device_id,
                    "turn_id": turn_id, "sha256": digest, "status": "processing", **metrics,
                    "expires_at": time.time() + self.settings.fire_audio_ttl_seconds}
            if handoff:
                item.update(status='staged', serial_audio=True, expires_at=handoff['expires_at'],
                    prepared_sha256=hashlib.sha256(prepared).hexdigest(), prepared_size_bytes=len(prepared))
            self.store.put("audio", item_id, item)
            path = self.store.path("audio", item_id, ".wav")
            path.write_bytes(prepared)
            if handoff:
                handoff.update(input_id=item_id, sha256=digest)
                session.audio_status.update(phase='awaiting_commit')
                self.awaiting.pop(session.id, None)
                self.service.persist(session)
                return {'status': 'staged', 'turn_id': turn_id, 'duplicate': False,
                    'sha256': digest, 'expires_at': handoff['expires_at']}
            session.audio_status = {"phase": "transcribing", "turn_id": turn_id, **metrics}
            self.store.log(session.id, "Audio input accepted: " + str(metrics))
            self.awaiting.pop(session.id, None)
            session.input_task = asyncio.create_task(self.transcribe(session, item, path))
            return {"status": "accepted", "turn_id": turn_id, "duplicate": False}
        except asyncio.CancelledError:
            if session.stopped or turn_id in session.retired_turns:
                return {"status": "cancelled", "turn_id": turn_id, "duplicate": False}
            raise
        except Exception as error:
            if session.audio_status.get('serial_audio'):
                self.serial_turns.pop(session.id, None)
            pending = self.awaiting.get(session.id)
            if pending and pending[0] == turn_id and session.turn_id == turn_id and not session.stopped:
                self.awaiting.pop(session.id, None)
                session.audio_status["phase"] = "input_failed"
                message = (str(error) if isinstance(error, ValueError) else
                           "Lydopplastingen ble avbrutt eller tok for lang tid. Prøv et nytt opptak.")
                if isinstance(error, CaptureSignalError):
                    await self.service.input_retry(session, message)
                else:
                    await self.service.failure(session, ValueError(message))
            if isinstance(error, (ValueError, TimeoutError)):
                raise
            raise ValueError("Lydopplastingen ble avbrutt. Prøv et nytt opptak.") from None
        finally:
            self.uploads.pop(upload_key, None)

    async def commit(self, session, event):
        require_audio_input(self.settings, session)
        handoff = self.serial_turn(session, 'input')
        if (not session.sockets or not handoff or event.turn_id != session.turn_id
                or event.sha256 != handoff.get('sha256') or not handoff.get('input_id')
                or session.lock.locked() or any(task and not task.done() for task in
                    (session.input_task, session.operation_task, session.speech_task))):
            raise ValueError('No matching staged audio for this admitted turn')
        item = self.store.get('audio', handoff['input_id'])
        path = self.store.path('audio', item['id'], '.wav')
        if (item['status'] != 'staged' or item['session_id'] != session.id
                or item['device_id'] != session.device_id or item['turn_id'] != event.turn_id
                or item['sha256'] != event.sha256 or item['expires_at'] <= time.time()
                or path.stat().st_size != item['prepared_size_bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest() != item['prepared_sha256']):
            raise ValueError('Staged audio is expired, consumed or changed')
        # Consumption precedes scheduling. A crash or unknown ACK cannot pay twice.
        item.update(status='committed', commit_event_id=event.event_id, committed_at=time.time())
        self.store.put('audio', item['id'], item, critical=True)
        handoff['kind'] = 'processing'
        session.audio_status.update(phase='transcribing')
        self.service.persist(session)
        session.input_task = asyncio.create_task(self.transcribe(session, item, path))
        return {'status': 'queued', 'turn_id': event.turn_id, 'sha256': event.sha256}

    @session_usage
    async def transcribe(self, session, item, path):
        try:
            await self.service.state(session, State.processing)
            async with asyncio.timeout(self.settings.fire_ai_timeout_seconds):
                text = await self.service.provider.transcribe(path.read_bytes())
            text = self.store.redactor.text(text).strip()
            if session.turn_id != item["turn_id"] or session.stopped:
                item["status"] = "cancelled"
                return
            if not text:
                if item.get("capture_rate_suspected"):
                    message = "Opptaket har feil tidsforhold. Trykk B og prøv igjen. Mikrofonens samplerate må kontrolleres hvis det gjentar seg."
                elif item.get("capture_gap_suspected"):
                    message = "Opptaket ser ufullstendig ut. Trykk B og prøv igjen. Mikrofonopptaket må kontrolleres hvis det gjentar seg."
                else:
                    message = "Jeg fikk ikke tak i ordene. Trykk B og prøv igjen nær mikrofonen. Samtalen er beholdt."
                item["status"] = "no_speech"
                await self.service.input_retry(session, message)
                return
            if len(text) > 4000 or len(text.encode("utf-8")) > 6000:
                raise ValueError("Taleomgangen er for lang. Prøv et kortere opptak.")
            session.audio_status["phase"] = "dialog"
            # Full text uses the dedicated transcript event/history; snapshots
            # must still fit the firmware's 8192-byte control-frame budget.
            session.audio_status["transcript"] = text[:300]
            await self.service.emit(session, {"type": "transcript", "turn_id": item["turn_id"], "text": text,
                                              "mode": self.settings.fire_ai_mode})
            await self.service.text(session, text, source="voice")
            item["status"] = "completed"
        except asyncio.CancelledError:
            item["status"] = "cancelled"
            raise
        except Exception as error:
            item["status"] = "failed"
            if session.turn_id == item["turn_id"] and not session.stopped:
                session.audio_status["phase"] = "input_failed"
                await self.service.failure(session, error)
        finally:
            path.unlink(missing_ok=True)
            self.store.put("audio", item["id"], item, critical=True)

    @session_usage
    async def speak(self, session, text):
        if not policy(self.settings, session.target, session.capabilities)["conversation_audio"]["output_enabled"]:
            return
        audio_id = new_id("audio")
        turn_id = session.turn_id
        path = self.store.path("audio", audio_id, ".pcm")
        partial = self.store.path("audio", audio_id, ".part")
        size = 0
        digest = hashlib.sha256()
        pending_sample = b""
        session.audio_status = {**session.audio_status, "phase": "generating_reply"}
        try:
            self.store.reserve(2048)
            async with asyncio.timeout(self.settings.fire_ai_timeout_seconds):
                with partial.open("wb") as handle:
                    async for chunk in self.service.provider.speech(text[:400]):
                        if not isinstance(chunk, bytes) or size + len(pending_sample) + len(chunk) > self.settings.fire_audio_max_output_bytes:
                            raise ValueError("Speech output exceeds PCM16 size/alignment limit")
                        if session.stopped or session.turn_id != turn_id:
                            raise ValueError("Speech turn was cancelled")
                        chunk = pending_sample + chunk
                        aligned = len(chunk) - len(chunk) % 2
                        pending_sample = chunk[aligned:]
                        chunk = chunk[:aligned]
                        self.store.reserve(len(chunk))
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if pending_sample:
                raise ValueError("Speech output ended with an incomplete PCM16 sample")
            if size == 0:
                raise ValueError("Empty speech output")
            os.replace(partial, path)
            item = {"id": audio_id, "session_id": session.id, "device_id": session.device_id, "turn_id": turn_id,
                    "status": "ready", "size_bytes": size, "sha256": digest.hexdigest(),
                    "expires_at": int(time.time()) + self.settings.fire_audio_ttl_seconds,
                    "sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "synthetic": True,
                    "mode": self.settings.fire_ai_mode,"ready_at":time.time(),"announcements":1}
            if self.serial_turn(session, 'processing'):
                item['serial_audio'] = True
            self.store.put("audio", audio_id, item)
            session.audio_id = audio_id
            session.audio_status = {**session.audio_status, "phase": "reply_ready", "output_bytes": size,
                'audio_id': audio_id}
            self.service.persist(session)
            if item.get('serial_audio'):
                self.schedule_serial_ready(session, item)
            else:
                await self.announce(session,item)
        except asyncio.CancelledError:
            path.unlink(missing_ok=True)
            raise
        except Exception as error:
            path.unlink(missing_ok=True)
            if session.stopped or session.turn_id != turn_id:
                return
            session.audio_status["phase"] = "reply_failed"
            self.store.log(session.id, "Speech failed: " + type(error).__name__, critical=True)
            await self.service.emit(session, {"type": "audio_error", "turn_id": turn_id,
                                              "message": "Talesvar feilet; tekstsvaret og forslaget er beholdt."})
            await self.restore_proposal(session)
        finally:
            partial.unlink(missing_ok=True)

    def clip(self, audio_id, identity, *, playback=False):
        item = self.store.get("audio", audio_id)
        if identity != "admin" and item["device_id"] != identity:
            raise PermissionError("Audio belongs to another device")
        if item["status"] != "ready" or item["expires_at"] <= time.time():
            raise FileNotFoundError("Audio expired")
        if item.get('serial_audio'):
            session = self.service.sessions.get(item['session_id'])
            handoff = (self.serial_turn(session, 'output') or
                       (self.serial_turn(session, 'playing') if playback else None)) if session else None
            if not handoff or handoff.get('audio_id') != audio_id:
                raise FileNotFoundError('Serial audio fetch expired or scope changed')
        path = self.store.path("audio", audio_id, ".pcm")
        if path.stat().st_size != item["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Audio integrity check failed")
        return item, path

    def download_result(self,audio_id,stats):
        with contextlib.suppress(OSError,ValueError,FileNotFoundError):
            item=self.store.get("audio",audio_id)
            if item["status"]!="ready":return
            item.update(server_transfer=stats,server_transfer_at=time.time())
            self.store.put("audio",audio_id,item)
            session=self.service.sessions.get(item["session_id"])
            if session and session.audio_id==audio_id:
                session.audio_status["server_transfer"]=stats
                self.service.persist(session)

    async def playback(self, session, event):
        if event.audio_id!=session.audio_id:
            with contextlib.suppress(FileNotFoundError):
                old=self.store.get("audio",event.audio_id)
                if (old["session_id"]==session.id and old["device_id"]==session.device_id and old["turn_id"]==event.turn_id
                        and old["status"] in {"cancelled","played","playback_failed","expired"}):
                    return "ignored"
        if (session.audio_status.get("phase")=="playback_failed" and session.audio_status.get("audio_id")==event.audio_id
                and session.turn_id==event.turn_id):
            return "ignored"  # Late ack after timeout cannot resurrect a cancelled clip.
        if event.audio_id != session.audio_id or event.turn_id != session.turn_id:
            raise ValueError("Playback does not match the current turn/clip")
        item, _ = self.clip(event.audio_id, session.device_id if session.target == "device" else "admin", playback=True)
        if item["session_id"] != session.id:
            raise ValueError("Audio session mismatch")
        if event.event=="audio_playback_failed":
            await self.playback_failed(session,item,event.error_code,"FIRE kunne ikke spille av svaret. Tekst og byggeforslag er beholdt.")
            return
        if event.event == "audio_playback_started":
            if session.activity != "idle":
                raise ValueError("Cannot start playback while recording/processing")
            await self.service.activity(session, "speaking")
            session.audio_status["phase"] = "playing"
            if item.get('serial_audio'):
                self.serial_turns[session.id]['kind'] = 'playing'
        else:
            if session.activity != "speaking":
                raise ValueError("Playback was not started")
            await self.service.activity(session, "idle")
            item["status"] = "played"
            self.store.put("audio", item["id"], item, critical=True)
            self.store.path("audio", item["id"], ".pcm").unlink(missing_ok=True)
            self.cancel(session)
            session.audio_status["phase"] = "played"
            if session.state == State.awaiting_build_confirmation and session.proposal_id:
                # FIRE's playback UI returns to idle. Restore the existing
                # offer after speech, with the SAME proposal ID; no action or
                # authorization is created by this repeated notification.
                await self.service.emit(session, {"type": "build_proposal", "proposal_id": session.proposal_id,
                    "project_id": session.project_id, "summary": session.summary, "turn_id": session.turn_id})
        self.service.persist(session)

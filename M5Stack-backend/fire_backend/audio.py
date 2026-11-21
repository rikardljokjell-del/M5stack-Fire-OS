"""Bounded half-duplex audio turns; raw audio never enters logs or packages."""
import array
import asyncio
import contextlib
import hashlib
import io
import os
import sys
import time
import wave

from .models import State
from .capabilities import policy, require_audio_input
from .storage import identifier, new_id


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
            raise ValueError("Recording is silent")
        return count
    except (wave.Error, EOFError) as error:
        raise ValueError("Invalid PCM WAV recording") from error


class AudioManager:
    def __init__(self, service):
        self.service = service
        self.store, self.settings = service.store, service.settings
        self.uploads = {}
        self.awaiting = {}
        # No audio survives a backend restart. Metadata is retained briefly only
        # for deduplication, and its previous URLs become immediately unavailable.
        for path in (self.store.root / "audio").iterdir():
            if path.suffix in {".pcm", ".wav", ".part"}:
                path.unlink(missing_ok=True)
        for item in self.store.list("audio"):
            if item["status"] in {"receiving", "processing", "ready"}:
                item.update(status="expired", expires_at=time.time())
                self.store.put("audio", item["id"], item, critical=True)

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
        self.awaiting.pop(session.id, None)
        if session.speech_task and session.speech_task is not asyncio.current_task() and not session.speech_task.done():
            session.speech_task.cancel()
        upload = self.uploads.get(session.id)
        if upload and upload is not asyncio.current_task():
            upload.cancel()
        for item in self.store.list("audio"):
            if item["session_id"] == session.id and item["status"] in {"processing", "ready"}:
                item.update(status="cancelled", expires_at=time.time())
                self.store.put("audio", item["id"], item, critical=True)
                for suffix in (".pcm", ".wav", ".part"):
                    self.store.path("audio", item["id"], suffix).unlink(missing_ok=True)
        session.audio_id = None

    def expect_upload(self, session):
        self.awaiting[session.id] = (session.turn_id, time.monotonic() + 25)

    async def expire_waiting(self):
        for session_id, (turn_id, deadline) in list(self.awaiting.items()):
            if time.monotonic() < deadline or session_id in self.uploads:
                continue
            self.awaiting.pop(session_id, None)
            session = self.service.sessions.get(session_id)
            if session and not session.stopped and session.turn_id == turn_id:
                await self.service.failure(session, ValueError("Lydopplastingen kom ikke frem. Trykk B og prøv et nytt opptak, eller bruk tekst på PC."))

    async def receive(self, session, turn_id, stream):
        identifier(turn_id)
        require_audio_input(self.settings, session)
        if session.id in self.uploads:
            raise ValueError("An upload is already active")
        self.uploads[session.id] = asyncio.current_task()
        try:
            data = bytearray()
            async with asyncio.timeout(20):
                async for chunk in stream:
                    if len(data) + len(chunk) > self.settings.fire_audio_max_input_bytes:
                        raise ValueError("Audio input size limit exceeded")
                    data.extend(chunk)
            digest = hashlib.sha256(data).hexdigest()
            item_id = "input-" + hashlib.sha256((session.id + ":" + turn_id).encode()).hexdigest()[:32]
            try:
                previous = self.store.get("audio", item_id)
            except FileNotFoundError:
                previous = None
            if previous:
                if previous["sha256"] != digest:
                    raise ValueError("turn_id reused with different audio")
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
            count = validate_wav(data)
            self.store.reserve(len(data) + 2048)
            item = {"id": item_id, "session_id": session.id, "device_id": session.device_id,
                    "turn_id": turn_id, "sha256": digest, "status": "processing", "samples": count,
                    "expires_at": time.time() + self.settings.fire_audio_ttl_seconds}
            self.store.put("audio", item_id, item)
            path = self.store.path("audio", item_id, ".wav")
            path.write_bytes(data)
            self.awaiting.pop(session.id, None)
            session.input_task = asyncio.create_task(self.transcribe(session, item, path))
            return {"status": "accepted", "turn_id": turn_id, "duplicate": False}
        except asyncio.CancelledError:
            raise
        except Exception as error:
            pending = self.awaiting.get(session.id)
            if pending and pending[0] == turn_id and session.turn_id == turn_id and not session.stopped:
                self.awaiting.pop(session.id, None)
                message = (str(error) if isinstance(error, ValueError) else
                           "Lydopplastingen ble avbrutt eller tok for lang tid. Prøv et nytt opptak.")
                await self.service.failure(session, ValueError(message))
            if isinstance(error, (ValueError, TimeoutError)):
                raise
            raise ValueError("Lydopplastingen ble avbrutt. Prøv et nytt opptak.") from None
        finally:
            self.uploads.pop(session.id, None)

    async def transcribe(self, session, item, path):
        try:
            await self.service.state(session, State.processing)
            async with asyncio.timeout(self.settings.fire_ai_timeout_seconds):
                text = await self.service.provider.transcribe(path.read_bytes())
            text = self.store.redactor.text(text).strip()
            if not text or len(text) > 4000 or session.turn_id != item["turn_id"] or session.stopped:
                raise ValueError("Empty, oversized or cancelled transcription")
            await self.service.emit(session, {"type": "transcript", "turn_id": item["turn_id"], "text": text,
                                              "mode": self.settings.fire_ai_mode})
            await self.service.text(session, text)
            item["status"] = "completed"
        except asyncio.CancelledError:
            item["status"] = "cancelled"
            raise
        except Exception as error:
            item["status"] = "failed"
            await self.service.failure(session, error)
        finally:
            path.unlink(missing_ok=True)
            self.store.put("audio", item["id"], item, critical=True)

    async def speak(self, session, text):
        if not policy(self.settings, session.target, session.capabilities)["conversation_audio"]["output_enabled"]:
            return
        audio_id = new_id("audio")
        turn_id = session.turn_id
        path = self.store.path("audio", audio_id, ".pcm")
        partial = self.store.path("audio", audio_id, ".part")
        size = 0
        digest = hashlib.sha256()
        try:
            self.store.reserve(2048)
            async with asyncio.timeout(self.settings.fire_ai_timeout_seconds):
                with partial.open("wb") as handle:
                    async for chunk in self.service.provider.speech(text[:400]):
                        if not isinstance(chunk, bytes) or len(chunk) % 2 or size + len(chunk) > self.settings.fire_audio_max_output_bytes:
                            raise ValueError("Speech output exceeds PCM16 size/alignment limit")
                        if session.stopped or session.turn_id != turn_id:
                            raise ValueError("Speech turn was cancelled")
                        self.store.reserve(len(chunk))
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            if size == 0:
                raise ValueError("Empty speech output")
            os.replace(partial, path)
            item = {"id": audio_id, "session_id": session.id, "device_id": session.device_id, "turn_id": turn_id,
                    "status": "ready", "size_bytes": size, "sha256": digest.hexdigest(),
                    "expires_at": int(time.time()) + self.settings.fire_audio_ttl_seconds,
                    "sample_rate": 24000, "channels": 1, "format": "pcm_s16le", "synthetic": True,
                    "mode": self.settings.fire_ai_mode}
            self.store.put("audio", audio_id, item)
            session.audio_id = audio_id
            self.service.persist(session)
            await self.service.emit(session, {"type": "audio_ready", "audio_id": audio_id,
                                              "download_url": f"/audio/{audio_id}",
                                              **{k: v for k, v in item.items() if k not in {"id", "session_id", "device_id", "status"}}})
        except asyncio.CancelledError:
            path.unlink(missing_ok=True)
            raise
        except Exception as error:
            path.unlink(missing_ok=True)
            self.store.log(session.id, "Speech failed: " + type(error).__name__, critical=True)
            await self.service.emit(session, {"type": "audio_error", "turn_id": turn_id,
                                              "message": "Talesvar feilet; tekstsvaret og forslaget er beholdt."})
        finally:
            partial.unlink(missing_ok=True)

    def clip(self, audio_id, identity):
        item = self.store.get("audio", audio_id)
        if identity != "admin" and item["device_id"] != identity:
            raise PermissionError("Audio belongs to another device")
        if item["status"] != "ready" or item["expires_at"] <= time.time():
            raise FileNotFoundError("Audio expired")
        path = self.store.path("audio", audio_id, ".pcm")
        if path.stat().st_size != item["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Audio integrity check failed")
        return item, path

    async def playback(self, session, event):
        if event.audio_id != session.audio_id or event.turn_id != session.turn_id:
            raise ValueError("Playback does not match the current turn/clip")
        item, _ = self.clip(event.audio_id, session.device_id if session.target == "device" else "admin")
        if item["session_id"] != session.id:
            raise ValueError("Audio session mismatch")
        if event.event == "audio_playback_started":
            if session.activity != "idle":
                raise ValueError("Cannot start playback while recording/processing")
            await self.service.activity(session, "speaking")
        else:
            if session.activity != "speaking":
                raise ValueError("Playback was not started")
            await self.service.activity(session, "idle")
            self.cancel(session)

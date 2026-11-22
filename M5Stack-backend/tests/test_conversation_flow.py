"""Conversation regressions across real dispatch, tasks, audio and persistence.

Gates synchronize races explicitly: no real microphone, API key or timing sleeps.
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from fire_backend.ai import MockProvider
from fire_backend.audio import AudioManager, CaptureSignalError
from fire_backend.models import DeviceEvent, DialogReply, SessionStart
from fire_backend.protocol import dispatch
from fire_backend.service import Backend, Conflict

from test_audio import wav_data
from test_device_protocol import CAPS, configured


class Socket:
    def __init__(self):
        self.events = []

    async def send_json(self, event):
        self.events.append(event)


class Conversation:
    def __init__(self, service, session, socket):
        self.service, self.session, self.socket = service, session, socket
        self.counter = 0

    async def send(self, event, **fields):
        self.counter += 1
        return await dispatch(self.service, self.session, DeviceEvent(
            device_id=self.session.device_id, protocol_version="0.2", boot_id=self.session.boot_id,
            session_id=self.session.id, event_id=f"event-flow-{self.counter}", event=event, **fields))

    async def record(self, turn):
        await self.send("listen_start", turn_id=turn)
        await self.send("listen_stop", turn_id=turn)

    async def upload(self, turn, data=None):
        async def chunks():
            yield wav_data() if data is None else data
        return await self.service.audio.receive(self.session, turn, chunks())

    async def finish_reply(self):
        await asyncio.wait_for(self.session.input_task, 2)
        if self.session.speech_task:
            await asyncio.wait_for(self.session.speech_task, 2)


@asynccontextmanager
async def conversation(tmp_path, provider=None, mode="develop"):
    service = Backend(configured(tmp_path, fire_audio_enabled=True), provider or MockProvider())
    service.audio = AudioManager(service)
    socket = Socket()
    try:
        session = await service.start(SessionStart(device_id="fire-01", protocol_version="0.2", target="device",
            boot_id="boot-flow", capabilities=CAPS, conversation_mode=mode), socket=socket, principal="fire-01")
        yield Conversation(service, session, socket)
    finally:
        await service.close()


class GatedProvider(MockProvider):
    def __init__(self, stage):
        self.stage, self.block = stage, True
        self.entered, self.cancelled = asyncio.Event(), asyncio.Event()
        self.dialog_closed = 0

    async def gate(self, stage):
        if self.block and self.stage == stage:
            self.entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def connect_dialog(self, context):
        owner = self
        class Manager:
            async def __aexit__(self, *args):
                owner.dialog_closed += 1
        return Manager(), object()

    async def transcribe(self, data):
        await self.gate("asr")
        return await super().transcribe(data)

    async def dialog(self, history, context, connection=None):
        await self.gate("dialog")
        return await super().dialog(history, context, connection)

    async def speech(self, text):
        yield b"\x00\x01" * 128
        await self.gate("tts")
        yield b"\x00\x01" * 128


@pytest.mark.parametrize("stage", ["asr", "dialog", "tts"])
async def test_barge_in_during_asr_dialog_or_speech_starts_next_recording_without_busy(tmp_path, stage):
    provider = GatedProvider(stage)
    async with conversation(tmp_path, provider) as flow:
        session = flow.session
        await flow.record("turn-old")
        assert (await flow.upload("turn-old"))["status"] == "accepted"
        await asyncio.wait_for(provider.entered.wait(), 2)
        old_task = session.speech_task if stage == "tts" else session.input_task

        await asyncio.wait_for(flow.send("listen_start", turn_id="turn-new"), 2)
        assert provider.cancelled.is_set() and old_task.cancelled()
        assert session.turn_id == "turn-new" and session.activity == "listening"
        assert session.state == "listening" and not session.last_error
        assert session.operation_task is None and not session.lock.locked()
        assert not list((tmp_path / "audio").glob("*.wav"))
        assert not list((tmp_path / "audio").glob("*.part"))
        assert not list((tmp_path / "audio").glob("*.pcm"))
        if stage in {"dialog", "tts"}:
            assert provider.dialog_closed == 1

        provider.block = False
        await flow.send("listen_stop", turn_id="turn-new")
        await flow.upload("turn-new")
        await flow.finish_reply()
        assert session.proposal_id and session.audio_id
        assert session.state == "awaiting_build_confirmation"
        assert not any("busy" in event.get("message", "").lower() for event in flow.socket.events)


async def test_late_playback_and_listen_stop_cannot_reset_new_recording(tmp_path):
    async with conversation(tmp_path) as flow:
        await flow.record("turn-old")
        await flow.upload("turn-old")
        await flow.finish_reply()
        old_audio = flow.session.audio_id
        await flow.send("audio_playback_started", audio_id=old_audio, turn_id="turn-old")
        assert flow.session.activity == "speaking"
        await flow.send("listen_start", turn_id="turn-new")
        for event in ("audio_playback_started", "audio_playback_finished"):
            result = await flow.send(event, audio_id=old_audio, turn_id="turn-old")
            assert result == {"status": "ignored", "reason": "retired_turn"}
        assert (await flow.send("listen_stop", turn_id="turn-old"))["status"] == "ignored"
        assert flow.session.turn_id == "turn-new" and flow.session.activity == "listening"
        assert not flow.session.audio_id and not flow.session.proposal_id


async def test_cancel_then_fresh_turn_preserves_conversation_and_cleans_audio(tmp_path):
    provider = GatedProvider("tts")
    async with conversation(tmp_path, provider) as flow:
        await flow.record("turn-old")
        await flow.upload("turn-old")
        await asyncio.wait_for(provider.entered.wait(), 2)
        history = list(flow.session.history)
        await flow.send("cancel_turn", turn_id="turn-old")
        assert flow.session.state == "idle" and flow.session.turn_id is None
        assert flow.session.history == history
        assert flow.session.speech_task.cancelled()
        assert not list((tmp_path / "audio").glob("*.part"))
        assert (await flow.send("cancel_turn", turn_id="turn-old"))["status"] == "ignored"
        provider.block = False
        await flow.record("turn-new")
        await flow.upload("turn-new")
        await flow.finish_reply()
        assert flow.session.proposal_id and flow.session.turn_id == "turn-new"


class AccidentalPlan(MockProvider):
    async def dialog(self, history, context, connection=None):
        return DialogReply(message="Et forslag.", clarification_needed=False, build_summary="Lag en sirkel")


@pytest.mark.parametrize("initial_chat", [True, False])
async def test_chat_mode_never_grants_build_even_if_provider_returns_a_plan(tmp_path, initial_chat):
    async with conversation(tmp_path, AccidentalPlan(), mode="chat" if initial_chat else "develop") as flow:
        if not initial_chat:
            await flow.send("mode_select", conversation_mode="chat")
        await flow.send("text", text="Lag en sirkel", turn_id="turn-chat")
        await flow.finish_reply()
        assert flow.session.conversation_mode == "chat" and flow.session.state == "idle"
        assert not flow.session.proposal_id and not flow.session.summary
        assert not any(event["type"] == "build_proposal" for event in flow.socket.events)
        assert "conversation_mode=chat" == flow.service.context_for(flow.session).splitlines()[0]
        with pytest.raises(Conflict):
            await flow.service.confirm_build(flow.session, "proposal-invented")
        assert not flow.service.store.list("builds")


class EmptyOnce(MockProvider):
    def __init__(self):
        self.calls = 0

    async def transcribe(self, data):
        self.calls += 1
        return "" if self.calls == 1 else await super().transcribe(data)


async def test_no_speech_is_recoverable_and_retains_prior_conversation(tmp_path):
    async with conversation(tmp_path, EmptyOnce()) as flow:
        await flow.send("text", text="Lag en sirkel", turn_id="turn-text")
        await flow.finish_reply()
        history = list(flow.session.history)
        await flow.record("turn-empty")
        await flow.upload("turn-empty")
        await flow.finish_reply()
        assert flow.session.state == "idle" and flow.session.activity == "idle"
        assert flow.session.history == history and not flow.session.proposal_id
        retries = [event for event in flow.socket.events if event["type"] == "input_retry"]
        assert len(retries) == 1 and retries[0]["recoverable"] is True
        assert not list((tmp_path / "audio").glob("*.wav"))
        await flow.record("turn-good")
        await flow.upload("turn-good")
        await flow.finish_reply()
        assert flow.session.proposal_id and not flow.session.last_error


async def test_silent_capture_recovers_without_sending_noise_to_provider(tmp_path):
    provider = EmptyOnce()
    async with conversation(tmp_path, provider) as flow:
        await flow.record("turn-silent")
        with pytest.raises(CaptureSignalError):
            await flow.upload("turn-silent", wav_data(amplitude=0))
        assert provider.calls == 0 and flow.session.state == "idle"
        assert flow.session.audio_status["phase"] == "retry"
        await flow.send("listen_start", turn_id="turn-retry")
        assert flow.session.activity == "listening" and not flow.session.last_error


async def test_late_upload_body_cannot_block_or_poison_the_next_turn(tmp_path):
    async with conversation(tmp_path) as flow:
        await flow.record("turn-old")
        entered, release = asyncio.Event(), asyncio.Event()
        data = wav_data()
        async def delayed_body():
            yield data[:100]
            entered.set()
            await release.wait()
            yield data[100:]
        old_upload = asyncio.create_task(flow.service.audio.receive(flow.session, "turn-old", delayed_body()))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await flow.record("turn-new")
            assert (await flow.upload("turn-new"))["status"] == "accepted"
            await flow.finish_reply()
            proposal, history = flow.session.proposal_id, list(flow.session.history)
            release.set()
            assert (await asyncio.wait_for(old_upload, 2))["status"] == "cancelled"
            assert flow.session.proposal_id == proposal and flow.session.history == history
            assert flow.session.turn_id == "turn-new" and not flow.session.last_error
            assert not flow.service.audio.uploads
            assert not list((tmp_path / "audio").glob("*.wav"))
        finally:
            if not old_upload.done():
                old_upload.cancel()
                await old_upload  # Retired HTTP bodies return a bounded cancelled receipt.


async def test_repeated_barge_in_reclaims_stalled_old_uploads_before_accepting_fresh_audio(tmp_path):
    async with conversation(tmp_path) as flow:
        tasks, releases, closed = [], [], []
        data = wav_data()

        def stalled_body(entered, release, finished):
            async def stream():
                try:
                    yield data[:100]
                    entered.set()
                    await release.wait()
                    yield data[100:]
                finally:
                    finished.set()
            return stream()

        try:
            for index in range(3):
                turn = f"turn-stalled-{index}"
                await flow.record(turn)
                entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
                releases.append(release)
                closed.append(finished)
                task = asyncio.create_task(flow.service.audio.receive(
                    flow.session, turn, stalled_body(entered, release, finished)))
                tasks.append(task)
                await asyncio.wait_for(entered.wait(), 2)
                assert len(flow.service.audio.uploads) == 1

            await flow.record("turn-fresh")
            assert (await flow.upload("turn-fresh"))["status"] == "accepted"
            await flow.finish_reply()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 2)
            assert all(result["status"] == "cancelled" for result in results)
            assert all(event.is_set() for event in closed)
            assert not flow.service.audio.uploads
            assert flow.session.turn_id == "turn-fresh" and flow.session.proposal_id
            assert not flow.session.last_error
            assert not list((tmp_path / "audio").glob("*.wav"))
            assert not list((tmp_path / "audio").glob("*.part"))
            assert not any("busy" in event.get("message", "").lower() for event in flow.socket.events)
        finally:
            for release in releases:
                release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_unrelated_http_request_cancellation_is_not_swallowed(tmp_path):
    async with conversation(tmp_path) as flow:
        await flow.record("turn-current")
        entered = asyncio.Event()
        async def body():
            entered.set()
            await asyncio.Event().wait()
            yield
        task = asyncio.create_task(flow.service.audio.receive(flow.session, "turn-current", body()))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not flow.service.audio.uploads
        assert flow.session.turn_id == "turn-current"
        assert not list((tmp_path / "audio").glob("*.wav"))


async def test_large_multibyte_transcript_cannot_overflow_firmware_control_frames(tmp_path):
    class Multibyte(MockProvider):
        async def transcribe(self, data):
            return "\u597d" * 2500
    async with conversation(tmp_path, Multibyte()) as flow:
        await flow.record("turn-unicode")
        await flow.upload("turn-unicode")
        await flow.finish_reply()
        assert "for lang" in flow.session.last_error
        assert not flow.session.history and not flow.session.proposal_id
        assert not any(event["type"] == "transcript" for event in flow.socket.events)
        assert not list((tmp_path / "audio").glob("*.wav"))

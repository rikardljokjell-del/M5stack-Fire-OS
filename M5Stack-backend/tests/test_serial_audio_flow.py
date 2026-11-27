"""Offline public-device voice handoff; no physical microphone/TLS/provider claim."""
import asyncio
import copy
import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fire_backend import audio as audio_module, protocol, service as service_module
from fire_backend.ai import MockProvider
from fire_backend.app import create_app
from fire_backend.audio import validate_wav
from fire_backend.models import DeviceEvent, DialogReply
from fire_backend.protocol import begin_event
from test_audio import wav_data
from test_device_protocol import CAPS, OTHER, Device, configured, headers
from test_session_reconnect import bounded_receive


PUBLIC_HOST = "fire.example.org"
QUIZ_REQUEST = "Lag et quizspill med spørsmål og poeng, styrt med de tre knappene."
PCM = b"\x00\x01" * 2400
LEGACY_STOP = {"event": "listen_stop", "device_id": "fire-01", "event_id": "legacy-stop-001",
               "protocol_version": "0.2", "session_id": "session-legacy",
               "boot_id": "boot-legacy", "turn_id": "turn-legacy"}
# Captured through the real begin_event BEFORE serial_audio existed (2026-11-27).
LEGACY_STOP_DIGEST = "ba13fdfebcccefeede857925a160b1be7290e4ee9997d3d83cd8265ff2288aec"


class VoiceProbe(MockProvider):
    def __init__(self):
        self.calls = {"transcribe": 0, "dialog": 0, "speech": 0, "generate": 0, "review": 0}
        self.histories = []

    async def transcribe(self, data):
        self.calls["transcribe"] += 1
        assert validate_wav(data) == 8000
        return QUIZ_REQUEST

    async def dialog(self, history, context, connection=None):
        self.calls["dialog"] += 1
        self.histories.append(copy.deepcopy(history))
        return DialogReply(message="Jeg kan lage et quizspill med poeng og tre knapper.",
                           clarification_needed=False, build_summary=QUIZ_REQUEST,
                           display_text="Quizspillet er planlagt")

    async def speech(self, text):
        self.calls["speech"] += 1
        yield PCM[:1000]
        yield PCM[1000:]

    async def generate(self, *args, **kwargs):
        self.calls["generate"] += 1
        raise AssertionError("Voice handoff must not build without BUILD")

    async def review(self, *args, **kwargs):
        self.calls["review"] += 1
        raise AssertionError("Voice handoff must not review without BUILD")


@contextmanager
def environment(tmp_path, *, speech=False, settings=None):
    settings = settings or configured(tmp_path, fire_audio_enabled=True, fire_speech_enabled=speech,
                                     fire_public_enabled=True, fire_device_host=PUBLIC_HOST,
                                     fire_web_origin="https://studio.example.org",
                                     fire_access_issuer="https://test.cloudflareaccess.com",
                                     fire_access_audience="test-studio")
    provider = VoiceProbe()
    with TestClient(create_app(settings, provider), base_url="https://" + PUBLIC_HOST) as client:
        yield SimpleNamespace(client=client, service=client.app.state.backend,
                              provider=provider, settings=settings)


def observed(device, kind, predicate=lambda packet: True):
    found = next((packet for packet in device.events
                  if packet["type"] == kind and predicate(packet)), None)
    return found or device.until(kind, predicate)


def acknowledged(device, sent):
    return observed(device, "event_ack", lambda packet: packet["event_id"] == sent["event_id"])


def outcome(device, sent):
    for _ in range(100):
        packet = device.socket.receive_json()
        device.events.append(packet)
        if packet["type"] == "error" or (packet["type"] == "event_ack" and packet.get("event_id") == sent["event_id"]):
            return packet
    raise AssertionError("No bounded event outcome")


@contextmanager
def connected(env, *, resume=None, counter=0, boot="boot-serial", device_id="fire-01", same=True):
    with env.client.websocket_connect("/ws/device", headers=headers(OTHER) if device_id == "fire-02" else headers()) as socket:
        bounded_receive(socket)
        peer = Device(socket, device_id=device_id, boot_id=boot)
        peer.counter = counter
        sent = peer.send("session_start", target="device", capabilities=CAPS,
                         **({"resume_session_id": resume} if resume else {}))
        started = peer.until("session_started")
        peer.session_id = started["session_id"]
        enabled = env.service.settings.fire_audio_enabled and CAPS["audio_input"]
        assert ("serial_audio_v1" in started["backend_features"]) == enabled
        acknowledged(peer, sent)
        if resume:
            snapshot = observed(peer, "session_snapshot")
            assert ("serial_audio_v1" in snapshot["backend_features"]) == enabled
        if resume and same:
            assert peer.session_id == resume
        yield peer, started


def grant_input(env, *, serial=True):
    with connected(env) as (peer, started):
        selected = peer.send("app_select", app_mode="new")
        chosen = peer.until("app_selected")
        acknowledged(peer, selected)
        turn = "turn-serial-input"
        acknowledged(peer, peer.send("listen_start", turn_id=turn))
        stopped = peer.send("listen_stop", turn_id=turn, serial_audio=serial)
        result = acknowledged(peer, stopped)["result"]
        if serial:
            assert result["turn_id"] == turn and result["serial_audio"] is True
            assert 19 <= result["commit_expires_at"] - result["upload_expires_at"] <= 21
        assert env.provider.calls == {name: 0 for name in env.provider.calls}
        return SimpleNamespace(sid=peer.session_id, boot=peer.boot_id, turn=turn,
                               project=chosen["project_id"], stop_result=result)


def post_input(env, grant, data=None, *, token=None):
    wire = wav_data() if data is None else data
    auth = headers() if token is None else headers(token)
    return env.client.post(f"/sessions/{grant.sid}/audio/{grant.turn}", content=wire,
                           headers={**auth, "Content-Type": "audio/wav"})


def staged_input(env, grant):
    wire = wav_data()
    response = post_input(env, grant, wire)
    assert response.status_code == 202, response.text
    staged = response.json()
    assert staged["status"] == "staged" and staged["turn_id"] == grant.turn
    assert staged["sha256"] == hashlib.sha256(wire).hexdigest()
    assert staged["expires_at"] == grant.stop_result["commit_expires_at"]
    assert env.provider.calls == {name: 0 for name in env.provider.calls}
    return staged


def no_builds(env):
    assert env.service.store.list("builds") == []
    assert env.service.store.list("packages") == []
    assert env.service.store.list("commands") == []
    assert env.provider.calls["generate"] == env.provider.calls["review"] == 0


def commit_input(env, peer, grant, staged, *, event_id="serial-commit-stable"):
    sent = peer.send("audio_input_commit", turn_id=grant.turn, sha256=staged["sha256"], event_id=event_id)
    ack = acknowledged(peer, sent)
    assert ack["status"] == "accepted", ack
    transcript = observed(peer, "transcript", lambda packet: packet.get("turn_id") == grant.turn)
    proposal = observed(peer, "build_proposal", lambda packet: packet.get("turn_id") == grant.turn)
    assert transcript["text"] == QUIZ_REQUEST
    assert proposal["project_id"] == grant.project and proposal["proposal_id"]
    assert env.provider.calls["transcribe"] == env.provider.calls["dialog"] == 1
    assert any(row["role"] == "user" and row["content"] == QUIZ_REQUEST for row in env.provider.histories[0])
    no_builds(env)
    return sent, proposal


def finish_task(env, name, sid):
    async def finish():
        task = getattr(env.service.session(sid), name)
        if task:
            await asyncio.wait_for(asyncio.shield(task), timeout=3)
    env.client.portal.call(finish)


def move_clock(monkeypatch, target):
    real = audio_module.time
    delta = target - real.time()
    clock = SimpleNamespace(time=lambda: real.time() + delta,
                            monotonic=lambda: real.monotonic() + delta)
    # Module variables only; never alter Python's global clock or event-loop timers.
    for module in (audio_module, protocol, service_module):
        monkeypatch.setattr(module, "time", clock)


def test_old_event_digest_and_false_default_stay_byte_compatible():
    class Records:
        def get(self, *args):
            raise FileNotFoundError()
        def put(self, *args, **kwargs):
            pass
    service = SimpleNamespace(store=Records())
    for fields in ({}, {"serial_audio": False}):
        record, _ = begin_event(service, DeviceEvent(**LEGACY_STOP, **fields))
        assert record["digest"] == LEGACY_STOP_DIGEST
    record, _ = begin_event(service, DeviceEvent(**LEGACY_STOP, serial_audio=True))
    assert record["digest"] != LEGACY_STOP_DIGEST


def test_public_new_app_voice_stages_without_ai_then_commits_once(tmp_path):
    with environment(tmp_path) as env:
        grant = grant_input(env)
        staged = staged_input(env, grant)
        repeat = post_input(env, grant)
        assert repeat.status_code == 202 and repeat.json()["sha256"] == staged["sha256"]
        assert env.provider.calls["transcribe"] == 0
        with connected(env, resume=grant.sid, counter=100) as (peer, started):
            assert started["project_id"] == grant.project
            commit_input(env, peer, grant, staged)
            assert env.provider.calls["speech"] == 0


def test_conflicting_audio_bytes_cannot_replace_staged_input_or_start_ai(tmp_path):
    with environment(tmp_path) as env:
        grant = grant_input(env)
        staged = staged_input(env, grant)
        changed = post_input(env, grant, wav_data(frequency=500))
        assert changed.status_code in {400, 409}
        with connected(env, resume=grant.sid, counter=100) as (peer, _):
            result = outcome(peer, peer.send("audio_input_commit", turn_id=grant.turn, sha256=staged["sha256"]))
            assert result["type"] == "error", result
            assert env.provider.calls == {name: 0 for name in env.provider.calls}
            no_builds(env)


@pytest.mark.parametrize("wrong", ["owner", "session", "boot", "turn", "sha256"])
def test_commit_rejects_wrong_scope_before_any_provider(tmp_path, wrong):
    with environment(tmp_path) as env:
        grant = grant_input(env)
        staged = staged_input(env, grant)
        with connected(env, resume=grant.sid, counter=100) as (peer, _):
            fields = {"turn_id": grant.turn, "sha256": staged["sha256"]}
            fields.update({"owner": {"device_id": "fire-02"}, "session": {"session_id": "session-other"},
                           "boot": {"boot_id": "boot-other"}, "turn": {"turn_id": "turn-other"},
                           "sha256": {"sha256": "0" * 64}}[wrong])
            before = copy.deepcopy(env.service.store.list("audio"))
            rejected = outcome(peer, peer.send("audio_input_commit", **fields))
            assert rejected["type"] == "error", rejected
            assert env.service.store.list("audio") == before
            assert env.provider.calls == {name: 0 for name in env.provider.calls}
            no_builds(env)


@pytest.mark.parametrize("invalidator", ["commit-expiry", "cancel", "new-project"])
def test_staged_input_is_not_a_reusable_or_renewable_ai_grant(tmp_path, monkeypatch, invalidator):
    with environment(tmp_path) as env:
        grant = grant_input(env)
        staged = staged_input(env, grant)
        with connected(env, resume=grant.sid, counter=100) as (peer, _):
            if invalidator == "commit-expiry":
                move_clock(monkeypatch, staged["expires_at"] + 1)
            elif invalidator == "cancel":
                acknowledged(peer, peer.send("cancel_turn", turn_id=grant.turn))
            else:
                selected = peer.send("app_select", app_mode="new")
                chosen = peer.until("app_selected")
                acknowledged(peer, selected)
                assert chosen["project_id"] != grant.project
            rejected = outcome(peer, peer.send("audio_input_commit", turn_id=grant.turn, sha256=staged["sha256"]))
            assert rejected["type"] == "error", rejected
            assert env.provider.calls == {name: 0 for name in env.provider.calls}
            no_builds(env)


@pytest.mark.parametrize("missing", ["opt-in", "upload-expiry", "owner"])
def test_upload_cannot_bypass_serial_admission(tmp_path, monkeypatch, missing):
    with environment(tmp_path) as env:
        grant = grant_input(env, serial=missing != "opt-in")
        if missing == "upload-expiry":
            move_clock(monkeypatch, grant.stop_result["upload_expires_at"] + 1)
        response = post_input(env, grant, token=OTHER if missing == "owner" else None)
        if missing == "opt-in" and response.status_code == 202:
            assert response.json()["status"] == "cancelled"
        else:
            assert response.status_code in {400, 403, 408, 409, 410}, response.text
        assert env.provider.calls == {name: 0 for name in env.provider.calls}
        no_builds(env)


def test_audio_policy_revoked_before_commit_never_consumes_or_starts_ai(tmp_path):
    with environment(tmp_path) as env:
        grant = grant_input(env)
        staged = staged_input(env, grant)
        env.service.settings.fire_audio_enabled = False
        with connected(env, resume=grant.sid, counter=100) as (peer, _):
            before = copy.deepcopy(env.service.store.list("audio"))
            handoff = copy.deepcopy(env.service.audio.serial_turns.get(grant.sid))
            rejected = outcome(peer, peer.send("audio_input_commit", turn_id=grant.turn, sha256=staged["sha256"]))
            assert rejected["type"] == "error" and rejected["code"] == "backend_audio_disabled", rejected
            assert env.service.store.list("audio") == before
            assert env.service.audio.serial_turns.get(grant.sid) == handoff
            assert env.provider.calls == {name: 0 for name in env.provider.calls}
            no_builds(env)


def test_staged_input_cannot_commit_after_cold_backend_restart(tmp_path):
    with environment(tmp_path) as env:
        grant = grant_input(env)
        staged = staged_input(env, grant)
        settings = env.settings
    with environment(tmp_path, settings=settings) as restarted:
        with connected(restarted, resume=grant.sid, counter=100, same=False) as (peer, _):
            rejected = outcome(peer, peer.send("audio_input_commit", turn_id=grant.turn, sha256=staged["sha256"]))
            assert rejected["type"] == "error", rejected
            assert restarted.provider.calls == {name: 0 for name in restarted.provider.calls}
            no_builds(restarted)


def test_lost_commit_ack_and_exact_event_replay_never_retranscribe(tmp_path):
    with environment(tmp_path) as env:
        grant = grant_input(env)
        staged = staged_input(env, grant)
        with connected(env, resume=grant.sid, counter=100) as (peer, _):
            sent = peer.send("audio_input_commit", turn_id=grant.turn,
                             sha256=staged["sha256"], event_id="commit-lost-ack")
            # Do not consume its ACK. Wait on the real bounded input task so the
            # finished operation is known before this socket is deliberately lost.
            async def completed():
                async with asyncio.timeout(3):
                    while env.service.session(grant.sid).input_task is None:
                        await asyncio.sleep(0)
                    await asyncio.shield(env.service.session(grant.sid).input_task)
            env.client.portal.call(completed)
        before = env.provider.calls.copy()
        with connected(env, resume=grant.sid, counter=200) as (peer, _):
            peer.socket.send_json(sent)
            duplicate = acknowledged(peer, sent)
            assert duplicate["status"] == "duplicate", duplicate
            assert env.provider.calls == before
            fresh = peer.send("audio_input_commit", turn_id=grant.turn, sha256=staged["sha256"])
            result = outcome(peer, fresh)
            assert result["type"] == "error" or result.get("result", {}).get("status") in {"already_committed", "completed"}
            assert env.provider.calls == before
            no_builds(env)


def ready_output(env):
    grant = grant_input(env)
    staged = staged_input(env, grant)
    with connected(env, resume=grant.sid, counter=100) as (peer, _):
        _, proposal = commit_input(env, peer, grant, staged)
        clip = observed(peer, "audio_ready", lambda packet: packet.get("turn_id") == grant.turn)
        finish_task(env, "speech_task", grant.sid)
        assert clip["serial_audio"] is True
        assert clip["fetch_expires_at"] <= clip["expires_at"]
        assert clip["fetch_expires_at"] <= env.service.store.get("audio", clip["audio_id"])["ready_at"] + 35
        assert env.provider.calls["speech"] == 1
        return grant, clip, proposal


def test_finished_output_survives_quiet_get_resume_and_existing_playback_receipts(tmp_path):
    with environment(tmp_path, speech=True) as env:
        grant, clip, proposal = ready_output(env)
        before = env.provider.calls.copy()
        response = env.client.get(clip["download_url"], headers=headers())
        assert response.status_code == 200 and response.content == PCM
        assert hashlib.sha256(response.content).hexdigest() == clip["sha256"]
        with connected(env, resume=grant.sid, counter=200) as (peer, _):
            assert env.service.session(grant.sid).proposal_id == proposal["proposal_id"]
            acknowledged(peer, peer.send("audio_playback_started", audio_id=clip["audio_id"], turn_id=grant.turn))
            finished = peer.send("audio_playback_finished", audio_id=clip["audio_id"], turn_id=grant.turn,
                                 event_id="playback-finished-stable")
            acknowledged(peer, finished)
            peer.socket.send_json(finished)
            assert observed(peer, "event_ack", lambda packet: packet.get("event_id") == finished["event_id"] and packet.get("status") == "duplicate")
            assert env.provider.calls == before
            no_builds(env)


@pytest.mark.parametrize("invalidator", ["expiry", "cancel"])
def test_output_quiet_fetch_does_not_extend_expiry_or_survive_cancel(tmp_path, monkeypatch, invalidator):
    with environment(tmp_path, speech=True) as env:
        grant, clip, _ = ready_output(env)
        before = env.provider.calls.copy()
        if invalidator == "expiry":
            move_clock(monkeypatch, clip["fetch_expires_at"] + 1)
        else:
            with connected(env, resume=grant.sid, counter=200) as (peer, _):
                acknowledged(peer, peer.send("cancel_turn", turn_id=grant.turn))
        response = env.client.get(clip["download_url"], headers=headers())
        assert response.status_code in {400, 404, 409, 410}
        assert env.provider.calls == before
        no_builds(env)

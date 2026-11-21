import asyncio
import io
import math
import struct
import time
import wave

import pytest
from fastapi.testclient import TestClient

from fire_backend.ai import MockProvider
from fire_backend.app import create_app
from fire_backend.audio import validate_wav, prepare_recording

from test_device_protocol import Device, configured, headers, OTHER


def wav_data(rate=16000, channels=1, width=2, seconds=0.5, amplitude=1800, frequency=440):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(width)
        file.setframerate(rate)
        samples = b"".join(struct.pack("<h", int(amplitude * math.sin(2 * math.pi * frequency * i / rate))) for i in range(int(rate * seconds)))
        file.writeframes(samples * channels if width == 2 else bytes(int(rate * seconds) * channels))
    return output.getvalue()


def recording(device, turn_id="turn-001"):
    device.ack(device.send("listen_start", turn_id=turn_id))
    device.ack(device.send("listen_stop", turn_id=turn_id))
    return turn_id


def test_native_ready_does_not_fake_an_active_microphone(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_audio_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            started = device.start()
            assert started["state"] == "idle" and started["activity"] == "idle"
            device.ack(device.send("listen_start", turn_id="turn-real"))
            session = client.app.state.backend.session(device.session_id)
            assert session.state == "listening" and session.activity == "listening"
            device.ack(device.send("cancel_turn"))
            assert session.state == "idle" and session.activity == "idle"


def test_adc_dc_bias_is_removed_with_bounded_gain_and_no_content_in_diagnostics():
    raw = wav_data(amplitude=100)
    with wave.open(io.BytesIO(raw), "rb") as handle:
        values = struct.unpack('<' + 'h'*handle.getnframes(), handle.readframes(handle.getnframes()))
    output = io.BytesIO()
    with wave.open(output, 'wb') as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
        handle.writeframes(struct.pack('<'+'h'*len(values), *(x+14000 for x in values)))
    normalized, metrics = prepare_recording(output.getvalue())
    assert metrics['dc_offset'] == 14000 and metrics['gain'] == 8
    assert metrics['duration_seconds'] == 0.5 and all(isinstance(v, (int, float)) for v in metrics.values())
    with wave.open(io.BytesIO(normalized), 'rb') as handle:
        result = struct.unpack('<'+'h'*handle.getnframes(), handle.readframes(handle.getnframes()))
    assert abs(sum(result)/len(result)) < 1 and max(result) <= 800


def test_audio_round_trip_is_scoped_bounded_and_deduplicated(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_audio_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            turn_id = recording(device)
            path = f"/sessions/{device.session_id}/audio/{turn_id}"
            data = wav_data()
            assert len(data) > 8192
            response = client.post(path, content=data, headers={**headers(), "Content-Type": "audio/wav"})
            assert response.status_code == 202
            assert device.until("transcript")["mode"] == "mock"
            proposal = device.until("build_proposal")
            clip = device.until("audio_ready")
            assert clip["synthetic"] is True and clip["mode"] == "mock"
            assert clip["sample_rate"] == 24000 and clip["size_bytes"] <= 1440000
            response = client.get(clip["download_url"], headers=headers())
            assert response.status_code == 200 and len(response.content) == clip["size_bytes"]
            assert response.headers["x-audio-format"] == "pcm_s16le"
            assert client.get(clip["download_url"], headers=headers(OTHER)).status_code == 403
            repeat = client.post(path, content=data, headers={**headers(), "Content-Type": "audio/wav"})
            assert repeat.status_code == 202 and repeat.json()["duplicate"] is True
            changed = client.post(path, content=wav_data(frequency=500), headers={**headers(), "Content-Type": "audio/wav"})
            assert changed.status_code == 400
            device.ack(device.send("audio_playback_started", audio_id=clip["audio_id"], turn_id=turn_id))
            assert client.get(f"/sessions/{device.session_id}", headers=headers()).json()["activity"] == "speaking"
            device.ack(device.send("audio_playback_finished", audio_id=clip["audio_id"], turn_id=turn_id))
            assert client.get(clip["download_url"], headers=headers()).status_code == 404
            assert client.app.state.backend.store.list("builds") == []
            assert client.app.state.backend.session(device.session_id).proposal_id == proposal["proposal_id"]
            assert list((tmp_path / "audio").glob("*.wav")) == []
        assert client.post("/session/start", content=b"x" * 9000, headers=headers()).status_code == 413


@pytest.mark.parametrize("data", [b"invalid", wav_data(amplitude=0), wav_data(rate=8000), wav_data(channels=2), wav_data(width=1), wav_data(seconds=0.01), wav_data()[:-8]])
def test_invalid_audio_rejected(data):
    with pytest.raises(ValueError):
        validate_wav(data)


def test_large_audio_authentication_and_chunk_limits(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_audio_enabled=True))) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            turn_id = recording(device)
            path = f"/sessions/{device.session_id}/audio/{turn_id}"
            assert client.post(path, content=b"x" * 600000, headers={"Content-Type": "audio/wav"}).status_code == 401
            assert client.post(path, content=b"x" * 600000, headers={**headers(), "Content-Type": "audio/wav"}).status_code == 413
            chunks = (b"x" * 4096 for _ in range(130))
            assert client.post(path, content=chunks, headers={**headers(), "Content-Type": "audio/wav"}).status_code == 413
            assert client.post(path, content=wav_data(), headers={**headers(OTHER), "Content-Type": "audio/wav"}).status_code == 403
            assert client.post(path, content=wav_data(), headers=headers()).status_code == 415
            assert client.app.state.backend.store.list("builds") == []


class SlowTranscribe(MockProvider):
    async def transcribe(self, data):
        await asyncio.sleep(60)


async def test_empty_transcript_reports_measured_capture_gaps_without_inventing_words(tmp_path):
    from fire_backend.audio import AudioManager
    from fire_backend.models import SessionStart
    from fire_backend.service import Backend
    from test_device_protocol import CAPS
    class Empty(MockProvider):
        async def transcribe(self, data):
            return ""
    service = Backend(configured(tmp_path, fire_audio_enabled=True), Empty())
    service.audio = AudioManager(service)
    try:
        session = await service.start(SessionStart(device_id="fire-01", protocol_version="0.2", target="device",
            boot_id="boot-gaps", capabilities=CAPS), principal="fire-01")
        session.turn_id, session.activity = "turn-gaps", "processing"
        session.audio_status = {"recording_wall_seconds": 5.0}
        async def stream():
            yield wav_data(seconds=1)
        await service.audio.receive(session, "turn-gaps", stream())
        await session.input_task
        assert session.audio_status["capture_gap_suspected"] and session.audio_status["capture_fraction"] == 0.2
        assert "ufullstendig" in session.last_error and session.state == "failed"
        assert not session.history and not service.store.list("builds")
    finally:
        await service.close()


def test_cancel_transcription_cleans_recording_and_never_builds(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_audio_enabled=True), SlowTranscribe())) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            turn_id = recording(device)
            path = f"/sessions/{device.session_id}/audio/{turn_id}"
            assert client.post(path, content=wav_data(), headers={**headers(), "Content-Type": "audio/wav"}).status_code == 202
            device.ack(device.send("cancel_turn"))
            session = client.app.state.backend.session(device.session_id)
            assert session.proposal_id is None and session.state == "idle"
            assert list((tmp_path / "audio").glob("*.wav")) == []
            assert client.app.state.backend.store.list("builds") == []


class FailedSpeech(MockProvider):
    async def speech(self, text):
        raise ValueError("Speech unavailable")
        yield b""


@pytest.mark.parametrize("complete", [True, False])
async def test_speech_accepts_fragmented_samples_but_rejects_incomplete_final_sample(tmp_path, complete):
    from fire_backend.audio import AudioManager
    from fire_backend.models import SessionStart
    from fire_backend.service import Backend
    from test_device_protocol import CAPS
    class Fragmented(MockProvider):
        async def speech(self, text):
            yield b"\x01"
            yield b"\x02\x03"
            if complete:
                yield b"\x04"
    service = Backend(configured(tmp_path, fire_audio_enabled=True), Fragmented())
    service.audio = AudioManager(service)
    try:
        session = await service.start(SessionStart(device_id="fire-01", protocol_version="0.2", target="device",
            boot_id="boot-fragments", capabilities=CAPS), principal="fire-01")
        session.turn_id = "turn-fragments"
        await service.text(session, "Lag en sirkel")
        await session.speech_task
        if complete:
            item, path = service.audio.clip(session.audio_id, "fire-01")
            assert path.read_bytes() == b"\x01\x02\x03\x04" and item["size_bytes"] == 4
        else:
            assert session.audio_id is None and not list((tmp_path/"audio").glob("*.pcm"))
        assert session.proposal_id and not service.store.list("builds")
    finally:
        await service.close()


def test_speech_failure_retains_text_and_build_proposal(tmp_path):
    with TestClient(create_app(configured(tmp_path, fire_audio_enabled=True), FailedSpeech())) as client:
        with client.websocket_connect("/ws/device", headers=headers()) as socket:
            device = Device(socket)
            device.start()
            turn_id = recording(device)
            client.post(f"/sessions/{device.session_id}/audio/{turn_id}", content=wav_data(), headers={**headers(), "Content-Type": "audio/wav"})
            device.until("transcript")
            proposal = device.until("build_proposal")
            device.until("audio_error")
            session = client.app.state.backend.session(device.session_id)
            assert session.proposal_id == proposal["proposal_id"]
            assert session.state == "awaiting_build_confirmation"
            assert list((tmp_path / "audio").glob("*.pcm")) == []
            assert list((tmp_path / "audio").glob("*.part")) == []

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
from fire_backend.audio import validate_wav

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
            assert session.proposal_id is None and session.state == "listening"
            assert list((tmp_path / "audio").glob("*.wav")) == []
            assert client.app.state.backend.store.list("builds") == []


class FailedSpeech(MockProvider):
    async def speech(self, text):
        raise ValueError("Speech unavailable")
        yield b""


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

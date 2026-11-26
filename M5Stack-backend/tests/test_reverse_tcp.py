"""Real loopback TCP/HTTP/WebSocket through a simulated FIRE listener."""
import asyncio
import base64
import hashlib
import json
import os
import struct
from contextlib import asynccontextmanager

import httpx
import pytest

from fire_backend.desktop_config import DesktopConfig, DesktopStore
from fire_backend.desktop_runtime import DesktopRuntime
from fire_backend.reverse_tcp import BridgeFailure, ReverseTCP, Slot, fire_address
from fire_backend.builds import verify_archive
from test_desktop import MemoryVault
from test_device_protocol import configured, CAPS, ADMIN, TOKEN, OTHER
from test_audio import wav_data


class FireListener:
    def __init__(self, reply=None, coalesced=b"", fragmented=False):
        self.reply = reply if reply is not None else {"type": "reverse_ready", "version": 1, "device_id": "fire-01"}
        self.coalesced, self.fragmented = coalesced, fragmented
        self.connections, self.prefaces, self.tasks = [], [], set()
        self.queue = asyncio.Queue()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.accept, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.connections.append(writer)
        try:
            self.prefaces.append(json.loads(await reader.readline()))
            answer = self.reply if isinstance(self.reply, bytes) else json.dumps(self.reply).encode() + b"\n"
            if self.fragmented:
                writer.write(answer[:7]); await writer.drain(); await asyncio.sleep(0.01)
                writer.write(answer[7:] + self.coalesced)
            else:
                writer.write(answer + self.coalesced)
            await writer.drain()
            await self.queue.put((reader, writer))
            await asyncio.Future()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            self.tasks.discard(task)

    async def take(self):
        return await asyncio.wait_for(self.queue.get(), 5)

    async def __aexit__(self, *args):
        self.server.close()
        for writer in self.connections:
            writer.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.wait_for(self.server.wait_closed(), 5)


async def close_writer(writer):
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


@asynccontextmanager
async def tcp_server(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close(); await server.wait_closed()


def bridge_settings(tmp_path, fire_port, backend_port):
    return configured(tmp_path, fire_backend_port=backend_port, fire_desktop_enabled=True, fire_audio_enabled=True,
                      fire_reverse_host="127.0.0.1", fire_reverse_port=fire_port, fire_reverse_device_id="fire-01")


@pytest.mark.asyncio
async def test_coalesced_or_fragmented_ready_preserves_binary_data_and_half_close(tmp_path):
    payload = bytes(range(256)) * 1500
    responses = []
    async def backend(reader, writer):
        request = await reader.read()  # Wait for the FIRE half-close.
        assert request == b"GET /half-close HTTP/1.1\r\n\r\n"
        writer.write(payload); await writer.drain()
        await close_writer(writer)
    async with tcp_server(backend) as port:
        async with FireListener(coalesced=b"GET /half-close HTTP/1.1\r\n\r\n", fragmented=True) as fire:
            bridge = ReverseTCP(bridge_settings(tmp_path, fire.port, port))
            task = asyncio.create_task(bridge._connection(Slot()))
            reader, writer = await fire.take()
            writer.write_eof(); await writer.drain()
            responses.append(await asyncio.wait_for(reader.read(), 5))
            await asyncio.wait_for(task, 5)
            assert responses == [payload]
            await close_writer(writer)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [b"invalid\n", b"x"*1025+b"\n", {"type": "reverse_failed"},
                                  {"type": "reverse_ready", "version": 2, "device_id": "fire-01"},
                                  {"type": "reverse_ready", "version": True, "device_id": "fire-01"},
                                  {"type": "reverse_ready", "version": 1, "device_id": "fire-02"}])
async def test_rejected_auth_never_connects_to_backend_or_reflects_peer_reply(tmp_path, reply):
    calls = []
    async def backend(reader, writer):
        calls.append(True)
        await close_writer(writer)
    async with tcp_server(backend) as port:
        async with FireListener(reply=reply) as fire:
            bridge = ReverseTCP(bridge_settings(tmp_path, fire.port, port))
            with pytest.raises(BridgeFailure) as error:
                await bridge._connection(Slot())
            assert str(error.value) in {"invalid_reverse_ready", "authentication_rejected"}
            assert calls == []


@pytest.mark.asyncio
async def test_pool_stays_at_four_idle_channels_and_replaces_a_disconnect(tmp_path):
    async with FireListener() as fire:
        bridge = ReverseTCP(bridge_settings(tmp_path, fire.port, 19876))
        await bridge.start()
        try:
            peers = [await fire.take() for _ in range(4)]
            await asyncio.sleep(0.05)
            assert bridge.status()["authenticated_channels"] == 4
            assert bridge.status()["active_channels"] == 0
            assert len(fire.prefaces) == 4
            assert all(p == {"type": "reverse_open", "version": 1, "device_id": "fire-01", "token": TOKEN} for p in fire.prefaces)
            encoded = json.dumps(bridge.status())
            assert TOKEN not in encoded and ADMIN not in encoded and OTHER not in encoded
            await close_writer(peers[0][1])
            await fire.take()
            assert len(fire.prefaces) == 5
        finally:
            async with asyncio.timeout(3):
                await bridge.close()
        assert not bridge.tasks and bridge.status()["state"] == "stopped"


@pytest.mark.asyncio
async def test_completed_reverse_ready_does_not_swallow_external_cancellation(tmp_path, monkeypatch):
    """Reproduce 3.11's completed-inner wait_for race without TCP timing."""
    task = None
    class Reader:
        async def readuntil(self, _separator):
            # With wait_for this runs in its inner task: cancellation is queued
            # before the completed-read waiter can resume the outer connection.
            asyncio.get_running_loop().call_soon(task.cancel)
            return b'{"type":"reverse_ready","version":1,"device_id":"fire-01"}\n'
        async def read(self, _size):
            await asyncio.Future()
    class Writer:
        closed = False
        def get_extra_info(self, _name):return None
        def write(self, _data):pass
        async def drain(self):pass
        def close(self):self.closed = True
        async def wait_closed(self):pass
    writer = Writer()
    async def connect(*_args, **_kwargs):return Reader(), writer
    monkeypatch.setattr(asyncio, 'open_connection', connect)
    bridge = ReverseTCP(bridge_settings(tmp_path, 19875, 19876))
    task = asyncio.create_task(bridge._connection(Slot()))
    try:
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done, 'Completed reverse_ready swallowed external cancellation'
        assert task.cancelled() and writer.closed
    finally:
        # Bound failure cleanup without cancelling the test's observation wait.
        if not task.done():task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("host", ["http://10.5.1.163", "10.5.1.163:8766", "0.0.0.0", "169.254.1.2", "8.8.8.8", "239.1.1.1"])
def test_fire_target_must_be_a_local_ipv4_address(host):
    with pytest.raises(ValueError):
        fire_address(host)


def test_reverse_config_is_opt_in_and_preserves_credentials(tmp_path):
    store = DesktopStore(tmp_path, MemoryVault())
    token = store.secret("device/m5stack-fire-01")
    store.save(store.config, api_key="sk-test-preserved-private")
    assert store.settings().fire_reverse_host == ""
    config = store.config.model_copy(update={"transport": "reverse_tcp", "reverse_host": "10.5.1.163",
                                           "reverse_device_id": "m5stack-fire-01"})
    store.save(config)
    saved = store.settings()
    assert saved.fire_reverse_host == "10.5.1.163" and saved.fire_reverse_port == 8766
    assert saved.device_tokens()[saved.fire_reverse_device_id] == token
    assert store.secret("openai") == "sk-test-preserved-private"
    assert token not in store.path.read_text()
    with pytest.raises(ValueError):
        DesktopConfig(transport="reverse_tcp")


class WireDevice:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.sid, self.counter = None, 0
        self.boot = "boot-reverse-test"

    async def frame(self, data, opcode=1):
        mask = os.urandom(4)
        header = bytes([0x80|opcode, 0x80|len(data)]) if len(data) < 126 else bytes([0x80|opcode, 0xFE])+struct.pack("!H", len(data))
        self.writer.write(header+mask+bytes(value ^ mask[i%4] for i, value in enumerate(data)))
        await self.writer.drain()

    async def send(self, event, **values):
        self.counter += 1
        event_id = "reverse-test-" + str(self.counter)
        await self.frame(json.dumps({"type": "device_event", "protocol_version": "0.2", "device_id": "fire-01",
            "boot_id": self.boot, "event_id": event_id, "event": event,
            **({"session_id": self.sid} if self.sid else {}), **values}).encode())
        return event_id

    async def until(self, kind, event_id=None):
        async with asyncio.timeout(30):
            while True:
                first = await self.reader.readexactly(2)
                opcode, length = first[0]&15, first[1]&127
                if length == 126:
                    length = struct.unpack("!H", await self.reader.readexactly(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", await self.reader.readexactly(8))[0]
                assert length <= 8192 and not first[1]&128
                data = await self.reader.readexactly(length)
                if opcode == 9:
                    await self.frame(data, 10); continue
                assert opcode == 1
                message = json.loads(data)
                assert message["type"] != "error", message
                if message["type"] == kind and (event_id is None or message.get("event_id") == event_id):
                    return message


async def raw_http(fire, request):
    reader, writer = await fire.take()
    for offset in range(0, len(request), 4096):
        writer.write(request[offset:offset+4096]); await writer.drain()
    response = await asyncio.wait_for(reader.read(), 15)
    await close_writer(writer)
    head, body = response.split(b"\r\n\r\n", 1)
    return head, body


@pytest.mark.asyncio
async def test_reverse_websocket_package_run_receipts_and_large_wav_upload(tmp_path):
    async with FireListener() as fire:
        # Pick a free local backend port without changing the user's running app.
        import socket
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
        runtime = DesktopRuntime()
        runtime.start(bridge_settings(tmp_path, fire.port, port))
        try:
            async with asyncio.timeout(8):
                while not runtime.ready:
                    await asyncio.sleep(0.02)
            reader, writer = await fire.take()
            key = base64.b64encode(os.urandom(16)).decode()
            writer.write((f"GET /ws/device HTTP/1.1\r\nHost: pc:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer {TOKEN}\r\n\r\n").encode())
            await writer.drain()
            response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            assert response.startswith(b"HTTP/1.1 101")
            device = WireDevice(reader, writer)
            await device.send("session_start", target="device", capabilities={**CAPS, "audio_input": True, "audio_output": False})
            started = await device.until("session_started")
            device.sid = started["session_id"]
            assert not started["physical_verified"]
            assert (await device.until("capability_status"))["code"] == "audio_output_unavailable"
            headers = {"Authorization": "Bearer "+ADMIN}
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers, trust_env=False) as http:
                (await http.post(f"/desktop/sessions/{device.sid}/text", json={"text": "Lag en sirkel"})).raise_for_status()
                proposal = await device.until("build_proposal")
                (await http.post("/build/confirm", json={"session_id": device.sid, "proposal_id": proposal["proposal_id"],
                                                        "event_id": "confirm-reverse-build"})).raise_for_status()
                ready = await device.until("package_ready")
                offer = await device.until("install_request")
                request = (f"GET {offer['download_url']} HTTP/1.1\r\nHost: pc\r\nAuthorization: Bearer {TOKEN}\r\nConnection: close\r\n\r\n").encode()
                head, body = await raw_http(fire, request)
                assert head.startswith(b"HTTP/1.1 200") and len(body) == offer["size_bytes"]
                # Current FIRE searches for this exact case on the wire.
                assert b"\r\nContent-Length: " + str(len(body)).encode() in head
                assert (ready["manifest"]["id"] + "-v" + ready["manifest"]["version"] + ".zip").encode() in head
                assert hashlib.sha256(body).hexdigest() == offer["archive_sha256"]
                archive = tmp_path / "received.zip"; archive.write_bytes(body)
                verify_archive(archive, ready["manifest"], offer["archive_sha256"])
                partial = (f"GET {offer['download_url']} HTTP/1.1\r\nHost: pc\r\nAuthorization: Bearer {TOKEN}\r\n"
                           "Range: bytes=0-99\r\nConnection: close\r\n\r\n").encode()
                range_head, range_body = await raw_http(fire, partial)
                assert range_head.startswith(b"HTTP/1.1 206") and range_body == body[:100]
                assert b"\r\nContent-Length: 100" in range_head
                await device.until("event_ack", await device.send("device_install_result", package_id=offer["package_id"],
                    install_id=offer["install_id"], archive_sha256=offer["archive_sha256"], status="ok"))
                (await http.post("/run/confirm", json={"session_id": device.sid, "package_id": offer["package_id"],
                                                      "event_id": "confirm-reverse-run"})).raise_for_status()
                run = await device.until("run_request")
                for event in ("app_started", "app_healthy"):
                    await device.until("event_ack", await device.send(event, package_id=offer["package_id"], run_id=run["run_id"]))
                await device.until("event_ack", await device.send("app_stopped", package_id=offer["package_id"], run_id=run["run_id"], reason="completed"))
                for event in ("listen_start", "listen_stop"):
                    await device.until("event_ack", await device.send(event, turn_id="turn-reverse"))
                wav = wav_data(seconds=3)
                request = (f"POST /sessions/{device.sid}/audio/turn-reverse HTTP/1.1\r\nHost: pc\r\nAuthorization: Bearer {TOKEN}\r\n"
                           f"Content-Type: audio/wav\r\nContent-Length: {len(wav)}\r\nConnection: close\r\n\r\n").encode()+wav
                head, body = await raw_http(fire, request)
                assert len(wav) > 8192 and head.startswith(b"HTTP/1.1 202")
                assert (await device.until("transcript"))["mode"] == "mock"
                await device.until("build_proposal")
                snapshot = (await http.get("/desktop/status")).json()
                assert snapshot["transport"]["mode"] == "reverse_tcp"
                assert len(snapshot["builds"]) == 1  # Audio never authorizes a build.
                assert snapshot["transport"]["bytes_from_fire"] > len(wav)
            await device.send("session_stop")
            await device.until("session_stopped")
            await close_writer(writer)
        finally:
            await asyncio.to_thread(runtime.stop)

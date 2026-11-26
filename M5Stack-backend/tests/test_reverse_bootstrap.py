"""Real loopback bridge bootstrap with a deliberately unobserved recovery reply."""
import asyncio
import base64
import inspect
import json
import os
import re
import socket
import struct
import time

import pytest
import uvicorn

from fire_backend.ai import MockProvider
from fire_backend.app import create_app
from test_device_protocol import TOKEN
from test_reverse_tcp import FireListener, WireDevice, bridge_settings, close_writer


class NoModelCalls(MockProvider):
    def __init__(self):
        self.calls = []

    def __getattribute__(self, name):
        value = super().__getattribute__(name)
        if name != 'close' and inspect.iscoroutinefunction(value):
            async def unexpected(*args, **kwargs):
                self.calls.append(name)
                raise AssertionError('Bootstrap must not call a model: ' + name)
            return unexpected
        return value


class BootstrapWire(WireDevice):
    """Existing device envelope, with small network reads and split writes."""
    def __init__(self, reader, writer, counter):
        super().__init__(reader, writer)
        self.counter, self.received = counter, []

    async def frame(self, data, opcode=1):
        mask = os.urandom(4)
        length = bytes([0x80 | len(data)]) if len(data) < 126 else b'\xfe' + struct.pack('!H', len(data))
        wire = bytes([0x80 | opcode]) + length + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(data))
        # Header/mask/JSON boundaries intentionally do not align with writes.
        for start, stop in ((0, 3), (3, 19), (19, len(wire))):
            self.writer.write(wire[start:stop])
            await self.writer.drain()
            await asyncio.sleep(0)

    async def read_exact(self, size):
        result = bytearray()
        while len(result) < size:
            result.extend(await self.reader.readexactly(min(37, size - len(result))))
        return bytes(result)

    async def until(self, kind, event_id=None):
        async with asyncio.timeout(8):
            while True:
                first = await self.read_exact(2)
                opcode, size = first[0] & 15, first[1] & 127
                assert not first[1] & 128
                if size == 126:
                    size = struct.unpack('!H', await self.read_exact(2))[0]
                elif size == 127:
                    size = struct.unpack('!Q', await self.read_exact(8))[0]
                assert size <= 8192
                data = await self.read_exact(size)
                if opcode == 9:
                    await self.frame(data, 10)
                    continue
                assert opcode == 1, 'Unexpected close before bootstrap completed'
                text = data.decode('utf-8')
                message = json.loads(text)
                # Same string/open-container/colon/comma count as fireJsonSafe.
                assert len(re.findall(r'"(?:[^"\\]|\\.)*"|[\{\[,:]', text)) <= 1024
                def depth(value):
                    children = value.values() if isinstance(value, dict) else value
                    return 1 + max((depth(v) for v in children), default=0) if isinstance(value, (dict, list)) else 0
                assert depth(message) <= 12
                assert message['type'] != 'error', message
                self.received.append(message)
                if message['type'] == kind and (event_id is None or message.get('event_id') == event_id):
                    return message


async def eventually(condition):
    async with asyncio.timeout(8):
        while not condition():
            await asyncio.sleep(0.01)


async def connect_wire(fire, port, counter):
    reader, writer = await fire.take()
    key = base64.b64encode(os.urandom(16)).decode()
    request = (f'GET /ws/device HTTP/1.1\r\nHost: pc:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
               f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer {TOKEN}\r\n\r\n').encode()
    writer.write(request[:31])
    await writer.drain()
    writer.write(request[31:])
    await writer.drain()
    response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
    assert response.startswith(b'HTTP/1.1 101')
    return BootstrapWire(reader, writer, counter)


@pytest.mark.asyncio
async def test_reverse_bootstrap_lost_recovery_reply_resumes_bound_successor(tmp_path):
    from fire_backend.api_registry import preview_capabilities
    from fire_backend.evolution_contract import EXTENSION
    # The actual native address list makes bootstrap substantially larger than
    # the legacy minimal fixture; this remains simulated capability evidence.
    caps = preview_capabilities()
    caps['hardware']['i2c_write_addresses'] = [i for i in range(8, 120) if i not in (16, 104, 117)]
    caps.update(evolution=EXTENSION, firmware_version='fire-os-1.6.0-rc4', audio_input=True, audio_output=True,
        service_methods={'wifi': ['status', 'scan'], 'bluetooth': ['scan', 'read_gatt', 'write_gatt', 'advertise', 'advertise_raw', 'close'],
                         'mic': ['level', 'record']}, service_modes={'bluetooth.scan': ['ble']})
    caps['data_engine'].update(capture_sources=['imu', 'mic', 'ble.advertisements'], capture_limits={
        'imu': {'duration_ms_max': 60000, 'max_records': 6000, 'sample_rates_hz': [50, 100]},
        'mic': {'duration_ms_max': 10000, 'max_records': 160000, 'sample_rates_hz': [8000, 16000]},
        'ble.advertisements': {'duration_ms_max': 60000, 'max_records': 6000}})
    provider = NoModelCalls()
    async with FireListener(fragmented=True) as fire:
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        assert port != 8765  # Never share the production listener or workspace.
        settings = bridge_settings(tmp_path, fire.port, port).model_copy(update={'fire_backend_host': '127.0.0.1'})
        app = create_app(settings, provider)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port,
            access_log=False, log_config=None, ws_max_size=8192, proxy_headers=False))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        peers = []
        try:
            await eventually(lambda: server.started)
            service = app.state.backend  # Same owner loop as the actual test server.
            first = await connect_wire(fire, port, 0)
            peers.append(first)
            event = await first.send('session_start', target='device', capabilities=caps)
            started = await first.until('session_started')
            await first.until('event_ack', event)
            old_id = started['session_id']
            old = service.sessions[old_id]
            await close_writer(first.writer)
            await eventually(lambda: old.disconnected_at is not None)
            old.disconnected_at = time.time() - settings.fire_session_resume_seconds - 1
            service.persist(old)

            # FIRE retains old_id: no bootstrap frame from this connection is read.
            lost = await connect_wire(fire, port, 100)
            peers.append(lost)
            lost_event = await lost.send('session_start', target='device', capabilities=caps, resume_session_id=old_id)
            await eventually(lambda: service.store.get('events', lost_event).get('status') == 'completed'
                             if service.store.path('events', lost_event).exists() else False)
            successor = service.store.get('events', lost_event)['result']['session_id']
            assert successor != old_id and lost.received == []
            await close_writer(lost.writer)

            retry = await connect_wire(fire, port, 200)
            peers.append(retry)
            event = await retry.send('session_start', target='device', capabilities=caps, resume_session_id=old_id)
            adopted = await retry.until('session_started')
            snapshot = await retry.until('session_snapshot')
            ack = await retry.until('event_ack', event)
            assert adopted['session_id'] == snapshot['session_id'] == ack['result']['session_id'] == successor
            assert len(json.dumps(adopted).encode()) > 4000
            assert adopted['capabilities'] == snapshot['capabilities']
            retry.sid = successor
            ping = await retry.send('ping')
            assert (await retry.until('pong'))['session_id'] == successor
            await retry.until('event_ack', ping)
            assert len(service.store.list('sessions')) == 2
            assert len(service.store.list('projects')) == 1
            assert service.store.list('builds') == service.store.list('commands') == service.usage.records() == []
            assert provider.calls == []
            assert service.reverse_tcp.status()['bytes_from_fire'] > 0
            assert service.reverse_tcp.status()['bytes_to_fire'] > 0
        finally:
            for peer in peers:
                await close_writer(peer.writer)
            server.should_exit = True
            await asyncio.wait_for(task, 8)
            listener.close()

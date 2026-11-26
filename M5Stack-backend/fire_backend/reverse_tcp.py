"""PC-initiated, authenticated TCP pool for the existing FIRE HTTP/WS clients.

Only device-token authentication precedes the transparent byte stream. No
provider key, admin token, payload bytes or peer error bodies are logged.
"""
import asyncio
import contextlib
from dataclasses import dataclass
import ipaddress
import json
import socket
import time


POOL_SIZE = 4
AUTH_LIMIT = 1024
CHUNK_SIZE = 8192


def fire_address(value):
    if not value:
        return ""
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        raise ValueError("Bruk FIREs IPv4-adresse, uten http:// eller port.") from None
    if not address.is_private or address.is_unspecified or address.is_multicast or address.is_link_local:
        raise ValueError("Omvendt TCP krever en lokal IPv4-adresse til FIRE.")
    return str(address)


class BridgeFailure(Exception):
    pass


@dataclass
class Slot:
    phase: str = "stopped"
    error: str = ""
    attempts: int = 0
    bytes_from_fire: int = 0
    bytes_to_fire: int = 0


class ReverseTCP:
    def __init__(self, settings):
        self.host = fire_address(settings.fire_reverse_host)
        self.port = settings.fire_reverse_port
        self.device_id = settings.fire_reverse_device_id
        self.backend_host = "::1" if settings.fire_backend_host == "::1" else "127.0.0.1"
        self.backend_port = settings.fire_backend_port
        self._token = settings.device_tokens().get(self.device_id, "")
        self.slots = [Slot() for _ in range(POOL_SIZE)]
        self.tasks = []
        self.closed = False
        if self.host:
            if not self._token or len(self._token) < 24:
                raise ValueError("Velg en lagret enhets-ID for omvendt TCP.")
            if self._token in {settings.fire_backend_token.get_secret_value(), settings.openai_api_key.get_secret_value()}:
                raise ValueError("Mobilbroen krever et eget enhetstoken.")
            if len(self._preface()) > AUTH_LIMIT:
                raise ValueError("Enhetstoken er for langt for reverse_open.")
            if self.host == self.backend_host and self.port == self.backend_port:
                raise ValueError("FIRE-porten kan ikke være backendens egen lokale port.")

    def _preface(self):
        return (json.dumps({"type": "reverse_open", "version": 1, "device_id": self.device_id,
                            "token": self._token}, separators=(",", ":")) + "\n").encode("utf-8")

    async def start(self):
        if self.host and not self.tasks:
            self.closed = False
            self.tasks = [asyncio.create_task(self._slot(slot)) for slot in self.slots]

    async def close(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        for slot in self.slots:
            slot.phase = "stopped"

    def status(self):
        authenticated = sum(s.phase in {"waiting", "relaying"} for s in self.slots)
        active = sum(s.phase == "relaying" for s in self.slots)
        error = next((s.error for s in self.slots if s.error), "")
        state = ("direct" if not self.host else "stopped" if self.closed else "ready" if authenticated
                 else "authentication_failed" if error in {"authentication_rejected", "invalid_reverse_ready"}
                 else "waiting_for_fire" if error else "connecting")
        return {"mode": "reverse_tcp" if self.host else "direct", "state": state,
                "fire_host": self.host, "fire_port": self.port, "device_id": self.device_id,
                "authenticated_channels": authenticated, "active_channels": active, "pool_size": POOL_SIZE,
                "last_error": error, "attempts": sum(s.attempts for s in self.slots),
                "bytes_from_fire": sum(s.bytes_from_fire for s in self.slots),
                "bytes_to_fire": sum(s.bytes_to_fire for s in self.slots), "physical_verified": False}

    async def _slot(self, slot):
        delay = 1
        while not self.closed:
            slot.phase, slot.error = "connecting", ""
            slot.attempts += 1
            started = time.monotonic()
            failed = False
            try:
                await self._connection(slot)
            except asyncio.CancelledError:
                raise
            except BridgeFailure as error:
                slot.error, failed = str(error), True
            except (OSError, TimeoutError, ConnectionError):
                slot.error, failed = "connection_failed", True
            except Exception:
                slot.error, failed = "transport_failed", True
            slot.phase = "retrying"
            if time.monotonic() - started > 10:
                delay = 1
            await asyncio.sleep(delay if failed else 0.25)
            delay = min(delay * 2, 10) if failed else 1

    async def _connection(self, slot):
        fire_writer = backend_writer = None
        try:
            # Direct awaits preserve external cancellation even when an I/O
            # future completes concurrently (wait_for has a race on 3.11).
            async with asyncio.timeout(3):
                fire_reader, fire_writer = await asyncio.open_connection(self.host, self.port, limit=AUTH_LIMIT)
            connection = fire_writer.get_extra_info("socket")
            if connection:
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                for option, value in (("TCP_KEEPIDLE", 15), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3)):
                    if hasattr(socket, option):
                        with contextlib.suppress(OSError):
                            connection.setsockopt(socket.IPPROTO_TCP, getattr(socket, option), value)
            slot.phase = "authenticating"
            fire_writer.write(self._preface())
            await fire_writer.drain()
            try:
                async with asyncio.timeout(3):
                    raw = await fire_reader.readuntil(b"\n")
                if len(raw) > AUTH_LIMIT:
                    raise ValueError
                answer = json.loads(raw)
            except (ValueError, UnicodeError, asyncio.LimitOverrunError, asyncio.IncompleteReadError, TimeoutError):
                raise BridgeFailure("invalid_reverse_ready") from None
            if not isinstance(answer, dict) or answer.get("type") != "reverse_ready":
                raise BridgeFailure("authentication_rejected")
            if type(answer.get("version")) is not int or answer["version"] != 1 or answer.get("device_id") != self.device_id:
                raise BridgeFailure("invalid_reverse_ready")
            slot.phase = "waiting"
            # Preserve all bytes following the ready newline, including a GET
            # coalesced in the same TCP packet. Idle pool slots have NO local
            # HTTP connection, avoiding Uvicorn's idle keep-alive timeout.
            first = await fire_reader.read(CHUNK_SIZE)
            if not first:
                return
            try:
                async with asyncio.timeout(3):
                    backend_reader, backend_writer = await asyncio.open_connection(self.backend_host, self.backend_port)
            except (OSError, TimeoutError):
                raise BridgeFailure("local_backend_unavailable") from None
            slot.phase = "relaying"
            backend_writer.write(first)
            await backend_writer.drain()
            slot.bytes_from_fire += len(first)
            await self._relay(fire_reader, fire_writer, backend_reader, backend_writer, slot)
        finally:
            for writer in (fire_writer, backend_writer):
                if writer:
                    writer.close()
            for writer in (fire_writer, backend_writer):
                if writer:
                    with contextlib.suppress(OSError, TimeoutError, ConnectionError):
                        async with asyncio.timeout(1):
                            await writer.wait_closed()

    async def _relay(self, fire_reader, fire_writer, backend_reader, backend_writer, slot):
        async def pump(reader, writer, from_fire):
            while chunk := await reader.read(CHUNK_SIZE):
                writer.write(chunk)
                await writer.drain()
                if from_fire:
                    slot.bytes_from_fire += len(chunk)
                else:
                    slot.bytes_to_fire += len(chunk)
            if writer.can_write_eof():
                writer.write_eof()
                await writer.drain()
        tasks = [asyncio.create_task(pump(fire_reader, backend_writer, True)),
                 asyncio.create_task(pump(backend_reader, fire_writer, False))]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            # Honour half-close for an HTTP response after upload EOF, but do
            # not retain an orphan stream indefinitely after its peer leaves.
            if pending:
                async with asyncio.timeout(5):
                    await asyncio.gather(*pending)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

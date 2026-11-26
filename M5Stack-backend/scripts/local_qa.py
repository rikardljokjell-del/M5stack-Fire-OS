"""Authenticated local UART QA; importing this module opens nothing.

One RAM-only arm per boot. This is software button emulation through the OS,
not a measurement of mechanical switches/GPIO latency. Never logs raw UART,
nonces, MACs or credentials. The operator must explicitly authorize a safe
fixture; the native OS remains responsible for its actual current-app gate.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import time

DOMAIN = b'FIRE-LOCAL-QA-v1\n'
MAX_WIRE = 512
SAFE_PACKAGE = 'build-67b5836c92034bebb8f0'
SAFE_SOURCE = '386d02a8cec3a6d211c793aff3c51a1f97929b7543d8764e037401448cc188b2'
CODES = {0: 'ok', 1: 'malformed', 2: 'authentication', 3: 'off', 4: 'expired',
         5: 'arm consumed', 6: 'sequence rejected', 7: 'command limit',
         8: 'state-only permission', 9: 'stale presentation', 10: 'unavailable',
         11: 'action blocked by OS', 12: 'internal failure'}


class QaError(RuntimeError):
    """Only fixed, non-secret diagnostics are exposed to the CLI."""


def require_safe_app(package: str, source: str) -> None:
    if package != SAFE_PACKAGE or source != SAFE_SOURCE:
        raise QaError('This QA harness permits only the approved safe fixture.')


def validate_plan(plan) -> list[dict]:
    if not isinstance(plan, list) or not 1 <= len(plan) <= 128:
        raise QaError('QA plan must contain1..128 explicit steps.')
    common = {'op', 'expect'}
    fields = {'state': common, 'button': common | {'button', 'hold'},
              'select': common | {'label', 'screen', 'max_steps'}, 'wait': common | {'timeout'}}
    for step in plan:
        if not isinstance(step, dict) or step.get('op') not in fields or set(step) - fields[step['op']]:
            raise QaError('Unsupported QA plan operation or field.')
        expected = step.get('expect', {})
        if not isinstance(expected, dict) or set(expected) - {'screen', 'index', 'label', 'detail', 'busy', 'error'}:
            raise QaError('Unsupported QA expectation.')
        for key, value in expected.items():
            if key in {'label', 'detail'}:
                if not isinstance(value, str) or len(value.encode('utf-8')) > (64 if key == 'label' else 32):
                    raise QaError('Invalid QA expectation text.')
            elif key == 'busy':
                if type(value) is not bool:
                    raise QaError('Invalid QA boolean expectation.')
            elif type(value) is not int or not 0 <= value <= 65535:
                raise QaError('Invalid QA numeric expectation.')
        if step['op'] == 'button' and (step.get('button') not in {'A', 'B', 'C'} or type(step.get('hold', False)) is not bool):
            raise QaError('Invalid QA button step.')
        if step['op'] == 'select':
            if not isinstance(step.get('label'), str) or not step['label'] or len(step['label'].encode('utf-8')) > 64:
                raise QaError('Invalid QA navigation label.')
            if 'screen' in step and (type(step['screen']) is not int or not 0 <= step['screen'] <= 65535):
                raise QaError('Invalid QA navigation screen.')
            if type(step.get('max_steps', 32)) is not int or not 1 <= step.get('max_steps', 32) <= 64:
                raise QaError('Invalid QA navigation bound.')
        if step['op'] == 'wait' and (type(step.get('timeout', 10)) not in {int, float} or not 0 < step.get('timeout', 10) <= 900):
            raise QaError('Invalid QA wait bound.')
    return plan


def _uint(value: str, maximum: int = 0xffffffff) -> int:
    if not re.fullmatch(r'0|[1-9][0-9]*', value):
        raise QaError('Invalid QA numeric field.')
    result = int(value)
    if result > maximum:
        raise QaError('QA numeric field exceeds its bound.')
    return result


def _hex(value: str, length: int) -> str:
    if len(value) != length or not re.fullmatch('[0-9a-f]+', value):
        raise QaError('Invalid QA hexadecimal field.')
    return value


def _text(value: str, maximum: int) -> str:
    if len(value) > maximum * 2 or len(value) % 2 or value and not re.fullmatch('[0-9a-f]+', value):
        raise QaError('Invalid bounded QA text.')
    try:
        return bytes.fromhex(value).decode('utf-8', errors='strict')
    except (ValueError, UnicodeDecodeError):
        raise QaError('Invalid QA UTF-8 text.') from None


class Authenticator:
    def __init__(self, key: bytes | bytearray):
        if not isinstance(key, (bytes, bytearray)) or len(key) < 24:
            raise QaError('A configured device credential is required.')
        self._key = bytearray(key)

    def encode(self, body: str) -> bytes:
        try:
            raw = body.encode('ascii')
        except UnicodeEncodeError:
            raise QaError('QA request must use canonical ASCII.') from None
        if b'\n' in raw or b'\r' in raw or any(c < 32 or c > 126 for c in raw):
            raise QaError('Invalid QA request characters.')
        tag = hmac.new(self._key, DOMAIN + raw, hashlib.sha256).hexdigest().encode()
        wire = raw + b'|' + tag + b'\n'
        if len(wire) > MAX_WIRE:
            raise QaError('QA request exceeds its bound.')
        return wire

    def decode(self, line: bytes) -> list[str]:
        if not isinstance(line, bytes) or len(line) > MAX_WIRE or not line.endswith(b'\n'):
            raise QaError('Invalid QA response length.')
        raw = line[:-1]
        if any(c < 32 or c > 126 for c in raw):
            raise QaError('Invalid QA response characters.')
        body, separator, tag = raw.rpartition(b'|')
        if not separator or not re.fullmatch(b'[0-9a-f]{64}', tag):
            raise QaError('Invalid authenticated QA response.')
        expected = hmac.new(self._key, DOMAIN + body, hashlib.sha256).hexdigest().encode()
        if not hmac.compare_digest(tag, expected):
            raise QaError('QA response authentication failed.')
        return body.decode('ascii').split('|')

    def clear(self) -> None:
        for index in range(len(self._key)):
            self._key[index] = 0


@dataclass(frozen=True)
class Snapshot:
    seq: int
    code: int
    duplicate: bool
    remaining: int
    screen: int
    index: int
    count: int
    context: int
    view: int
    identity: str
    presented: int
    busy: bool
    error: int
    frame_crc: int
    label: str
    detail: str


def decode_snapshot(parts: list[str], nonce: str, seq: int) -> Snapshot:
    # Authenticator removes the MAC before returning fields.
    if len(parts) != 19 or parts[:2] != ['FQ1', 'R'] or parts[2] != nonce or _uint(parts[3]) != seq:
        raise QaError('QA reply is not bound to the current request.')
    code = _uint(parts[4], 12)
    return Snapshot(seq, code, bool(_uint(parts[5], 1)), _uint(parts[6], 500),
        _uint(parts[7], 65535), _uint(parts[8], 65535), _uint(parts[9], 65535),
        _uint(parts[10]), int(_hex(parts[11], 16), 16), _hex(parts[12], 64),
        _uint(parts[13]), bool(_uint(parts[14], 1)), _uint(parts[15], 65535),
        int(_hex(parts[16], 8), 16), _text(parts[17], 64), _text(parts[18], 32))


class Session:
    """A single exclusive, already-open serial stream; no automatic reset."""
    def __init__(self, stream, key: bytes, *, ttl: int = 300, limit: int = 500,
                 buttons: bool = False, safe_package: str | None = None,
                 safe_source: str | None = None, timeout: float = 3.0):
        if not 1 <= ttl <= 900 or not 1 <= limit <= 500 or not 0 < timeout <= 10:
            raise QaError('Invalid QA session limits.')
        if buttons:
            require_safe_app(safe_package or '', safe_source or '')
        self.stream, self.auth = stream, Authenticator(key)
        self.ttl, self.limit, self.mask = ttl, limit, 3 if buttons else 1
        self.timeout, self._nonce, self._seq = timeout, '', 0
        self._buffer = bytearray()
        self._discard = False
        self._uncertain = self._stopped = False
        self.last: Snapshot | None = None

    def _line(self, deadline: float) -> bytes:
        while time.monotonic() < deadline:
            raw = self.stream.read(1)
            if not raw:
                continue
            byte = raw[0]
            if byte == 10:
                line = bytes(self._buffer) + b'\n'
                rejected = self._discard
                self._buffer.clear()
                self._discard = False
                if not rejected and line.startswith(b'FQ1|'):
                    return line
                if b'rst:0x' in line or b'Guru Meditation' in line or b'Task watchdog got triggered' in line:
                    raise QaError('Device reset or watchdog detected during QA.')
                continue  # Never retain or echo unrelated diagnostics.
            if self._discard:
                continue
            if len(self._buffer) >= MAX_WIRE - 1 or byte < 32 or byte > 126:
                self._buffer.clear()
                self._discard = True
            else:
                self._buffer.append(byte)
        raise QaError('No authenticated QA response before the deadline.')

    def _exchange(self, wire: bytes, expected: str, seq: int | None = None) -> list[str]:
        # Retries use EXACT bytes/nonce/sequence. Native caches the last receipt;
        # an uncertain button is never issued again with a fresh sequence.
        for _attempt in range(2):
            written = self.stream.write(wire)
            if written is not None and written != len(wire):
                self._uncertain = True
                raise QaError('Incomplete QA write; outcome is unknown.')
            deadline = time.monotonic() + self.timeout
            try:
                while True:
                    parts = self.auth.decode(self._line(deadline))
                    if parts[:2] != ['FQ1', expected]:
                        continue
                    if expected == 'R' and (len(parts) != 19 or parts[2] != self._nonce or _uint(parts[3]) != seq):
                        continue
                    return parts
            except QaError as error:
                if str(error) != 'No authenticated QA response before the deadline.':
                    self._uncertain = True
                    raise
        self._uncertain = True
        raise QaError('QA outcome is unknown; no fresh action will be issued.')

    def arm(self) -> Snapshot:
        if self._nonce:
            raise QaError('This host session has already requested an arm.')
        challenge = self._exchange(b'FQ1|HELLO\n', 'C')
        if len(challenge) != 4 or not 0 < _uint(challenge[3]) <= 120000:
            raise QaError('QA boot challenge is unavailable.')
        self._nonce = _hex(challenge[2], 32)
        body = f'FQ1|ARM|{self._nonce}|{self.ttl}|{self.limit}|{self.mask}'
        reply = self._exchange(self.auth.encode(body), 'R', 0)
        self.last = decode_snapshot(reply, self._nonce, 0)
        if self.last.code:
            raise QaError('QA arm rejected: ' + CODES[self.last.code])
        return self.last

    def _command(self, op: str, button: int = 0, expected: Snapshot | None = None) -> Snapshot:
        if not self._nonce or self._uncertain or self._stopped:
            raise QaError('No active, certain QA host session.')
        if self.last is not None and self.last.remaining == 0:
            raise QaError('QA command budget exhausted.')
        self._seq += 1
        context, view, identity = (expected.context, expected.view, expected.identity) if expected else (0, 0, '0' * 64)
        body = f'FQ1|DO|{self._nonce}|{self._seq}|{op}|{button}|{context}|{view:016x}|{identity}'
        parts = self._exchange(self.auth.encode(body), 'R', self._seq)
        self.last = decode_snapshot(parts, self._nonce, self._seq)
        if self.last.code:
            if self.last.code in {2, 3, 4, 5, 6, 7, 12}:
                self._uncertain = True
            raise QaError('QA command rejected: ' + CODES[self.last.code])
        return self.last

    def state(self) -> Snapshot:
        return self._command('STATE')

    def button(self, button: str, *, hold: bool = False, expected: Snapshot | None = None,
               wait_presented: bool = True) -> Snapshot:
        if self.mask != 3 or button not in {'A', 'B', 'C'}:
            raise QaError('Button action is outside the approved QA scope.')
        shown = expected or self.last
        if shown is None or not shown.context:
            raise QaError('A presented screen is required before a button action.')
        result = self._command('HOLD' if hold else 'CLICK', ord(button) - ord('A'), shown)
        if wait_presented:
            return self.wait(lambda state: 0 < ((state.presented - shown.presented) & 0xffffffff) < 0x80000000,
                             timeout=5)
        return result

    def wait(self, predicate, *, timeout: float = 10, poll: float = 0.5) -> Snapshot:
        if not 0 < timeout <= 900 or not 0.1 <= poll <= 5:
            raise QaError('Invalid QA observation deadline.')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.state()
            if predicate(state):
                return state
            time.sleep(min(poll, max(0, deadline - time.monotonic())))
        raise QaError('Expected presented state was not observed.')

    def select(self, label: str, *, screen: int | None = None, max_steps: int = 32) -> Snapshot:
        if not isinstance(label, str) or not label or len(label.encode('utf-8')) > 64 or not 1 <= max_steps <= 64:
            raise QaError('Invalid QA navigation target.')
        state = self.state()
        seen = set()
        for _ in range(max_steps):
            if screen is not None and state.screen != screen:
                raise QaError('Navigation reached an unexpected screen.')
            if state.label == label:
                return self.button('B', expected=state)
            marker = (state.screen, state.index, state.label)
            if marker in seen:
                break
            seen.add(marker)
            state = self.button('C', expected=state)
        raise QaError('Requested menu label was not found; nothing was selected.')

    def stop(self) -> None:
        if self._nonce and not self._uncertain and not self._stopped and self.last and self.last.remaining:
            self._command('STOP')
        self._stopped = True

    def close(self) -> None:
        try:
            self.stop()
        finally:
            self.auth.clear()
            self.stream.close()

    def public(self, state: Snapshot) -> dict:
        value = asdict(state)
        # Defense in depth if a native label is ever incorrectly sanitized.
        token = bytes(self.auth._key).decode('utf-8', errors='ignore')
        for name in ('label', 'detail'):
            if token:
                value[name] = value[name].replace(token, '[REDACTED]')
            value[name] = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', value[name])
        return value


def device_key(device_id: str) -> bytes:
    # Lazy import: importing/testing the wire codec never opens the Vault.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fire_backend.desktop_config import DesktopStore
    key = DesktopStore().secret('device/' + device_id)
    if not key:
        raise QaError('The selected device has no stored credential.')
    return key.encode('utf-8')


def open_port(name: str):
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1)
    port.dtr = False
    port.rts = False
    port.port = name
    port.open()  # Never toggle reset/boot pins after opening.
    return port


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--device-id', default='m5stack-fire-01')
    parser.add_argument('--ttl', type=int, default=300)
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--safe-package')
    parser.add_argument('--safe-source')
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('state')
    button = sub.add_parser('button')
    button.add_argument('button', choices=['A', 'B', 'C'])
    button.add_argument('--hold', action='store_true')
    batch = sub.add_parser('batch')
    batch.add_argument('plan', type=Path)
    args = parser.parse_args(argv)
    session = None
    try:
        buttons = args.operation != 'state'
        if buttons:
            require_safe_app(args.safe_package or '', args.safe_source or '')
        plan = None
        if args.operation == 'batch':
            if args.plan.stat().st_size > 65536:
                raise QaError('QA plan is too large.')
            plan = validate_plan(json.loads(args.plan.read_text(encoding='utf-8')))
        if not 1 <= args.ttl <= 900 or not 1 <= args.limit <= 500:
            raise QaError('Invalid QA session limits.')
        key = device_key(args.device_id)
        stream = open_port(args.port)
        try:
            session = Session(stream, key, ttl=args.ttl, limit=args.limit, buttons=buttons,
                safe_package=args.safe_package, safe_source=args.safe_source)
        except BaseException:
            stream.close()
            raise
        state = session.arm()
        steps = plan if plan is not None else [{'op': args.operation, **({'button': args.button, 'hold': args.hold} if args.operation == 'button' else {})}]
        for step in steps:
            if not isinstance(step, dict) or step.get('op') not in {'state', 'button', 'select', 'wait'}:
                raise QaError('Unsupported QA plan operation.')
            expected = step.get('expect', {})
            if not isinstance(expected, dict) or set(expected) - {'screen', 'index', 'label', 'detail', 'busy', 'error'}:
                raise QaError('Unsupported QA expectation.')
            if step['op'] == 'wait':
                state = session.wait(lambda current: all(getattr(current, key) == value for key, value in expected.items()),
                    timeout=float(step.get('timeout', 10)))
            else:
                state = session.state()
                if any(getattr(state, key) != value for key, value in expected.items()):
                    raise QaError('Presented state does not match the explicit test step.')
                if step['op'] == 'button':
                    state = session.button(step.get('button'), hold=step.get('hold', False), expected=state)
                elif step['op'] == 'select':
                    state = session.select(step.get('label'), screen=step.get('screen'), max_steps=int(step.get('max_steps', 32)))
            print(json.dumps(session.public(state), ensure_ascii=True), flush=True)
        return 0
    except (QaError, OSError, ValueError, TypeError):
        print('Local QA stopped safely. No raw serial data or credentials were retained.', flush=True)
        return 1
    finally:
        if session:
            try:
                session.close()
            except (QaError, OSError):
                pass


if __name__ == '__main__':
    raise SystemExit(main())

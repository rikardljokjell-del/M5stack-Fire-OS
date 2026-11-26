"""Bounded host UART resynchronization; no port, Vault, network or device."""
import importlib.util
from pathlib import Path
import sys

import pytest


SPEC = importlib.util.spec_from_file_location(
    'fire_local_qa_uart_test', Path(__file__).resolve().parents[1] / 'scripts/local_qa.py')
host = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = host
SPEC.loader.exec_module(host)
KEY = b'local-qa-synthetic-test-key-only'
NONCE = '0123456789abcdef0123456789abcdef'
IDENTITY = 'a' * 64


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now


class Serial:
    """A single cached receipt/action, with deterministic empty-read timing."""
    def __init__(self, clock):
        self.clock = clock
        self.auth = host.Authenticator(KEY)
        self.rx = bytearray()
        self.writes = []
        self.actions = 0
        self.mode = ''
        self.last_request = None
        self.challenge_mode = ''
        self.challenge_requests = 0
        self.first_reply = True

    def reply(self, seq, *, code=0, duplicate=False, invalid_numeric=False):
        values = ['FQ1', 'R', NONCE, str(seq), str(code), str(int(duplicate)),
                  '501' if invalid_numeric else '490', '2', '1', '4', '7',
                  '0000000000000009', IDENTITY, '2', '0', '0', '12345678',
                  b'Main'.hex(), b'Ready'.hex()]
        return self.auth.encode('|'.join(values))

    def write(self, wire):
        self.writes.append(wire)
        if wire == b'FQ1|HELLO\n':
            self.challenge_requests += 1
            challenge = 'FQ1|C|' + NONCE + '|110000'
            if self.challenge_mode == 'invalid' and self.challenge_requests == 1:
                challenge = 'FQ1|C|' + 'g' * 32 + '|110000'
            elif self.challenge_mode == 'invalid_window' and self.challenge_requests == 1:
                challenge = 'FQ1|C|' + NONCE + '|120001'
            self.rx.extend(self.auth.encode(challenge))
            return len(wire)
        fields = self.auth.decode(wire)
        if fields[1] == 'ARM':
            self.rx.extend(self.reply(0))
            return len(wire)
        if self.mode == 'short_write':
            return len(wire) - 1
        if self.mode == 'write_error':
            raise OSError('synthetic write fault')
        duplicate = wire == self.last_request
        negative = int(self.mode.split('_')[-1]) if self.mode.startswith('negative_') else 0
        if not duplicate:
            self.last_request = wire
            if fields[4] in {'CLICK', 'HOLD'} and not negative:
                assert fields[6:9] == ['7', '0000000000000009', IDENTITY]
                self.actions += 1
        good = self.reply(int(fields[3]), code=negative, duplicate=duplicate)
        bad = b'FQ1|R|FIRE inventory scan apps=14 complete=1 elapsed_ms=42\n'
        if self.mode == 'invalid_only' or self.mode == 'shape' and self.first_reply:
            self.rx.extend(bad)
        elif self.mode == 'mac' and self.first_reply:
            self.rx.extend(good[:-2] + (b'0' if good[-2:-1] != b'0' else b'1') + b'\n')
        elif self.mode == 'numeric' and self.first_reply:
            self.rx.extend(self.reply(int(fields[3]), invalid_numeric=True))
        elif self.mode == 'wrong_binding' and self.first_reply:
            self.rx.extend(self.reply(int(fields[3]) + 1))
        elif self.mode == 'shape_then_good' and self.first_reply:
            self.rx.extend(bad + good)
        elif self.mode == 'reset':
            self.rx.extend(b'rst:0x1 (POWERON_RESET)\n')
        else:
            self.rx.extend(good)
        self.first_reply = False
        return len(wire)

    def read(self, size):
        if self.mode == 'read_error':
            raise OSError('synthetic read fault')
        if not self.rx:
            self.clock.now += .005
        value = bytes(self.rx[:size])
        del self.rx[:size]
        return value


def session(monkeypatch, *, challenge=''):
    clock = Clock()
    monkeypatch.setattr(host.time, 'monotonic', clock.monotonic)
    stream = Serial(clock)
    stream.challenge_mode = challenge
    client = host.Session(stream, KEY, buttons=True, safe_package=host.SAFE_PACKAGE,
                          safe_source=host.SAFE_SOURCE, timeout=.02)
    shown = client.arm()
    stream.writes.clear()
    return client, stream, clock, shown


@pytest.mark.parametrize('damage', ['shape', 'mac', 'numeric', 'wrong_binding'])
def test_damaged_candidate_retries_exact_cached_action(monkeypatch, damage):
    client, stream, clock, shown = session(monkeypatch)
    stream.mode = damage
    result = client.button('B', expected=shown, wait_presented=False)
    assert result.code == 0 and result.duplicate
    assert stream.actions == 1
    assert len(stream.writes) == 2 and stream.writes[0] == stream.writes[1]
    assert clock.now <= 2 * client.timeout + .005


def test_later_valid_candidate_uses_original_deadline_without_retry(monkeypatch):
    client, stream, clock, shown = session(monkeypatch)
    stream.mode = 'shape_then_good'
    assert client.button('B', expected=shown, wait_presented=False).code == 0
    assert len(stream.writes) == 1 and stream.actions == 1
    assert clock.now == 0


def test_invalid_only_is_bounded_unknown_and_never_new_sequence(monkeypatch):
    client, stream, clock, shown = session(monkeypatch)
    stream.mode = 'invalid_only'
    with pytest.raises(host.QaError, match='outcome is unknown'):
        client.button('B', expected=shown, wait_presented=False)
    assert stream.actions == 1 and client._uncertain
    assert len(stream.writes) == 2 and stream.writes[0] == stream.writes[1]
    assert clock.now <= 2 * client.timeout + .005
    with pytest.raises(host.QaError, match='No active, certain'):
        client.button('B', expected=shown, wait_presented=False)
    assert len(stream.writes) == 2


@pytest.mark.parametrize('code', [9, 11, 12])
def test_valid_authenticated_rejection_is_not_noise_or_retried(monkeypatch, code):
    client, stream, _, shown = session(monkeypatch)
    stream.mode = f'negative_{code}'
    with pytest.raises(host.QaError, match='QA command rejected'):
        client.button('B', expected=shown, wait_presented=False)
    assert client.last.code == code
    assert client._uncertain == (code == 12)  # Existing Stale/Blocked explicit-control semantics.
    assert len(stream.writes) == 1 and stream.actions == 0


@pytest.mark.parametrize('fault', ['reset', 'short_write', 'read_error', 'write_error'])
def test_reset_io_and_short_write_stop_without_resynchronizing(monkeypatch, fault):
    client, stream, _, shown = session(monkeypatch)
    stream.mode = fault
    with pytest.raises((host.QaError, OSError)):
        client.button('B', expected=shown, wait_presented=False)
    assert client._uncertain and len(stream.writes) == 1
    with pytest.raises(host.QaError, match='No active, certain'):
        client.state()
    assert len(stream.writes) == 1


@pytest.mark.parametrize('challenge', ['invalid', 'invalid_window'])
def test_authenticated_malformed_challenge_cannot_be_used_to_arm(monkeypatch, challenge):
    client, stream, clock, _ = session(monkeypatch, challenge=challenge)
    assert stream.challenge_requests == 2 and client._nonce == NONCE
    assert clock.now <= client.timeout + .005

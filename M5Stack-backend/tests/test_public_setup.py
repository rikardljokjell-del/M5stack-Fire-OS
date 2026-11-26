"""Public setup preserves the same profile; Windows startup tests are isolated."""
import importlib.util
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fire_backend.desktop_config import DesktopStore

ROOT = Path(__file__).resolve().parents[1]


class Vault:
    def __init__(self):
        self.data = {}
        self.writes = 0

    def get(self, key):
        return self.data.get(key, '')

    def put(self, key, value):
        self.writes += 1
        self.data[key] = value


@pytest.mark.parametrize('save', [False, True])
@pytest.mark.parametrize('transport', [None, 'direct', 'reverse_tcp'])
def test_public_setup_changes_only_public_fields_without_vault_writes(tmp_path, monkeypatch, capsys, save, transport):
    vault = Vault()
    store = DesktopStore(tmp_path / 'same profile', vault)
    store.save_values(store.config.model_copy(update={'transport': 'reverse_tcp',
        'reverse_host': '192.168.1.50', 'reverse_device_id': store.config.device_ids[0]}))
    before = store.config.model_dump()
    raw_before = store.path.read_bytes()
    vault_before, writes_before = dict(vault.data), vault.writes
    spec = importlib.util.spec_from_file_location('configure_public_test', ROOT / 'scripts/configure_public.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'DesktopStore', lambda: store)
    args = ['configure_public', '--web-origin', 'https://studio.example.org/',
            '--device-host', 'fire.example.org', '--access-issuer', 'https://team.cloudflareaccess.com/',
            '--access-audience', 'the-application-audience'] + (['--save'] if save else [])
    if transport is not None:
        args += ['--transport', transport]
    monkeypatch.setattr(sys, 'argv', args)
    module.main()
    after = store.config.model_dump()
    changed = {key for key in before if before[key] != after[key]}
    expected = {'public_enabled', 'web_origin', 'device_host', 'access_issuer', 'access_audience'}
    if transport == 'direct':
        expected.add('transport')
    assert changed == (expected if save else set())
    assert after['reverse_host'] == before['reverse_host'] and after['reverse_device_id'] == before['reverse_device_id']
    assert vault.data == vault_before and vault.writes == writes_before
    assert (store.path.read_bytes() == raw_before) is not save
    output = capsys.readouterr().out
    assert all(secret not in output for secret in vault.data.values())


def test_invalid_public_setup_preserves_all_existing_settings(tmp_path, monkeypatch):
    store = DesktopStore(tmp_path, Vault())
    before = store.path.read_bytes()
    spec = importlib.util.spec_from_file_location('invalid_public_setup', ROOT / 'scripts/configure_public.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'DesktopStore', lambda: store)
    monkeypatch.setattr(sys, 'argv', ['configure_public', '--web-origin', 'https://same.example.org',
        '--device-host', 'same.example.org', '--access-issuer', 'https://team.cloudflareaccess.com',
        '--access-audience', 'audience', '--save'])
    with pytest.raises(SystemExit):
        module.main()
    assert store.path.read_bytes() == before



def startup_module():
    spec = importlib.util.spec_from_file_location('startup_setup_test', ROOT / 'scripts/backend_startup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_startup_reads_same_nonsecret_profile_without_vault_access(tmp_path, monkeypatch):
    from fire_backend import desktop_config
    module = startup_module()
    config = desktop_config.DesktopConfig(port=32123)
    path = tmp_path / 'settings.json'
    path.write_text(config.model_dump_json())
    def forbidden():
        pytest.fail('Startup must not open Windows Vault')
    monkeypatch.setattr(desktop_config, 'WindowsVault', forbidden)
    assert module.configured_port(path) == 32123
    path.write_text(json.dumps({'accidental_extra_secret': 'secret-value-must-not-be-logged'}))
    with pytest.raises(ValueError) as error:
        module.configured_port(path)
    assert 'secret-value' not in str(error.value)


def environment(tmp_path):
    root = tmp_path / "backend with spaces & o'hara"
    (root / '.venv/Scripts').mkdir(parents=True)
    (root / 'scripts').mkdir()
    # Existence is checked; these test files are never executed.
    (root / '.venv/Scripts/pythonw.exe').touch()
    (root / 'scripts/backend_startup.py').touch()
    return root


def test_startup_command_uses_absolute_existing_environment_and_no_shell(tmp_path):
    module = startup_module()
    root = environment(tmp_path)
    command = module.startup_command(root)
    assert '-ExecutionPolicy' not in command and 'powershell' not in command.lower()
    assert str(root / '.venv/Scripts/pythonw.exe') in command
    assert str(root / 'scripts/backend_startup.py') in command
    assert command.endswith(' --run')
    if os.name == 'nt':
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        count = ctypes.c_int()
        pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
        assert pointer
        try:
            assert [pointer[i] for i in range(count.value)] == [str(root / '.venv/Scripts/pythonw.exe'),
                                                              str(root / 'scripts/backend_startup.py'), '--run']
        finally:
            kernel.LocalFree(pointer)


@pytest.mark.skipif(os.name != 'nt', reason='Actual registry operations use an isolated Windows test key')
def test_startup_registry_idempotency_and_foreign_entry_preservation(tmp_path):
    import winreg
    module = startup_module()
    command = module.startup_command()
    key_path = r'Software\FIREStartupTest-' + uuid.uuid4().hex
    try:
        assert module.registry_action('status', command, key_path=key_path) == 'not_installed'
        assert module.registry_action('install', command, key_path=key_path) == 'installed'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            assert winreg.QueryValueEx(key, module.ENTRY) == (command, winreg.REG_SZ)
            before = winreg.QueryInfoKey(key)[2]
            with pytest.raises(ValueError, match='exceeds 260'):
                module.registry_action('install', 'x' * 261, key_path=key_path)
            assert winreg.QueryValueEx(key, module.ENTRY) == (command, winreg.REG_SZ)
            assert module.registry_action('install', command, key_path=key_path) == 'installed'
            assert module.registry_action('status', command, key_path=key_path) == 'installed'
            assert winreg.QueryInfoKey(key)[2] == before
            winreg.SetValueEx(key, module.ENTRY, 0, winreg.REG_EXPAND_SZ, command)
            with pytest.raises(ValueError, match='different startup entry'):
                module.registry_action('remove', command, key_path=key_path)
            assert winreg.QueryValueEx(key, module.ENTRY) == (command, winreg.REG_EXPAND_SZ)
            winreg.SetValueEx(key, module.ENTRY, 0, winreg.REG_SZ, command)
            winreg.SetValueEx(key, 'Unrelated entry', 0, winreg.REG_SZ, 'preserve')
            assert module.registry_action('remove', command, key_path=key_path) == 'removed'
            assert module.registry_action('remove', command, key_path=key_path) == 'not_installed'
            assert winreg.QueryValueEx(key, 'Unrelated entry')[0] == 'preserve'
            winreg.SetValueEx(key, module.ENTRY, 0, winreg.REG_SZ, 'Someone else owns this')
            for action in ('install', 'remove', 'status'):
                with pytest.raises(ValueError, match='different startup entry'):
                    module.registry_action(action, command, key_path=key_path)
            assert winreg.QueryValueEx(key, module.ENTRY)[0] == 'Someone else owns this'
    finally:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                for name in (module.ENTRY, 'Unrelated entry'):
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass


def health_server(port, valid=True):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            body = json.dumps({'status': 'ok', 'version': '0.2.0', 'protocol_versions': ['0.2']}
                              if valid else {'service': 'not FIRE'}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.mark.skipif(os.name != 'nt', reason='Exercises the actual Windows named launch guard')
def test_startup_run_reuses_entry_once_with_concurrency_and_running_backend(tmp_path):
    module = startup_module()
    root = environment(tmp_path)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    entered, release = threading.Event(), threading.Event()
    calls, servers = [], []

    def launch(args, **kwargs):
        calls.append((args, kwargs))
        entered.set()
        assert release.wait(5)
        servers.append(health_server(port))

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(module.run, root, port=port, popen=launch)
            if not entered.wait(3):
                first.result(timeout=2)
                pytest.fail('The launch guard did not reach the existing entry')
            try:
                assert module.run(root, port=port, popen=launch) == 'startup_in_progress'
            finally:
                release.set()
            assert first.result(timeout=12) == 'started'
            assert module.run(root, port=port, popen=launch) == 'already_running'
        assert calls == [([str(root / '.venv/Scripts/pythonw.exe'), '-m', 'fire_backend.desktop_entry'],
                          {'cwd': str(root), 'creationflags': subprocess.CREATE_NO_WINDOW})]
    finally:
        release.set()
        for server, thread in servers:
            server.shutdown()
            server.server_close()
            thread.join(2)


def test_startup_refuses_foreign_listener_without_launching(tmp_path, monkeypatch):
    module = startup_module()
    root = environment(tmp_path)
    if os.name != 'nt':
        monkeypatch.setattr(module, 'launch_lock', lambda _root: nullcontext(True))
    server, thread = health_server(0, valid=False)
    calls = []
    try:
        with pytest.raises(ValueError, match='port is in use'):
            module.run(root, port=server.server_port, popen=lambda *a, **k: calls.append((a, k)))
        assert not calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)

"""One owned current-user startup entry for the existing Windows backend."""
import argparse
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

if os.name == 'nt':
    import winreg
else:
    winreg = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fire_backend.desktop_config import DesktopConfig, data_directory

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
ENTRY = 'FIRE Backend'


def startup_command(root=ROOT):
    root = Path(root).resolve()
    python = root / '.venv/Scripts/pythonw.exe'
    helper = root / 'scripts/backend_startup.py'
    if not python.is_file() or not helper.is_file():
        raise ValueError('The existing checkout and Python environment are required.')
    return subprocess.list2cmdline([str(python), str(helper), '--run'])


def registry_action(action, command, *, registry=None, key_path=RUN_KEY):
    """Only the exact command owned by this checkout may be removed/replaced."""
    registry = registry or winreg
    if registry is None:
        raise ValueError('Windows current-user startup requires Windows.')
    if action == 'install' and len(command) > 260:
        raise ValueError('The Windows Run command exceeds 260 characters; use a shorter checkout path.')
    access = registry.KEY_QUERY_VALUE | (registry.KEY_SET_VALUE if action != 'status' else 0)
    try:
        key = registry.OpenKey(registry.HKEY_CURRENT_USER, key_path, 0, access)
    except FileNotFoundError:
        if action != 'install':
            return 'not_installed'
        key = registry.CreateKeyEx(registry.HKEY_CURRENT_USER, key_path, 0, access)
    with key:
        try:
            value, kind = registry.QueryValueEx(key, ENTRY)
        except FileNotFoundError:
            value, kind = None, None
        if value is not None and (kind != registry.REG_SZ or value != command):
            raise ValueError('A different startup entry uses this name; it was not changed.')
        if action == 'install' and value is None:
            registry.SetValueEx(key, ENTRY, 0, registry.REG_SZ, command)
            return 'installed'
        if action == 'remove' and value is not None:
            registry.DeleteValue(key, ENTRY)
            return 'removed'
        return 'installed' if value is not None else 'not_installed'


def configured_port(settings_path=None):
    path = Path(settings_path) if settings_path else data_directory() / 'settings.json'
    if not path.exists():
        return 8765
    # Same non-secret schema/profile as the existing launcher. No Vault reads.
    try:
        config = DesktopConfig.model_validate_json(path.read_text(encoding='utf-8'))
    except ValueError:
        raise ValueError('Existing backend settings are invalid; no extra backend was started.') from None
    return config.port


def listening(port):
    # A closed Windows loopback port may time out instead of refusing a TCP
    # connect immediately. An exclusive bind probe does not listen or expose
    # a service, and distinguishes a free port without a network retry delay.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == 'nt':
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('127.0.0.1', port))
        return False
    except OSError as error:
        if error.errno in {errno.EADDRINUSE, errno.EACCES} or getattr(error, 'winerror', None) in {10013, 10048}:
            return True
        raise ValueError('Local port check failed; no extra backend was started.') from None


def healthy(port):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                return False
            value = json.loads(raw)
            return (isinstance(value, dict) and value.get('status') == 'ok' and
                    value.get('version') == '0.2.0' and isinstance(value.get('protocol_versions'), list)
                    and '0.2' in value['protocol_versions'])
    except (OSError, ValueError, TypeError, urllib.error.HTTPError):
        return False


@contextmanager
def launch_lock(root):
    """Serialize transient startup helpers, not backend work or app jobs."""
    if os.name != 'nt':
        raise ValueError('Windows startup requires Windows.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    name = 'Local\\FIREBackendStartup-' + hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise OSError('Could not guard backend startup.')
    held = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result not in {0, 0x80, 0x102}:
            raise OSError('Could not guard backend startup.')
        held = result in {0, 0x80}
        yield held
    finally:
        if held:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def run(root=ROOT, *, port=None, popen=None):
    root = Path(root).resolve()
    startup_command(root)  # Validate the same installed environment first.
    port = configured_port() if port is None else port
    with launch_lock(root) as held:
        if not held:
            return 'startup_in_progress'
        if listening(port):
            if healthy(port):
                return 'already_running'
            raise ValueError('The configured port is in use; no extra backend was started.')
        # This is the exact existing start-ui.ps1 Pythonw entry, with the same
        # working directory, DesktopStore/Vault and final WorkspaceLock guard.
        (popen or subprocess.Popen)([str(root / '.venv/Scripts/pythonw.exe'), '-m', 'fire_backend.desktop_entry'],
            cwd=str(root), creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if healthy(port):
                return 'started'
            time.sleep(.25)
        raise ValueError('The existing entry was launched once; readiness is not confirmed.')


def main():
    parser = argparse.ArgumentParser(description='Manage only this checkout\'s current-user backend startup.')
    actions = parser.add_mutually_exclusive_group()
    for action in ('install', 'remove', 'status', 'run'):
        actions.add_argument('--' + action, action='store_true')
    args = parser.parse_args()
    action = next((name for name in ('install', 'remove', 'run') if getattr(args, name)), 'status')
    try:
        result = run() if action == 'run' else registry_action(action, startup_command())
        print(result)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except OSError:
        raise SystemExit('Startup setup failed. Check the current user and installed environment.') from None


if __name__ == '__main__':
    main()

"""Desktop service lifecycle, diagnostics and local control of existing sessions."""
import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid

import httpx
import uvicorn

from .app import create_app
from .security import Redactor


class WorkspaceLock:
    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.file = (Path(root) / "backend.lock").open("a+b")
        if self.file.seek(0, 2) == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ValueError("En annen backend bruker datamappen. Stopp den først.") from None

    def close(self):
        self.file.close()


class LogBuffer(logging.Handler):
    def __init__(self, settings):
        super().__init__()
        self.lines = []
        self.redactor = Redactor(settings.openai_api_key.get_secret_value(), settings.fire_backend_token.get_secret_value(),
                                 *settings.device_tokens().values())

    def emit(self, record):
        line = self.redactor.text(record.getMessage())[:500]
        with self.lock:
            self.lines.append(time.strftime("%H:%M:%S  ") + line)
            self.lines[:] = self.lines[-250:]

    def text(self):
        with self.lock:
            return "\n".join(self.lines)


class DesktopRuntime:
    def __init__(self):
        self.thread = None
        self.server = None
        self.settings = None
        self.app = None
        self.failure = ""
        self.logs = None
        self.base_url = None

    @property
    def alive(self):
        return bool(self.thread and self.thread.is_alive())

    @property
    def ready(self):
        return bool(self.alive and self.server and self.server.started and not self.server.should_exit)

    def start(self, settings):
        if self.alive:
            raise ValueError("Backend kjører allerede.")
        if settings.fire_ai_mode == "openai" and not settings.openai_api_key.get_secret_value():
            raise ValueError("Legg inn API-nøkkel under OpenAI, eller velg testmodus.")
        self.settings, self.failure = settings, ""
        self.logs = LogBuffer(settings)
        self.app = create_app(settings)
        self.base_url = f"http://127.0.0.1:{settings.fire_backend_port}"
        config = uvicorn.Config(self.app, host=settings.fire_backend_host, port=settings.fire_backend_port,
                                workers=1, access_log=False, ws_max_size=8192, log_config=None, loop="asyncio", http="h11")
        self.server = uvicorn.Server(config)
        server = self.server

        def serve():
            lock, listener = None, None
            logger = logging.getLogger("uvicorn.error")
            logger.addHandler(self.logs)
            logger.setLevel(logging.INFO)
            try:
                lock = WorkspaceLock(settings.fire_workspace)
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if os.name == "nt":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind((settings.fire_backend_host, settings.fire_backend_port))
                listener.listen(128)
                server.run(sockets=[listener])
            except BaseException:
                self.failure = "Kunne ikke starte backend. Kontroller om porten/datamappen er i bruk eller om lagringsmappen er tilgjengelig."
            finally:
                if listener:
                    listener.close()
                if lock:
                    lock.close()
                logger.removeHandler(self.logs)

        self.thread = threading.Thread(target=serve, name="FIRE backend", daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=12)
        if self.alive:
            raise ValueError("Backend avslutter fortsatt. Vent før du prøver igjen.")

    def request(self, method, path, **kwargs):
        if not self.ready:
            raise ValueError("Start backend først.")
        headers = {"Authorization": "Bearer " + self.settings.fire_backend_token.get_secret_value()}
        with httpx.Client(base_url=self.base_url, headers=headers, timeout=8, trust_env=False) as client:
            response = client.request(method, path, **kwargs)
            if response.is_error:
                # Server responses are redacted; never include request headers.
                raise ValueError(self.logs.redactor.text(response.text)[:300])
            return response.json()

    def snapshot(self):
        if not self.ready:
            return {"sessions": [], "devices": [], "builds": []}
        return self.request("GET", "/desktop/status")

    def send_text(self, session_id, text):
        return self.request("POST", f"/desktop/sessions/{session_id}/text", json={"text": text})

    def install_saved(self, session_id, package_id):
        return self.request("POST", f"/desktop/sessions/{session_id}/install", json={"package_id": package_id})

    def select_app(self, session_id, mode, **values):
        return self.request("POST", f"/desktop/sessions/{session_id}/app", json={"app_mode": mode, **values})

    def delete_app(self, project_id):
        return self.request("DELETE", f"/projects/{project_id}")

    def confirm(self, session_id, kind, item_id):
        field = "proposal_id" if kind == "build" else "package_id"
        return self.request("POST", f"/{kind}/confirm", json={"session_id": session_id, field: item_id,
                                                                "event_id": "desktop-" + uuid.uuid4().hex})


def lan_addresses():
    addresses = set()
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = entry[4][0]
            if not ip.startswith(("127.", "169.254.")):
                addresses.add(ip)
    except OSError:
        pass
    return sorted(addresses)


def network_info():
    if os.name != "nt":
        return "", False
    command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-NetConnectionProfile | Select-Object -ExpandProperty NetworkCategory"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return result.stdout.strip(), result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return "", False


def configure_firewall(port):
    """Explicit UI action; Windows asks for elevation. No tokens in arguments."""
    import ctypes
    program = firewall_program().replace("'", "''")
    name = f"FIRE Backend LAN {port}"
    command = (
        "$ErrorActionPreference='Stop'; "
        f"Get-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue | Remove-NetFirewallRule; "
        f"New-NetFirewallRule -DisplayName '{name}' -Direction Inbound -Action Allow -Protocol TCP "
        f"-LocalPort {int(port)} -Program '{program}' -Profile Any -RemoteAddress LocalSubnet | Out-Null"
    )
    # A checked port and escaped executable path are the only interpolated values.
    import base64
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
        f"-NoProfile -NonInteractive -EncodedCommand {encoded}", None, 0)
    if result <= 32:
        raise ValueError("Windows tillot ikke brannmuroppsettet. Prøv igjen med administratorgodkjenning.")


def firewall_ready(port):
    if os.name != "nt":
        return False
    program = firewall_program().replace("'", "''")
    command = (f"$rules=Get-NetFirewallApplicationFilter -Program '{program}' -ErrorAction SilentlyContinue | Get-NetFirewallRule; "
               "foreach($rule in $rules) { if($rule.Enabled -eq 'True' -and $rule.Direction -eq 'Inbound' -and $rule.Action -eq 'Allow') { "
               "$ports=$rule | Get-NetFirewallPortFilter; "
               f"if($ports.LocalPort -contains 'Any' -or $ports.LocalPort -contains '{int(port)}') {{ 'ready' }} }} }}")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        return b"ready" in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def firewall_program():
    # A Windows venv's pythonw.exe is a redirector; the real listening process
    # uses the base interpreter image. Firewall rules must match that image.
    executable = sys.executable if getattr(sys, "frozen", False) else getattr(sys, "_base_executable", sys.executable)
    return str(Path(executable).resolve())


def check_api_key(settings, key):
    """List models only; does not generate content or claim live dialogue verification."""
    from openai import OpenAI
    if not key:
        raise ValueError("Legg inn eller lagre API-nøkkelen først.")
    try:
        with OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=18, max_retries=0) as client:
            available = {model.id for model in client.models.list()}
        selected = [settings.dialog_model, settings.code_model]
        if settings.audio_enabled:
            selected += [settings.transcribe_model, settings.speech_model]
        missing = [name for name in selected if name not in available]
        return ("Nøkkelen er godtatt. " + ("Disse modellnavnene finnes ikke i kontolisten: " + ", ".join(missing)
                if missing else "Valgte modeller finnes i kontolisten.")
                + " Tale og kodegenerering er ikke testet av denne kontrollen.")
    except Exception as error:
        status = getattr(error, "status_code", None)
        if status == 401:
            raise ValueError("OpenAI avviste nøkkelen. Kontroller at den er riktig og aktiv.") from None
        if status == 429:
            raise ValueError("OpenAI begrenset forespørselen. Kontroller konto/kreditt og prøv senere.") from None
        raise ValueError("Kunne ikke kontrollere OpenAI. Kontroller internett, nøkkel og kontotilgang.") from None

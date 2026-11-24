"""Real local HTTP/start/restart test, isolated files and mock models only."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fire_backend.desktop_config import DesktopStore
from fire_backend.desktop_runtime import DesktopRuntime


class TemporaryVault:
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key, "")
    def put(self, key, value): self.values[key] = value


def wait_for(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.05)
    raise RuntimeError("Isolated mock server did not become ready")


def main():
    runtime = DesktopRuntime()
    with tempfile.TemporaryDirectory(prefix="fire-studio-smoke-") as temporary:
        root = Path(temporary)
        store = DesktopStore(root / "config", TemporaryVault())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        store.save(store.config.model_copy(update={"mode": "mock", "allow_lan": False, "port": port,
                                                  "workspace": str(root / "data")}))
        before = (store.secret("admin"), store.secret("device/m5stack-fire-01"))
        runtime.config_store = store
        try:
            runtime.start(store.settings())
            wait_for(lambda: runtime.ready)
            def browser_login(browser):
                path = runtime.request("POST", "/desktop/web-login", json={})["path"]
                result = browser.post("/web/local-login", json={"code": path.split("signin=")[1]})
                result.raise_for_status()
                browser.headers["X-Fire-CSRF"] = result.json()["csrf"]
            with httpx.Client(base_url=runtime.base_url, headers={"Origin": runtime.base_url},
                              timeout=5, trust_env=False) as browser:
                browser_login(browser)
                assert browser.get("/web/status").json()["mode"] == "mock"
                assert browser.get("/ui/").status_code == 200
                assert browser.patch("/web/settings", json={"values": {"speech_enabled": False}}).status_code == 200
                old_app = runtime.app
                assert browser.post("/web/settings/apply", json={}).status_code == 200
                wait_for(lambda: runtime.app is not old_app and runtime.ready)
                assert browser.get("/web/status").status_code == 401
                browser_login(browser)
                assert browser.get("/web/settings").json()["values"]["speech_enabled"] is False
                assert runtime.settings.fire_speech_enabled is False
                assert before == (store.secret("admin"), store.secret("device/m5stack-fire-01"))
                assert browser.get("/web/status").json()["jobs"]["active_count"] == 0
            print(json.dumps({"ok": True, "mode": "mock", "http": "real_local_server",
                              "controlled_restart": True, "credentials_preserved": True,
                              "old_cookie_revoked": True, "paid_calls": 0}))
        finally:
            runtime.stop()


if __name__ == "__main__":
    main()

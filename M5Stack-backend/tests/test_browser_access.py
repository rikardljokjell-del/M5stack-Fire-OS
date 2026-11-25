"""Real HTTP surfaces, signed JWTs and the existing offline backend, no paid calls."""
import asyncio
import json
import time

import jwt
import pytest
from pydantic import SecretStr
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from fire_backend.app import create_app
from fire_backend.config import Settings
from fire_backend.desktop_config import DesktopConfig, DesktopStore

ADMIN = "test-admin-credential-" + "a" * 24
DEVICE = "test-device-credential-" + "d" * 24
ORIGIN = "https://studio.example.org"
ISSUER = "https://test-team.cloudflareaccess.com"


class Vault:
    def __init__(self): self.data = {}
    def get(self, key): return self.data.get(key, "")
    def put(self, key, value): self.data[key] = value


@pytest.fixture
def web(tmp_path):
    store = DesktopStore(tmp_path / "desktop", Vault())
    store.save(store.config.model_copy(update={"workspace": str(tmp_path / "data"), "mode": "mock", "device_ids": ["fire01"]}),
               device_tokens={"fire01": DEVICE})
    settings = store.settings().model_copy(update={"fire_backend_token": SecretStr(ADMIN), "fire_public_enabled": True,
                  "fire_web_origin": ORIGIN, "fire_device_host": "fire.example.org",
                  "fire_access_issuer": ISSUER, "fire_access_audience": "studio-aud"})
    app = create_app(settings, config_store=store)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = app.state.browser_auth
    auth.keys = {"good": private.public_key()}
    auth.keys_until = time.monotonic() + 300
    def token(**updates):
        claims = {"iss": ISSUER, "aud": "studio-aud", "sub": "user1", "exp": time.time()+120,
                  "iat": time.time()-1, "type": "app", **updates}
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "good"})
    with TestClient(app, base_url=ORIGIN) as client:
        client.headers.update({"Origin": ORIGIN, "Cf-Access-Jwt-Assertion": token()})
        login = client.post("/web/login", json={})
        assert login.status_code == 200, login.text
        client.headers["X-Fire-CSRF"] = login.json()["csrf"]
        yield client, app, store, token


def test_public_surfaces_never_trust_proxy_loopback_or_admin_bearer(web):
    client, app, _, _ = web
    assert client.get("/web/status").status_code == 200
    # Public browser host cannot reach the desktop or device APIs at all.
    for path in ("/desktop/status", "/projects", "/device/context"):
        assert client.get(path, headers={"Authorization": "Bearer " + ADMIN}).status_code == 403
    with TestClient(app, base_url="https://fire.example.org") as device:
        for authorization in (None, "Bearer " + ADMIN):
            headers = {"X-Forwarded-For": "127.0.0.1", "Cf-Access-Authenticated-User-Email": "owner@example.org"}
            if authorization: headers["Authorization"] = authorization
            assert device.get("/device/context", headers=headers).status_code == 403
        assert device.get("/device/context", headers={"Authorization": "Bearer " + DEVICE}).status_code == 200
        assert device.get("/web/status", headers={"Authorization": "Bearer " + DEVICE}).status_code == 403
    assert client.get("/web/status", headers={"Host": "evil.example.org"}).status_code == 403


@pytest.mark.parametrize("claims", [{"iss": "https://evil.cloudflareaccess.com"}, {"aud": "other"},
    {"exp": 1}, {"iat": time.time()+10000}, {"sub": "other"}])
def test_jwt_claims_are_rechecked_even_with_valid_application_cookie(web, claims):
    client, _, _, token = web
    assert client.get("/web/status", headers={"Cf-Access-Jwt-Assertion": token(**claims)}).status_code == 401


def test_forged_jwt_and_device_token_cannot_sign_browser_in(web):
    client, _, _, token = web
    bad = token()[:-10] + "AAAAAAAAAA"
    assert client.post("/web/login", headers={"Cf-Access-Jwt-Assertion": bad}, json={}).status_code == 401
    client.cookies.clear()
    assert client.get("/web/status", headers={"Authorization": "Bearer " + DEVICE}).status_code == 401
    assert client.post("/web/login", headers={"Cf-Access-Jwt-Assertion": "", "Cf-Access-Authenticated-User-Email": "owner"}, json={}).status_code == 401


@pytest.mark.parametrize("path,method", [("settings", "patch"), ("settings/apply", "post"),
    ("conversations/missing/build", "post"), ("conversations/missing/run", "post"),
    ("apps/missing", "delete"), ("jobs/missing/cancel", "post"),
    ("runtime-ai", "patch"), ("apps/missing/runtime-ai", "patch")])
def test_all_browser_mutations_require_csrf_and_exact_origin(web, path, method):
    client, _, _, _ = web
    call = getattr(client, method)
    assert call("/web/"+path, headers={"X-Fire-CSRF": ""}).status_code == 403
    assert call("/web/"+path, headers={"Origin": "https://evil.example.org"}).status_code == 403


def test_runtime_switch_and_generation_mode_use_existing_authenticated_settings(web):
    client,app,store,_=web
    vault_before=dict(store.vault.data)
    assert client.patch('/web/runtime-ai',json={'enabled':False}).status_code==200
    assert not app.state.backend.settings.fire_runtime_ai_enabled and not store.config.runtime_ai_enabled
    assert client.patch('/web/runtime-ai',json={'enabled':'false'}).status_code==400
    project=app.state.backend.new_project('fire01','device')
    assert client.patch('/web/apps/'+project['id']+'/runtime-ai',json={'enabled':False}).status_code==200
    assert not app.state.backend.runtime_ai.app_enabled(project['id'])
    start=client.post('/web/conversations',json={'device_id':'fire01','runtime_ai_mode':'off'})
    assert start.status_code==200 and start.json()['runtime_ai_mode']=='off'
    sid=start.json()['session_id']
    assert client.post('/web/conversations/'+sid+'/mode',json={'runtime_ai_mode':'auto'}).status_code==200
    assert app.state.backend.sessions[sid].runtime_ai_mode=='auto'
    assert store.config.runtime_ai_developer_mode=='auto'  # Session choice is explicit, not a global rewrite.
    assert store.vault.data==vault_before


def test_local_bootstrap_is_short_lived_single_use_and_never_contains_admin(tmp_path):
    settings = Settings(_env_file=None, fire_ai_mode="mock", fire_workspace=tmp_path,
                        fire_backend_token=ADMIN, fire_desktop_enabled=True)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/desktop/web-login", json={}).status_code in {401, 403}
        result = client.post("/desktop/web-login", headers={"Authorization": "Bearer "+ADMIN}, json={})
        assert result.status_code == 200
        assert ADMIN not in result.text and "?" not in result.json()["path"]
        code = result.json()["path"].split("signin=")[1]
        headers = {"Origin": "http://testserver"}
        assert client.post("/web/local-login", headers=headers, json={"code": code}).status_code == 200
        assert client.post("/web/local-login", headers=headers, json={"code": code}).status_code == 401
        assert client.get("/web/status").status_code == 200
        assert "HttpOnly" in result.headers.get("set-cookie", "") or "fire_session" in client.cookies


def test_offline_authoring_confirmation_gates_and_durable_context(web):
    client, app, _, _ = web
    start = client.post("/web/conversations", json={"device_id": "fire01"})
    assert start.status_code == 200, start.text
    s = start.json(); sid = s["session_id"]
    assert s["target"] == "pc_simulation" and s["desktop_device_id"] == "fire01"
    assert client.post(f"/web/conversations/{sid}/build", json={"proposal_id": "wrong"}).status_code == 409
    assert client.post(f"/web/conversations/{sid}/run", json={"package_id": "wrong"}).status_code == 409
    assert client.post(f"/web/conversations/{sid}/text", json={"text": "Lag en timer"}).status_code == 200
    deadline = time.monotonic()+2
    while time.monotonic() < deadline:
        saved = app.state.backend.store.get("sessions", sid)
        if len(saved.get("history", [])) >= 2: break
        time.sleep(.02)
    assert len(saved["history"]) >= 2
    app.state.backend.sessions.pop(sid)
    resumed = client.post(f"/web/conversations/{sid}/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["session_id"] == sid and resumed.json()["history"] == saved["history"]
    assert app.state.backend.store.list("builds") == []  # No implicit paid build on resume.


def test_write_only_config_uses_same_desktop_store_and_blocks_busy_changes(web):
    client, app, store, _ = web
    key = "sk-fake-only-test-" + "z"*40
    response = client.patch("/web/settings", json={"values": {"speech_enabled": False}, "openai_api_key": key})
    assert response.status_code == 200, response.text
    assert not store.config.speech_enabled and store.secret("openai") == key
    result = client.get("/web/settings")
    assert result.json()["openai_configured"] and key not in result.text
    assert "credential_namespace" not in result.text and ADMIN not in result.text and DEVICE not in result.text
    assert key not in store.path.read_text()
    app.state.backend.active_build_id = "busy"
    client.portal.call(app.state.backend.build_lock.acquire)
    assert client.patch("/web/settings", json={"values": {"speech_enabled": True}}).status_code == 409
    client.portal.call(app.state.backend.build_lock.release)


def test_browser_cancel_retires_turn_and_invalidates_audio(web):
    client, app, _, _ = web
    sid = client.post("/web/conversations", json={"device_id": "fire01"}).json()["session_id"]
    s = app.state.backend.session(sid)
    s.turn_id = "turn-old"
    s.audio_status = {"phase": "playing"}
    assert client.post(f"/web/conversations/{sid}/cancel", json={}).status_code == 200
    assert s.turn_id is None and "turn-old" in s.retired_turns


def test_local_lan_device_transport_preserved_but_browser_admin_is_not_exposed(web):
    _, app, _, _ = web
    with TestClient(app, base_url="http://192.168.1.50:8765") as lan:
        assert lan.get("/device/context", headers={"Authorization": "Bearer "+DEVICE}).status_code == 200
        assert lan.get("/desktop/status", headers={"Authorization": "Bearer "+ADMIN}).status_code == 403
        assert lan.get("/web/status").status_code == 403


def test_static_ui_is_local_csp_restricted_and_contains_no_credentials(web):
    client, _, _, _ = web
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert ADMIN not in response.text and DEVICE not in response.text
    js = client.get("/ui/assets/app.js")
    assert js.status_code == 200 and "history.replaceState" in js.text and "localStorage" not in js.text


def test_openai_mode_never_grants_anonymous_loopback_admin(tmp_path):
    from fire_backend.auth import principal
    settings = Settings(_env_file=None, fire_workspace=tmp_path, fire_ai_mode="openai")
    with pytest.raises(PermissionError): principal(settings, None)

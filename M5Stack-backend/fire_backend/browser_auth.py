"""Browser credentials never become device/admin bearer credentials."""
import asyncio
import hashlib
import hmac
import ipaddress
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import HTTPException
from starlette.responses import PlainTextResponse

COOKIE = "fire_session"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def host_of(value):
    try:
        parsed = urlsplit("//" + value)
        if parsed.username or parsed.path or parsed.query or parsed.fragment:
            return ""
        return parsed.hostname or ""
    except ValueError:
        return ""


@dataclass
class BrowserSession:
    subject: str
    origin: str
    expires: float
    csrf: str
    remote: bool


class BrowserAuth:
    def __init__(self, settings):
        self.settings = settings
        self.sessions = {}
        self.codes = {}
        self.keys = {}
        self.keys_until = 0
        self.last_fetch = -100
        self.key_lock = asyncio.Lock()
        self.failures = {}

    def origin(self, request):
        host = request.headers.get("host", "")
        if self.settings.fire_public_enabled and host_of(host) == urlsplit(self.settings.fire_web_origin).hostname:
            return self.settings.fire_web_origin
        if host_of(host) not in LOCAL_HOSTS:
            raise HTTPException(403, "Host is not allowed")
        return f"http://{host}"

    def origin_check(self, request):
        if request.headers.get("origin") != self.origin(request):
            raise HTTPException(403, "Origin is not allowed")

    async def verify_access(self, token):
        if not self.settings.fire_public_enabled or not token or len(token) > 16384:
            raise HTTPException(401, "Access sign-in required")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError
            kid = header["kid"]
            async with self.key_lock:
                if kid not in self.keys or time.monotonic() >= self.keys_until:
                    if time.monotonic() - self.last_fetch < 30:
                        raise ValueError
                    self.last_fetch = time.monotonic()
                    async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
                        async with client.stream("GET", self.settings.fire_access_issuer + "/cdn-cgi/access/certs") as response:
                            response.raise_for_status()
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                body.extend(chunk)
                                if len(body) > 65536:
                                    raise ValueError
                    import json
                    keys = json.loads(body).get("keys", [])
                    self.keys = {k["kid"]: jwt.PyJWK.from_dict(k).key for k in keys[:8]
                                 if k.get("kty") == "RSA" and k.get("alg", "RS256") == "RS256"}
                    self.keys_until = time.monotonic() + 300
            claims = jwt.decode(token, self.keys[kid], algorithms=["RS256"],
                                issuer=self.settings.fire_access_issuer,
                                audience=self.settings.fire_access_audience,
                                options={"require": ["exp", "iat", "sub", "iss", "aud"]})
            if not isinstance(claims["sub"], str) or not claims["sub"] or claims.get("type", "app") != "app":
                raise ValueError
            return claims
        except (jwt.PyJWTError, ValueError, KeyError, TypeError, httpx.HTTPError):
            raise HTTPException(401, "Access identity could not be verified") from None

    def create(self, response, subject, origin, expires=None, remote=False):
        now = time.time()
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires > now}
        if len(self.sessions) >= 64:
            raise HTTPException(429, "Too many signed-in browsers")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expiry = min(expires or now + 3600, now + 3600)
        self.sessions[digest(token)] = BrowserSession(subject, origin, expiry, csrf, remote)
        response.set_cookie(COOKIE, token, max_age=max(1, int(expiry-now)), httponly=True,
                            secure=origin.startswith("https:"), samesite="strict", path="/")
        return {"signed_in": True, "csrf": csrf, "expires_at": expiry}

    async def require(self, request):
        key = digest(request.cookies.get(COOKIE, ""))
        session = self.sessions.get(key)
        if not session or session.expires <= time.time() or session.origin != self.origin(request):
            self.sessions.pop(key, None)
            raise HTTPException(401, "Sign in again")
        # Remote revocation/expired Access identity cannot be bypassed with an
        # application cookie alone. Verify Access on every protected request.
        if session.remote:
            claims = await self.verify_access(request.headers.get("cf-access-jwt-assertion"))
            if claims["sub"] != session.subject:
                raise HTTPException(401, "Access identity changed")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            self.origin_check(request)
            if not hmac.compare_digest(request.headers.get("x-fire-csrf", "").encode(), session.csrf.encode()):
                raise HTTPException(403, "CSRF check failed")
        return session

    def bootstrap(self):
        self.codes = {k: v for k, v in self.codes.items() if v > time.time()}
        if len(self.codes) >= 8:
            raise HTTPException(429, "Too many sign-in links")
        code = secrets.token_urlsafe(32)
        self.codes[digest(code)] = time.time() + 60
        return code

    def consume(self, code):
        if not isinstance(code, str) or self.codes.pop(digest(code), 0) <= time.time():
            raise HTTPException(401, "Sign-in link expired")


class SurfaceBoundary:
    """Host/path separation also applies to WebSockets; proxy IP grants nothing."""
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = host_of(headers.get("host", ""))
        path = scope.get("path", "")
        raw = scope.get("raw_path", b"").lower()
        local = host in LOCAL_HOSTS
        web = self.settings.fire_public_enabled and host == urlsplit(self.settings.fire_web_origin).hostname
        device = self.settings.fire_public_enabled and host == self.settings.fire_device_host
        try:
            lan = self.settings.fire_backend_host == "0.0.0.0" and ipaddress.ip_address(host).is_private
        except ValueError:
            lan = False
        # Existing reverse-TCP peers use the configured PC's LAN name in Host.
        # A scoped device credential may use that data plane, never web/desktop.
        device_name = False
        if not local and not web and not device:
            from .auth import principal
            try:
                identity = principal(self.settings, headers.get("authorization"))
                device_name = identity != "admin" and (not self.settings.fire_public_enabled or
                              bool(self.settings.fire_reverse_host) and identity == self.settings.fire_reverse_device_id)
            except PermissionError:
                pass
        bad = (sum(k.lower() == b"host" for k, _ in scope.get("headers", [])) != 1
               or not (local or web or device or lan or device_name) or b"%2f" in raw or b"%5c" in raw or "\\" in path or "//" in path)
        if (lan or device_name) and not local and (path == "/" or path.startswith(("/ui", "/web", "/desktop"))):
            bad = True
        if web and not (path in {"/", "/health"} or path.startswith(("/ui", "/web/"))):
            bad = True
        if device and (path == "/" or path.startswith(("/ui", "/web", "/desktop", "/firmware"))):
            bad = True
        if device and path != "/health":
            from .auth import principal
            try:
                if principal(self.settings, headers.get("authorization")) == "admin":
                    bad = True
            except PermissionError:
                bad = True
        if path.startswith("/desktop") and (not local or headers.get("origin")):
            bad = True
        if headers.get("origin") and not path.startswith(("/ui", "/web")) and path != "/":
            bad = True
        if bad:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await PlainTextResponse("Host, path or origin is not allowed", status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)

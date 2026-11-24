"""Read-only GitHub release metadata. Never downloads or stores firmware binaries."""
import asyncio
import base64
import json
import re
import time

import httpx

REPOSITORY = "rikardljokjell-del/M5stack-Fire-OS"
RELEASES = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=12"
INDEX = f"https://raw.githubusercontent.com/{REPOSITORY}/main/firmware/index.json"


async def fetch_json(client, url):
    async with client.stream("GET", url, headers={"Accept": "application/vnd.github+json"}) as result:
        result.raise_for_status()
        body = bytearray()
        async for chunk in result.aiter_bytes():
            body.extend(chunk)
            if len(body) > 1048576:
                raise ValueError
    return json.loads(body)


def index_entries(data):
    """Legacy index and signed-index envelopes are metadata, never trusted OTA approval."""
    if not isinstance(data, dict):
        raise ValueError
    signed = data.get("schema") == 2
    if signed:
        if (set(data) != {"schema", "algorithm", "key_id", "payload", "signature"}
                or data["algorithm"] != "ecdsa-p256-sha256" or not isinstance(data["payload"], str)):
            raise ValueError
        try:
            raw = base64.b64decode(data["payload"], validate=True)
            if len(raw) > 16384:
                raise ValueError
            payload = json.loads(raw)
        except (ValueError, TypeError):
            raise ValueError("Invalid signed firmware metadata") from None
    else:
        payload = data
    if not isinstance(payload, dict):
        raise ValueError
    files = payload.get("files", payload.get("releases", []))
    if not isinstance(files, list):
        raise ValueError
    if payload.get("target") != "m5stack-fire" or payload.get("repository") != REPOSITORY:
        raise ValueError
    if signed and (len(files) > 8 or payload.get("layout") != "fire-ab-recovery-v1" or payload.get("min_recovery") != 1):
        raise ValueError
    return [{"version": str(r.get("version", ""))[:80], "name": str(r.get("name", r.get("version", "")))[:100],
             "notes": str(r.get("notes", r.get("description", "")))[:1500],
             "published_at": r.get("published_at"), "prerelease": bool(r.get("prerelease")),
             "target": r.get("target", payload.get("target")),
             "signed": signed, "legacy_unsigned": not signed,
             "signature_verified": False, "source": "firmware/index.json",
             "compatibility": "Metadata. FIRE kontrollerer target, størrelse, hash og signatur."}
            for r in files[:24] if isinstance(r, dict)]


class FirmwareCatalog:
    def __init__(self):
        self.cached = []
        self.checked = 0
        self.error = ""
        self.lock = asyncio.Lock()

    async def get(self):
        async with self.lock:
            if time.time() - self.checked > 300:
                self.checked = time.time()
                try:
                    async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as client:
                        results = await asyncio.gather(fetch_json(client, INDEX), fetch_json(client, RELEASES), return_exceptions=True)
                    index, data = results
                    entries = index_entries(index) if not isinstance(index, Exception) else []
                    if isinstance(data, Exception):
                        data = []
                    if not isinstance(data, list):
                        raise ValueError
                    releases = [{"version": str(r.get("tag_name", ""))[:80],
                                    "name": str(r.get("name", ""))[:100],
                                    "notes": str(r.get("body", ""))[:1500],
                                    "published_at": r.get("published_at"),
                                    "prerelease": bool(r.get("prerelease")),
                                    "url": f"https://github.com/{REPOSITORY}/releases",
                                    "compatibility": "FIRE kontrollerer target, hash og signatur før installasjon."}
                                   for r in data[:12] if isinstance(r, dict) and not r.get("draft")]
                    self.cached = entries + [r for r in releases if r['version'] not in {e['version'] for e in entries}]
                    if all(isinstance(r, Exception) for r in results):
                        raise ValueError
                    self.error = ""
                except (httpx.HTTPError, ValueError, TypeError):
                    self.error = "GitHub-katalogen kunne ikke hentes. Sist hentede oversikt beholdes."
        return {"releases": self.cached, "checked_at": self.checked, "error": self.error,
                "source": f"https://github.com/{REPOSITORY}/tree/main/firmware", "read_only": True}

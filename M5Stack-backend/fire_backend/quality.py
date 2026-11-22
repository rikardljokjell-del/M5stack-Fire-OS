"""Evidence-based app repair memory. Device text never becomes executable policy."""
import hashlib
import json
import re
import time
import zipfile

from .storage import new_id

RULES = {
    "bounds": "Clamp display coordinates and RGB values; use finite integers and keep moving objects within screen bounds.",
    "nil": "Initialize state before callbacks. Check table indices, empty lists and missing values, including after reset and collisions.",
    "budget": "Keep callbacks short and bounded; cap table growth, loops and drawing operations over the entire run.",
    "api": "Use only declared fire APIs and the restricted base/math functions. Do not assume standard Lua libraries exist.",
    "text": "Display strings must fit 80 UTF-8 bytes. Format numbers safely without relying on unavailable string APIs.",
    "runtime": "Exercise init, update, reset, each button held and rapid input across the full advertised runtime. Inspect all branches.",
}


def failure_class(message):
    text = message.lower()
    if any(word in text for word in ("bounds", "integer", "range", "coordinate")): return "bounds"
    if any(word in text for word in ("nil", "index", "length")): return "nil"
    if any(word in text for word in ("memory", "budget", "timeout", "instruction")): return "budget"
    if any(word in text for word in ("text exceeds", "utf-8")): return "text"
    if any(word in text for word in ("api", "undeclared", "forbidden", "unsupported")): return "api"
    return "runtime"


class Quality:
    def __init__(self, store):
        self.store = store

    def record(self, *, project_id, package_id=None, source_hash=None, message, provenance, device_id=None, build_id=None):
        category = failure_class(message)
        safe = self.store.redactor.text(message)[:1200]
        fingerprint = hashlib.sha256(json.dumps([project_id, package_id, source_hash, category, safe, provenance], ensure_ascii=True).encode()).hexdigest()[:32]
        case_id = "case-" + fingerprint
        try:
            case = self.store.get("quality", case_id)
        except FileNotFoundError:
            case = {"id":case_id,"project_id":project_id,"package_id":package_id,"source_sha256":source_hash,
                    "device_id":device_id,"build_id":build_id,"category":category,"message":safe,
                    "provenance":provenance,"status":"open","first_seen":time.time(),"count":0}
        case.update(count=case["count"]+1,last_seen=time.time())
        self.store.put("quality",case_id,case,critical=True)
        self.store.put("quality", "rule-"+category,
            {"id":"rule-"+category,"project_id":None,"category":category,"provenance":"fixed_rule_registry"},critical=True)
        if package_id:
            package=self.store.get("packages",package_id)
            package["quality"]={"blocked":True,"case_id":case_id,"reason":category}
            self.store.put("packages",package_id,package,critical=True)
        return case

    def record_validation(self, build, source, message):
        return self.record(project_id=build["project_id"], build_id=build["id"],
            source_hash=hashlib.sha256(source.encode()).hexdigest(), message=message, provenance="release_validator")

    def cases(self, project_id):
        return sorted((x for x in self.store.list("quality") if x["project_id"]==project_id),key=lambda x:x["last_seen"],reverse=True)[:12]

    def policy(self):
        # Only fixed, reviewed rules are promoted. No generated prompt/code from logs.
        categories={case["category"] for case in self.store.list("quality")}
        return "\nLearned regression precautions (fixed rules from observed failures):\n"+"\n".join(RULES[k] for k in sorted(categories) if k in RULES) if categories else ""

    def reject_known_failure(self, project_id, source_hash):
        if any(c.get("project_id")==project_id and c.get("source_sha256")==source_hash and c.get("package_id") for c in self.store.list("quality")):
            raise ValueError("Generated source is identical to a version reported broken. Make a substantive repair before release.")

    async def diagnose(self, service, session, text):
        from .builds import validate_release, verify_archive
        project=self.store.get("projects",session.project_id)
        package_id=session.base_package_id or project.get("latest_package")
        if not package_id: return None
        package=self.store.get("packages",package_id)
        if package["project_id"]!=session.project_id: raise PermissionError("Repair package scope mismatch")
        path=self.store.path("packages",package_id,".zip")
        verify_archive(path,package["manifest"],package["archive_sha256"])
        report=self.record(project_id=session.project_id,package_id=package_id,device_id=session.device_id,
            source_hash=package["manifest"]["checksum"],message=text,provenance="user_report")
        with zipfile.ZipFile(path) as archive:
            source=archive.read(f"apps/{package['manifest']['id']}/main.lua").decode("utf-8")
        reproduced=False
        error="Not reproduced on PC; preserve requirements and harden the app using correlated device evidence."
        try:
            await validate_release({**package["manifest"],"main_lua":source},self.store,session.id)
        except (ValueError,TimeoutError) as failure:
            reproduced=True
            error=self.store.redactor.text(str(failure))[:2400]
            self.record(project_id=session.project_id,package_id=package_id,source_hash=package["manifest"]["checksum"],
                        message=error,provenance="repair_reproduction",device_id=session.device_id)
        evidence=[{k:c.get(k) for k in ("id","category","message","provenance","package_id")} for c in self.cases(session.project_id) if c.get("package_id")==package_id]
        result={"package_id":package_id,"source_sha256":package["manifest"]["checksum"],"reproduced_on_pc":reproduced,
                "validator_error":error,"cases":evidence[:6],"case_id":report["id"]}
        self.store.put("quality",report["id"],{**self.store.get("quality",report["id"]),"diagnosis":result},critical=True)
        return result

    def candidate(self, project_id, failed_package_id, candidate_id):
        for case in self.cases(project_id):
            if case.get("package_id")==failed_package_id:
                case.update(status="candidate_validated_on_pc",candidate_package_id=candidate_id)
                self.store.put("quality",case["id"],case,critical=True)

    def observed_healthy(self, project_id, package_id):
        for case in self.cases(project_id):
            if case.get("candidate_package_id")==package_id:
                case.update(status="device_reported_healthy",healthy_at=time.time())
                self.store.put("quality",case["id"],case,critical=True)


def require_deliverable(package):
    if package.get("quality",{}).get("blocked"):
        raise ValueError("Denne appversjonen er sperret etter en feil. Velg appen og be om reparasjon for en ny testet versjon.")
    if package.get("validation",{}).get("suite") != "release-v1":
        raise ValueError("Denne eldre pakken mangler utvidet kjøretidstest. Velg appen og be om reparasjon/ny bygging før levering.")


def repair_requested(text):
    return bool(re.search(r"\b(fiks|reparer|feilsøk|feilsok|fix|repair|debug)\b|\b(rett|rette|undersøk|undersøke)\b.*\b(feil|app)|(?:funker|fungerer|virker|kjører|starter|works|run)\s+(?:ikke|not)|ikke\s+(?:fungerer|virker|kjører)",text,re.I))

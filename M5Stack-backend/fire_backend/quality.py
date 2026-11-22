"""Evidence-based app repair memory. Device text never becomes executable policy."""
import hashlib
import json
import re
import time
import zipfile
import unicodedata
from difflib import SequenceMatcher

from .storage import new_id
from .rendering import VISUAL_POLICY


class RepairChoiceNeeded(ValueError):
    """A real ambiguity, never a request for device debugging."""


def name_words(text):
    text = text.casefold().replace("æ", "ae").replace("ø", "o")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    words = re.findall(r"[a-z0-9]+", text)
    def stem(word):
        for suffix in ("ene", "en", "et"):
            if len(word) - len(suffix) >= 4 and word.endswith(suffix):
                return word[:-len(suffix)]
        return word
    return {stem(w) for w in words if w not in {"app", "appen", "program", "programmet"}}

RULES = {
    "rendering": VISUAL_POLICY,
    "bounds": "Clamp display coordinates and RGB values; use finite integers and keep moving objects within screen bounds.",
    "nil": "Initialize state before callbacks. Check table indices, empty lists and missing values, including after reset and collisions.",
    "budget": "Keep callbacks short and bounded: at most 24 output operations and 120000 display-work units per callback. Simplify a complete visible scene instead of splitting its drawing across updates; nonvisual preparation may be spread over updates. Cap tables/loops. Compile/top-level timing and a null Lua VM are firmware issues, not fixes achievable by cosmetic app rewrites.",
    "api": "Use only declared fire APIs and the restricted base/math functions. Do not assume standard Lua libraries exist.",
    "text": "Display strings must fit 80 UTF-8 bytes. Format numbers safely without relying on unavailable string APIs.",
    "runtime": "Exercise init, update, reset, each button held and rapid input across the full advertised runtime. Inspect all branches.",
}


def failure_class(message):
    text = message.lower()
    if "visual frame" in text or any(word in text for word in ("flimr", "flimmer", "flicker", "blank frame")): return "rendering"
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

    def feedback(self, session, event):
        if event.event not in {"device_install_result","app_started","app_healthy","app_failed","app_stopped","app_diagnostic"}:
            return
        package=self.store.get("packages",event.package_id)
        report={"id":event.event_id or new_id("feedback"),"device_id":session.device_id,"boot_id":session.boot_id,
                "project_id":package["project_id"],"package_id":package["id"],"source_sha256":package["manifest"]["checksum"],
                "event":event.event,"reported_at":time.time(),"error_code":event.error_code,"message":event.message,
                "diagnostics":event.diagnostics.model_dump(exclude_none=True) if event.diagnostics else {}}
        self.store.put("feedback",report["id"],report,critical=True)
        prior=sorted((r for r in self.store.list("feedback") if r["device_id"]==session.device_id),key=lambda r:r["reported_at"],reverse=True)
        for old in prior[100:]:self.store.path("feedback",old["id"]).unlink(missing_ok=True)

    def cases(self, project_id):
        return sorted((x for x in self.store.list("quality") if x["project_id"]==project_id),key=lambda x:x["last_seen"],reverse=True)[:12]

    def policy(self):
        # Only fixed, reviewed rules are promoted. No generated prompt/code from logs.
        categories={case["category"] for case in self.store.list("quality")}
        return "\nLearned regression precautions (fixed rules from observed failures):\n"+"\n".join(RULES[k] for k in sorted(categories) if k in RULES) if categories else ""

    def reject_known_failure(self, project_id, source_hash):
        if any(c.get("project_id")==project_id and c.get("source_sha256")==source_hash and c.get("package_id") for c in self.store.list("quality")):
            raise ValueError("Generated source is identical to a version reported broken. Make a substantive repair before release.")

    def repair_target(self, service, session, text, *, source="text", continuing_repair=False):
        owner = session.device_id if session.target == "device" else session.desktop_device_id
        projects = [p for p in self.store.list("projects") if p.get("owner_device_id") == owner and service.app_versions(p)]
        words = name_words(text)
        selected = next((p for p in projects if p["id"] == session.project_id and
                         any(v["id"] == session.base_package_id for v in service.app_versions(p))), None)
        explicit_switch = bool(re.search(r"\b(bytt|annen|annet|isteden|instead|switch)\b|i stedet|\b(?:lag|opprett|create)\b", text, re.I))
        resembles_selected = selected and any(SequenceMatcher(None, heard, known).ratio() >= 0.6
            for heard in words if len(heard) >= 5 for known in name_words(selected["name"]) if len(known) >= 5)
        voice_focus = bool(selected and session.app_mode == "update" and source == "voice" and not explicit_switch)
        matches = []
        for project in projects:
            versions = service.app_versions(project)
            aliases = [project.get("name", ""), service.project_app_id(project) or ""]
            aliases += [p["manifest"]["name"] for p in versions]
            score = max((len(n) for alias in aliases if (n := name_words(alias)) and n <= words), default=0)
            if score:
                matches.append((score, project))
        if voice_focus and resembles_selected:
            project = selected
        elif matches:
            best = max(score for score, _ in matches)
            choices = [p for score, p in matches if score == best]
            if len(choices) != 1:
                raise RepairChoiceNeeded("Hvilken app mener du: " + ", ".join(p["name"]+" ("+str(service.project_app_id(p))+")" for p in choices[:4]) + "?")
            project = choices[0]
        else:
            # ASR names are uncertain. Explicit picker/base identity and an
            # ongoing repair outrank an unrecognized spoken name, unless the
            # user clearly switches tasks. A recognized other app still wins.
            use_focus = bool(selected and session.app_mode == "update" and not explicit_switch and
                             (source == "voice" or continuing_repair and resembles_selected))
            subject = re.search(r"\b(?:fiks|reparer|fix|repair)\s+([^.!?,]+)", text, re.I)
            generic = {"den", "det", "denne", "dette", "feil", "feilen", "problem", "problemet", "spill", "spillet", "som", "ikke", "funger", "fungerer", "er", "min", "mitt", "meg", "for", "a", "og"}
            if subject and name_words(subject[1]) - generic and not use_focus:
                raise RepairChoiceNeeded("Jeg finner ikke appen du nevner. Tilgjengelige apper: " + ", ".join(p["name"] for p in projects[:4]) + ".")
            if explicit_switch:
                raise RepairChoiceNeeded("Hvilken app vil du bytte til: " + ", ".join(p["name"] for p in projects[:4]) + "?")
            project = selected or next((p for p in projects if p["id"] == session.project_id), None)
            if project is None and session.target == "device":
                device = service.device_record(session)
                package_ids = {device.get("running_package_id"), device.get("installed_package_id")}
                focused = [p for p in projects if any(v["id"] in package_ids for v in service.app_versions(p))]
                if len(focused) == 1:
                    project = focused[0]
            if project is None and len(projects) == 1:
                project = projects[0]
            if project is None:
                raise RepairChoiceNeeded("Hvilken app skal jeg reparere: " + ", ".join(p["name"] for p in projects[:4]) + "?" if projects else "Jeg finner ingen lagret app på denne enheten.")
        if project["id"] == session.project_id and session.base_package_id:
            package = next((p for p in service.app_versions(project) if p["id"] == session.base_package_id), None)
            if package:
                return project, package
        if session.target == "device":
            return project, service.update_base(project, service.device_record(session))
        return project, service.app_versions(project)[0]

    async def select_repair_target(self, service, session, text, *, source="text", continuing_repair=False):
        project, package = self.repair_target(service, session, text, source=source, continuing_repair=continuing_repair)
        # Source identity is verified in diagnose before it is used. Do not use
        # select_app here: it clears the active audio turn and takes its lock.
        if session.target == "device":
            device = service.device_record(session)
            if device.get("active_run_id") or device.get("pending_run_id") or device.get("pending_rollback_id"):
                raise ValueError("Venter på at forrige appoperasjon avsluttes før reparasjon.")
            for pending in service.pending_commands(session):
                if pending["kind"] == "install":
                    service.finish_command(pending, "superseded")
                    if device.get("pending_install_id") == pending["id"]:
                        device["pending_install_id"] = None
            device.update(project_id=project["id"], **{k:device.get("projects",{}).get(project["id"],{}).get(k) for k in ("current","previous","backup")})
            session.app_revision = device.get("app_change_counter", 0)
            self.store.put("devices", device["id"], device)
        if session.project_id != project["id"]:
            await service.close_dialog(session)
            session.resume_project_aliases = (session.resume_project_aliases + [session.project_id])[-8:]
            session.history = session.history[-1:]  # Keep this request; no other app's dialogue.
        session.project_id, session.base_package_id = project["id"], package["id"]
        session.app_mode, session.install_permitted = "update", True
        session.package_id = session.build_id = None
        await service.emit(session, {"type":"app_selected","app_mode":"update","project_id":project["id"],
            "app_id":package["manifest"]["id"],"base_package_id":package["id"],"name":package["manifest"]["name"]})
        return package

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
        native = sorted((c for c in self.store.list("quality") if c.get("project_id")==session.project_id and c.get("package_id")==package_id
            and c.get("provenance") in {"device_receipt","device_diagnostic"}),key=lambda c:c["last_seen"],reverse=True)
        device = service.device_record(session) if session.target=="device" else {}
        failed_this_boot = (device.get("runtime_status")=="failed" or
            device.get("last_failure_boot_id")==session.boot_id and device.get("last_failure_package_id")==package_id or
            any(c.get("kind")=="run" and c.get("status")=="failed" and c.get("device_id")==session.device_id
                and c.get("boot_id")==session.boot_id and c.get("package_id")==package_id for c in self.store.list("commands")))
        result["blocked_device_runtime"] = bool(native and "invalid lua source" in native[0]["message"].lower()
            and failed_this_boot and device.get("installed_package_id")==package_id)
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
    if package.get("validation",{}).get("suite") != "release-v3":
        raise ValueError("Denne eldre pakken mangler utvidet kjøretidstest. Velg appen og be om reparasjon/ny bygging før levering.")


def repair_requested(text):
    return bool(re.search(r"\b(fiks|reparer|feilsøk|feilsok|fix|repair|debug)\b|\b(rett|rette|undersøk|undersøke)\b.*\b(feil|app)|(?:funker|fungerer|virker|kjører|starter|works|run)\s+(?:ikke|not)|ikke\s+(?:fungerer|virker|kjører)",text,re.I))

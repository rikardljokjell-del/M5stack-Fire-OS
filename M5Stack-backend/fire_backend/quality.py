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
from .failure_learning import REGRESSION_CHECKS,regression_evidence,repair_delta,source_delta,source_from_archive,source_guard_eligible


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
    "audio_level":"Primary audio uses relative channel gain255/255 by default under OS master/mute. Do not mistake byte gain for percentage or hide near-muted defaults; exercise sound-enabled playback and immediate stop.",
    "rendering": VISUAL_POLICY,
    "bounds": "Clamp display coordinates and RGB values; use finite integers and keep moving objects within screen bounds.",
    "nil": "Initialize state before callbacks. Check table indices, empty lists and missing values, including after reset and collisions.",
    "budget": "Keep callbacks short and bounded: at most 24 output operations, 256 text bytes and 120000 display-work units per callback. Cache text/rotation/state transformations outside the hot rendering path. At most ONE rgb.set per callback: the current native adapter synchronously sends the WHOLE strip. Queue changed LEDs across updates; never resend unchanged colours. At most 128 cumulative grid cells, INCLUDING black cells; native grid performs fillRect per cell. Exercise the cold first frame with real rendering and initial RGB together. Simplify a complete visible scene instead of splitting its drawing across updates. Cap tables/loops. PC budgets are risk proxies, not ESP32 timing guarantees; native callbacks must account for host calls and preemption.",
    "api": "Use only declared fire APIs and the restricted base/math functions. Do not assume standard Lua libraries exist.",
    "text": "Display strings must fit 80 UTF-8 bytes. Format numbers safely without relying on unavailable string APIs.",
    "runtime": "Exercise init, update, reset, each button held and rapid input across the full advertised runtime. Inspect all branches.",
    "installation": "Do not rewrite valid app code for a failed transfer or unavailable SD. Preserve the tested package and diagnose storage/transfer before retrying installation.",
}


def failure_class(message):
    text = message.lower()
    if any(word in text for word in ("audio_level_ok","audio gain","lydstyrke","inaudible")):return "audio_level"
    if "design:" in text or "visual_quality_ok" in text:return "design"
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

    def record(self, *, project_id, package_id=None, source_hash=None, message, provenance, device_id=None, build_id=None,block_package=True):
        package=self.store.get("packages",package_id) if package_id else None
        source_hash=source_hash or (package["manifest"]["checksum"] if package else None)
        category = "installation" if provenance=="device_installation" else failure_class(message)
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
        case.setdefault("regression",regression_evidence(category))
        case.setdefault("failure_evidence",{"source_sha256":source_hash,"provenance":provenance,
            "physical_failure_observed":provenance in {"device_receipt","device_diagnostic"},"root_cause_verified":False})
        self.store.put("quality",case_id,case,critical=True)
        self.store.put("quality", "rule-"+category,
            {"id":"rule-"+category,"project_id":None,"category":category,"provenance":"fixed_rule_registry"},critical=True)
        if package_id and block_package:
            package["quality"]={"blocked":True,"case_id":case_id,"reason":category}
            self.store.put("packages",package_id,package,critical=True)
        if package and source_hash and re.fullmatch(r"[a-f0-9]{64}",source_hash) and source_guard_eligible(provenance,package,safe):
            # Survives deletion without retaining app names, source or logs.
            guard_id="bad-source-"+source_hash[:48]
            self.store.put("quality",guard_id,{"id":guard_id,"project_id":None,"category":category,
                "source_sha256":source_hash,"provenance":"observed_native_source_failure", "last_seen":time.time()},critical=True)
        if package_id and provenance in {"device_receipt","device_diagnostic"}:
            for prior in self._project_cases(project_id):
                if prior.get("candidate_package_id")==package_id:
                    prior.update(status="candidate_failed_on_device",candidate_failure_case_id=case_id)
                    if prior.get("fix"):
                        prior["fix"].update(status="failed_on_device",physical_resolution_verified=False)
                    self.store.put("quality",prior["id"],prior,critical=True)
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
        if event.event=="device_install_result" and event.status=="failed":
            self.record(project_id=package["project_id"],package_id=package["id"],device_id=session.device_id,
                source_hash=package["manifest"]["checksum"],message=(event.error_code or "install_failed")+": "+(event.message or ""),
                provenance="device_installation",block_package=False)
        if event.event in {"app_failed","app_diagnostic","device_install_result"}:
            matching={"app_failed":"device_receipt","app_diagnostic":"device_diagnostic","device_install_result":"device_installation"}[event.event]
            for case in self._project_cases(package["project_id"]):
                if case.get("package_id")==package["id"] and case.get("provenance")==matching:
                    case.setdefault("failure_evidence",{})["latest_feedback"]={
                        "event_id":report["id"],"event":event.event,"boot_id":session.boot_id,
                        "run_id":event.run_id,"error_code":event.error_code,"diagnostics":report["diagnostics"]}
                    self.store.put("quality",case["id"],case,critical=True)
                    break
        prior=sorted((r for r in self.store.list("feedback") if r["device_id"]==session.device_id),key=lambda r:r["reported_at"],reverse=True)
        for old in prior[100:]:self.store.path("feedback",old["id"]).unlink(missing_ok=True)

    def _project_cases(self,project_id):
        return sorted((x for x in self.store.list("quality") if x.get("project_id")==project_id),key=lambda x:x.get("last_seen",0),reverse=True)

    def cases(self, project_id):
        return self._project_cases(project_id)[:12]

    def policy(self):
        # Only fixed, reviewed rules are promoted. No generated prompt/code from logs.
        categories={case["category"] for case in self.store.list("quality")}
        # The full mandatory design policy is supplied once by the builder.
        # Repeating it here used to multiply every generation/review prompt.
        rules={**RULES,"design":"Apply the mandatory FIRE experience policy: coherent full-screen layout, readable hierarchy, predictable three-button controls, complete scenes and verified settings/effects."}
        return ("\nLearned regression precautions (fixed rules from observed failures):\n"+"\n".join(rules[k] for k in sorted(categories) if k in rules)
            +"\nRequired regression checks:\n"+"\n".join(REGRESSION_CHECKS[k] for k in sorted(categories) if k in REGRESSION_CHECKS)) if categories else ""

    def reject_known_failure(self, project_id, source_hash):
        if any(c.get("provenance")=="observed_native_source_failure" and c.get("source_sha256")==source_hash for c in self.store.list("quality")):
            raise ValueError("Generated source is identical to a live app with an observed native runtime failure. Make a substantive repair before release.")
        if any(c.get("project_id")==project_id and c.get("source_sha256")==source_hash and c.get("package_id")
               and c.get("provenance") not in {"device_installation","package_contract"} for c in self.store.list("quality")):
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
            resources=(session.capabilities or {}).get("hardware") or package.get("validation",{}).get("resources_used",{})
            await validate_release({**package["manifest"],"main_lua":source,"hardware":resources},self.store,session.id)
        except (ValueError,TimeoutError) as failure:
            reproduced=True
            error=self.store.redactor.text(str(failure))[:2400]
            self.record(project_id=session.project_id,package_id=package_id,source_hash=package["manifest"]["checksum"],
                        message=error,provenance="repair_reproduction",device_id=session.device_id)
        evidence=[{k:c.get(k) for k in ("id","category","message","provenance","package_id","regression","fix")} for c in self.cases(session.project_id) if c.get("package_id")==package_id]
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
        old=self.store.get("packages",failed_package_id);candidate=self.store.get("packages",candidate_id)
        if old["project_id"]!=project_id or candidate["project_id"]!=project_id:
            raise PermissionError("Repair evidence package scope mismatch")
        delta=repair_delta(self.store,old,candidate)
        for case in self._project_cases(project_id):
            if case.get("package_id")==failed_package_id:
                case.update(status="candidate_validated_on_pc",candidate_package_id=candidate_id)
                if case.get("fix") and case["fix"].get("candidate_package_id")!=candidate_id:
                    case["fix_history"]=(case.get("fix_history",[])+[case["fix"]])[-4:]
                case["fix"]={**delta,"status":"candidate_on_pc" if delta["source_changed"] else "candidate_unchanged",
                    "category":case["category"],"rule_id":regression_evidence(case["category"])["rule_id"],
                    "required_regression_check":REGRESSION_CHECKS.get(case["category"],REGRESSION_CHECKS["runtime"]),
                    "candidate_package_id":candidate_id,"recorded_at":time.time()}
                case["fix"]["summary"]=("Ny kandidat med endret kilde" if delta["source_changed"] else "Kandidaten har uendret kilde")+"; PC-validert, men fysisk feilretting er ikke bekreftet."
                self.store.put("quality",case["id"],case,critical=True)

    def validated_build(self,build_id,package_id):
        """Connect internal rejected attempts to the first deliverable candidate."""
        package=self.store.get("packages",package_id)
        build=self.store.get("builds",build_id)
        if package["build_id"]!=build_id or package["project_id"]!=build["project_id"]:
            raise PermissionError("Internal repair evidence build scope mismatch")
        cases=[c for c in self._project_cases(package["project_id"])
               if c.get("build_id")==build_id and c.get("package_id") is None][:4]
        if not cases:return
        final_source=source_from_archive(self.store,package)
        folder=self.store.path("builds",build_id,"")
        attempts={}
        for number in range(1,5):
            path=folder/f"attempt-{number}.lua"
            if path.is_file() and path.stat().st_size<=100000:
                payload=path.read_bytes()
                attempts[hashlib.sha256(payload).hexdigest()]=(number,payload.decode("utf-8"))
        review_summary=(package.get("validation",{}).get("pre_delivery_review",{}).get("checks",{}).get("repair_summary") or "")
        for case in cases:
            prior=attempts.get(case.get("source_sha256"))
            delta=source_delta(prior[1],final_source,None,package.get("validation")) if prior else {
                "from_source_sha256":case.get("source_sha256"),"candidate_source_sha256":package["manifest"]["checksum"],
                "source_changed":case.get("source_sha256")!=package["manifest"]["checksum"],
                "delta_status":"source_unavailable","semantic_fix_verified":False,"physical_resolution_verified":False}
            case.update(status="candidate_validated_on_pc",candidate_package_id=package_id)
            case["fix"]={**delta,"status":"candidate_on_pc" if delta["source_changed"] else "candidate_unchanged",
                "origin":"internal_correction","failed_attempt":prior[0] if prior else None,
                "candidate_package_id":package_id,"recorded_at":time.time(),"category":case["category"],
                "rule_id":regression_evidence(case["category"])["rule_id"],
                "required_regression_check":REGRESSION_CHECKS.get(case["category"],REGRESSION_CHECKS["runtime"]),
                "summary":"Internt avvist forsøk er knyttet til PC-validert kandidat; fysisk feilretting er ikke bekreftet."}
            if review_summary:
                case["fix"].update(reviewer_summary=self.store.redactor.text(str(review_summary))[:1200],
                                  reviewer_summary_provenance="model_review_unverified")
            self.store.put("quality",case["id"],case,critical=True)

    def observed_healthy(self, project_id, package_id):
        for case in self._project_cases(project_id):
            if case.get("candidate_package_id")==package_id:
                case["healthy_at"]=time.time()
                if case.get("status")!="candidate_failed_on_device":case["status"]="device_reported_healthy"
                if case.get("fix") and case["fix"].get("status")!="failed_on_device":
                    case["fix"].update(status="initial_device_observation",physical_resolution_verified=False)
                self.store.put("quality",case["id"],case,critical=True)


def require_deliverable(package):
    if package.get("quality",{}).get("blocked"):
        raise ValueError("Denne appversjonen er sperret etter en feil. Velg appen og be om reparasjon for en ny testet versjon.")
    if package.get("validation",{}).get("suite") != "release-v4":
        raise ValueError("Denne eldre pakken mangler utvidet kjøretidstest. Velg appen og be om reparasjon/ny bygging før levering.")
    validation=package.get("validation",{})
    if validation.get("native_host_policy"):
        from .rendering import NATIVE_HOST_POLICY
        profiles=validation.get("profiles") or []
        if (validation["native_host_policy"]!=NATIVE_HOST_POLICY or not profiles or
                any(type(p.get("max_callback_rgb_calls")) is not int or not 0<=p["max_callback_rgb_calls"]<=1 or
                    type(p.get("max_callback_grid_cells")) is not int or not 0<=p["max_callback_grid_cells"]<=128 for p in profiles)):
            raise ValueError("Appversjonen mangler bestått kontroll av native RGB-/grid-belastning.")
    if validation.get("pre_delivery_review_required"):
        review=validation.get("pre_delivery_review") or {}
        from .app_quality import AppReview
        try:
            schema=AppReview
            if "experience_policy_version" in review:
                from .app_quality import FireAppReview,UX_POLICY_VERSION
                if review["experience_policy_version"] not in {"fire-experience-v1",UX_POLICY_VERSION}:raise ValueError("Unsupported experience policy")
                schema=FireAppReview
            checks_ok=schema.model_validate(review.get("checks",{})).approved
        except ValueError:checks_ok=False
        if (review.get("approved") is not True or review.get("source_sha256")!=package["manifest"]["checksum"]
                or not checks_ok or package.get("mode")=="openai" and review.get("mode")!="openai_source_review"):
            raise ValueError("Appversjonen mangler godkjent funksjons- og designkontroll for denne kildekoden.")


def repair_requested(text):
    return bool(re.search(r"\b(fiks|reparer|feilsøk|feilsok|fix|repair|debug)\b|\b(rett|rette|undersøk|undersøke)\b.*\b(feil|app)|(?:funker|fungerer|virker|kjører|starter|works|run)\s+(?:ikke|not)|ikke\s+(?:fungerer|virker|kjører)",text,re.I))

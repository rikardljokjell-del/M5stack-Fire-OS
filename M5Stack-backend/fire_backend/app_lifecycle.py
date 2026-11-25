"""Device app presence, explicit project selection and immutable version history."""
import time

from .models import State
from .storage import new_id
from .app_manager import AppManager


class AppLifecycle(AppManager):
    async def request_inventory(self, session):
        if session.target != "device":
            return
        device = self.device_record(session)
        device.update(inventory_status="requested", inventory_requested_at=time.time())
        self.store.put("devices", device["id"], device)
        await self.emit(session, {"type": "app_inventory_request", "reason": "connection", "boot_id": session.boot_id})

    def new_project(self, device_id, target):
        project = {"id": new_id("app"), "name": "Ny app", "current": None, "previous": None,
                   "backup": None, "candidate": None, "latest_package": None, "next_version": 1,
                   "schema_version": 2, "owner_device_id": device_id if target == "device" else None}
        self.store.put("projects", project["id"], project)
        return project

    def project_app_id(self, project):
        if project.get("app_id"):
            return project["app_id"]
        if project.get("latest_package"):
            return self.store.get("packages", project["latest_package"])["manifest"]["id"]
        return None

    def app_project(self, device_id, project_id=None, app_id=None):
        if project_id:
            try:
                project = self.store.get("projects", project_id)
            except FileNotFoundError:
                # Continue app currently falls back to the SD folder ID.
                if app_id and app_id != project_id:
                    raise ValueError("Ulike app-/prosjekt-ID-er.") from None
                return self.app_project(device_id, app_id=project_id)
            if project.get("owner_device_id") != device_id:
                raise PermissionError("Appen tilhører en annen enhet.")
            if app_id and self.project_app_id(project) != app_id:
                raise ValueError("app_id og project_id peker på ulike apper.")
            return project
        matches = [p for p in self.store.list("projects") if p.get("owner_device_id") == device_id
                   and self.project_app_id(p) == app_id]
        if len(matches) != 1:
            raise ValueError("Velg en app som finnes i denne enhetens backendhistorikk.")
        return matches[0]

    def app_versions(self, project):
        builds = {b["id"]: b for b in self.store.list("builds")}
        packages = [p for p in self.store.list("packages") if p["project_id"] == project["id"]
                    and builds.get(p["build_id"], {}).get("status") == "ready"]
        return sorted(packages, key=lambda p: int(p["manifest"]["version"].split(".")[-1]), reverse=True)

    def app_presence(self, device, app_id):
        return device.get("apps", {}).get(app_id, {})

    def update_base(self, project, device):
        versions = self.app_versions(project)
        if not versions:
            raise ValueError("Appen har ingen testet versjon å oppdatere.")
        present = self.app_presence(device, self.project_app_id(project))
        candidates = [present.get("package_id"), device.get("projects", {}).get(project["id"], {}).get("current"),
                      project.get("latest_package")]
        return next((p for candidate in candidates for p in versions if p["id"] == candidate), versions[0])

    def backend_delete_check(self, project, *, ignore_session_id=None):
        if any(r['project_id']==project['id'] for r in self.data_engine.tasks.values()):
            return False,'Databehandling pågår. Vent eller avbryt først.'
        if any(r['project_id']==project['id'] for r in self.runtime_ai.tasks.values()):
            return False,'AI-analyse pågår. Vent eller avbryt først.'
        if any(item['build']['project_id']==project['id'] and not item['task'].done() for item in self.device_builds.values()):
            return False,'Appen bygges i bakgrunnen.'
        if self.repairs.active_project(project['id']):
            return False,'Appen repareres i bakgrunnen. Vent til reparasjonen er ferdig før sletting.'
        device_id = project.get("owner_device_id")
        active=[s for s in self.sessions.values() if not s.stopped and s.project_id==project["id"] and s.id!=ignore_session_id]
        if any(s.desktop_device_id for s in active):
            return False,"Appen er åpen i en PC-samtale. Avslutt PC-samtalen før sletting."
        if active:
            return False, "Velg Ny app eller en annen app før historikken slettes."
        if any(p["id"] in self.active_downloads for p in self.app_versions(project)):
            return False, "En nedlasting av appen pågår fortsatt."
        if not device_id:  # Existing PC-only mock projects never assert SD state.
            return True, ""
        try:
            device = self.store.get("devices", device_id)
        except FileNotFoundError:
            return False, "FIRE har ikke bekreftet at appen er slettet."
        presence = self.app_presence(device, self.project_app_id(project))
        if (not device.get("online") or device.get("storage_ready") is not True
                or presence.get("boot_id") != device.get("boot_id")
                or presence.get("connection_epoch") != device.get("connection_epoch")
                or presence.get("reported_at", 0) < device.get("last_storage_failure_at", 0)
                or presence.get("state") not in {"deleted", "missing"}):
            if device.get("online") and device.get("inventory_status") == "requested":
                return False, "FIRE har ikke levert en oppdatert SD-oversikt ennå. Firmware må bekrefte slettingen før PC-historikken kan slettes."
            return False, "FIRE må være tilkoblet og bekrefte at appen er borte fra SD-kortet."
        package_ids = {p["id"] for p in self.app_versions(project)}
        if any(c["package_id"] in package_ids and c["status"] in {"pending", "started", "healthy"}
               for c in self.store.list("commands")):
            return False, "En appoperasjon pågår fortsatt."
        return True, ""

    def delete_app_history(self, project):
        allowed, reason = self.backend_delete_check(project)
        if not allowed:
            raise ValueError(reason)
        package_ids = {p["id"] for p in self.store.list("packages") if p["project_id"] == project["id"]}
        # Do not discard someone else's retained references, even if corrupt
        # legacy metadata accidentally points across device ownership.
        for device in self.store.list("devices"):
            refs = any(device.get(k) in package_ids for k in ("current", "previous", "backup", "installed_package_id", "running_package_id"))
            if (refs or device.get("projects", {}).get(project["id"])) and device["id"] != project.get("owner_device_id"):
                raise ValueError("En annen enhet har fortsatt referanser til appen.")
        for saved in self.store.list("sessions"):
            if saved["project_id"] == project["id"]:
                saved.update(stopped=True, proposal_id=None, package_id=None, history=[], summary="", progress={},
                             build_id=None, base_package_id=None, last_error="", audio_status={}, turn_id=None,repair_context=None)
                self.store.put("sessions", saved["session_id"], saved, critical=True)
        for device in self.store.list("devices"):
            changed = bool(device.get("projects", {}).pop(project["id"], None))
            for key in ("current", "previous", "backup", "installed_package_id", "running_package_id"):
                if device.get(key) in package_ids:
                    device[key], changed = None, True
            if changed:
                self.store.put("devices", device["id"], device, critical=True)
        self.store.delete_project(project["id"])

    def delete_app_version(self,project,package_id):
        allowed,reason=self.backend_delete_check(project)
        if not allowed:raise ValueError(reason)
        versions=self.app_versions(project)
        package=next((p for p in versions if p["id"]==package_id),None)
        if not package:raise ValueError("Versjonen tilhører ikke denne appen.")
        if len(versions)==1:
            self.delete_app_history(project)
            return
        for device in self.store.list("devices"):
            refs=[device.get(k) for k in ("current","previous","backup","installed_package_id","running_package_id")]
            refs+=list(device.get("projects",{}).get(project["id"],{}).values())
            if package_id in refs and device["id"]!=project.get("owner_device_id"):
                raise ValueError("En annen enhet har fortsatt referanse til versjonen.")
        # Validate recursive target before altering any pointers.
        self.store.validate_build_directory(package["build_id"])
        remaining=[p for p in versions if p["id"]!=package_id]
        for key in ("current","previous","backup","candidate","last_simulated_package_id","simulated_previous","simulated_backup"):
            if project.get(key)==package_id:project[key]=None
        if project.get("latest_package")==package_id:
            project["latest_package"]=remaining[0]["id"]
            project["name"]=remaining[0]["manifest"]["name"]
        self.store.put("projects",project["id"],project,critical=True)
        for device in self.store.list("devices"):
            for key in ("current","previous","backup","installed_package_id","running_package_id","last_failure_package_id"):
                if device.get(key)==package_id:device[key]=None
            for key,value in list(device.get("projects",{}).get(project["id"],{}).items()):
                if value==package_id:device["projects"][project["id"]][key]=None
            self.store.put("devices",device["id"],device,critical=True)
        for saved in self.store.list("sessions"):
            if saved["project_id"]==project["id"] and any(saved.get(k)==package_id for k in ("package_id","base_package_id","build_id")):
                saved.update(package_id=None,base_package_id=None,build_id=None,proposal_id=None,repair_context=None,stopped=True)
                self.store.put("sessions",saved["session_id"],saved,critical=True)
        self.store.delete_version_files(package)

    def app_catalog(self, device_id, session=None):
        try:
            device = self.store.get("devices", device_id)
        except FileNotFoundError:
            device = {}
        apps = []
        for project in self.store.list("projects"):
            if project.get("owner_device_id") != device_id or not project.get("latest_package"):
                continue
            versions = self.app_versions(project)
            if not versions:
                continue
            presence = self.app_presence(device, self.project_app_id(project))
            allowed, reason = self.backend_delete_check(project)
            device_allowed,device_reason=self.manager_delete_check(session,project) if session else (False,reason)
            downloadable,download_reason=self.app_download_check(versions[0],session.capabilities if session else device.get("capabilities"))
            apps.append({"app_id": self.project_app_id(project), "project_id": project["id"], "name": project["name"],
                         "latest_package_id": versions[0]["id"], "latest_version": versions[0]["manifest"]["version"],
                         "base_package_id": self.update_base(project, device)["id"], "version_count": len(versions),
                         "device_presence": presence.get("state", "unknown"),
                         "can_delete_backend": allowed, "delete_block_reason": reason,
                         "can_delete_from_device":device_allowed,"device_delete_block_reason":device_reason,
                         "downloadable":downloadable,"download_block_reason":download_reason})
        return sorted(apps, key=lambda a: (a["name"].casefold(), a["app_id"]))

    def require_app_choice_idle(self, session, *, held_lock=False):
        if (session.stopped or not session.sockets or (session.lock.locked() and not held_lock) or session.operation_task
                or (session.input_task and not session.input_task.done()) or session.activity in {"listening", "processing", "speaking"}
                or session.state in {State.building, State.testing, State.processing, State.running, State.starting,
                                     State.stopping, State.rollback_pending}):
            raise ValueError("Avslutt aktivt opptak, bygg eller kjøring før du velger app.")
        device = self.device_record(session)
        if device.get("active_run_id") or device.get("pending_run_id"):
            raise ValueError("Stopp forrige app før du velger en annen.")
        return device

    async def select_app(self, session, event):
        await self.release_foreground(session)
        device = self.require_app_choice_idle(session)
        project, base = None, None
        if event.app_mode == "update":
            project = self.app_project(session.device_id, event.project_id, event.app_id)
            versions = self.app_versions(project)
            if event.base_package_id:
                base = next((p for p in versions if p["id"] == event.base_package_id), None)
                if not base:
                    raise ValueError("Basisversjonen tilhører ikke den valgte appen.")
            else:
                base = self.update_base(project, device)
            from dataclasses import replace
            self.verify_package(replace(session, project_id=project["id"]), base["id"])
        async with session.lock:
            await self.close_dialog(session)
            if session.stopped or not session.sockets:
                raise ValueError("FIRE ble frakoblet før appvalget.")
            if hasattr(self, "audio"):
                self.audio.cancel(session)
            for command in self.pending_commands(session):
                self.finish_command(command, "superseded")
            project = project or self.new_project(session.device_id, session.target)
            session.project_id, session.base_package_id = project["id"], base["id"] if base else None
            session.app_mode, session.install_permitted = event.app_mode, True
            session.conversation_mode = "develop"
            session.resume_project_aliases = []
            session.resumed_from_build_id = None
            session.development_context_id = None
            session.app_revision = device.get("app_change_counter", 0)
            session.package_id = session.build_id = session.proposal_id = session.turn_id = None
            session.summary, session.last_error, session.progress, session.history = "", "", {}, []
            session.audio_status, session.recording_started_at = {}, None
            device.update(project_id=project["id"], **{k: device.get("projects", {}).get(project["id"], {}).get(k)
                                                     for k in ("current", "previous", "backup")})
            self.store.put("devices", device["id"], device)
            await self.activity(session, "idle")
            await self.state(session, State.idle)
            selected = {"app_mode": session.app_mode, "project_id": project["id"],
                        "app_id": self.project_app_id(project), "base_package_id": session.base_package_id}
            await self.emit(session, {"type": "app_selected", **selected})
            return selected

    def present_app(self, device, app_id, **fields):
        old = self.app_presence(device, app_id)
        device.setdefault("apps", {})[app_id] = {**old, **fields, "state": "present", "boot_id": device["boot_id"],
                                                   "reported_at": time.time(), "connection_epoch": device.get("connection_epoch", 0)}

    async def absent_app(self, session, app_id, state):
        device = self.device_record(session)
        old = self.app_presence(device, app_id)
        counter = device.get("app_change_counter", 0) + 1
        device.update(app_change_counter=counter, storage_ready=True)
        device.setdefault("apps", {})[app_id] = {**old, "state": state, "boot_id": session.boot_id,
            "reported_at": time.time(), "connection_epoch": device.get("connection_epoch", 0),
            "last_absent_counter": counter, "package_id": None}
        packages = {p["id"]: p for p in self.store.list("packages") if p["manifest"]["id"] == app_id
                    and self.store.get("projects", p["project_id"]).get("owner_device_id") == session.device_id}
        for command in self.store.list("commands"):
            if command["device_id"] == session.device_id and command["package_id"] in packages and command["status"] in {"pending", "started", "healthy"}:
                self.finish_command(command, "cancelled_by_device_delete")
        for key in ("installed_package_id", "running_package_id"):
            if device.get(key) in packages:
                device[key] = None
                if key == "running_package_id":
                    device.update(active_run_id=None, pending_run_id=None, runtime_status="stopped")
        for key in ("pending_install_id", "pending_run_id", "active_run_id", "pending_rollback_id"):
            if device.get(key):
                command = self.store.get("commands", device[key])
                if command["package_id"] in packages:
                    device[key] = None
        self.store.put("devices", device["id"], device, critical=True)
        project = self.store.get("projects", session.project_id)
        if self.project_app_id(project) == app_id:
            session.install_permitted, session.proposal_id = False, None
            session.last_error = "Appen er borte fra FIRE. Velg Ny app, Endre app eller en lagret pakke før du fortsetter."
            if session.state not in {State.building, State.testing, State.processing}:
                await self.state(session, State.failed)
            self.persist(session)
        await self.emit(session, {"type": "app_presence", "app_id": app_id, "state": state})

    async def inventory(self, session, event):
        device = self.device_record(session)
        resolved = []
        # Validate the complete report before changing any presence metadata.
        for item in event.apps:
            matches = [p for p in self.store.list("packages") if p["manifest"]["id"] == item.app_id
                       and self.store.get("projects", p["project_id"]).get("owner_device_id") == session.device_id
                       and (not item.version or p["manifest"]["version"] == item.version)
                       and (not item.checksum or p["manifest"]["checksum"] == item.checksum)
                       and (not item.package_id or p["id"] == item.package_id)]
            if item.package_id and not matches:
                raise ValueError("Inventarpakken tilhører ikke denne enheten/appen/versjonen.")
            matched = max(matches, key=lambda p: int(p["manifest"]["version"].split(".")[-1])) if matches and (item.package_id or item.version or item.checksum) else None
            resolved.append((item, matched))
        device["storage_ready"] = event.storage_ready
        device.update(inventory_status="complete" if event.storage_ready and event.complete else "partial" if event.storage_ready else "unavailable",
                      inventory_reported_at=time.time())
        if not event.storage_ready:
            device["last_storage_failure_at"] = time.time()
        if event.storage_ready:
            for item, matched in resolved:
                self.present_app(device, item.app_id, version=item.version, checksum=item.checksum,
                                 package_id=matched["id"] if matched else None)
        self.store.put("devices", device["id"], device, critical=True)
        if event.complete and event.storage_ready:
            seen = {app.app_id for app in event.apps}
            pending = {c["package_id"] for c in self.pending_commands(session) if c["kind"] == "install"}
            for app in self.app_catalog(session.device_id):
                if app["app_id"] not in seen:
                    old = self.app_presence(device, app["app_id"])
                    if not old and app["latest_package_id"] in pending:
                        continue  # A first installation has not reached SD yet.
                    if (old.get("state") not in {"missing", "deleted"} or old.get("boot_id") != session.boot_id
                            or old.get("connection_epoch") != device.get("connection_epoch")
                            or old.get("reported_at", 0) < device.get("last_storage_failure_at", 0)):
                        await self.absent_app(session, app["app_id"], "missing")
        return {"status": "recorded", "count": len(event.apps)}

    async def app_event(self, session, event):
        if event.event=="app_download":
            package=self.store.get("packages",event.package_id)
            project=self.app_project(session.device_id,event.project_id or package["project_id"],event.app_id)
            if package["project_id"]!=project["id"]:raise PermissionError("Pakken tilhører ikke valgt app.")
            allowed,reason=self.app_download_check(package,session.capabilities)
            if not allowed:raise ValueError(reason)
            return await self.install_saved(session,package["id"])
        if event.event=="app_backend_delete_prepare":return await self.prepare_backend_delete(session,event)
        if event.event=="app_backend_delete_confirm":return await self.confirm_backend_delete(session,event)
        if event.event == "app_select":
            return await self.select_app(session, event)
        if event.event == "app_deleted":
            await self.absent_app(session, event.app_id, "deleted")
            return {"status": "recorded", "app_id": event.app_id}
        if event.event == "app_inventory":
            return await self.inventory(session, event)
        if event.event == "app_list":
            apps = self.app_catalog(session.device_id,session)
            page, size = apps[event.offset:event.offset+4], 4
            message = {"type": "app_catalog", "apps": page}
        else:
            project = self.app_project(session.device_id, event.project_id, event.app_id)
            versions = self.app_versions(project)
            apps=[]
            for package in versions:
                downloadable,reason=self.app_download_check(package,session.capabilities)
                apps.append({"package_id":package["id"],"version":package["manifest"]["version"],
                    "checksum":package["manifest"]["checksum"],"archive_sha256":package["archive_sha256"],
                    "size_bytes":package["size_bytes"],"downloadable":downloadable,"download_block_reason":reason})
            page, size = apps[event.offset:event.offset+8], 8
            message = {"type": "app_versions", "project_id": project["id"], "versions": page}
        message.update(offset=event.offset, next_offset=event.offset+size if event.offset+size < len(apps) else None,
                       request_event_id=event.event_id)
        await self.emit(session, message)
        return {"status": "listed", "count": len(page)}

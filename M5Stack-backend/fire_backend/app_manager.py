"""Device App Manager operations, scoped to the authenticated device and boot."""
import hashlib
import time

from .models import State
from .storage import canonical, new_id


class AppManager:
    def app_download_check(self, package, capabilities=None):
        from .quality import require_deliverable
        try:
            require_deliverable(package)
            if capabilities:
                manifest=package["manifest"]
                if (not set(manifest["required_services"])<=set(capabilities["services"])
                        or manifest["max_memory"]>capabilities["max_memory"]
                        or capabilities["max_runtime_ms"]!=0 and
                        (manifest["max_runtime_ms"]==0 or manifest["max_runtime_ms"]>capabilities["max_runtime_ms"])):
                    return False,"Versjonen krever funksjoner eller ressurser som FIRE ikke annonserer."
            if not self.store.path("packages",package["id"],".zip").is_file():
                return False,"Pakkefilen mangler på backend."
            return True,""
        except ValueError as error:
            return False,str(error)

    def manager_delete_check(self,session,project,*,held_lock=False):
        if session.target!="device" or session.protocol_version!="0.2" or project.get("owner_device_id")!=session.device_id:
            raise PermissionError("Appen tilhører ikke denne enheten.")
        try:
            self.require_app_choice_idle(session,held_lock=held_lock)
        except ValueError as error:
            return False,str(error)
        # The caller may be the idle session selecting this app. It is rehomed
        # only after explicit confirmation; every other session still blocks.
        return self.backend_delete_check(project,ignore_session_id=session.id)

    def app_revision_hash(self,project):
        return hashlib.sha256(canonical({"project_id":project["id"],"latest":project.get("latest_package"),
            "next_version":project.get("next_version"),"versions":[[p["id"],p["manifest"]["checksum"],p["archive_sha256"]]
            for p in self.app_versions(project)]})).hexdigest()

    async def prepare_backend_delete(self,session,event):
        project=self.app_project(session.device_id,event.project_id,event.app_id)
        allowed,reason=self.manager_delete_check(session,project)
        if not allowed:raise ValueError(reason)
        versions=self.app_versions(project)
        if not versions:raise ValueError("Appen har ingen lagrede versjoner.")
        if event.delete_scope=="version" and not any(p["id"]==event.package_id for p in versions):
            raise ValueError("Versjonen tilhører ikke denne appen.")
        now=time.time()
        old=sorted((j for j in self.store.list("app_deletions") if j["device_id"]==session.device_id),key=lambda j:j["created_at"],reverse=True)
        if sum(j["status"]=="pending" and j["expires_at"]>now for j in old)>=8:
            raise ValueError("For mange åpne slettingsvalg. Vent litt og oppdater listen.")
        for item in old[99:]:self.store.path("app_deletions",item["id"]).unlink(missing_ok=True)
        job={"id":new_id("delete"),"device_id":session.device_id,"session_id":session.id,"boot_id":session.boot_id,
            "project_id":project["id"],"app_id":self.project_app_id(project),"name":project["name"],
            "delete_scope":event.delete_scope,"package_id":event.package_id,"version_count":len(versions),
            "revision":self.app_revision_hash(project),"created_at":now,"expires_at":int(now)+90,"status":"pending"}
        self.store.put("app_deletions",job["id"],job)
        reply={"delete_id":job["id"],"project_id":project["id"],"app_id":job["app_id"],"name":job["name"],
            "delete_scope":job["delete_scope"],"package_id":job["package_id"],"version_count":job["version_count"],
            "expires_at":job["expires_at"]}
        await self.emit(session,{"type":"app_backend_delete_ready",**reply})
        return {"status":"confirmation_required",**reply}

    async def confirm_backend_delete(self,session,event):
        job=self.store.get("app_deletions",event.delete_id)
        if (job["device_id"]!=session.device_id or job["session_id"]!=session.id or job["boot_id"]!=session.boot_id):
            raise PermissionError("Slettingsbekreftelsen tilhører en annen enhet eller oppstart.")
        if job["status"]!="pending" or job["expires_at"]<=time.time():
            raise ValueError("Slettingsvalget er brukt eller utløpt. Oppdater listen og velg på nytt.")
        project=self.app_project(session.device_id,job["project_id"],job["app_id"])
        allowed,reason=self.manager_delete_check(session,project)
        if not allowed:raise ValueError(reason)
        async with session.lock:
            changing=session.project_id==project["id"]
            if changing:await self.close_dialog(session)
            allowed,reason=self.manager_delete_check(session,project,held_lock=True)
            if not allowed:raise ValueError(reason)
            # Closing a model connection can yield; re-read the authoritative
            # revision and TTL after that await, before any destructive action.
            project=self.app_project(session.device_id,job["project_id"],job["app_id"])
            if job["expires_at"]<=time.time() or self.app_revision_hash(project)!=job["revision"]:
                raise ValueError("Apphistorikken er endret eller valget er utløpt. Oppdater listen og bekreft på nytt.")
            job["status"]="executing";self.store.put("app_deletions",job["id"],job,critical=True)
            replacement=None
            try:
                if changing:
                    replacement=self.new_project(session.device_id,"device")
                    if hasattr(self,"audio"):self.audio.cancel(session)
                    session.project_id=replacement["id"]
                    session.base_package_id=session.package_id=session.build_id=session.proposal_id=session.turn_id=None
                    session.summary=session.last_error=""
                    session.history=[];session.progress={};session.audio_status={};session.repair_context=None
                    session.resume_project_aliases=[];session.app_mode="new";session.install_permitted=True
                    session.state=State.idle;session.activity="idle"
                    device=self.device_record(session)
                    device.update(project_id=replacement["id"],current=None,previous=None,backup=None)
                    self.store.put("devices",device["id"],device,critical=True)
                    self.persist(session)
                if job["delete_scope"]=="all":self.delete_app_history(project)
                else:self.delete_app_version(project,job["package_id"])
                remaining=[p for p in self.store.list("packages") if p["project_id"]==project["id"]]
                result={"status":"deleted","delete_id":job["id"],"project_id":project["id"],"app_id":job["app_id"],
                    "delete_scope":job["delete_scope"],"package_id":job["package_id"],"remaining_versions":len(remaining),
                    "replacement_project_id":replacement["id"] if replacement else None}
                job.update(status="completed",result=result)
                self.store.put("app_deletions",job["id"],job,critical=True)
            except Exception:
                job["status"]="failed";self.store.put("app_deletions",job["id"],job,critical=True)
                raise
            if replacement:
                await self.emit(session,{"type":"app_selected","app_mode":"new","project_id":replacement["id"],"app_id":None,"base_package_id":None})
            await self.emit(session,{"type":"app_backend_deleted",**result})
            return result

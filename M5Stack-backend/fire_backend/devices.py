"""Physical-device lifecycle. PC simulation never writes these version pointers."""
import time

from .models import State
from .storage import new_id


class DeviceLifecycle:
    def device_view(self, session):
        return {key: value for key, value in self.device_record(session).items() if key not in {"projects", "apps"}}

    def device_record(self, session):
        if session.target != "device":
            raise ValueError("Physical receipt rejected for a PC-only session")
        return self.store.get("devices", session.device_id)

    def pending_commands(self, session):
        return [c for c in self.store.list("commands") if c["session_id"] == session.id
                and c["status"] == "pending" and c["expires_at"] > time.time()]

    def issue_command(self, session, kind, package_id, **fields):
        lifetime = 300 if kind == "install" else self.settings.fire_command_timeout_seconds
        command = {"id": new_id(kind), "kind": kind, "status": "pending",
                   "device_id": session.device_id, "session_id": session.id,
                   "package_id": package_id, "boot_id": session.boot_id,
                   "expires_at": int(time.time()) + lifetime, **fields}
        # Persist before sending. Lost delivery is reconciled, never blindly re-executed.
        self.store.put("commands", command["id"], command)
        return command

    def command_message(self, command):
        return {"type": command["kind"] + "_request", command["kind"] + "_id": command["id"],
                **{k: v for k, v in command.items() if k not in {"id", "status", "kind", "device_id", "session_id"}}}

    def match_command(self, session, command_id, kind, package_id):
        if not command_id or not package_id:
            raise ValueError(f"{kind}_id and package_id are required")
        try:
            command = self.store.get("commands", command_id)
        except FileNotFoundError:
            raise ValueError("Unknown device command ID") from None
        if (command["kind"] != kind or command["device_id"] != session.device_id
                or command["session_id"] != session.id or command["boot_id"] != session.boot_id
                or command["package_id"] != package_id or command["expires_at"] <= time.time()
                or command["status"] not in {"pending", "started", "healthy"}):
            raise ValueError("Receipt does not match an active command for this boot/session/package")
        return command

    def finish_command(self, command, status):
        command["status"] = status
        command["updated_at"] = time.time()
        self.store.put("commands", command["id"], command, critical=True)

    def verify_package(self, session, package_id):
        from .builds import verify_archive
        package = self.store.get("packages", package_id)
        if package["project_id"] != session.project_id or self.store.get("builds", package["build_id"])["status"] != "ready":
            raise ValueError("Package is not a successful build for this project")
        verify_archive(self.store.path("packages", package_id, ".zip"), package["manifest"], package["archive_sha256"])
        if session.capabilities:
            manifest, caps = package["manifest"], session.capabilities
            from .api_registry import package_compatibility
            incompatible=package_compatibility(package,caps)
            if incompatible:raise ValueError(incompatible)
            if (not set(manifest["required_services"]) <= set(caps["services"])
                    or manifest["max_memory"] > caps["max_memory"]
                    or (caps["max_runtime_ms"] != 0 and (manifest["max_runtime_ms"] == 0 or manifest["max_runtime_ms"] > caps["max_runtime_ms"]))):
                raise ValueError("Package exceeds the actual device API or resource capabilities")
        return package

    async def offer_install(self, session, package):
        from .quality import require_deliverable
        require_deliverable(self.store.get("packages", package["id"]))
        device = self.device_record(session)
        presence = self.app_presence(device, package["manifest"]["id"])
        if (not session.install_permitted or presence.get("last_absent_counter", 0) > session.app_revision):
            raise ValueError("Appen ble fjernet fra FIRE. Velg appen/pakken på nytt før gjeninstallasjon.")
        if device["boot_id"] != session.boot_id:
            raise ValueError("Device boot changed")
        for pending in self.pending_commands(session):
            if pending["kind"] == "install":
                self.finish_command(pending, "superseded")
        command = self.issue_command(session, "install", package["id"],
                                     project_id=package["project_id"], app_id=package["manifest"]["id"],
                                     archive_sha256=package["archive_sha256"], size_bytes=package["size_bytes"],
                                     download_url=f"/packages/{package['id']}/download")
        device["pending_install_id"] = command["id"]
        self.store.put("devices", device["id"], device)
        await self.state(session, State.awaiting_install)
        if (session.project_id!=package['project_id'] or session.package_id!=package['id'] or
                self.store.get('commands',command['id'])['status']!='pending'):
            return command  # The user changed app while state delivery yielded.
        await self.emit(session, self.command_message(command))
        return command

    async def device_run(self, session, package_id):
        if session.state != State.installed or package_id != session.package_id:
            raise ValueError("A matching installed package must await explicit run confirmation")
        device = self.device_record(session)
        if device.get("storage_ready") is False:
            raise ValueError("SD-kortet er ikke tilgjengelig på FIRE.")
        if not session.install_permitted:
            raise ValueError("Appen er slettet fra FIRE; velg og installer på nytt.")
        if not device["online"] or device["boot_id"] != session.boot_id:
            raise ValueError("Device is offline or boot changed")
        if device.get("active_run_id") or device.get("pending_run_id") or (device.get("running_package_id") and device["runtime_status"] not in {"stopped", "failed"}):
            raise ValueError("Stop and confirm the previous run before starting another")
        if device.get("installed_package_id") != package_id:
            raise ValueError("Installation has not been confirmed by this device")
        package = self.verify_package(session, package_id)
        from .quality import require_deliverable
        require_deliverable(package)
        command = self.issue_command(session, "run", package_id, archive_sha256=package["archive_sha256"])
        device.update(runtime_status="starting", pending_run_id=command["id"])
        self.store.put("devices", device["id"], device)
        await self.state(session, State.starting)
        await self.emit(session, self.command_message(command))
        return {"status": "awaiting_device_start", "target": "device", "run_id": command["id"], "package_id": package_id}

    async def request_app_stop(self, session):
        device = self.device_record(session)
        run_id = device.get("active_run_id") or device.get("pending_run_id")
        if not device["online"] or not run_id:
            raise ValueError("No reachable device run to stop")
        for pending in self.pending_commands(session):
            if pending["kind"] == "stop" and pending["run_id"] == run_id:
                await self.emit(session, self.command_message(pending))
                return pending
        run = self.store.get("commands", run_id)
        command = self.issue_command(session, "stop", run["package_id"], run_id=run_id)
        await self.state(session, State.stopping)
        await self.emit(session, self.command_message(command))
        return command

    async def device_receipt(self, session, event):
        device = self.device_record(session)
        if not device["online"] or event.boot_id != session.boot_id or device["boot_id"] != event.boot_id:
            raise ValueError("Receipt from an old or offline boot")
        package_id = event.package_id
        if event.event == "device_install_result":
            command = self.match_command(session, event.install_id, "install", package_id)
            if device.get("pending_install_id") != event.install_id or session.package_id != package_id:
                raise ValueError("Installation offer was superseded")
            if event.status not in {"ok", "failed"}:
                raise ValueError("Installation status required")
            if event.status == "ok" and event.archive_sha256 != command["archive_sha256"]:
                raise ValueError("Installation archive checksum mismatch")
            if event.status == "ok":
                package = self.verify_package(session, package_id)
                device["storage_ready"] = True
                self.present_app(device, package["manifest"]["id"], package_id=package_id,
                                 version=package["manifest"]["version"], checksum=package["manifest"]["checksum"])
                device["installed_package_id"] = package_id
                device["pending_install_id"] = None
                self.finish_command(command, "completed")
                state = State.installed
            else:
                self.finish_command(command, "failed")
                device["pending_install_id"] = None
                device["last_install_error"] = event.error_code or "install_failed"
                device["last_install_message"] = event.message or "Enheten rapporterte mislykket installasjon."
                state = State.failed
        elif event.event in {"app_started", "app_healthy", "app_failed"}:
            command = self.match_command(session, event.run_id, "run", package_id)
            if event.run_id != (device.get("active_run_id") or device.get("pending_run_id")):
                raise ValueError("Receipt is not for the current run")
            if event.event == "app_started":
                if command["status"] != "pending" or device["installed_package_id"] != package_id:
                    raise ValueError("Run was already started or package is not installed")
                device.update(running_package_id=package_id, active_run_id=event.run_id,
                              pending_run_id=None, runtime_status="running")
                self.finish_command(command, "started")
                state = State.running
            elif event.event == "app_healthy":
                if command["status"] != "started" or device.get("running_package_id") != package_id:
                    raise ValueError("App must start before reporting healthy")
                self.finish_command(command, "healthy")
                self.quality.observed_healthy(session.project_id, package_id)
                if device.get("last_failure_package_id")==package_id:
                    device.update(last_failure_package_id=None,last_failure_boot_id=None)
                if device.get("current") != package_id:
                    device.update(backup=device.get("previous"), previous=device.get("current"), current=package_id)
                device.setdefault("projects", {})[session.project_id] = {key: device.get(key) for key in ("current", "previous", "backup")}
                state = State.running
            else:
                if not event.error_code:
                    raise ValueError("App failure requires error_code")
                failed_package = self.store.get("packages", package_id)
                self.quality.record(project_id=session.project_id,package_id=package_id,device_id=session.device_id,
                    source_hash=failed_package["manifest"]["checksum"],message=(event.error_code+": "+(event.message or "")),provenance="device_receipt")
                self.finish_command(command, "failed")
                device.update(running_package_id=None, runtime_status="failed", last_error=event.error_code,
                              active_run_id=None, pending_run_id=None,last_failure_package_id=package_id,last_failure_boot_id=session.boot_id)
                restore = device.get("current") if device.get("current") != package_id else device.get("previous")
                state = State.failed
                if restore:
                    self.verify_package(session, restore)
                    rollback = self.issue_command(session, "rollback", restore, failed_package_id=package_id, start=False)
                    device["pending_rollback_id"] = rollback["id"]
                    self.store.put("devices", device["id"], device, critical=True)
                    await self.state(session, State.rollback_pending)
                    await self.emit(session, self.command_message(rollback))
                    return {"rollback_id": rollback["id"]}
        elif event.event == "app_stopped":
            if event.run_id != (device.get("active_run_id") or device.get("pending_run_id")):
                raise ValueError("Stop receipt is not for the current run")
            if event.stop_id:
                command = self.match_command(session, event.stop_id, "stop", package_id)
                if command["run_id"] != event.run_id:
                    raise ValueError("Stopped run ID mismatch")
                self.finish_command(command, "completed")
            else:
                command = self.match_command(session, event.run_id, "run", package_id)
                if command["status"] not in {"started", "healthy"} or event.reason not in {"completed", "user_exit", "runtime_limit"}:
                    raise ValueError("Natural stop requires a started run and explicit reason")
            run = self.store.get("commands", event.run_id)
            self.finish_command(run, "stopped")
            device.update(running_package_id=None, active_run_id=None, pending_run_id=None, runtime_status="stopped")
            state = State.installed
        elif event.event == "rollback_result":
            command = self.match_command(session, event.rollback_id, "rollback", package_id)
            if device.get("pending_rollback_id") != event.rollback_id or event.status not in {"ok", "failed"}:
                raise ValueError("Rollback status or ID mismatch")
            self.finish_command(command, "completed" if event.status == "ok" else "failed")
            device["pending_rollback_id"] = None
            state = State.failed
            if event.status == "ok":
                if device.get("current") != package_id:
                    device.update(current=package_id, previous=device.get("backup"), backup=None)
                device.setdefault("projects", {})[session.project_id] = {key: device.get(key) for key in ("current", "previous", "backup")}
                device.update(installed_package_id=package_id, running_package_id=None, runtime_status="stopped")
                session.package_id = package_id
                state = State.installed
        else:
            raise ValueError("Unknown device receipt")
        self.store.put("devices", device["id"], device, critical=True)
        session.last_error = (device.get("last_install_message", "Installasjonen feilet.") if event.event == "device_install_result" and event.status == "failed" else
                              event.message or event.error_code or "Appen feilet på FIRE." if event.event == "app_failed" else "")
        await self.state(session, state)
        await self.emit(session, {"type": "device_status", "device": self.device_view(session)})
        return {"status": "recorded", "package_id": package_id}

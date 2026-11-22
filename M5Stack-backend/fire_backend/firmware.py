"""Explicit firmware file storage; never builds, flashes or executes firmware."""
import hashlib
import os
import re
import time

from .storage import new_id

MAX_FIRMWARE_BYTES = 4 * 1024 * 1024


class Firmware:
    def __init__(self,service):
        self.service,self.store=service,service.store
        for group in ("firmware","firmware_jobs"):(self.store.root/group).mkdir(exist_ok=True)
        for job in self.store.list("firmware_jobs"):
            if job["status"]=="pending":
                job["status"]="unknown"
                self.store.put("firmware_jobs",job["id"],job,critical=True)

    async def upload(self,stream,filename,version):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,59}\.bin",filename or ""):
            raise ValueError("Velg en .bin-fil med kort filnavn uten mellomrom eller mappesti.")
        if not version or len(version)>64 or any(ord(c)<32 for c in version):
            raise ValueError("Oppgi en kort firmwareversjon.")
        data=bytearray()
        async for chunk in stream:
            if len(data)+len(chunk)>MAX_FIRMWARE_BYTES:raise ValueError("Firmwarefilen er større enn 4 MB.")
            data.extend(chunk)
        # ESP32 image header: magic E9, 1..16 segments, chip ID 0 at bytes 12..13.
        # This identifies a candidate image, NOT a flashability/signature guarantee.
        if len(data)<32 or data[0]!=0xE9 or not 1<=data[1]<=16 or data[12:14]!=b"\0\0":
            raise ValueError("Forventet en ESP32-firmware.bin, ikke ZIP eller samlet flash-dump.")
        if any(secret.encode() in data for secret in self.store.redactor.secrets):
            raise ValueError("Firmwarefilen inneholder en lagret nøkkel/token og kan ikke deles med enheten.")
        digest=hashlib.sha256(data).hexdigest()
        for item in self.store.list("firmware"):
            if item["sha256"]==digest:return item
        item={"id":new_id("fw"),"filename":filename,"version":version,"size_bytes":len(data),"sha256":digest,
              "created_at":time.time(),"kind":"esp32_app_image","flash_verified":False}
        self.store.reserve(len(data)+2048)
        path=self.store.path("firmware",item["id"],".bin")
        temp=path.with_suffix(".bin.tmp")
        try:
            temp.write_bytes(data)
            with temp.open("r+b") as handle:os.fsync(handle.fileno())
            os.replace(temp,path)
            self.store.put("firmware",item["id"],item)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:temp.unlink(missing_ok=True)
        return item

    def catalog(self):
        for job in self.store.list("firmware_jobs"):
            if job["status"]=="pending" and job["expires_at"]<=time.time():
                job["status"]="expired";self.store.put("firmware_jobs",job["id"],job,critical=True)
        return {"files":sorted(self.store.list("firmware"),key=lambda x:x["created_at"],reverse=True),
                "transfers":sorted(self.store.list("firmware_jobs"),key=lambda x:x["created_at"],reverse=True)[:50]}

    async def send(self,firmware_id,device_id):
        item=self.store.get("firmware",firmware_id)
        session=next((s for s in self.service.sessions.values() if s.target=="device" and s.device_id==device_id and s.sockets and not s.stopped),None)
        if not session:raise ValueError("FIRE må være tilkoblet før filen kan sendes til SD-kortet.")
        if not session.capabilities.get("firmware_storage",False):
            raise ValueError("Denne firmwareversjonen annonserer ikke mottak til /firmware. Se device-instruksen i GitHub.")
        self.service.require_app_choice_idle(session)
        if item["size_bytes"]>session.capabilities.get("firmware_max_bytes",MAX_FIRMWARE_BYTES):
            raise ValueError("Firmwarefilen overskrider enhetens annonserte filgrense.")
        if any(j["device_id"]==device_id and j["status"]=="pending" and j["expires_at"]>time.time() for j in self.store.list("firmware_jobs")):
            raise ValueError("En firmwareoverføring pågår allerede.")
        filename="fire-"+item["sha256"][:16]+".bin"
        job={"id":new_id("fwstore"),"firmware_id":firmware_id,"device_id":device_id,"session_id":session.id,
             "boot_id":session.boot_id,"status":"pending","created_at":time.time(),"expires_at":int(time.time())+300,
             "sha256":item["sha256"],"size_bytes":item["size_bytes"],"sd_path":"/firmware/"+filename}
        self.store.put("firmware_jobs",job["id"],job)
        await self.service.emit(session,{"type":"firmware_store_request","transfer_id":job["id"],"firmware_id":firmware_id,
            "filename":filename,"version":item["version"],"sha256":item["sha256"],"size_bytes":item["size_bytes"],
            "sd_path":job["sd_path"],"expires_at":job["expires_at"],"download_url":f"/firmware/{firmware_id}/download?transfer_id={job['id']}"})
        return job

    def transfer(self,firmware_id,transfer_id,identity):
        job=self.store.get("firmware_jobs",transfer_id)
        session=self.service.sessions.get(job["session_id"])
        if (identity!=job["device_id"] or firmware_id!=job["firmware_id"] or job["status"]!="pending"
                or job["expires_at"]<=time.time() or not session or session.stopped or not session.sockets
                or session.boot_id!=job["boot_id"]):
            raise PermissionError("Firmware transfer scope/expiry mismatch")
        return job

    def download(self,firmware_id,transfer_id,identity):
        self.transfer(firmware_id,transfer_id,identity)
        item=self.store.get("firmware",firmware_id);path=self.store.path("firmware",firmware_id,".bin")
        if path.stat().st_size!=item["size_bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:
            raise ValueError("Firmware checksum mismatch")
        return path

    def receipt(self,session,event):
        job=self.transfer(event.firmware_id,event.transfer_id,session.device_id)
        if job["session_id"]!=session.id or job["boot_id"]!=session.boot_id:raise PermissionError("Firmware receipt session mismatch")
        if event.status=="ok" and event.sha256!=job["sha256"]:raise ValueError("Stored firmware checksum mismatch")
        job.update(status="stored" if event.status=="ok" else "failed",error_code=event.error_code,reported_at=time.time())
        self.store.put("firmware_jobs",job["id"],job,critical=True)
        return {"status":job["status"],"sd_path":job["sd_path"],"installed":False}

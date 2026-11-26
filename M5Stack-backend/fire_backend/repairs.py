"""Device-error repairs survive closing the device page or its conversation.

The explicit build_confirm consumes a short-lived proposal. A private PC-target
session reuses the normal builder/reviewer without installing or running code.
"""
import asyncio
import contextlib
import time
import zipfile

from .models import State
from .storage import new_id
from .builds import verify_archive
from .quality import require_deliverable
from .status_text import VERSION as STATUS_TEXT_VERSION,repair_text
from .generation_errors import BuildPaused


ACTIVE = {"queued", "building"}


class Repairs:
    def __init__(self, service):
        self.service,self.store=service,service.store
        self.tasks,self.watchers,self.workers={},{},{}
        # Unknown paid work is never silently replayed after a backend restart.
        for job in self.store.list('repairs'):
            if job['status'] in ACTIVE:
                job.update(status='interrupted',message='Backend ble startet på nytt. Trykk Fix error igjen.',progress=0)
                self.save(job)

    def save(self, job):
        job['updated_at']=time.time()
        self.store.put('repairs',job['id'],job,critical=True)

    def active_project(self, project_id):
        return any(j['project_id']==project_id and j['status'] in ACTIVE for j in self.store.list('repairs'))

    def owned(self, session, job_id):
        job=self.store.get('repairs',job_id)
        if session.target!='device' or session.protocol_version!='0.2' or job['device_id']!=session.device_id:
            raise PermissionError('Repair belongs to another device')
        return job

    def resolve(self,session,event):
        if session.target!='device' or session.protocol_version!='0.2':raise PermissionError('Device repair requires protocol0.2')
        if not event.app_id:raise ValueError('app_identity_required: velg app hvis kjørekonteksten mangler identitet')
        project=self.service.app_project(session.device_id,None,event.app_id)
        versions=self.service.app_versions(project)
        if not versions:raise ValueError('source_unavailable: backend har ingen lagret kildekode for denne appen')
        by_id={p['id']:p for p in versions}
        if event.package_id and event.package_id not in by_id:
            # Never let another app/device package supply repair evidence.
            try:other=self.store.get('packages',event.package_id)
            except FileNotFoundError:other=None
            if other and other['project_id']!=project['id']:raise PermissionError('Repair package belongs to another app')
        selected=None;identity='latest_available';warnings=[]
        if event.sha256:
            matches=[p for p in versions if p['manifest']['checksum']==event.sha256]
            if not matches:raise ValueError('source_identity_mismatch: kildehash finnes ikke i den valgte appens historikk')
            selected=next((p for p in matches if event.app_version and p['manifest']['version']==event.app_version),None)
            selected=selected or next((p for p in matches if p['id']==event.package_id),matches[0]);identity='source_checksum'
            if event.package_id and selected['id']!=event.package_id:warnings.append('reported_package_mapping_mismatch')
        elif event.app_version:
            selected=next((p for p in versions if p['manifest']['version']==event.app_version),None)
            if selected:identity='reported_version'
            else:warnings.append('reported_version_not_in_backend')
        if selected is None and event.package_id in by_id:
            selected=by_id[event.package_id];identity='reported_package'
        device=self.service.device_record(session)
        presence=device.get('apps',{}).get(event.app_id,{})
        if selected is None and presence.get('package_id') in by_id:
            selected=by_id[presence['package_id']];identity='device_inventory'
        selected=selected or versions[0]
        source=self.source(selected)
        if event.diagnostics and event.diagnostics.source_bytes is not None and event.diagnostics.source_bytes!=len(source.encode('utf-8')):
            warnings.append('reported_source_size_mismatch')
            if identity not in {'source_checksum','reported_version'}:
                # A byte count cannot identify code. Prefer a known inventory
                # package, otherwise latest, but mark attribution uncertain.
                selected=by_id.get(presence.get('package_id'),versions[0]);source=self.source(selected)
                identity='inventory_or_latest_after_conflict'
        latest=by_id.get(project.get('latest_package'),versions[0])
        return project,selected,latest,identity,warnings

    def source(self,package):
        path=self.store.path('packages',package['id'],'.zip')
        verify_archive(path,package['manifest'],package['archive_sha256'])
        with zipfile.ZipFile(path) as archive:
            return archive.read(f"apps/{package['manifest']['id']}/main.lua").decode('utf-8')

    def public(self,job):
        keys=('project_id','app_id','name','status','phase','progress','message','proposal_id','expires_at',
              'reported_package_id','failed_package_id','failed_version','base_package_id','base_version',
              'latest_package_id','latest_version','newer_version_available','target_resolution','identity_warnings',
              'build_id','package_id','version','updated_at')
        return {'repair_id':job['id'],**{k:job[k] for k in keys if k in job},'app_name':job.get('name'),'message':repair_text(job),
                'status_text_version':STATUS_TEXT_VERSION,'physical_verified':False}

    async def emit(self,session,job):
        if job['status']=='ready':
            try:
                package=self.store.get('packages',job['package_id'])
                allowed,reason=self.service.app_download_check(package,session.capabilities)
                if not allowed:raise ValueError(reason)
            except (ValueError,FileNotFoundError) as error:
                job.update(status='unavailable',phase='unavailable',message=self.service.redactor.text(str(error))[:240] or 'Pakken er ikke lenger tilgjengelig.')
                self.save(job)
        self.watchers.setdefault(job['id'],set()).add(session.id)
        await self.service.emit(session,{'type':'app_repair_status',**self.public(job)})
        return self.public(job)

    async def notify(self,job):
        for sid in tuple(self.watchers.get(job['id'],())):
            peer=self.service.sessions.get(sid)
            if peer and not peer.stopped and peer.device_id==job['device_id']:
                with contextlib.suppress(Exception):await self.emit(peer,job)

    async def build_progress(self,build):
        """Keep repair identity/status correct when its same build is resumed."""
        if not build.get('repair_job_id'):return
        job=self.store.get('repairs',build['repair_job_id'])
        job.update(build_id=build['id'],phase=build['phase'],progress=build['progress'],
            status=build['status'],attempt=build.get('generation_attempt',0),total=build.get('max_attempts'))
        if build['status']=='ready':
            package=self.store.get('packages',build['package_id'])
            job.update(package_id=package['id'],version=package['manifest']['version'])
        if build['status']=='failed':job['message']=build.get('error','')
        self.save(job);await self.notify(job)

    async def prepare(self,session,event):
        project,failed,latest,identity,warnings=self.resolve(session,event)
        capabilities=session.capabilities or self.service.device_record(session).get('capabilities')
        if not capabilities:raise ValueError('Enheten må fullføre capability-handshake før reparasjon.')
        jobs=sorted((j for j in self.store.list('repairs') if j['device_id']==session.device_id and j['project_id']==project['id']),key=lambda j:j['updated_at'],reverse=True)
        for old in jobs:
            same=old['failed_package_id']==failed['id']
            reusable=old['status'] in ACTIVE or same and old['status']=='awaiting_confirmation' and old['expires_at']>time.time() and old['boot_id']==session.boot_id
            if same and old['status']=='ready':
                try:require_deliverable(self.store.get('packages',old['package_id']));reusable=True
                except (ValueError,FileNotFoundError):pass
            if reusable:return await self.emit(session,old)
        if sum(j['status'] in ACTIVE|{'awaiting_confirmation'} and j.get('expires_at',0)>time.time() for j in self.store.list('repairs') if j['device_id']==session.device_id)>=8:
            raise ValueError('For mange åpne reparasjoner; fullfør eksisterende valg først.')
        job={'id':new_id('repair'),'device_id':session.device_id,'boot_id':session.boot_id,'project_id':project['id'],
             'app_id':event.app_id,'name':project['name'],'status':'awaiting_confirmation','phase':'prepared','progress':0,
             'proposal_id':new_id('proposal'),'expires_at':int(time.time())+300,'created_at':time.time(),
             'reported_package_id':event.package_id,'failed_package_id':failed['id'],'failed_version':failed['manifest']['version'],
             'reported_version':event.app_version,'reported_source_sha256':event.sha256,'run_id':event.run_id,
             'last_button':event.button,'last_button_action':event.action,
             'base_package_id':latest['id'],'base_version':latest['manifest']['version'],
             'latest_package_id':latest['id'],'latest_version':latest['manifest']['version'],
             'newer_version_available':latest['id']!=failed['id'],'target_resolution':identity,'identity_warnings':warnings,
             'capabilities':capabilities,'error_code':event.error_code or 'user_reported_failure',
             'error_message':self.service.redactor.text(event.message or 'Appen fungerer ikke; analyser og reparer med lagret kildekode og feilhistorikk.')[:240],
             'diagnostics':event.diagnostics.model_dump(exclude_none=True) if event.diagnostics else {},
             'message':'Klar til å analysere og reparere valgt app.'}
        self.save(job)
        return await self.emit(session,job)

    async def confirm(self,session,event):
        job=self.owned(session,event.repair_id)
        if event.proposal_id!=job['proposal_id']:raise ValueError('Repair proposal mismatch')
        if job['status'] in ACTIVE|{'ready'}:return await self.emit(session,job)
        if job['status']!='awaiting_confirmation' or job['expires_at']<=time.time() or job['boot_id']!=session.boot_id:
            raise ValueError('Reparasjonsforslaget er brukt eller utløpt. Forbered på nytt.')
        other=next((j for j in self.store.list('repairs') if j['project_id']==job['project_id'] and j['status'] in ACTIVE),None)
        if other:return await self.emit(session,other)
        if sum(j['status'] in ACTIVE for j in self.store.list('repairs'))>=16:raise ValueError('Reparasjonskøen er full; prøv igjen senere.')
        self.source(self.store.get('packages',job['base_package_id']))
        job.update(status='queued',phase='queued',progress=0,message='Venter på ledig bygger.',confirmed_event_id=event.event_id)
        self.save(job)
        self.tasks[job['id']]=asyncio.create_task(self.run(job['id']))
        return await self.emit(session,job)

    async def status(self,session,event):
        if event.repair_id:job=self.owned(session,event.repair_id)
        else:
            project=self.service.app_project(session.device_id,None,event.app_id)
            jobs=[j for j in self.store.list('repairs') if j['device_id']==session.device_id and j['project_id']==project['id']]
            if not jobs:
                result={'type':'app_repair_status','app_id':event.app_id,'status':'not_found',
                        'message':repair_text({'status':'not_found'}),'status_text_version':STATUS_TEXT_VERSION}
                await self.service.emit(session,result);return result
            job=max(jobs,key=lambda j:j['updated_at'])
        return await self.emit(session,job)

    async def cancel(self,session,event):
        """Cancel this repair even while it is waiting without a build ID."""
        job=self.owned(session,event.repair_id)
        if job['status'] in {'ready','cancelled','unavailable'}:
            return await self.emit(session,job)
        entry=self.service.build_entry(job.get('build_id')) if job.get('build_id') else None
        task=self.tasks.get(job['id']) or (entry['task'] if entry else None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):await task
        self.tasks.pop(job['id'],None)
        self.workers.pop(job['id'],None)
        job=self.store.get('repairs',job['id'])
        # Publication may win the race. A tested package is preserved and
        # offered normally; cancellation cannot revoke or delete it.
        if job.get('build_id'):
            build=self.store.get('builds',job['build_id'])
            if task and task.done() and build['status'] in ACTIVE:
                self.service.device_builds.pop(build['id'],None)
                build.update(status='failed',phase='failed',error='Build cancelled')
                self.store.put('builds',build['id'],build,critical=True)
            if build['status']=='ready':
                package=self.store.get('packages',build['package_id'])
                job.update(status='ready',phase='ready',progress=100,package_id=package['id'],version=package['manifest']['version'])
                self.save(job)
                return await self.emit(session,job)
            if session.build_id==build['id']:
                session.task=None;session.build_id=None;session.progress={}
                await self.service.state(session,State.idle)
        job.update(status='cancelled',phase='cancelled',progress=0,message='Reparasjonen ble avbrutt.')
        self.save(job);await self.notify(job)
        return await self.emit(session,job)

    async def run(self,job_id):
        worker=None
        try:
            job=self.store.get('repairs',job_id)
            while self.service.build_lock.locked():
                if self.store.get('repairs',job_id).get('pause_requested'):raise BuildPaused()
                await asyncio.sleep(.1)
            if self.store.get('repairs',job_id).get('pause_requested'):raise BuildPaused()
            # No yields between selecting the source and reserving the builder.
            from .service import Session
            project=self.store.get('projects',job['project_id'])
            base=self.store.get('packages',project.get('latest_package') or job['base_package_id'])
            if base['project_id']!=project['id']:raise PermissionError('Repair base scope mismatch')
            job.update(base_package_id=base['id'],base_version=base['manifest']['version'])
            original=self.store.get('builds',base['build_id']).get('summary') or project.get('last_confirmed_summary') or project['name']
            worker=Session(new_id('session'),new_id('pc'),project['id'],state=State.awaiting_build_confirmation,
                desktop_device_id=job['device_id'],capabilities=job['capabilities'],app_mode='update',base_package_id=base['id'],
                proposal_id=job['proposal_id'],summary=original+'\nReparer denne appen automatisk. Analyser kildekode og tilgjengelige feil; behold avtalte funksjoner. Ikke be brukeren finne logger eller trykke BUILD igjen.')
            worker.repair_context={'package_id':job['failed_package_id'],'reported_package_id':job['reported_package_id'],
                'target_resolution':job['target_resolution'],'identity_warnings':job['identity_warnings'],
                'reported_version':job.get('reported_version'),'reported_source_sha256':job.get('reported_source_sha256'),
                'boot_id':job['boot_id'],'run_id':job.get('run_id'),
                'last_button':job.get('last_button'),'last_button_action':job.get('last_button_action'),
                'error_code':job['error_code'],'message':job['error_message'],'diagnostics':job['diagnostics'],
                'cases':self.service.quality.cases(project['id']),
                'latest_version_used_as_base':base['manifest']['version'],'physical_root_cause_verified':False}
            build=await self.service.confirm_build(worker,job['proposal_id'])
            build.update(repair_job_id=job_id,confirmed_event_id=job['confirmed_event_id'])
            from .jobs import context_record
            notes=context_record(self.store,job_id)
            if notes['revision']:self.store.put('job_context',build['id'],{**notes,'id':build['id']})
            self.workers[job_id]={'build':build,'worker':worker,'task':worker.task}
            self.store.put('builds',build['id'],build)
            job.update(status='building',build_id=build['id']);self.save(job)
            while not worker.task.done():
                await asyncio.wait({worker.task},timeout=.5)
                if worker.progress:
                    job.update(phase=worker.progress['phase'],progress=worker.progress['progress'],message=self.service.redactor.text(worker.progress['message'])[:240],
                               attempt=worker.progress.get('attempt',1),total=worker.progress.get('total',4))
                    self.save(job);await self.notify(job)
            await worker.task
            build=self.store.get('builds',build['id'])
            if build.get('error_code')=='build_paused':raise BuildPaused()
            if build['status']!='ready':raise ValueError(build.get('error','Reparasjonen kunne ikke godkjennes.'))
            package=self.store.get('packages',build['package_id']);require_deliverable(package)
            job.update(status='ready',phase='ready',progress=100,package_id=package['id'],version=package['manifest']['version'],
                message='Ny testet versjon er klar. Last ned og bekreft kjøring, eller hent senere i App Manager.')
            self.save(job);await self.notify(job)
        except BuildPaused as error:
            job=self.store.get('repairs',job_id);job.update(status='paused',phase='paused',message=str(error));self.save(job)
            await self.notify(job)
        except asyncio.CancelledError:
            if worker and worker.task and not worker.task.done():
                worker.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await worker.task
            job=self.store.get('repairs',job_id);job.update(status='interrupted',phase='interrupted',message='Backend stoppet. Trykk Fix error igjen.',progress=0);self.save(job)
            raise
        except Exception as error:
            job=self.store.get('repairs',job_id);job.update(status='failed',phase='failed',progress=0,message=self.service.redactor.text(str(error))[:240]);self.save(job)
            await self.notify(job)
        finally:
            if worker:
                worker.stopped=True;self.service.persist(worker)
            self.tasks.pop(job_id,None)
            self.workers.pop(job_id,None)

    async def close(self):
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)

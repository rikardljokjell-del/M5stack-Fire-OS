"""Scoped build discovery, device-independent completion and resumable notices."""
import copy
import asyncio
import contextlib
import time

from .models import State
from .status_text import VERSION,TEXT,build_text,error_text
from .quality import require_deliverable
from .generation_errors import build_failure
from .storage import new_id


class BuildLifecycle:
    def build_entry(self,build_id):
        entry=self.device_builds.get(build_id)
        if entry:return entry
        return next((item for item in self.repairs.workers.values() if item['build']['id']==build_id),None)

    def owned_build(self,session,build_id):
        if session.target!='device' or session.protocol_version!='0.2':raise PermissionError('Device build action required')
        build=self.store.get('builds',build_id)
        project=self.store.get('projects',build['project_id'])
        if project.get('owner_device_id')!=session.device_id or build.get('owner_device_id',session.device_id)!=session.device_id:
            raise PermissionError('Build belongs to another device')
        return build

    def build_view(self,build):
        project=self.store.get('projects',build['project_id'])
        phase=build.get('phase','queued');status=build['status']
        message=build_text(phase,operation=build.get('operation','new'),attempt=build.get('generation_attempt',1),
                           total=build.get('max_attempts',4),progress=build.get('progress',0),detail=build.get('error',''))
        package_id=build.get('package_id') if status=='ready' else None
        package=self.store.get('packages',package_id) if package_id else None
        available=False
        failed=build_failure(self.store,build) if status=='failed' else {}
        if failed:failed['diagnostic_message']=failed['diagnostic_message'][:240]
        if failed:message=failed['error_status']
        if package:
            try:require_deliverable(package);available=True
            except ValueError:message=TEXT['test_failed']
        return {'build_id':build['id'],'project_id':project['id'],'app_id':project.get('app_id'),
                'operation':build.get('operation','new'),'repair_id':build.get('repair_job_id'),
                'created_at':build.get('created_at',build.get('phase_started_at',0)),
                'name':package['manifest']['name'] if package else project['name'],'status':status,'phase':phase,'progress':build.get('progress',0),
                'message':message,'background':build.get('background',False),'package_id':package_id,
                'resume_count':build.get('resume_count',0),'attempt':build.get('generation_attempt',build.get('attempts',0)),
                'total':build.get('max_attempts'),
                'version':package['manifest']['version'] if package else None,
                'can_open':available or status=='failed' and bool(build.get('summary')) or status not in {'ready','failed'} and bool(self.build_entry(build['id'])),
                'can_resume':status=='failed' and bool(build.get('summary')),
                **failed,
                'status_text_version':VERSION,'physical_verified':False}

    async def build_notices(self,session):
        if session.target!='device':return
        # Boot/reconnect discovery must not depend on the user having pressed
        # Background first. Foreground workers also survive a device reboot.
        owned=[b for b in self.store.list('builds') if b.get('owner_device_id')==session.device_id]
        active=[b for b in owned if b['status'] not in {'ready','failed'}]
        failed=[b for b in owned if b['status']=='failed']
        # A historical failure must never overwrite a current build's progress.
        # All failures remain discoverable through the paged Resume catalog.
        # Send queued jobs first and the running worker last, so a one-slot
        # firmware status cache consistently retains actual running progress.
        active.sort(key=lambda b:(b['status']!='queued',b.get('created_at',0)))
        visible=active or sorted(failed,key=lambda b:b.get('created_at',0),reverse=True)[:1]
        for build in visible:
            with contextlib.suppress(FileNotFoundError):
                await self.emit(session,{'type':'build_job_status',**self.build_view(build)})
        pending=[b for b in self.store.list('builds') if b.get('owner_device_id')==session.device_id and
                 (b.get('background') or b.get('notice_pending')) and b['status']=='ready' and not b.get('notice_ack')]
        pending.sort(key=lambda b:b.get('created_at',0),reverse=True)
        for build in pending[:4]:
            try:
                view=self.build_view(build)
                if view['can_open']:
                    await self.emit(session,{'type':'build_ready_notice',**view,'message':TEXT['build_ready']})
            except FileNotFoundError:continue

    async def notify_build_progress(self,build):
        view=self.build_view(build)
        for peer in tuple(self.sessions.values()):
            if not peer.stopped and peer.target=='device' and peer.sockets and peer.device_id==build.get('owner_device_id'):
                await self.emit(peer,{'type':'build_job_status',**view})

    async def notify_build_ready(self,build):
        for peer in tuple(self.sessions.values()):
            if not peer.stopped and peer.target=='device' and peer.sockets and peer.device_id==build.get('owner_device_id'):
                await self.build_notices(peer)

    async def resume_build(self,session,build):
        from .models import DeviceEvent
        if build['status']=='failed':
            await self.restore_failed_build(session,build)
            result={'type':'build_resumed','build_id':build['id'],'project_id':session.project_id,
                    'state':session.state,'proposal_id':session.proposal_id,'package_id':None,
                    'progress':session.progress,'history_restored':True,'can_retry':True,
                    'phase':'failed','progress_percent':0,
                    'message':build_failure(self.store,build)['error_status'],
                    'status_text_version':VERSION,**{**build_failure(self.store,build),'diagnostic_message':session.last_error}}
            await self.emit(session,result)
            # Full manual notes stay on the backend; never overflow the 8 KiB
            # control-message limit when reopening a heavily refined plan.
            preview=build['summary']
            if len(preview.encode('utf-8'))>4000:
                preview='Fortsett den lagrede appplanen. Hele planen og alle tillegg er bevart i backend.'
            await self.emit(session,{'type':'build_proposal','proposal_id':session.proposal_id,
                                    'summary':preview,'project_id':session.project_id,'plan_restored':True,
                                    'message':'Planen er bevart. Prøv igjen eller endre planen.'})
            return result
        session.last_error=''
        session.resumed_from_build_id=None
        snapshot=build.get('resume_context',{})
        if build['status']=='ready':
            package=self.store.get('packages',build['package_id']);require_deliverable(package)
            selection=DeviceEvent(event='app_select',device_id=session.device_id,protocol_version='0.2',
                event_id='internal-build-resume',session_id=session.id,boot_id=session.boot_id,
                app_mode='update',project_id=build['project_id'],base_package_id=package['id'])
            await self.select_app(session,selection)
            session.package_id=package['id'];session.build_id=build['id']
            session.progress={'type':'build_progress','build_id':build['id'],'phase':'ready','progress':100,
                              'message':TEXT['ready'],'status_text_version':VERSION}
            device=self.device_record(session)
            if device.get('installed_package_id')==package['id'] and device.get('storage_ready') is not False:
                await self.state(session,State.installed)
            else:
                await self.state(session,State.ready_to_run)
                await self.emit(session,{'type':'package_ready','package_id':package['id'],'manifest':package['manifest'],
                    'archive_sha256':package['archive_sha256'],'project_id':session.project_id,'size_bytes':package['size_bytes'],
                    'download_url':f"/packages/{package['id']}/download"})
                await self.offer_install(session,package)
        else:
            entry=self.build_entry(build['id'])
            if not entry or entry['task'].done():raise ValueError('Bygget kan ikke gjenopptas nå.')
            await self.release_foreground(session)
            self.require_app_choice_idle(session)
            current=self.store.get('builds',build['id'])
            if current['status']=='ready':return await self.resume_build(session,current)
            if entry['task'].done():raise ValueError('Bygget kan ikke gjenopptas nå.')
            worker=entry['worker']
            # Reattach the new device boot/session to progress, never reuse old
            # install/run IDs or mutate the immutable generation snapshot.
            session.project_id=build['project_id'];session.build_id=build['id'];session.task=entry['task']
            session.base_package_id=worker.base_package_id;session.app_mode=worker.app_mode
            session.state=State.testing if entry['build'].get('phase')=='testing' else State.building
            entry['build'].update(foreground_session_id=session.id,background=False)
            self.store.put('builds',build['id'],entry['build'])
            if worker.progress:session.progress=dict(worker.progress);await self.emit(session,session.progress)
        session.history=copy.deepcopy(snapshot.get('history',[]))
        session.summary=snapshot.get('summary',build.get('summary',''))
        self.persist(session)
        result={'type':'build_resumed','build_id':build['id'],'project_id':session.project_id,
                'base_package_id':session.base_package_id,'package_id':session.package_id,'state':session.state,
                'progress':session.progress,'history_restored':True,'message':TEXT['resumed'],
                'phase':session.progress.get('phase',build.get('phase')),
                'progress_percent':session.progress.get('progress',build.get('progress',0)),
                'status':self.store.get('builds',build['id'])['status'],'resume_count':build.get('resume_count',0),
                'status_text_version':VERSION}
        await self.emit(session,result)
        return result

    async def restore_failed_build(self,session,build):
        """Restore context only. A fresh explicit build_confirm authorizes spending."""
        project=self.store.get('projects',build['project_id'])
        owner=session.device_id if session.target=='device' else session.desktop_device_id
        if not owner or project.get('owner_device_id')!=owner or build.get('owner_device_id',owner)!=owner:
            raise PermissionError('Build belongs to another device')
        if build['status']!='failed' or not build.get('summary'):
            raise ValueError('Velg en mislykket jobb med lagret plan.')
        if session.resumed_from_build_id==build['id'] and session.state==State.awaiting_build_confirmation:
            return
        await self.release_foreground(session)
        if session.target=='device':self.require_app_choice_idle(session)
        elif session.lock.locked() or session.operation_task or session.task and not session.task.done():
            raise ValueError('Fullfør eller avbryt PC-jobben før Resume.')
        snapshot=build.get('resume_context',{})
        base=snapshot.get('base_package_id')
        if base:
            package=self.store.get('packages',base)
            if package['project_id']!=project['id']:raise ValueError('Basisversjonen tilhører en annen app.')
        from .jobs import apply_context
        summary,_=apply_context(self.store,build,1)
        session.project_id=project['id'];session.summary=summary
        session.history=copy.deepcopy(snapshot.get('history',[]))
        session.app_mode='update' if base else 'new';session.base_package_id=base
        session.package_id=None;session.build_id=build['id'];session.task=None
        session.conversation_mode='develop';session.install_permitted=True
        session.resumed_from_build_id=build['id'];session.proposal_id=new_id('proposal')
        if build.get('repair_context'):
            import json
            session.repair_context=json.loads(build['repair_context'])
        else:session.repair_context=None
        session.last_error=build_failure(self.store,build)['diagnostic_message'][:240]
        session.progress={'type':'build_progress','build_id':build['id'],'phase':'failed','progress':0,
                          'message':build_failure(self.store,build)['error_status'],'can_resume':True,
                          **build_failure(self.store,build),'status_text_version':VERSION}
        await self.state(session,State.awaiting_build_confirmation)
        self.persist(session)

    async def build_event(self,session,event):
        if event.event=='build_jobs':
            if session.target!='device':raise PermissionError('Device build action required')
            builds=[b for b in self.store.list('builds') if b.get('owner_device_id')==session.device_id]
            rows=[]
            for b in builds:
                try:rows.append(self.build_view(b))
                except FileNotFoundError:continue
            rows.sort(key=lambda v:({'building':3,'queued':2,'ready':1}.get(v['status'],0),v['created_at']),reverse=True)
            page=rows[event.offset:event.offset+4]
            reply={'type':'build_jobs','jobs':page,'offset':event.offset,
                   'next_offset':event.offset+4 if event.offset+4<len(rows) else None,
                   'active_run':{k:self.device_record(session).get(k) for k in ('active_run_id','pending_run_id','running_package_id','runtime_status')}}
            await self.emit(session,reply);return {'status':'listed','count':len(page)}
        build=self.owned_build(session,event.build_id)
        if event.event=='build_cancel':
            entry=self.build_entry(build['id'])
            repair=next((j for j in self.store.list('repairs') if j.get('build_id')==build['id']),None)
            task=self.repairs.tasks.get(repair['id']) if repair else entry['task'] if entry else None
            if build['status'] not in {'ready','failed'} and task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await task
                # A queued coroutine cancelled before starting never runs finally.
                if build['id'] in self.device_builds:
                    self.device_builds.pop(build['id'],None)
                    build.update(status='failed',phase='failed',error='Build cancelled')
                    self.store.put('builds',build['id'],build,critical=True)
                if session.build_id==build['id']:
                    session.task=None;session.build_id=None;session.progress={}
                    await self.state(session,State.idle)
                if repair:
                    repair=self.store.get('repairs',repair['id'])
                    repair.update(status='failed',phase='failed',message='Build cancelled',progress=0)
                    self.repairs.save(repair);await self.repairs.notify(repair)
                await self.notify_build_progress(self.store.get('builds',build['id']))
            after=self.store.get('builds',build['id'])
            reply={'type':'build_cancelled','build_id':build['id'],'status':after['status'],
                   'message':TEXT['build_ready'] if after['status']=='ready' else error_text(after.get('error','')),
                   'status_text_version':VERSION}
            await self.emit(session,reply);return reply
        if event.event=='build_background':
            if session.build_id!=build['id']:raise ValueError('Build is not active in this session')
            self.detach_device_build(session)
            await self.release_foreground(session)
            reply={'type':'build_backgrounded','build_id':build['id'],'message':TEXT['background'],'status_text_version':VERSION}
            await self.emit(session,reply);return reply
        if event.event=='build_resume':return await self.resume_build(session,build)
        if build['status']!='ready':raise ValueError('Build notice is not ready')
        if event.notification_action=='open':await self.resume_build(session,build)
        # Dismiss means close a completed notice, never delete the app/project.
        build=self.store.get('builds',build['id'])
        build['notice_ack']={'action':event.notification_action,'at':time.time(),'event_id':event.event_id}
        self.store.put('builds',build['id'],build)
        reply={'type':'build_notice_closed','build_id':build['id'],'action':event.notification_action,
               'message':TEXT['dismissed'],'status_text_version':VERSION}
        await self.emit(session,reply);return reply

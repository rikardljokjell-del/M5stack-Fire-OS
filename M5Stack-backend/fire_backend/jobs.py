"""Local job monitoring and bounded, revisioned manual development context."""
import time
from .status_text import build_text,error_text
from .generation_errors import build_failure

ACTIVE={'queued','building'}
CLOSED={'packaging','ready','failed'}

class ContextChanged(ValueError):pass


def context_record(store,build_id):
    try:return store.get('job_context',build_id)
    except FileNotFoundError:return {'id':build_id,'revision':0,'applied_revision':0,'notes':[]}


def apply_context(store,build,attempt):
    record=context_record(store,build['id'])
    summary=build['summary']
    if record['notes']:
        summary+='\nUser refinements, oldest to newest; preserve earlier agreed features unless explicitly changed:\n'
        summary+='\n'.join(n['text'] for n in record['notes'])
    build['effective_summary']=summary
    return summary,record['revision']


def mark_context_applied(store,build_id,revision,attempt):
    record=context_record(store,build_id)
    if record['revision']:
        record.update(applied_revision=revision,applied_attempt=attempt,applied_at=time.time())
        store.put('job_context',build_id,record)


def require_current_context(store,build,revision):
    if context_record(store,build['id'])['revision']!=revision:
        raise ContextChanged('Ny kontekst mottatt. Kandidaten må oppdateres før levering.')


class Jobs:
    def __init__(self,service):self.service=service;self.store=service.store

    async def resume(self,build_id):
        build=self.store.get('builds',build_id)
        if build['status']!='failed' or not build.get('summary'):raise ValueError('Velg en mislykket jobb med lagret plan.')
        project=self.store.get('projects',build['project_id'])
        owner=project.get('owner_device_id')
        if not owner or owner not in self.service.settings.device_tokens():raise PermissionError('Unknown device owner')
        session=next((s for s in self.service.sessions.values() if not s.stopped and
                      s.desktop_device_id==owner and s.resumed_from_build_id==build_id and
                      s.state=='awaiting_build_confirmation'),None)
        if session is None:
            session=await self.service.desktop_conversation(owner,project_id=project['id'],
                base_package_id=build.get('resume_context',{}).get('base_package_id'))
            await self.service.restore_failed_build(session,build)
        return {**self.service.snapshot(session),'history':session.history,'progress':session.progress}

    def context(self,build_id,text):
        build=self.store.get('builds',build_id)
        paused=build['status']=='failed' and build.get('error_code')=='build_paused'
        if not paused and (build['status'] not in ACTIVE or build.get('phase') in CLOSED):
            raise ValueError('Jobben er avsluttet eller pakken ferdigstilles. Bruk Aktivitet for neste oppdatering.')
        if not isinstance(text,str) or not 1<=len(text.strip())<=2000:raise ValueError('Skriv 1–2000 tegn med kontekst.')
        record=context_record(self.store,build_id)
        if len(record['notes'])>=8:raise ValueError('Maks åtte konteksttillegg per jobb. Fortsett i en ny oppdatering.')
        record['revision']+=1
        record['notes'].append({'revision':record['revision'],'text':self.service.redactor.text(text.strip()),'at':time.time()})
        self.store.put('job_context',build_id,record)
        self.store.log(build_id,'Manuell kontekst lagret, revisjon '+str(record['revision']))
        return {'status':'pending','revision':record['revision'],'message':'Konteksten er lagret for neste generering. Pågående modellkall endres ikke.'}

    async def control(self,session,event):
        """Native controls reuse the existing build/repair lifecycle and context."""
        from .models import State
        repair=self.service.repairs.owned(session,event.repair_id) if event.repair_id else None
        build=self.service.owned_build(session,event.build_id or repair.get('build_id')) if event.build_id or repair and repair.get('build_id') else None
        project_id=build['project_id'] if build else repair['project_id']
        action=event.job_action
        target=session.job_context_target
        if action in {'resume','cancel','delete'} and target and (
                build and target.get('build_id')==build['id'] or repair and target.get('repair_id')==repair['id']):
            session.job_context_target=None;self.service.persist(session)
        reply={'type':'job_control_result','job_action':action,'build_id':build['id'] if build else None,
               'repair_id':repair['id'] if repair else build.get('repair_job_id'), 'status':'ok'}
        if action=='context':
            if build and build['status'] not in ACTIVE and build.get('error_code')!='build_paused':raise ValueError('Åpne Resume før du endrer en avsluttet jobb.')
            if event.text is None:
                if session.operation_task or session.input_task and not session.input_task.done():raise ValueError('Fullfør taleomgangen først.')
                self.service.detach_device_build(session)
                session.job_context_target={'build_id':build['id'] if build else None,'repair_id':repair['id'] if repair else None,
                    'project_id':project_id,'device_id':session.device_id,'expires_at':time.time()+300}
                self.service.persist(session)
                reply.update(status='context_ready',message='Si mer kontekst',display_text='Si mer kontekst')
            else:reply.update(self.add_owned_context(session,build,repair,event.text))
        elif action=='delete':
            entry=self.service.build_entry(build['id']) if build else None
            task=(entry or {}).get('task') or (self.service.repairs.tasks.get(repair['id']) if repair else None)
            if (task and not task.done() or build and build['status'] not in {'ready','failed'} or
                    not build and repair['status'] in {'queued','building','awaiting_confirmation'}):raise ValueError('Avbryt aktiv jobb før du fjerner den fra Resume.')
            record=build or repair;record['resume_hidden_at']=time.time()
            self.store.put('builds' if build else 'repairs',record['id'],record,critical=True)
            reply.update(status='hidden',message='Fjernet fra Resume; app og historikk beholdt.')
        elif action=='pause':
            if build and build.get('evolution_job_id'):
                job=self.store.get('evolution_jobs',build['evolution_job_id'])
                await self.service.evolution.control(session.device_id,job['project_id'],'pause',
                    self.service.evolution.state(session.device_id,job['project_id'])['revision'],job_id=job['id'])
            elif build:
                if build['status'] not in ACTIVE:raise ValueError('Jobben er allerede avsluttet.')
                build['pause_requested']=True
                entry=self.service.build_entry(build['id'])
                if entry:entry['build']['pause_requested']=True
                self.store.put('builds',build['id'],build,critical=True)
            else:
                if repair['status'] not in {'queued','building'}:raise ValueError('Jobben kan ikke pauses nå.')
                repair['pause_requested']=True;self.service.repairs.save(repair)
            reply.update(status='pause_requested',message='Pauser etter gjeldende kall',display_text='Pauser etter gjeldende kall')
        elif action=='resume':
            if build:
                if build.get('evolution_job_id'):
                    job=self.store.get('evolution_jobs',build['evolution_job_id'])
                    result=await self.service.evolution.control(session.device_id,job['project_id'],'resume',
                        self.service.evolution.state(session.device_id,job['project_id'])['revision'],job_id=job['id'])
                    reply.update(status='resumed',message='Evolution fortsetter med sitt bekreftede mandat')
                    await self.service.emit(session,reply);return reply
                if build.get('resume_hidden_at'):
                    build.pop('resume_hidden_at');self.store.put('builds',build['id'],build)
                return await self.service.resume_build(session,build)
            if repair['status']=='awaiting_confirmation':return await self.service.repairs.emit(session,repair)
            if repair['status']!='paused' or not repair.get('confirmed_event_id'):raise ValueError('Jobben krever en ny reparasjonsbekreftelse.')
            project=self.store.get('projects',project_id)
            if project.get('latest_package')!=repair['base_package_id'] or session.capabilities!=repair['capabilities']:
                raise ValueError('App eller tilganger er endret; bruk Fix error for nytt forslag.')
            repair.update(pause_requested=False,status='queued');self.service.repairs.save(repair)
            import asyncio
            self.service.repairs.tasks[repair['id']]=asyncio.create_task(self.service.repairs.run(repair['id']))
            reply.update(status='resumed',message='Fortsetter den bekreftede reparasjonen')
        elif action=='cancel':
            if build and build.get('evolution_job_id'):
                job=self.store.get('evolution_jobs',build['evolution_job_id'])
                await self.service.evolution.control(session.device_id,job['project_id'],'stop',
                    self.service.evolution.state(session.device_id,job['project_id'])['revision'],
                    job_id=job['id'],mandate_id=build['evolution_mandate_id'])
            if repair:return await self.service.repairs.cancel(session,event)
            from .models import DeviceEvent
            return await self.service.build_event(session,event.model_copy(update={'event':'build_cancel'}))
        elif action=='background':
            if build and session.build_id==build['id']:
                return await self.service.build_event(session,event.model_copy(update={'event':'build_background','build_id':build['id']}))
            if repair:self.service.repairs.watchers.get(repair['id'],set()).discard(session.id)
            reply.update(status='backgrounded',message='Jobben fortsetter i bakgrunnen')
        await self.service.emit(session,reply)
        return reply

    def add_owned_context(self,session,build,repair,text):
        if not text or not 1<=len(text.strip().encode('utf-8'))<=2000:raise ValueError('Konteksten må være 1–2000 UTF8 bytes.')
        if build:return self.context(build['id'],text)
        if repair['status'] not in {'queued','paused'}:raise ValueError('Kontekst kan ikke legges til denne jobben nå.')
        record=context_record(self.store,repair['id'])
        if len(record['notes'])>=8:raise ValueError('Maks åtte konteksttillegg per jobb.')
        record['revision']+=1;record['notes'].append({'revision':record['revision'],'text':self.service.redactor.text(text.strip()),'at':time.time()})
        self.store.put('job_context',repair['id'],record)
        return {'status':'pending','message':'Konteksten er lagret for neste generering.'}

    async def consume_context(self,session,text):
        target=session.job_context_target
        session.job_context_target=None;self.service.persist(session)
        if session.stopped or target['device_id']!=session.device_id or target['expires_at']<time.time():raise ValueError('Kontekstvalget er utløpt. Velg jobben igjen.')
        build=self.service.owned_build(session,target['build_id']) if target.get('build_id') else None
        repair=self.service.repairs.owned(session,target['repair_id']) if target.get('repair_id') else None
        if (build or repair)['project_id']!=target['project_id']:raise PermissionError('Kontekstjobben er endret.')
        result=self.add_owned_context(session,build,repair,text)
        await self.service.emit(session,{'type':'assistant_message','text':result['message'],'display_text':'Kontekst lagret'})
        from .models import State
        await self.service.state(session,State.idle);await self.service.activity(session,'idle')
        return result

    def snapshot(self):
        rows=[];projects={p['id']:p for p in self.store.list('projects')};usage=self.service.usage.records()
        costs=self.service.usage.build_costs();conversation_costs=self.service.usage.conversation_costs()
        evolution={j['id']:j for j in self.store.list('evolution_jobs')}
        for b in self.store.list('builds'):
            if b.get('evolution_job_id') in evolution:continue
            p=projects.get(b['project_id'],{});record=context_record(self.store,b['id'])
            active=b['status'] in ACTIVE;error=b.get('error','') if not active else ''
            failure=build_failure(self.store,b) if error else {}
            paused=b.get('error_code')=='build_paused' and b['status']=='failed'
            if paused:failure['error_status']='På pause. Velg Resume.'
            rows.append({'id':b['id'],'build_id':b['id'],'project_id':b['project_id'],'name':p.get('name','App'),
                'operation':b.get('operation','repair' if b.get('repair_of') else 'update' if b.get('repair_job_id') else 'build'),
                'status':'paused' if paused else b['status'],'phase':'paused' if paused else b.get('phase','queued'),'progress':b.get('progress',0),
                'message':build_text(b.get('phase'),operation=b.get('operation','new'),attempt=b.get('generation_attempt',1),
                    total=b.get('max_attempts',4),progress=b.get('progress',0),detail=error),
                'error':failure.get('diagnostic_message',error),'error_status':failure.get('error_status',''),
                'error_code':failure.get('error_code',''),'can_resume':b['status']=='failed' and bool(b.get('summary')) and bool(p.get('owner_device_id')),
                'last_validation_error':b.get('last_validation_error',''),'summary':b.get('effective_summary',b.get('summary','')),
                'attempt':b.get('generation_attempt',b.get('attempts',0)),'max_attempts':b.get('max_attempts',4),
                'reused_candidate_from':b.get('reused_candidate_from'),
                'created_at':b.get('created_at',b.get('phase_started_at',0)),'phase_started_at':b.get('phase_started_at'),
                'retry_at':b.get('retry_at') if active and b.get('phase')=='api_wait' else None,
                'phase_seconds':b.get('phase_seconds',{}),'package_id':b.get('package_id'),
                'can_add_context':paused or active and b.get('phase') not in CLOSED,
                'context':record,'context_pending':record['revision']>record['applied_revision'],
                'estimated_usd':costs.get(b['id'],{}).get('estimated_usd',0),
                'cost_detail':costs.get(b['id'],{}),'resume_count':b.get('resume_count',0),
                'usage_unknown':sum(u['usage_source']=='reservation' for u in usage if u.get('build_id')==b['id'])})
        for repair in self.store.list('repairs'):
            if not repair.get('build_id') and repair['status'] in {'queued','awaiting_confirmation','paused'}:
                rows.append({'id':repair['id'],'name':repair.get('name','Reparasjon'),'operation':'repair','status':repair['status'],
                    'phase':repair['status'],'message':'På pause' if repair['status']=='paused' else 'Venter på bygger' if repair['status']=='queued' else 'Venter på bekreftelse',
                    'progress':0,'can_add_context':False,'created_at':repair.get('updated_at',0),'context':{},'context_pending':False})
        for session in self.service.sessions.values():
            if session.stopped or session.build_id or session.evolution_job_id or session.state not in {'failed','processing','listening','awaiting_build_confirmation'}:continue
            error=session.last_error if session.state=='failed' else ''
            price=conversation_costs.get(session.id,{'estimated_usd':None,'price_kind':'unknown','usage_record_missing':True})
            rows.append({'id':session.id,'project_id':session.project_id,'name':projects.get(session.project_id,{}).get('name','Samtale'),
                'operation':'dialog','status':getattr(session.state,'value',session.state),'phase':session.audio_status.get('phase',session.activity),
                'message':error_text(error) if error else 'Venter på byggebekreftelse' if session.proposal_id else 'Behandler samtalen',
                'error':error,'error_status':error_text(error) if error else '', 'summary':session.summary,
                'progress':0,'created_at':session.last_seen,'can_add_context':False,'context':{},'context_pending':False,
                'estimated_usd':price['estimated_usd'],'cost_detail':price})
        for row in rows:
            if row.get('error_status'):row['message']=row['error_status']
        from .evolution import ACTIVE as EVOLUTION_ACTIVE
        for job in evolution.values():
            project=projects.get(job['project_id'])
            if not project:continue
            price=self.service.usage._totals([r for r in usage if r.get('evolution_job_id')==job['id']])
            active=job['state'] in EVOLUTION_ACTIVE
            rows.append({'id':job['id'],'project_id':job['project_id'],'name':project['name'],
                'operation':'evolution_'+job['operation'],'status':'building' if active else job['state'],
                'phase':job['state'],'message':job.get('message','Evolution'),'progress':job.get('progress',0),
                'summary':self.store.get('evolution_mandates',job['mandate_id'])['goal'].get('description','Frosset strategi-evaluering'),
                'error':job.get('reason',''),'created_at':job['created_at'],'can_add_context':False,'can_resume':False,
                'context':{},'context_pending':False,'estimated_usd':price['estimated_usd'],'cost_detail':price,
                'build_ids':job.get('build_ids',[]),'package_id':job.get('best_package_id'),
                'evolution_job_id':job['id'],'physical_verified':False})
        display_active=ACTIVE|{'processing','listening'}
        rows.sort(key=lambda r:(r['status'] in display_active,r['created_at']),reverse=True)
        pending=len(self.service.runtime_ai.tasks)
        pausing=sum(self.service.evolution.in_flight(j['id']) for j in evolution.values() if j['state'] not in EVOLUTION_ACTIVE)
        return {'jobs':rows[:100],'active_count':sum(r['status'] in display_active for r in rows)+pending+pausing,'runtime_ai_pending':pending}

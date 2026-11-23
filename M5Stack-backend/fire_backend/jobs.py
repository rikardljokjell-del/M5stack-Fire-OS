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
        if build['status'] not in ACTIVE or build.get('phase') in CLOSED:
            raise ValueError('Jobben er avsluttet eller pakken ferdigstilles. Bruk Aktivitet for neste oppdatering.')
        if not isinstance(text,str) or not 1<=len(text.strip())<=2000:raise ValueError('Skriv 1–2000 tegn med kontekst.')
        record=context_record(self.store,build_id)
        if len(record['notes'])>=8:raise ValueError('Maks åtte konteksttillegg per jobb. Fortsett i en ny oppdatering.')
        record['revision']+=1
        record['notes'].append({'revision':record['revision'],'text':self.service.redactor.text(text.strip()),'at':time.time()})
        self.store.put('job_context',build_id,record)
        self.store.log(build_id,'Manuell kontekst lagret, revisjon '+str(record['revision']))
        return {'status':'pending','revision':record['revision'],'message':'Konteksten er lagret for neste generering. Pågående modellkall endres ikke.'}

    def snapshot(self):
        rows=[];projects={p['id']:p for p in self.store.list('projects')};usage=self.service.usage.records()
        for b in self.store.list('builds'):
            p=projects.get(b['project_id'],{});record=context_record(self.store,b['id'])
            error=b.get('error','');active=b['status'] in ACTIVE
            failure=build_failure(self.store,b) if error else {}
            rows.append({'id':b['id'],'build_id':b['id'],'project_id':b['project_id'],'name':p.get('name','App'),
                'operation':b.get('operation','repair' if b.get('repair_of') else 'update' if b.get('repair_job_id') else 'build'),
                'status':b['status'],'phase':b.get('phase','queued'),'progress':b.get('progress',0),
                'message':build_text(b.get('phase'),operation=b.get('operation','new'),attempt=b.get('generation_attempt',1),
                    total=b.get('max_attempts',4),progress=b.get('progress',0),detail=error),
                'error':failure.get('diagnostic_message',error),'error_status':failure.get('error_status',''),
                'error_code':failure.get('error_code',''),'can_resume':b['status']=='failed' and bool(b.get('summary')) and bool(p.get('owner_device_id')),
                'last_validation_error':b.get('last_validation_error',''),'summary':b.get('effective_summary',b.get('summary','')),
                'attempt':b.get('generation_attempt',b.get('attempts',0)),'max_attempts':b.get('max_attempts',4),
                'created_at':b.get('created_at',b.get('phase_started_at',0)),'phase_started_at':b.get('phase_started_at'),
                'retry_at':b.get('retry_at') if active and b.get('phase')=='api_wait' else None,
                'phase_seconds':b.get('phase_seconds',{}),'package_id':b.get('package_id'),
                'can_add_context':active and b.get('phase') not in CLOSED,
                'context':record,'context_pending':record['revision']>record['applied_revision'],
                'estimated_usd':sum(u['estimated_usd'] for u in usage if u.get('build_id')==b['id']),
                'usage_unknown':sum(u['usage_source']=='reservation' for u in usage if u.get('build_id')==b['id'])})
        for repair in self.store.list('repairs'):
            if not repair.get('build_id') and repair['status'] in {'queued','awaiting_confirmation'}:
                rows.append({'id':repair['id'],'name':repair.get('name','Reparasjon'),'operation':'repair','status':repair['status'],
                    'phase':'queued','message':'Venter på bygger' if repair['status']=='queued' else 'Venter på bekreftelse',
                    'progress':0,'can_add_context':False,'created_at':repair.get('updated_at',0),'context':{},'context_pending':False})
        for session in self.service.sessions.values():
            if session.stopped or session.build_id or session.state not in {'failed','processing','listening','awaiting_build_confirmation'}:continue
            error=session.last_error if session.state=='failed' else ''
            rows.append({'id':session.id,'project_id':session.project_id,'name':projects.get(session.project_id,{}).get('name','Samtale'),
                'operation':'dialog','status':getattr(session.state,'value',session.state),'phase':session.audio_status.get('phase',session.activity),
                'message':error_text(error) if error else 'Venter på byggebekreftelse' if session.proposal_id else 'Behandler samtalen',
                'error':error,'error_status':error_text(error) if error else '', 'summary':session.summary,
                'progress':0,'created_at':session.last_seen,'can_add_context':False,'context':{},'context_pending':False})
        for row in rows:
            if row.get('error_status'):row['message']=row['error_status']
        display_active=ACTIVE|{'processing','listening'}
        rows.sort(key=lambda r:(r['status'] in display_active,r['created_at']),reverse=True)
        return {'jobs':rows[:100],'active_count':sum(r['status'] in display_active for r in rows)}

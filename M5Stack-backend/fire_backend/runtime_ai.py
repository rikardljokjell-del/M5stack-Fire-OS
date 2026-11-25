"""OS-bound runtime inference jobs on the existing authenticated connection."""
import asyncio
import contextlib
import hashlib
import time

from .runtime_contract import EXTENSION,LIMITS,RuntimeAIError,available,compact,request_data,result_data
from .metering import usage_scope,usage_session
from .models import Manifest
from .usage import UsageBudgetError
from .data_engine import DataError

IDENTITY=('request_id','app_id','package_id','source_sha256','run_id','boot_id')


class RuntimeAI:
    def __init__(self,service):
        self.service=service;self.store=service.store;self.tasks={}
        for record in self.store.list('runtime_ai'):
            if record.get('state')=='pending':
                record.update(state='cancelled',error_code='cancelled',finished_at=time.time())
                self.store.put('runtime_ai',record['id'],record,critical=True)

    def app_enabled(self,project_id):
        try:override=self.store.get('runtime_ai_settings',project_id)['enabled']
        except FileNotFoundError:override=True
        return override

    def enabled(self,project_id):
        return self.service.settings.fire_runtime_ai_enabled and self.app_enabled(project_id)

    async def set_app_enabled(self,project_id,enabled):
        if type(enabled) is not bool:raise ValueError('Expected enabled boolean')
        self.store.get('projects',project_id)
        self.store.put('runtime_ai_settings',project_id,{'id':project_id,'enabled':enabled})
        if not enabled:
            for rid,entry in list(self.tasks.items()):
                if entry['project_id']==project_id:await self.cancel(rid,'disabled')
        return {'enabled':enabled}

    def authorize(self,session,identity,*,check_enabled=True):
        if session.target!='device' or session.stopped or not session.sockets:raise RuntimeAIError('not_connected')
        try:device=self.service.device_record(session)
        except (KeyError,OSError,ValueError):raise RuntimeAIError('stale_run') from None
        if not available(device.get('capabilities') or {}):raise RuntimeAIError('permission_denied')
        if (not device.get('online') or device.get('boot_id')!=identity['boot_id'] or session.boot_id!=identity['boot_id'] or
            device.get('active_run_id')!=identity['run_id'] or device.get('running_package_id')!=identity['package_id'] or
            device.get('runtime_status') not in {'running','healthy'}):raise RuntimeAIError('stale_run')
        try:
            package=self.store.get('packages',identity['package_id']);manifest=Manifest.model_validate(package['manifest'])
            project=self.store.get('projects',package['project_id'])
        except (KeyError,OSError,ValueError):raise RuntimeAIError('permission_denied') from None
        if (project.get('owner_device_id')!=session.device_id or manifest.id!=identity['app_id'] or
            manifest.checksum!=identity['source_sha256'] or 'ai' not in manifest.required_services or
            manifest.runtime_ai is None):raise RuntimeAIError('permission_denied')
        if check_enabled and not self.enabled(project['id']):raise RuntimeAIError('disabled')
        return project['id']

    async def emit(self,session,record):
        await self.service.emit(session,{'type':'runtime_ai_result',**{k:record[k] for k in IDENTITY},
            'state':record['state'],'result_json':record.get('result_json',''),'error_code':record.get('error_code','')})

    async def request(self,session,event):
        identity={k:getattr(event,k) for k in IDENTITY}
        try:
            project_id=self.authorize(session,identity)
            data,schema=request_data(event.instructions,event.data_json,event.schema_json,event.timeout_ms)
            if any(self.service.redactor.text(v)!=v for v in (event.instructions,event.data_json,event.schema_json)):raise RuntimeAIError('permission_denied')
            if self.store.path('runtime_ai',event.request_id).exists():
                old=self.store.get('runtime_ai',event.request_id)
                digest=hashlib.sha256(compact([event.instructions,data,schema]).encode()).hexdigest()
                if old['device_id']!=session.device_id or any(old[k]!=identity[k] for k in IDENTITY) or old.get('payload_sha256')!=digest:raise RuntimeAIError('permission_denied')
                # Never resend a charged request, including across reconnects.
                return {'status':old['state'],'request_id':event.request_id}
            if any(v['app_id']==identity['app_id'] and v['device_id']==session.device_id for v in self.tasks.values()):raise RuntimeAIError('busy')
        except RuntimeAIError as error:
            await self.emit(session,{**identity,'state':'failed','error_code':error.code})
            return {'status':'rejected','error_code':error.code,'request_id':event.request_id}
        record={'id':event.request_id,**identity,'device_id':session.device_id,'session_id':session.id,
                'project_id':project_id,'state':'pending','started_at':time.time(),'timeout_ms':event.timeout_ms,
                'payload_sha256':hashlib.sha256(compact([event.instructions,data,schema]).encode()).hexdigest()}
        # Instructions/observations/result content are not diagnostic logs.
        self.store.put('runtime_ai',record['id'],record,critical=True)
        entry={**record,'record':record,'task':asyncio.create_task(self.run(session,record,event.instructions,data,schema))}
        self.tasks[record['id']]=entry
        return {'status':'pending','request_id':record['id']}

    async def run(self,session,record,instructions,data,schema):
        state='failed';code='provider_error';result=''
        scope=usage_scope.set({'project_id':record['project_id'],'session_id':session.id,'runtime_request_id':record['id']})
        session_scope=usage_session.set(None)
        try:
            self.authorize(session,record)
            deadline=asyncio.get_running_loop().time()+record['timeout_ms']/1000
            resolved, refs = await asyncio.wait_for(
                self.service.data_engine.resolve_ai_refs(session, record, instructions, data, schema),
                record['timeout_ms']/1000)
            self.authorize(session,record)
            if self.service.redactor.value(resolved)!=resolved:raise RuntimeAIError('permission_denied')
            record['dataset_refs'] = refs
            remaining=deadline-asyncio.get_running_loop().time()
            if remaining<=0:raise asyncio.TimeoutError
            answer=await asyncio.wait_for(self.service.provider.runtime_ai(instructions,resolved,schema),remaining)
            self.authorize(session,record)
            if refs:self.service.data_engine.check_ai_refs(session, record, refs)
            result=result_data(answer,schema)
            # Do not send an actual credential back even if a model echoes one.
            if self.service.redactor.text(result)!=result:raise RuntimeAIError('invalid_result')
            if refs:record['assessment_ref']=self.service.data_engine.save_ai_assessment(session,record,refs,result)
            state='completed';code=''
        except asyncio.TimeoutError:code='timeout'
        except asyncio.CancelledError:state='cancelled';code=record.get('cancel_reason','cancelled')
        except UsageBudgetError:code='budget_exceeded'
        except RuntimeAIError as error:code=error.code
        except DataError as error:code=error.code
        except (Exception,):code='provider_error'
        finally:
            usage_session.reset(session_scope);usage_scope.reset(scope)
            record.update(state=state,error_code=code,finished_at=time.time(),latency_ms=round((time.time()-record['started_at'])*1000))
            try:self.store.put('runtime_ai',record['id'],record,critical=True)
            finally:self.tasks.pop(record['id'],None)
        # Recheck after every await. A stale result is never delivered to a new run.
        try:self.authorize(session,record,check_enabled=state=='completed')
        except (RuntimeAIError,KeyError,ValueError):return
        await self.emit(session,{**record,'result_json':result})

    async def cancel(self,request_id,reason='cancelled'):
        entry=self.tasks.get(request_id)
        if entry:
            # The coroutine owns this same record; cancellation keeps its reason.
            entry['record']['cancel_reason']=reason
            entry['task'].cancel()
            with contextlib.suppress(asyncio.CancelledError):await entry['task']
            if request_id in self.tasks:  # Cancelled before its first CPU turn.
                record=entry['record'];record.update(state='cancelled',error_code=reason,finished_at=time.time())
                self.store.put('runtime_ai',request_id,record,critical=True);self.tasks.pop(request_id,None)
                session=self.service.sessions.get(record['session_id'])
                if session:
                    try:self.authorize(session,record,check_enabled=False)
                    except (RuntimeAIError,KeyError,ValueError):return
                    await self.emit(session,record)

    async def cancel_event(self,session,event):
        identity={k:getattr(event,k) for k in IDENTITY}
        try:record=self.store.get('runtime_ai',event.request_id)
        except FileNotFoundError:return {'status':'not_found'}
        if record['device_id']!=session.device_id or any(record[k]!=identity[k] for k in IDENTITY):raise PermissionError('Runtime request scope mismatch')
        await self.cancel(event.request_id)
        return {'status':'cancelled'}

    async def cancel_session(self,session):
        for rid,entry in list(self.tasks.items()):
            if entry['session_id']==session.id:await self.cancel(rid)

    async def cancel_run(self,session,run_id):
        for rid,entry in list(self.tasks.items()):
            if entry['session_id']==session.id and entry['run_id']==run_id:await self.cancel(rid)

    async def close(self):
        for rid in list(self.tasks):await self.cancel(rid)

    async def set_global_enabled(self,enabled,config_store=None):
        if type(enabled) is not bool:raise ValueError('Expected enabled boolean')
        if config_store:
            config_store.save(config_store.config.model_copy(update={'runtime_ai_enabled':enabled}))
        self.service.settings.fire_runtime_ai_enabled=enabled
        if not enabled:
            for rid in list(self.tasks):await self.cancel(rid,'disabled')
        return self.snapshot()

    def snapshot(self):
        return {'enabled':self.service.settings.fire_runtime_ai_enabled,
                'developer_mode':self.service.settings.fire_runtime_ai_developer_mode,
                'model':self.service.settings.openai_runtime_model,'pending':len(self.tasks),
                'extension':EXTENSION,'costs_by_project':self.service.usage.runtime_costs(),
                'jobs':[{k:r.get(k) for k in ('id','project_id','state','error_code','started_at','latency_ms')} for r in sorted(self.store.list('runtime_ai'),key=lambda r:r['started_at'],reverse=True)[:50]]}

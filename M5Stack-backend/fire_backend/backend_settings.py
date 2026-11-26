"""Native OS adapter over the existing desktop settings and usage ledger."""
import asyncio
import contextlib
import hashlib
import json
import time

from .storage import canonical,new_id
from .desktop_config import DesktopConfig
from .evolution_contract import REGISTRY,LIMITS,json_object,available
from .model_catalog import ROLE_MODELS


ROLES={'dialog_model':'openai_realtime_model','code_model':'openai_code_model',
    'review_model':'openai_review_model','transcribe_model':'openai_transcribe_model',
    'speech_model':'openai_speech_model','runtime_model':'openai_runtime_model'}
LIMIT_FIELDS=tuple(next(p['limits'] for p in REGISTRY['backend_settings']['patches'] if 'limits' in p))


class BackendSettings:
    def __init__(self,service,config_store=None):
        self.service=service;self.store=service.store;self.config_store=config_store;self.lock=asyncio.Lock()

    def values(self):
        if self.config_store:return self.config_store.config
        values={role:getattr(self.service.settings,key) for role,key in ROLES.items()}
        values.update({k:getattr(self.service.settings,'fire_'+k) for k in LIMIT_FIELDS})
        values.update(runtime_ai_enabled=self.service.settings.fire_runtime_ai_enabled,
            runtime_ai_developer_mode=self.service.settings.fire_runtime_ai_developer_mode)
        return DesktopConfig(credential_namespace='0'*32,**values)

    def revision(self):
        active={k:getattr(self.service.settings,v) for k,v in ROLES.items()}
        active.update({k:getattr(self.service.settings,'fire_'+k) for k in LIMIT_FIELDS})
        active.update(runtime_ai_enabled=self.service.settings.fire_runtime_ai_enabled,
            runtime_ai_developer_mode=self.service.settings.fire_runtime_ai_developer_mode)
        return int(hashlib.sha256(canonical({'saved':self.values().model_dump(),'active':active})).hexdigest()[:8],16)

    def snapshot(self,owner,view='summary',role=None,offset=0):
        if owner not in self.service.settings.device_tokens():raise PermissionError('Unknown settings owner')
        config=self.values()
        value={'revision':self.revision(),'available':self.config_store is not None,'view':view,
            'runtime':{'enabled':self.service.settings.fire_runtime_ai_enabled,'developer_mode':self.service.settings.fire_runtime_ai_developer_mode},
            'selected':{r:getattr(self.service.settings,ROLES[r]) for r in ROLE_MODELS},'items':[],'offset':offset,'has_more':False}
        value['derived_roles']={'evolution_analysis':self.service.settings.openai_review_model,'evolution_reflection':self.service.settings.openai_review_model}
        if view=='models':
            if role is not None and role not in ROLE_MODELS:raise ValueError('Ukjent modellrolle.')
            choices=list(ROLE_MODELS[role]) if role else []
            value.update(role=role,choices=choices[offset:offset+4],roles=list(ROLE_MODELS),has_more=len(choices)>offset+4)
        elif view=='limits':
            limits={k:getattr(self.service.settings,'fire_'+k) for k in LIMIT_FIELDS}
            bounds={}
            for k in LIMIT_FIELDS:
                boolean=isinstance(limits[k],bool)
                bounds[k]={'type':'boolean','choices':[False,True]} if boolean else {
                    'type':'integer' if k.endswith('calls') else 'number','minimum':0,'maximum':1000000,
                    'choices':[0,1,2,5,10,20,50,100] if k.endswith('calls') else [0,.10,.25,.50,1,2,5,10]}
            value.update(limits=limits,bounds=bounds,evolution_app_limits='Appens Evolution-innstillinger',
                account_quotas_unchanged=True)
        elif view=='usage':
            value['selected']={}
            value['limits_summary']={k:getattr(self.service.settings,'fire_'+k) for k in LIMIT_FIELDS}
            rows=[]
            for r in self.service.usage.cost_records(self.service.usage.records()):
                try:project=self.store.get('projects',r['project_id']) if r.get('project_id') else None
                except FileNotFoundError:project=None
                scoped=(project and project.get('owner_device_id')==owner) or r.get('device_id')==owner
                if not scoped and r.get('session_id'):
                    try:
                        s=self.store.get('sessions',r['session_id']);scoped=(s.get('desktop_device_id') or s.get('device_id'))==owner
                    except FileNotFoundError:pass
                if not scoped:continue
                item={k:r[k] for k in ('id','operation','project_id','build_id','session_id','model','started_at','estimated_usd',
                    'provider_calculated_usd','empirical_estimated_usd','price_kind','status','usage_source','tokens_measured',
                    'input_tokens','cached_tokens','output_tokens') if k in r and r[k] is not None}
                if project:item['app_name']=project['name']
                rows.append(item)
            rows.sort(key=lambda r:r['started_at'],reverse=True)
            value['items']=rows[offset:offset+4];value['has_more']=len(rows)>offset+4
            costs=self.service.usage.project_costs()
            projects=[p for p in self.store.list('projects') if p.get('owner_device_id')==owner]
            value['app_totals']=[{'project_id':p['id'],'name':p['name'],
                **{k:costs.get(p['id'],{}).get(k,0) for k in ('estimated_usd','provider_calculated_usd','empirical_estimated_usd','unknown_usage_requests','unestimated_requests')},
                **({'historical_estimate':{'estimated_usd':costs[p['id']]['historical_estimate']['estimated_usd']}} if costs.get(p['id'],{}).get('historical_estimate') else {})}
                for p in projects[offset:offset+4]]
            value['app_totals_has_more']=len(projects)>offset+4;value['has_more']=value['has_more'] or value['app_totals_has_more']
            # Keep all four operations/app totals and their actual price/token
            # provenance. These redundant header/total fields belong to other
            # views and can otherwise overflow the existing native envelope.
            for key in ('runtime','selected','derived_roles'):value.pop(key,None)
            for row in value['items']:row.pop('estimated_usd',None)
            for row in value['app_totals']:
                row.pop('estimated_usd',None)
                if not row['unestimated_requests']:row.pop('unestimated_requests')
            if len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))>LIMITS['snapshot_json_bytes']:
                for row in value['items']:row.pop('started_at',None)
            if len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))>LIMITS['snapshot_json_bytes']:
                for row in value['app_totals']:row.pop('project_id',None)  # Display-only totals, no commands/grants.
        elif view!='summary':raise ValueError('Ukjent innstillingsvisning.')
        self.service.evolution.bounded(value)
        return value

    def patch(self,payload):
        config=self.values();keys=set(payload)
        if keys=={'runtime_ai_mode'} and isinstance(payload['runtime_ai_mode'],str) and payload['runtime_ai_mode'] in {'auto','off'}:
            enabled=payload['runtime_ai_mode']=='auto'
            changes={'runtime_ai_enabled':enabled,'runtime_ai_developer_mode':payload['runtime_ai_mode']}
        elif keys=={'model_role','model'}:
            role=payload['model_role'];model=payload['model']
            if not isinstance(role,str) or role not in ROLE_MODELS or not isinstance(model,str) or model not in ROLE_MODELS[role]:raise ValueError('Velg en av backendens tillatte modeller.')
            changes={role:model}
        elif keys=={'disable_all_limits'} and payload['disable_all_limits'] is True:
            changes={k:False for k in ('cost_limits_enabled','runtime_ai_limits_enabled','evolution_cost_limits_enabled')}
        elif keys=={'limits'} and isinstance(payload['limits'],dict) and payload['limits'] and set(payload['limits'])<=set(LIMIT_FIELDS):
            changes=payload['limits']
            for k,v in changes.items():
                if k.endswith('enabled'):
                    if type(v) is not bool:raise ValueError('Forventet av/på.')
                elif type(v) not in (int,float) or not 0<=v<=1000000 or k.endswith('calls') and type(v) is not int:
                    raise ValueError('Grensen er utenfor backendens valgliste.')
        else:raise ValueError('Ukjent innstillingsendring.')
        return DesktopConfig.model_validate({**config.model_dump(),**changes}),changes

    async def prepare(self,owner,payload,revision):
        if owner not in self.service.settings.device_tokens():raise PermissionError('Unknown settings owner')
        if not self.config_store:raise ValueError('Backendens lagrede innstillingsprofil er ikke tilgjengelig.')
        if revision!=self.revision():raise ValueError('Innstillingene er endret. Hent dem på nytt.')
        _,changes=self.patch(payload)
        proposal={'id':new_id('settings'),'event':'backend_settings_proposal','device_id':owner,
            'revision':revision,'changes':changes,'patch':payload,'state':'pending','expires_at':time.time()+300}
        self.store.put('events',proposal['id'],proposal,critical=True)
        return proposal

    async def confirm(self,owner,proposal_id,revision,event_id):
        async with self.lock:
            if owner not in self.service.settings.device_tokens():raise PermissionError('Unknown settings owner')
            proposal=self.store.get('events',proposal_id)
            if proposal.get('event')!='backend_settings_proposal' or proposal.get('device_id')!=owner:raise PermissionError('Settings approval scope mismatch')
            if proposal['state']=='applied':return proposal['result']
            if proposal['expires_at']<=time.time() or proposal['revision']!=revision or self.revision()!=revision:
                raise ValueError('Innstillingsforslaget er utløpt eller endret.')
            config,changes=self.patch(proposal['patch'])
            if any(k in ROLE_MODELS for k in changes):
                from .browser_api import busy
                if busy(self.service):return {'status':'busy','display_text':'Vent på gjeldende jobb','revision':revision}
            self.config_store.save_values(config)
            settings=self.service.settings
            for k,v in changes.items():setattr(settings,ROLES[k] if k in ROLES else 'fire_'+k,v)
            old_dialogs=[]
            if 'dialog_model' in changes:
                for session in self.service.sessions.values():
                    if session.dialog_manager:
                        old_dialogs.append(session.dialog_manager)
                        session.dialog_manager=session.dialog_connection=None
            if config.runtime_ai_developer_mode=='off':
                # Native global OFF also disables generation policy, while app OFF survives AUTO.
                for rid in list(self.service.runtime_ai.tasks):await self.service.runtime_ai.cancel(rid,'disabled')
            result={'status':'applied','display_text':'Innstillinger lagret','revision':self.revision()}
            proposal.update(state='applied',confirmed_event_id=event_id,result=result,applied_at=time.time())
            self.store.put('events',proposal_id,proposal,critical=True)
            for manager in old_dialogs:
                with contextlib.suppress(Exception):await asyncio.wait_for(manager.__aexit__(None,None,None),3)
            return result

    async def event(self,session,event):
        if session.target!='device' or not available(session.capabilities):raise PermissionError('Settings require authenticated OS capability')
        owner=session.device_id
        if event.event=='backend_settings_prepare':
            proposal=await self.prepare(owner,json_object(event.settings_json),event.expected_revision)
            result={'type':'backend_settings_proposal','request_id':event.request_id,'proposal_id':proposal['id'],
                'revision':proposal['revision'],'expires_at':int(proposal['expires_at']),
                'settings_json':self.service.evolution.bounded({'changes':proposal['changes'],'display_text':'Bekreft innstillingen'})}
        else:
            outcome=None
            if event.event=='backend_settings_confirm':outcome=await self.confirm(owner,event.proposal_id,event.expected_revision,event.event_id)
            value=self.snapshot(owner,event.view or 'summary',event.role,event.offset)
            if outcome:value['action']=outcome
            result={'type':'backend_settings_snapshot','request_id':event.request_id,'revision':value['revision'],
                'settings_json':self.service.evolution.bounded(value)}
        await self.service.emit(session,result);return result

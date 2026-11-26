"""Source-bound Evolution orchestration on the existing Store/Builder/ledger."""
import asyncio
import contextlib
import copy
import hashlib
import json
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout

from .storage import canonical, new_id
from .evolution_contract import CONTRACT, EXTENSION, LIMITS, json_object
from .evolution_models import EvolutionConfig, EvolutionPrepare, EvolutionLimits
from .metering import usage_scope, usage_session
from .usage import UsageBudgetError


ACTIVE={'queued','analyzing','reflecting','building','comparing'}
UNFINISHED=ACTIVE|{'awaiting_build_confirm','paused','blocked_unknown'}
PHASES={'queued':'Venter på ledig bygger','analyzing':'Vurderer appfunn','reflecting':'Forbedrer arbeidsmåten',
        'building':'Bygger kandidat','comparing':'Sammenligner resultater','awaiting_build_confirm':'Klar til å bygge',
        'awaiting_install':'Kandidat klar til test','paused':'Evolution er satt på pause','stopped':'Evolution er stoppet',
        'blocked_unknown':'Ukjent kostnad må avklares','invalidated':'Grunnlaget er endret','failed':'Evolution trenger oppfølging',
        'needs_physical':'Trenger fysisk kontroll','suggested':'Forslag klart','not_improved':'Ingen bedre kandidat'}
PHASES['awaiting_strategy_approval']='Strategi klar til godkjenning'


class EvolutionPaused(UsageBudgetError):
    def __init__(self,message='Evolution er satt på pause; neste handling er ikke startet.'):
        super().__init__(message,code='evolution_paused')


def digest(value):return hashlib.sha256(canonical(value)).hexdigest()


def finding_key(source, finding):
    volatile={'timestamp','reported_at','created_at','updated_at','first_seen','last_seen','count','counts','occurrences','dropped_batches'}
    def stable(v):
        if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if k not in volatile}
        if isinstance(v,list):return [stable(x) for x in v]
        return v
    return digest({'source_sha256':source,'finding':stable(finding)})


class Evolution:
    def __init__(self,service):
        self.service=service;self.store=service.store;self.tasks={};self.workers={}
        self.stop_flags={}
        self.manual_waiters={}
        self.executing_actions=set()
        for group in ('evolution_states','evolution_proposals','evolution_mandates','evolution_jobs','evolution_findings','evolution_telemetry','evolution_evaluations'):
            (self.store.root/group).mkdir(exist_ok=True)
        self.service.usage.evolution_admit=self.before_paid_request
        self.service.provider.evolution_output_cap=self.output_cap
        for job in self.store.list('evolution_jobs'):
            if job.get('state') in ACTIVE|{'awaiting_build_confirm'}:
                unknown=self.unknown_usage(job['id']) or self.unknown_actions(job)
                job.update(state='blocked_unknown' if unknown else 'paused',reason='backend_restarted',updated_at=time.time())
                self.save_job(job)

    def owned(self,owner,project_id):
        project=self.store.get('projects',project_id)
        if not owner or project.get('owner_device_id')!=owner:raise PermissionError('Evolution project owner mismatch')
        return project

    def state(self,owner,project_id):
        self.owned(owner,project_id)
        try:return self.store.get('evolution_states',project_id)
        except FileNotFoundError:return {'id':project_id,'project_id':project_id,'device_id':owner,'revision':0,
            'config':EvolutionConfig().model_dump(),'pending_proposal_id':None}

    def config(self,owner,project_id):return EvolutionConfig.model_validate(self.state(owner,project_id)['config'])

    def capabilities(self,owner):
        try:caps=self.store.get('devices',owner).get('capabilities')
        except FileNotFoundError:caps=None
        if not caps:raise ValueError('Enheten må ha rapportert funksjonene sine før Evolution.')
        return caps

    def models(self):
        return {'generate':self.service.settings.openai_code_model,'review':self.service.settings.openai_review_model,
                'analysis':self.service.settings.openai_review_model,'reflection':self.service.settings.openai_review_model,
                'provider_mode':self.service.settings.fire_ai_mode}

    def binding(self,owner,project_id,base_id,context_id,evaluation,limits,goal,permissions,requirements_summary=...):
        project=self.owned(owner,project_id);base=None
        if base_id:
            base=self.store.get('packages',base_id)
            if base['project_id']!=project_id:raise PermissionError('Evolution base belongs to another project')
            from .builds import verify_archive
            verify_archive(self.store.path('packages',base_id,'.zip'),base['manifest'],base['archive_sha256'])
        context=self.service.data_engine.context(owner,context_id) if context_id else None
        if context and context['parent_project_id']!=project_id:raise PermissionError('Evolution context belongs to another project')
        from .jobs import context_record
        notes=context_record(self.store,base['build_id']) if base else {}
        from .evolution_strategies import Strategies
        from .evolution_knowledge import Knowledge
        return {'project_id':project_id,'device_id':owner,'base_package_id':base_id,
            'base_source_sha256':base['manifest']['checksum'] if base else None,
            'base_archive_sha256':base['archive_sha256'] if base else None,
            'development_context_id':context_id,'development_context_sha256':context['snapshot_sha256'] if context else None,
            'requirements_sha256':digest({'initial':project.get('original_user_request'),'summary':project.get('last_confirmed_summary') if requirements_summary is ... else requirements_summary,'goal':goal}),
            'source_context_sha256':digest(notes),'capabilities_sha256':digest(self.capabilities(owner)),
            'models':self.models(),'permissions':sorted(permissions),'limits':limits,
            'runtime_ai_policy':{'enabled':self.service.settings.fire_runtime_ai_enabled,
                'developer_mode':self.service.settings.fire_runtime_ai_developer_mode,
                'app_enabled':self.service.runtime_ai.app_enabled(project_id)},
            'strategy_sha256':Strategies(self.store).freeze(owner,project_id)['snapshot_sha256'],
            'preferences_sha256':digest(Knowledge(self.store).preferences(owner)),
            'evaluation_id':evaluation['id'],'evaluation_sha256':evaluation['snapshot_sha256'],
            'evaluation_context_sha256':evaluation['context_sha256'],'evolution_contract':CONTRACT}

    def validate_mandate(self,mandate_id,job_id=None,*,allow_paused=False):
        mandate=self.store.get('evolution_mandates',mandate_id)
        if job_id and mandate['job_id']!=job_id:raise PermissionError('Evolution mandate/job mismatch')
        if mandate['state']=='paused' and not allow_paused:raise EvolutionPaused('Evolution er satt på pause; neste handling er ikke startet.')
        if mandate['state'] not in ({'active','paused'} if allow_paused else {'active'}):raise UsageBudgetError('Evolution-mandatet er ikke aktivt.')
        if mandate['expires_at']<=time.time():raise ValueError('Evolution-mandatet er utløpt.')
        state=self.state(mandate['device_id'],mandate['project_id']);config=EvolutionConfig.model_validate(state['config'])
        if not config.enabled or not getattr(config.flags,mandate['operation']):raise ValueError('Evolution-funksjonen er slått av.')
        if state['revision']!=mandate['approved_revision']:raise ValueError('Evolution-innstillingene er endret.')
        binding=mandate['binding'];evaluation=self.store.get('evolution_evaluations',binding['evaluation_id'])
        from .evolution_replay import validate_evaluation
        validate_evaluation(self.service,mandate['device_id'],evaluation)
        actual=self.binding(mandate['device_id'],mandate['project_id'],binding['base_package_id'],
            binding['development_context_id'],evaluation,binding['limits'],mandate['goal'],binding['permissions'],mandate['initial_summary'])
        actual['frozen_context_sha256']=digest(mandate['frozen_context'])
        if mandate.get('inherited_candidate'):
            self.retained_permission_candidate(mandate['device_id'],mandate['project_id'],mandate['inherited_candidate'])
            actual['inherited_candidate_sha256']=digest(mandate['inherited_candidate'])
        if mandate.get('owner_cohort'):
            from .evolution_strategies import validate_owner_evaluation
            validate_owner_evaluation(self.service,mandate['device_id'],mandate['owner_cohort'])
            actual['owner_cohort_sha256']=mandate['owner_cohort']['snapshot_sha256']
            actual['project_bindings_sha256']=digest(mandate['project_bindings'])
            for pid,scope in mandate['project_bindings'].items():
                old=scope['binding'];ev=self.store.get('evolution_evaluations',old['evaluation_id'])
                new=self.binding(mandate['device_id'],pid,old['base_package_id'],old['development_context_id'],
                    ev,old['limits'],mandate['goal'],old['permissions'],scope['initial_summary'])
                new['frozen_context_sha256']=digest(scope['frozen_context'])
                if digest(new)!=digest(old):raise ValueError('En av de godkjente app-evalueringene er endret.')
                p=self.owned(mandate['device_id'],pid)
                if p.get('latest_package')!=scope['initial_latest_package'] or p.get('last_confirmed_summary')!=scope['initial_summary']:
                    raise ValueError('Brukeren har endret en app i det frosne prøvesettet.')
        if digest(actual)!=mandate['binding_sha256']:raise ValueError('Evolution-grunnlaget er endret; godkjenn et nytt mandat.')
        project=self.owned(mandate['device_id'],mandate['project_id'])
        allowed={mandate.get('initial_latest_package'),binding['base_package_id']}
        summaries={mandate['initial_summary']}
        for build_id in mandate.get('build_ids',[]):
            build=self.store.get('builds',build_id)
            from .jobs import context_record
            if context_record(self.store,build_id)['revision']!=0:raise ValueError('Ny brukerkontekst krever et nytt mandat.')
            if (build.get('evolution_job_id')!=mandate['job_id'] or build.get('evolution_mandate_id')!=mandate_id
                    or build.get('resume_context',{}).get('base_package_id')!=self.scope(mandate,build['project_id'])['base_package_id']):
                raise ValueError('Evolution-kandidatens avstamning er endret.')
            if build.get('status')=='ready' and build['project_id']==mandate['project_id'] and not mandate.get('owner_cohort'):
                allowed.add(build.get('package_id'));summaries.add(build.get('effective_summary',build.get('summary')))
        if project.get('latest_package') not in allowed:raise ValueError('En annen oppdatering har endret appens siste kilde.')
        if project.get('last_confirmed_summary') not in summaries:raise ValueError('Brukeren har endret appens bekreftede krav.')
        for peer in self.service.sessions.values() if not mandate.get('owner_cohort') else ():
            if peer.stopped or peer.project_id!=project['id'] or peer.evolution_job_id:continue
            if peer.base_package_id and peer.base_package_id!=binding['base_package_id']:
                raise ValueError('Brukeren har valgt en annen basisversjon.')
            if peer.development_context_id and peer.development_context_id!=binding['development_context_id']:
                raise ValueError('Brukeren har valgt et annet datagrunnlag.')
        return mandate

    def scope(self,mandate,project_id):
        if mandate.get('owner_cohort'):
            if project_id not in mandate['project_bindings']:raise PermissionError('App outside the approved evaluation cohort')
            return mandate['project_bindings'][project_id]['binding']
        if project_id!=mandate['project_id']:raise PermissionError('App outside the approved mandate')
        return mandate['binding']

    async def prepare(self,owner,project_id,operation,payload,expected_revision):
        state=self.state(owner,project_id)
        if state['revision']!=expected_revision:raise ValueError('Evolution-valget er utdatert. Oppdater oversikten.')
        inherited=None
        if isinstance(payload,dict) and set(payload)=={'permission_job_id'}:
            payload,inherited=self.permission_request(owner,project_id,operation,payload['permission_job_id'])
        if operation=='configure':
            value=EvolutionConfig.model_validate(payload).model_dump()
            content={'operation':operation,'config':value}
        elif operation in {'strategy_app','strategy_owner'}:
            if set(payload)-{'strategy_id','stage','project_ids','goal','limits','autonomy'} or not isinstance(payload.get('strategy_id'),str):raise ValueError('Velg én arkivert strategi.')
            from .evolution_strategies import Strategies
            strategy=Strategies(self.store)._record(owner,payload['strategy_id'])
            content={'operation':operation,'strategy_id':strategy['id'],'strategy_sha256':strategy['snapshot_sha256']}
            stage=payload.get('stage','evaluate' if operation=='strategy_owner' and strategy['scope']=='app' else 'adopt')
            if operation=='strategy_owner' and stage=='evaluate':
                content.update(self.prepare_owner_trial(owner,project_id,strategy,payload,state))
            elif stage!='adopt' or set(payload)-{'strategy_id','stage'}:raise ValueError('Ugyldig strategi-adopsjon.')
        else:
            config=EvolutionConfig.model_validate(state['config'])
            if not config.enabled or not getattr(config.flags,operation):raise ValueError('Slå på denne Evolution-funksjonen først.')
            payload=dict(payload)
            if payload.pop('mode',operation)!=operation or payload.pop('project_id',project_id)!=project_id:
                raise PermissionError('Evolution request scope mismatch')
            request=EvolutionPrepare.model_validate({'project_id':project_id,'mode':operation,'expected_revision':expected_revision,**payload})
            base_id=request.base_package_id
            if operation!='generate' and not base_id:raise ValueError('Velg den eksakte basisversjonen.')
            limits=(request.limits or config.limits).model_dump()
            autonomy=request.autonomy or config.autonomy
            goal={'kind':'metric' if operation in {'optimize','evolve'} else 'functional','operation':operation,
                  'description':request.goal,'requirements':request.goal if not base_id else self.store.get('builds',self.store.get('packages',base_id)['build_id']).get('summary',request.goal),'minimum_improvement_percent':5}
            if goal['kind']=='metric':
                if not request.metric:raise ValueError('Velg et målbart forbedringsmål.')
                goal['metric']=request.metric
                if request.metric not in self.metric_choices(base_id):raise ValueError('Målet er ikke målt med et sammenlignbart grunnlag. Velg en tilgjengelig PC-ressurs; fysisk ytelse kan ikke antas.')
            from .evolution_replay import prepare_evaluation
            evaluation=prepare_evaluation(self.service,owner,project_id,base_id,request.development_context_id,goal)
            self.store.put('evolution_evaluations',evaluation['id'],evaluation,critical=True)
            permissions=self.store.get('packages',base_id)['manifest']['permissions'] if base_id else ['fire.display','fire.buttons']
            if request.permissions is not None:
                from .api_registry import ALL_SERVICES
                if (len(request.permissions)!=len(set(request.permissions)) or
                        any(not p.startswith('fire.') or p[5:] not in ALL_SERVICES for p in request.permissions) or
                        any(p[5:] not in self.capabilities(owner)['services'] for p in request.permissions) or
                        not set(permissions)<=set(request.permissions)):
                    raise ValueError('Godkjenn en eksplisitt utvidelse av eksisterende tillatelser.')
                permissions=request.permissions
            binding=self.binding(owner,project_id,base_id,request.development_context_id,evaluation,limits,goal,permissions)
            content={'operation':operation,'goal':goal,'autonomy':autonomy,'binding':binding,
                     'binding_sha256':digest(binding),'limits':limits}
            from .development_context import capture as history_capture
            from .knowledge_context import capture as knowledge_capture
            content['frozen_context']={'development':history_capture(self.store,project_id,owner,base_id),
                'knowledge':knowledge_capture(self.store,owner,request.goal,current_project_id=project_id)}
            binding['frozen_context_sha256']=digest(content['frozen_context']);content['binding_sha256']=digest(binding)
            if inherited:
                content['inherited_candidate']=inherited;binding['inherited_candidate_sha256']=digest(inherited)
                content['binding_sha256']=digest(binding)
        proposal={'id':new_id('evo-proposal'),'project_id':project_id,'device_id':owner,
            'expected_revision':expected_revision,'expires_at':time.time()+300,'state':'pending',**content}
        self.store.put('evolution_proposals',proposal['id'],proposal,critical=True)
        state['pending_proposal_id']=proposal['id'];self.store.put('evolution_states',project_id,state,critical=True)
        return self.public_proposal(proposal)

    def public_proposal(self,proposal):
        value={k:v for k,v in proposal.items() if k not in {'binding','frozen_context','owner_cohort','project_bindings','inherited_candidate'}}
        if 'goal' in value:value['goal']={k:v for k,v in value['goal'].items() if k!='requirements'}
        if proposal.get('binding'):
            b=proposal['binding'];value['scope']={k:b[k] for k in ('base_package_id','base_source_sha256','development_context_id','evaluation_id','models','permissions')}
        value['cost_enforcement']=self.service.settings.fire_evolution_cost_limits_enabled
        value['display_text']='Bekreft Evolution-valget'
        if proposal.get('owner_cohort'):
            value['cohort']=[{k:e[k] for k in ('project_id','base_package_id','base_source_sha256','base_archive_sha256')}
                for e in proposal['owner_cohort']['entries']]
        return value

    async def confirm(self,owner,project_id,proposal_id,expected_revision,confirmation_id=None,*,suggest_authorization=None):
        state=self.state(owner,project_id);proposal=self.store.get('evolution_proposals',proposal_id)
        if proposal['device_id']!=owner or proposal['project_id']!=project_id:raise PermissionError('Evolution proposal scope mismatch')
        if proposal['state']=='accepted':return proposal.get('result',{})
        if (state['revision']!=expected_revision or proposal['expected_revision']!=expected_revision or
                state.get('pending_proposal_id')!=proposal_id or proposal['expires_at']<=time.time()):
            raise ValueError('Evolution-forslaget er brukt, utløpt eller endret.')
        operation=proposal['operation']
        if suggest_authorization is not None:
            if (proposal.get('autonomy')!='suggest' or operation!='repair' or
                    suggest_authorization!=state.get('approval') or not suggest_authorization):
                raise PermissionError('Suggest requires the existing confirmed configuration')
            confirmation_id=suggest_authorization['event_id']
            proposal['authorization']={'kind':'previously_confirmed_suggest_configuration',**suggest_authorization}
        elif confirmation_id is None:
            confirmation_id=new_id('action')
            self.store.put('events',confirmation_id,{'id':confirmation_id,'device_id':owner,
                'event':'evolution_confirm','proposal_id':proposal_id,'status':'completed','created_at':time.time(),
                'provenance':'authenticated_backend_action'},critical=True)
        proposal['confirmed_event_id']=confirmation_id
        if operation=='configure':
            from .evolution_knowledge import Knowledge
            knowledge=Knowledge(self.store)
            authorization={'kind':'manual','proposal_id':proposal_id,'event_id':confirmation_id}
            for note in proposal['config'].get('user_preferences',[]):knowledge.remember(owner,note,authorization=authorization)
            for note in proposal['config'].get('remove_user_preferences',[]):knowledge.forget(owner,note,authorization=authorization)
            proposal['config']['user_preferences']=[];proposal['config']['remove_user_preferences']=[]
            state.update(config=proposal['config'],revision=expected_revision+1,pending_proposal_id=None,
                approval={'proposal_id':proposal_id,'event_id':confirmation_id})
            self.store.put('evolution_states',project_id,state,critical=True)
            for job in self.store.list('evolution_jobs'):
                if job['project_id']==project_id and job['state'] in UNFINISHED:
                    await self.control(owner,project_id,'revoke',state['revision'],job_id=job['id'])
            result={'status':'configured','revision':state['revision']}
        elif operation in {'strategy_app','strategy_owner'} and not proposal.get('owner_cohort'):
            result=await self.adopt_strategy(owner,project_id,proposal,state)
        else:
            if self.active_project(project_id):raise ValueError('Evolution arbeider allerede med denne appen.')
            if proposal.get('owner_cohort') and any(self.active_project(pid) for pid in proposal['project_bindings']):
                raise ValueError('En av appene har allerede aktiv Evolution. Prøvesettet er ikke startet.')
            binding=proposal['binding'];limits=proposal['limits']
            evaluation=self.store.get('evolution_evaluations',binding['evaluation_id'])
            actual=self.binding(owner,project_id,binding['base_package_id'],binding['development_context_id'],evaluation,limits,proposal['goal'],binding['permissions'])
            actual['frozen_context_sha256']=digest(proposal['frozen_context'])
            if proposal.get('inherited_candidate'):
                self.retained_permission_candidate(owner,project_id,proposal['inherited_candidate'])
                actual['inherited_candidate_sha256']=digest(proposal['inherited_candidate'])
            if proposal.get('owner_cohort'):
                from .evolution_strategies import validate_owner_evaluation
                validate_owner_evaluation(self.service,owner,proposal['owner_cohort'])
                actual['owner_cohort_sha256']=proposal['owner_cohort']['snapshot_sha256']
                actual['project_bindings_sha256']=digest(proposal['project_bindings'])
            if digest(actual)!=proposal['binding_sha256']:raise ValueError('Grunnlaget er endret etter forslaget.')
            job_id=new_id('evolution');mandate_id=new_id('mandate')
            execution_operation='evolve' if proposal.get('owner_cohort') else operation
            mandate={'id':mandate_id,'job_id':job_id,'device_id':owner,'project_id':project_id,'operation':execution_operation,
                'state':'active','created_at':time.time(),'expires_at':time.time()+limits['mandate_ttl_days']*86400,
                'approved_revision':expected_revision,'approved_proposal_id':proposal_id,'binding':binding,
                'binding_sha256':proposal['binding_sha256'],'limits':limits,'goal':proposal['goal'],'autonomy':proposal['autonomy'],
                'initial_latest_package':self.store.get('projects',project_id).get('latest_package'),'build_ids':[]}
            mandate['authorization']=proposal.get('authorization',{'kind':'manual','proposal_id':proposal_id,'event_id':confirmation_id})
            mandate['initial_summary']=self.store.get('projects',project_id).get('last_confirmed_summary')
            mandate['frozen_context']=proposal['frozen_context']
            if proposal.get('inherited_candidate'):mandate['inherited_candidate']=proposal['inherited_candidate']
            if proposal.get('owner_cohort'):
                mandate.update(owner_cohort=proposal['owner_cohort'],project_bindings=proposal['project_bindings'])
            self.store.put('evolution_mandates',mandate_id,mandate,critical=True)
            job={'id':job_id,'mandate_id':mandate_id,'device_id':owner,'project_id':project_id,'operation':execution_operation,
                'state':'awaiting_build_confirm' if proposal['autonomy']=='manual' and execution_operation!='evolve' else 'queued',
                'created_at':time.time(),'updated_at':time.time(),'build_ids':[],'candidate_ids':[],
                'binding_sha256':proposal['binding_sha256'],'physical_verified':False}
            self.save_job(job)
            if proposal.get('inherited_candidate'):
                old=self.store.get('evolution_mandates',proposal['inherited_candidate']['mandate_id'])
                old.update(state='revoked',superseded_by=mandate_id)
                self.store.put('evolution_mandates',old['id'],old,critical=True)
            result={'status':'prepared','job_id':job_id,'mandate_id':mandate_id,'state':job['state'],'revision':state['revision']}
            self.start(job_id)
        proposal.update(state='accepted',result=result,accepted_at=time.time());self.store.put('evolution_proposals',proposal_id,proposal,critical=True)
        return result

    def permission_request(self,owner,project_id,operation,job_id):
        if not isinstance(job_id,str):raise ValueError('Velg den eksisterende tillatelsesforespørselen.')
        job=self.store.get('evolution_jobs',job_id)
        if job['device_id']!=owner or job['project_id']!=project_id or job['state']!='permission_required':raise PermissionError('Permission request belongs to another app or is stale')
        mandate=self.validate_mandate(job['mandate_id'],job_id,allow_paused=True)
        if mandate.get('owner_cohort') or operation!=mandate['operation']:raise ValueError('Godkjenn tillatelsene i den eksakte appens eget mandat først.')
        build=self.store.get('builds',job['current_build_id']);attempt=build.get('attempts',0)
        meta=json.loads((self.store.path('builds',build['id'],'')/f'candidate-{attempt}.json').read_text(encoding='utf-8'))
        reference={'job_id':job_id,'mandate_id':mandate['id'],'build_id':build['id'],'attempt':attempt,
            'source_sha256':meta['source_sha256'],'base_package_id':mandate['binding']['base_package_id'],
            'models':mandate['binding']['models'],'capabilities_sha256':mandate['binding']['capabilities_sha256']}
        self.retained_permission_candidate(owner,project_id,reference)
        request={'goal':mandate['goal']['description'],'base_package_id':mandate['binding']['base_package_id'],
            'development_context_id':mandate['binding']['development_context_id'],'autonomy':mandate['autonomy'],
            'limits':mandate['limits'],'permissions':job['requested_permissions']}
        if mandate['goal'].get('metric'):request['metric']=mandate['goal']['metric']
        return request,reference

    def retained_permission_candidate(self,owner,project_id,reference):
        from .models import GeneratedApp
        build=self.store.get('builds',reference['build_id'])
        if (build['project_id']!=project_id or build.get('owner_device_id')!=owner or
                build.get('evolution_job_id')!=reference['job_id'] or build.get('evolution_mandate_id')!=reference['mandate_id'] or
                build.get('error_code')!='evolution_permission_required' or reference['models']!=self.models() or
                reference['capabilities_sha256']!=digest(self.capabilities(owner))):raise PermissionError('Retained candidate source/model/owner binding changed')
        folder=self.store.path('builds',build['id'],'');attempt=reference['attempt']
        source=(folder/f'attempt-{attempt}.lua').read_bytes()
        meta=json.loads((folder/f'candidate-{attempt}.json').read_text(encoding='utf-8'))
        if (len(source)>100000 or hashlib.sha256(source).hexdigest()!=reference['source_sha256'] or
                meta['source_sha256']!=reference['source_sha256'] or meta['base_package_id']!=reference['base_package_id']):raise ValueError('Den bevarte kandidaten er endret.')
        return GeneratedApp(name=meta['name'],main_lua=source.decode('utf-8'),required_services=meta['required_services'],
            test_sequences=json.loads((folder/f'test-plan-{attempt}.json').read_text(encoding='utf-8')))

    def candidate(self,build):
        if not build.get('evolution_mandate_id'):return None
        mandate=self.validate_mandate(build['evolution_mandate_id'],build['evolution_job_id'])
        key=build.get('evolution_resume_response_key')
        if key and build.get('resume_checkpoint',{}).get('error_code')=='evolution_paused':
            action=self.store.get('evolution_jobs',mandate['job_id']).get('actions',{}).get(key,{})
            if action.get('state')=='completed' and action.get('operation')=='generate' and action.get('response_build_id')==build['id']:
                raw=json.loads((self.store.path('builds',build['id'],'')/('evolution-'+key+'.json')).read_text(encoding='utf-8'))
                if digest(raw)!=action['result_sha256']:raise ValueError('Den ferdige genereringsresponsen er endret.')
                from .models import GeneratedApp
                build['reused_candidate_from']=build['id']
                return GeneratedApp.model_validate(raw)
        reference=mandate.get('inherited_candidate')
        if not reference:return None
        candidate=self.retained_permission_candidate(mandate['device_id'],build['project_id'],reference)
        build['reused_candidate_from']=reference['build_id']
        return candidate

    def prepare_owner_trial(self,owner,project_id,strategy,payload,state):
        from .evolution_strategies import prepare_owner_evaluation
        config=EvolutionConfig.model_validate(state['config'])
        if not config.enabled or not config.flags.evolve:raise ValueError('Slå på Evolution Evolve før strategi-evaluering.')
        limits=EvolutionLimits.model_validate(payload.get('limits') or config.limits.model_dump()).model_dump()
        autonomy=payload.get('autonomy',config.autonomy)
        if autonomy not in {'manual','assisted','auto_build'}:raise ValueError('Strategiprøven krever konkrete byggebekreftelser eller Auto Build-mandat.')
        original=self.store.get('evolution_evaluations',strategy['evaluation_id'])['policy']['goal']
        trial_goal=payload.get('goal') or {k:original[k] for k in ('kind','metric','minimum_improvement_percent') if k in original}
        cohort=prepare_owner_evaluation(self.service,owner,project_id,strategy['id'],payload.get('project_ids'),trial_goal)
        if any(cohort['goal']['metric'] not in self.metric_choices(e['base_package_id']) for e in cohort['entries']):
            raise ValueError('Målet kan ikke måles sammenlignbart i hele det godkjente prøvesettet.')
        if limits['max_builds']<len(cohort['entries']):raise ValueError('Denne prøven krever minst tre uttrykkelig godkjente kandidatbygg; øk byggantallet før bekreftelse.')
        from .development_context import capture
        from .knowledge_context import capture as knowledge_capture
        scopes={}
        for entry in cohort['entries']:
            pid=entry['project_id'];base=self.store.get('packages',entry['base_package_id']);evaluation=entry['evaluation']
            self.store.put('evolution_evaluations',evaluation['id'],evaluation)
            frozen={'development':capture(self.store,pid,owner,base['id']),
                'knowledge':knowledge_capture(self.store,owner,str(cohort['goal']),current_project_id=pid)}
            binding=self.binding(owner,pid,base['id'],None,evaluation,limits,cohort['goal'],base['manifest']['permissions'])
            binding['frozen_context_sha256']=digest(frozen)
            project=self.owned(owner,pid)
            scopes[pid]={'binding':binding,'frozen_context':frozen,'initial_latest_package':project.get('latest_package'),
                'initial_summary':project.get('last_confirmed_summary')}
        origin=scopes[project_id];binding=copy.deepcopy(origin['binding'])
        binding.update(owner_cohort_sha256=cohort['snapshot_sha256'],project_bindings_sha256=digest(scopes))
        return {'stage':'evaluate','owner_cohort':cohort,'project_bindings':scopes,'binding':binding,'binding_sha256':digest(binding),
            'frozen_context':origin['frozen_context'],'goal':cohort['goal'],'limits':limits,'autonomy':autonomy}

    def save_job(self,job):
        job['updated_at']=time.time();job['message']=PHASES.get(job['state'],'Evolution oppdateres')
        self.store.put('evolution_jobs',job['id'],job,critical=True)

    def active_project(self,project_id,*,jobs=None):
        for job in (self.store.list('evolution_jobs') if jobs is None else jobs):
            if job['state'] not in ACTIVE|{'awaiting_build_confirm'} and not self.in_flight(job['id']):continue
            mandate=self.store.get('evolution_mandates',job['mandate_id'])
            if job['project_id']==project_id or project_id in mandate.get('project_bindings',{}):return True
        return False

    def in_flight(self,job_id):
        task=self.workers.get(job_id,{}).get('task')
        return any(j==job_id for j,_ in self.executing_actions) or bool(task and not task.done())

    def unknown_usage(self,job_id):
        return [r for r in self.service.usage.records() if r.get('evolution_job_id')==job_id
            and r.get('status') in {'pending','unknown','failed','cancelled'} and r.get('usage_source')!='provider'
            and not (r.get('status')=='pending' and any(j==job_id for j,_ in self.executing_actions))]

    def unknown_actions(self,job):
        return [key for key,value in job.get('actions',{}).items() if value['state'] in {'pending','unknown'} and
            (job['id'],key) not in self.executing_actions]

    def before_paid_request(self,mandate_id,job_id,reserve,records,model,operation):
        try:mandate=self.validate_mandate(mandate_id,job_id)
        except EvolutionPaused:raise
        except (ValueError,KeyError,OSError) as error:raise UsageBudgetError(str(error),code='evolution_invalidated') from None
        if self.unknown_usage(job_id) or self.unknown_actions(self.store.get('evolution_jobs',job_id)):
            raise UsageBudgetError('Et tidligere Evolution-kall har ukjent kostnad eller resultat. Ingen automatisk gjentakelse.',code='evolution_unknown_outcome')
        expected=mandate['binding']['models'].get({'evolution_analysis':'analysis','evolution_reflection':'reflection'}.get(operation,operation))
        if model!=expected:raise UsageBudgetError('Evolution-modellen er endret.',code='evolution_invalidated')
        own=[r for r in records if r.get('evolution_mandate_id')==mandate_id]
        limits=mandate['limits'];exposure=sum(r['estimated_usd'] for r in own)
        day=self.service.usage._day(time.time())
        target=usage_scope.get().get('project_id') or mandate['project_id'];self.scope(mandate,target)
        daily=sum(r['estimated_usd'] for r in records if r.get('evolution_mandate_id') and r.get('project_id')==target and self.service.usage._day(r['started_at'])==day)
        if self.service.settings.fire_evolution_cost_limits_enabled and (exposure+reserve>limits['budget_usd']+1e-12 or daily+reserve>limits['daily_app_budget_usd']+1e-12):
            raise UsageBudgetError('Evolution-budsjettet er nådd. Forløpet er bevart.',code='evolution_cost_limit')
        if operation=='evolution_analysis' and any(r['operation']==operation for r in own):
            raise UsageBudgetError('Dette funnet er allerede analysert. Ingen AI-polling.',code='evolution_iteration_limit')
        if operation=='generate':
            build_id=usage_scope.get().get('build_id')
            if sum(r['operation']=='generate' and r.get('build_id')==build_id for r in own)>=limits['max_generations_per_build']:
                raise UsageBudgetError('Evolution har brukt de avtalte genereringsforsøkene.',code='evolution_iteration_limit')

    def output_cap(self,mandate_id,operation):
        mandate=self.validate_mandate(mandate_id)
        key={'evolution_analysis':'analysis','evolution_reflection':'reflection'}.get(operation,operation)
        if key not in mandate['limits']['output_tokens']:raise UsageBudgetError('Ukjent Evolution-operasjon.')
        return mandate['limits']['output_tokens'][key]

    def authorize_build(self,session,proposal_id,mandate_id,*,explicit=False):
        mandate=self.validate_mandate(mandate_id)
        job=self.store.get('evolution_jobs',mandate['job_id'])
        if explicit and job['state']!='awaiting_build_confirm':
            raise UsageBudgetError('Evolution-jobben krever eksplisitt Fortsett før et nytt bygg kan godkjennes.',code='evolution_paused')
        binding=self.scope(mandate,session.project_id)
        owner=session.desktop_device_id if session.target!='device' else session.device_id
        if (mandate['device_id']!=owner or binding['base_package_id']!=session.base_package_id or
                session.proposal_id!=proposal_id or job.get('proposal_id')!=proposal_id or
                (mandate['autonomy']!='auto_build' and not explicit)):
            raise PermissionError('Evolution-mandatet autoriserer ikke dette gjeldende forslaget.')
        continuing=session.resumed_from_build_id in mandate['build_ids']
        if len(mandate['build_ids'])>=mandate['limits']['max_builds'] and not continuing:raise UsageBudgetError('Alle avtalte kandidatbygg er brukt.',code='evolution_iteration_limit')
        return {'kind':'explicit_build_confirm' if explicit else 'evolution_mandate','mandate_id':mandate_id,'job_id':mandate['job_id'],
            'proposal_id':proposal_id,'binding_sha256':mandate['binding_sha256'],
            'generations_per_build':mandate['limits']['max_generations_per_build']}

    def note_build(self,build):
        mandate=self.validate_mandate(build['evolution_mandate_id'],build['evolution_job_id'])
        if build['id'] not in mandate['build_ids']:mandate['build_ids'].append(build['id'])
        self.store.put('evolution_mandates',mandate['id'],mandate,critical=True)
        job=self.store.get('evolution_jobs',mandate['job_id']);job['build_ids']=list(mandate['build_ids']);job['current_build_id']=build['id'];job['proposal_id']=None;self.save_job(job)
        if job.get('strategy_components'):
            build['evolution_strategy_components_sha256']=digest(job['strategy_components'])
            build['evolution_strategy_components']=copy.deepcopy(job['strategy_components'])
            self.store.put('builds',build['id'],build,critical=True)
        if mandate.get('owner_cohort'):
            build['evolution_evaluation_only']=True
            self.store.put('builds',build['id'],build,critical=True)

    def build_progress(self,build):
        if not build.get('evolution_job_id'):return
        job=self.store.get('evolution_jobs',build['evolution_job_id'])
        job.update(progress=build.get('progress',0),build_phase=build.get('phase'))
        self.save_job(job)

    def start(self,job_id):
        if job_id in self.tasks and not self.tasks[job_id].done():return
        self.stop_flags[job_id]=threading.Event()
        task=asyncio.create_task(self.run(job_id));self.tasks[job_id]=task
        task.add_done_callback(lambda t:self.tasks.pop(job_id,None) if self.tasks.get(job_id) is t else None)

    def cost(self,job_id):
        return self.service.usage._totals([r for r in self.service.usage.records() if r.get('evolution_job_id')==job_id])

    def worker(self,job,mandate,project_id=None):
        from .service import Session
        from .models import State
        project_id=project_id or job['project_id'];binding=self.scope(mandate,project_id);goal=mandate['goal']
        requirements=goal.get('requirements') or self.store.get('builds',self.store.get('packages',binding['base_package_id'])['build_id'])['summary']
        summary=requirements+'\nMålrettet endring: '+goal.get('description','Forbedre '+goal.get('metric','arbeidsmåten')+' uten funksjons- eller ressursregresjon.')
        worker=Session(new_id('session'),new_id('pc'),project_id,state=State.awaiting_build_confirmation,
            desktop_device_id=job['device_id'],capabilities=copy.deepcopy(self.capabilities(job['device_id'])),
            app_mode='update' if binding['base_package_id'] else 'new',base_package_id=binding['base_package_id'],
            proposal_id=new_id('proposal'),summary=summary,development_context_id=binding['development_context_id'])
        worker.evolution_job_id=job['id']
        if job.get('current_build_id'):
            previous=self.store.get('builds',job['current_build_id'])
            if previous['project_id']==project_id and previous.get('error_code') in {'evolution_paused','cost_limit','evolution_cost_limit'}:
                worker.resumed_from_build_id=previous['id']
        self.workers[job['id']]={'worker':worker,'build':{},'task':None}
        return worker

    async def wait_foreground(self,job):
        while True:
            self.validate_mandate(job['mandate_id'],job['id'])
            busy=self.service.build_lock.locked() or bool(self.service.device_builds) or any(
                not s.stopped and s.evolution_job_id!=job['id'] and (s.lock.locked() or
                    s.operation_task and not s.operation_task.done() or s.input_task and not s.input_task.done())
                for s in self.service.sessions.values()) or any(
                    j['status'] in {'queued','building'} for j in self.store.list('repairs'))
            if not busy:return
            await asyncio.sleep(.1)

    async def provider_operation(self,job,operation,payload):
        mandate=self.validate_mandate(job['mandate_id'],job['id'])
        from .evolution_models import EvolutionAnalysis,EvolutionReflection
        schema={'evolution_analyze':EvolutionAnalysis,'evolution_reflect':EvolutionReflection}[operation]
        payload=self.service.redactor.value(payload)
        key=digest([operation,mandate['binding_sha256'],payload])
        job.update(self.store.get('evolution_jobs',job['id']))
        action=job.get('actions',{}).get(key)
        if action and action['state']=='completed':
            if digest(action['result'])!=action['result_sha256']:raise ValueError('Det lagrede AI-resultatet er endret.')
            return schema.model_validate(action['result'])
        if action and action['state'] in {'pending','unknown'}:raise UsageBudgetError('Det tidligere AI-resultatet er uavklart; kallet gjentas ikke.')
        action={'operation':operation,'input_sha256':key,'binding_sha256':mandate['binding_sha256'],
            'state':'pending','started_at':time.time()}
        job.setdefault('actions',{})[key]=action;self.save_job(job)
        self.executing_actions.add((job['id'],key))
        before={r['id'] for r in self.service.usage.records() if r.get('evolution_job_id')==job['id']}
        token=usage_scope.set({'project_id':job['project_id'],'evolution_job_id':job['id'],'evolution_mandate_id':job['mandate_id']})
        try:
            answer=schema.model_validate((await getattr(self.service.provider,operation)(payload)).model_dump())
            action.update(state='completed',result=answer.model_dump(),result_sha256=digest(answer.model_dump()),finished_at=time.time())
            latest=self.store.get('evolution_jobs',job['id']);latest.setdefault('actions',{})[key]=action;self.save_job(latest);job.update(latest)
            return answer
        except BaseException as error:
            after={r['id'] for r in self.service.usage.records() if r.get('evolution_job_id')==job['id']}
            action.update(state='not_admitted' if isinstance(error,UsageBudgetError) and after==before else 'unknown')
            latest=self.store.get('evolution_jobs',job['id']);latest.setdefault('actions',{})[key]=action;self.save_job(latest);job.update(latest)
            raise
        finally:
            usage_scope.reset(token);self.executing_actions.discard((job['id'],key))

    async def build_candidate(self,job,mandate,components=None,project_id=None):
        if job['operation']=='repair':
            blockers=[f for f in self.store.list('evolution_findings') if f['project_id']==job['project_id'] and
                f['source_sha256']==mandate['binding']['base_source_sha256'] and
                f['finding']['category'] in {'deployment','os_driver','missing_capability','ambiguous_timing'}]
            if blockers:
                job.update(state='needs_physical',reason='Avklar installasjon/OS/maskinvare før Lua-kilden endres.');self.save_job(job)
                raise PermissionError(job['reason'])
        await self.wait_foreground(job)
        worker=self.worker(job,mandate,project_id)
        job.update(state='building',strategy_components=components,proposal_id=worker.proposal_id);self.save_job(job)
        if mandate['autonomy'] in {'manual','assisted'}:
            self.service.sessions[worker.id]=worker;self.service.persist(worker)
            job.update(state='awaiting_build_confirm',session_id=worker.id,proposal_id=worker.proposal_id);self.save_job(job)
            waiter=asyncio.Event();self.manual_waiters[job['id']]=waiter
            await self.notify_manual(job)
            while True:
                self.validate_mandate(mandate['id'],job['id'])
                entry=self.workers[job['id']]
                if entry.get('task'):
                    worker=entry['worker'];break
                try:await asyncio.wait_for(waiter.wait(),.25)
                except TimeoutError:continue
                waiter.clear()
            build=self.store.get('builds',worker.build_id)
        else:build=await self.service.confirm_build(worker,worker.proposal_id,evolution_mandate_id=mandate['id'])
        job.update(self.store.get('evolution_jobs',job['id']))
        self.workers[job['id']].update(build=build,task=worker.task)
        await worker.task
        job.update(self.store.get('evolution_jobs',job['id']))
        build=self.store.get('builds',build['id'])
        if build['status']!='ready':
            if build.get('error_code')=='evolution_permission_required':
                job.update(state='permission_required',reason=build.get('error'),requested_permissions=build.get('requested_permissions',[]));self.save_job(job)
                raise PermissionError('Kandidaten krever separat godkjenning av nye tillatelser.')
            raise ValueError(build.get('error','Kandidaten bestod ikke vanlige porter.'))
        return build['package_id']

    async def assess(self,job,mandate,package_id):
        self.validate_mandate(mandate['id'],job['id'])
        from .evolution_compare import assess_packages
        evaluation=self.store.get('evolution_evaluations',mandate['binding']['evaluation_id'])
        job['state']='comparing';self.save_job(job)
        verdict=await assess_packages(self.service,job['device_id'],mandate['binding']['base_package_id'],package_id,evaluation,mandate['goal'])
        self.validate_mandate(mandate['id'],job['id'])
        job.setdefault('comparisons',[]).append({'package_id':package_id,'verdict':verdict})
        if package_id not in job['candidate_ids']:job['candidate_ids'].append(package_id)
        passed=verdict['status'] in {'validated_candidate','improved'}
        if passed:job['best_package_id']=package_id
        candidate=self.store.get('packages',package_id)
        candidate['evolution_adoption']='candidate' if passed else 'not_adopted'
        self.store.put('packages',package_id,candidate)
        if not passed:
            project=self.store.get('projects',job['project_id'])
            if project.get('latest_package')==package_id:
                project['latest_package']=job.get('best_package_id') or mandate['binding']['base_package_id']
                project['last_confirmed_summary']=mandate['initial_summary']
                if project['latest_package']:project['name']=self.store.get('packages',project['latest_package'])['manifest']['name']
                self.store.put('projects',project['id'],project,critical=True)
        job.update(comparison=verdict,state='awaiting_install' if passed else 'not_improved')
        job['progress']=100
        self.save_job(job)
        if passed:
            await self.service.notify_build_ready(self.store.get('builds',candidate['build_id']))
        return verdict

    def build_context(self,mandate_id,project_id=None):
        mandate=self.validate_mandate(mandate_id)
        project_id=project_id or mandate['project_id'];binding=self.scope(mandate,project_id)
        frozen=copy.deepcopy(mandate['project_bindings'][project_id]['frozen_context'] if mandate.get('owner_cohort') else mandate['frozen_context'])
        from .development_context import validate
        from .knowledge_context import validate as validate_knowledge
        if frozen['development']:validate(frozen['development'],project_id,mandate['device_id'],binding['base_package_id'])
        if frozen['knowledge']:validate_knowledge(frozen['knowledge'],mandate['device_id'])
        return frozen

    async def evolve(self,job,mandate):
        """GEPA proposes bounded strategy data; Builder still creates every app."""
        from .evolution_gepa import optimize_strategy,validate_candidate
        from .evolution_strategies import Strategies
        from .evolution_compare import METRICS,validation_metrics
        metric=mandate['goal']['metric']
        if metric not in METRICS or METRICS[metric][1] not in {'simulation','simulation_proxy'}:
            job.update(state='needs_physical',reason='Målet mangler sammenlignbare fysiske målinger; ingen Lua-omskriving utføres.')
            self.save_job(job);return
        strategies=Strategies(self.store);seed=strategies.freeze(job['device_id'],job['project_id'])
        owner_loop=asyncio.get_running_loop();flag=self.stop_flags[job['id']]
        # Inputs are fixed host profiles, separate from model-created plans.
        train=[{'id':'release-idle','profile':'idle'}];holdout=[{'id':'release-rapid','profile':'rapid'}]
        packages=job.setdefault('strategy_packages',{digest(seed['components']):mandate['binding']['base_package_id']})
        scores={};baseline={}
        for row in job.get('strategy_evaluations',[]):
            if row.get('record_sha256')!=digest({k:v for k,v in row.items() if k!='record_sha256'}):raise ValueError('Lagret strategimåling er endret.')
            scores[(row['components_sha256'],row['case_id'])]={k:row[k] for k in ('score','output','feedback','evidence')}
            if row['components_sha256']==digest(seed['components']):baseline[row['case_id']]=row['output']['value']

        async def evaluate(components,case):
            self.validate_mandate(mandate['id'],job['id'])
            if flag.is_set():raise InterruptedError('Evolution er stoppet.')
            key=digest(components)
            if key not in packages:
                current=self.validate_mandate(mandate['id'],job['id'])
                packages[key]=await self.build_candidate(job,current,components)
                job['strategy_packages']=packages;self.save_job(job)
            score_key=(key,case['id'])
            package=self.store.get('packages',packages[key])
            source=self.service.repairs.source(package)
            if score_key in scores:
                if scores[score_key]['output']['source_sha256']!=package['manifest']['checksum']:raise ValueError('Lagret måling gjelder en annen kilde.')
                return scores[score_key]
            caps=self.capabilities(job['device_id'])
            from .builds import simulate
            observed=await simulate({**package['manifest'],'main_lua':source,'profile':case['profile'],
                'capture_at_ms':[],'hardware':caps.get('hardware') or {},'service_methods':caps.get('service_methods'),
                'service_modes':caps.get('service_modes'),'data_capture':caps.get('data_engine') or {}},self.store,package['build_id'])
            metrics=validation_metrics(observed)
            if metric not in metrics:raise ValueError('Evalueringen målte ikke den valgte ressursen.')
            value=metrics[metric]['value']
            if key==digest(seed['components']):baseline[case['id']]=value
            before=baseline.get(case['id'])
            if before is None:raise ValueError('Uavhengig basisprofil må måles først.')
            score=max(0,min(1,1-value/(2*before))) if before else .5 if value==0 else 0
            result={'score':score,'output':{'metric':metric,'value':value,'source_sha256':package['manifest']['checksum']},
                'feedback':'Bevar alle krav og øvrige ressurser. '+metric+'='+str(value),
                'evidence':'simulation_proxy' if METRICS[metric][1]=='simulation_proxy' else 'simulation'}
            scores[score_key]=result
            row={'components_sha256':key,'case_id':case['id'],**result};row['record_sha256']=digest(row)
            job.setdefault('strategy_evaluations',[]).append(row)
            self.save_job(job);return result

        async def propose(components,traces,keys):
            if flag.is_set():raise InterruptedError('Evolution er stoppet.')
            job['state']='reflecting';self.save_job(job)
            answer=await self.provider_operation(job,'evolution_reflect',{'strategy':components,'training_findings':traces,
                'mutable_components':keys,'allowed_context_keys':['history','feedback','data','hardware','examples'],
                'allowed_examples':[],'repair_methods':['targeted','reproduce_first','preserve_baseline'],
                'goal':mandate['goal']})
            self.validate_mandate(mandate['id'],job['id'])
            value=answer.model_dump();candidate={k:value[k] for k in ('guidance','repair_method')}
            candidate.update({k:json.dumps(value[k],separators=(',',':')) for k in ('context_selection','example_ids')})
            return validate_candidate(candidate)

        def dispatch(callback,*args):
            future=asyncio.run_coroutine_threadsafe(callback(*args),owner_loop)
            try:
                while True:
                    if flag.is_set():raise InterruptedError('Evolution er stoppet.')
                    try:return future.result(timeout=.1)
                    except FutureTimeout:continue
            except BaseException:
                future.cancel();raise

        def optimize():
            return optimize_strategy(seed['components'],train,holdout,
                lambda c,e:dispatch(evaluate,c,e),lambda c,d,k:dispatch(propose,c,d,k),
                stop=flag.is_set,max_evaluations=16,max_proposals=mandate['limits']['max_builds'])
        result=await self.service.data_engine.thread_work(optimize,cancelled=flag.set)
        candidate=result['candidate'];key=digest(candidate)
        if key==digest(seed['components']):
            job.update(state='not_improved',optimizer_result=result);self.save_job(job);return
        package_id=packages[key];verdict=await self.assess(job,mandate,package_id)
        evaluation=self.store.get('evolution_evaluations',mandate['binding']['evaluation_id'])
        independent=all((key,c['id']) in scores and scores[(key,c['id'])]['score']>=scores[(digest(seed['components']),c['id'])]['score'] for c in train+holdout)
        record=strategies.archive_candidate(job['device_id'],job['project_id'],seed['id'],candidate,evaluation,
            {'status':verdict['status'],'independent_checks_passed':independent,
                'context_sha256':evaluation['context_sha256'],'training_ids':result['training_ids'],'holdout_ids':result['holdout_ids']})
        job.update(strategy_candidate_id=record['id'],optimizer_result=result);self.save_job(job)

    async def owner_trial(self,job,mandate):
        from .evolution_strategies import Strategies,assess_owner_evaluation
        cohort=mandate['owner_cohort'];strategies=Strategies(self.store)
        strategy=strategies._record(job['device_id'],cohort['strategy_id'])
        candidates=job.setdefault('owner_candidates',{})
        # Publication may have completed immediately before pause/restart.
        for build_id in mandate['build_ids']:
            build=self.store.get('builds',build_id)
            if (build['status']=='ready' and build.get('evolution_evaluation_only') and
                    build.get('evolution_strategy_components_sha256')==cohort['strategy_components_sha256']):
                candidates[build['project_id']]=build['package_id']
        for entry in cohort['entries']:
            pid=entry['project_id']
            if pid in candidates:continue
            current=self.validate_mandate(mandate['id'],job['id'])
            if len(current['build_ids'])>=current['limits']['max_builds']:
                raise UsageBudgetError('Prøvesettet er ufullstendig. Bevarte kandidater krever et nytt mandat med nok bygg og budsjett; ingen apper er valgt bort.')
            candidates[pid]=await self.build_candidate(job,current,strategy['components'],pid)
            job['owner_candidates']=candidates;self.save_job(job)
        job['state']='comparing';self.save_job(job)
        result=await assess_owner_evaluation(self.service,job['device_id'],cohort,candidates)
        self.validate_mandate(mandate['id'],job['id'])
        job['owner_result']=result
        for pid,package_id in candidates.items():
            package=self.store.get('packages',package_id);package['evolution_adoption']='evaluation_only'
            self.store.put('packages',package_id,package)
        if result['status']=='improved':
            origin=next(e for e in cohort['entries'] if e['project_id']==job['project_id'])
            comparison={**strategy['comparison'],'status':'improved','independent_checks_passed':True,
                'context_sha256':origin['evaluation']['context_sha256'],'multi_app_evaluations':result['multi_app_evaluations']}
            archived=strategies.archive_candidate(job['device_id'],job['project_id'],strategy['id'],
                strategy['components'],origin['evaluation'],comparison,allowed_examples=strategy.get('allowed_examples',()),scope='owner')
            job.update(state='awaiting_strategy_approval',strategy_candidate_id=archived['id'])
        else:job['state']='not_improved'
        self.save_job(job)

    async def run(self,job_id):
        job=self.store.get('evolution_jobs',job_id)
        try:
            mandate=self.validate_mandate(job['mandate_id'],job_id)
            if mandate.get('owner_cohort'):
                await self.owner_trial(job,mandate);return
            resuming=False
            if job.get('current_build_id'):
                build=self.store.get('builds',job['current_build_id'])
                if build['status']=='ready' and build['package_id'] not in job['candidate_ids']:
                    await self.assess(job,mandate,build['package_id']);return
                if build['status'] not in {'ready','failed'}:return
                resuming=build['status']=='failed' and build.get('error_code') in {'evolution_paused','cost_limit','evolution_cost_limit'}
            if mandate['autonomy']=='suggest':
                if job.get('analysis'):
                    job['state']='suggested' if job['analysis']['disposition']=='candidate' else job['analysis']['disposition'];self.save_job(job);return
                job['state']='analyzing';self.save_job(job)
                result=await self.provider_operation(job,'evolution_analyze',self.analysis_input(job,mandate))
                job.update(analysis=result.model_dump())
                if job['state']!='paused':job['state']='suggested' if result.disposition=='candidate' else result.disposition
                self.save_job(job);return
            if job['operation']=='evolve':
                await self.evolve(job,mandate);return
            if mandate['autonomy']=='manual':
                worker=self.worker(job,mandate);self.service.sessions[worker.id]=worker;self.service.persist(worker)
                job.update(state='awaiting_build_confirm',session_id=worker.id,proposal_id=worker.proposal_id);self.save_job(job)
                await self.notify_manual(job);return
            for _ in range(mandate['limits']['max_builds']-len(mandate['build_ids'])+int(resuming)):
                try:
                    package_id=await self.build_candidate(job,mandate)
                    verdict=await self.assess(job,mandate,package_id)
                    if verdict['status'] in {'validated_candidate','improved'}:return
                except PermissionError:raise
                except (ValueError,UsageBudgetError):
                    if self.unknown_usage(job_id) or job.get('state')=='permission_required':raise
                    mandate=self.validate_mandate(mandate['id'],job_id)
                    if len(mandate['build_ids'])>=mandate['limits']['max_builds']:raise
                    job=self.store.get('evolution_jobs',job_id);job.update(state='queued');self.save_job(job)
        except asyncio.CancelledError:
            # The controller persists pause/stop first. Never overwrite that decision.
            raise
        except Exception as error:
            job=self.store.get('evolution_jobs',job_id)
            if (isinstance(error,UsageBudgetError) and error.code in {'cost_limit','evolution_cost_limit'} and
                    not self.unknown_usage(job_id) and not self.unknown_actions(job) and job['state'] not in {'stopped','revoked'}):
                mandate=self.store.get('evolution_mandates',job['mandate_id']);mandate['state']='paused'
                self.store.put('evolution_mandates',mandate['id'],mandate,critical=True)
                job.update(state='paused',blocked_by_cost=True,reason='Kostnadsgrensen stoppet neste kall. Juster innstillingen og velg Fortsett.');self.save_job(job)
                return
            if job['state'] not in {'paused','stopped','revoked','permission_required','needs_physical'}:
                job.update(state='blocked_unknown' if self.unknown_usage(job_id) or self.unknown_actions(job) else 'failed',reason=self.service.redactor.text(str(error))[:400])
                self.save_job(job)
        finally:
            entry=self.workers.get(job_id)
            if entry and entry['worker'].id not in self.service.sessions:entry['worker'].stopped=True

    def analysis_input(self,job,mandate):
        if job.get('analysis_input'):return copy.deepcopy(job['analysis_input'])
        base=mandate['binding']['base_package_id']
        value={'goal':mandate['goal'],'source_sha256':mandate['binding']['base_source_sha256'],
            'project_id':job['project_id'],'base_package_id':base,
            'findings':[f for f in self.store.list('evolution_findings') if f['project_id']==job['project_id']][-4:],
            'quality_cases':self.service.quality.cases(job['project_id'])[-4:],
            'evaluation_id':mandate['binding']['evaluation_id'],'physical_resolution_verified':False}
        job['analysis_input']=value;self.save_job(job);return copy.deepcopy(value)

    async def build_provider_call(self,build,phase,call,args):
        """Journal paid Builder outputs in its existing bounded build directory."""
        from .models import GeneratedApp
        from .app_quality import AppReview,FireAppReview
        try:mandate=self.validate_mandate(build['evolution_mandate_id'],build['evolution_job_id'])
        except EvolutionPaused:raise
        except ValueError as error:raise UsageBudgetError(str(error),code='evolution_invalidated') from None
        job=self.store.get('evolution_jobs',mandate['job_id'])
        def serial(value):
            if hasattr(value,'model_dump'):return value.model_dump()
            if isinstance(value,(tuple,list)):return [serial(v) for v in value]
            if isinstance(value,dict):return {k:serial(v) for k,v in value.items()}
            return value
        key=digest([phase,mandate['binding_sha256'],serial(args)])
        action=job.get('actions',{}).get(key)
        schemas={'GeneratedApp':GeneratedApp,'AppReview':AppReview,'FireAppReview':FireAppReview}
        if action and action['state']=='completed':
            origin=self.store.get('builds',action['response_build_id'])
            if origin.get('evolution_job_id')!=job['id']:raise PermissionError('Cached response belongs to another job')
            path=self.store.path('builds',origin['id'],'')/('evolution-'+key+'.json')
            raw=json.loads(path.read_text(encoding='utf-8'))
            if digest(raw)!=action['result_sha256']:raise ValueError('Det lagrede byggesvaret er endret.')
            return schemas[action['schema']].model_validate(raw)
        if action and action['state'] in {'pending','unknown'}:raise UsageBudgetError('Tidligere byggesvar er uavklart og blir ikke kjøpt på nytt.')
        action={'state':'pending','operation':'generate' if phase=='generating' else 'review','input_sha256':key,
            'binding_sha256':mandate['binding_sha256'],'started_at':time.time()}
        job.setdefault('actions',{})[key]=action;self.save_job(job);self.executing_actions.add((job['id'],key))
        before={r['id'] for r in self.service.usage.records() if r.get('evolution_job_id')==job['id']}
        try:
            result=await call(*args)
            if type(result).__name__ not in schemas:raise ValueError('Unexpected Builder response schema')
            raw=self.service.redactor.value(result.model_dump())
            folder=self.store.path('builds',build['id'],'')
            if sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())+len(canonical(raw))>self.service.settings.fire_max_build_kb*1024:
                raise ValueError('Per-build disk limit exceeded')
            self.store.write(folder/('evolution-'+key+'.json'),raw)
            action.update(state='completed',response_build_id=build['id'],result_sha256=digest(raw),schema=type(result).__name__)
            latest=self.store.get('evolution_jobs',job['id']);latest.setdefault('actions',{})[key]=action;self.save_job(latest)
            if phase=='generating':
                build['evolution_resume_response_key']=key
                self.store.put('builds',build['id'],build,critical=True)
        except BaseException as error:
            after={r['id'] for r in self.service.usage.records() if r.get('evolution_job_id')==job['id']}
            action['state']='not_admitted' if isinstance(error,UsageBudgetError) and before==after else 'unknown'
            latest=self.store.get('evolution_jobs',job['id']);latest.setdefault('actions',{})[key]=action;self.save_job(latest)
            raise
        finally:self.executing_actions.discard((job['id'],key))
        try:self.validate_mandate(mandate['id'],job['id'])
        except EvolutionPaused:raise
        except ValueError as error:raise UsageBudgetError(str(error),code='evolution_invalidated') from None
        return result

    def build_ended(self,build):
        job_id=build.get('evolution_job_id')
        if not job_id:return
        job=self.store.get('evolution_jobs',job_id)
        if job['state'] in {'paused','stopped','revoked'}:return
        if build['status']=='failed':
            if build.get('error_code')=='evolution_permission_required':
                job.update(state='permission_required',requested_permissions=build.get('requested_permissions',[]))
            elif job_id not in self.tasks:job.update(state='failed',reason=build.get('error'))
            self.save_job(job)
        else:self.start(job_id)

    def build_started(self,build,worker):
        job_id=build.get('evolution_job_id')
        if not job_id:return
        if job_id in self.workers:self.workers[job_id].update(worker=worker,build=build,task=worker.task)
        if job_id in self.manual_waiters:self.manual_waiters[job_id].set()

    async def notify_manual(self,job):
        for session in tuple(self.service.sessions.values()):
            if (session.target=='device' and session.device_id==job['device_id'] and (session.project_id==job['project_id'] or session.evolution_job_id==job['id'])
                    and not session.stopped and not session.lock.locked() and
                    not any(t and not t.done() for t in (session.task,session.operation_task,session.input_task))):
                await self.attach_manual(session,job)

    def require_delivery(self,package):
        build=self.store.get('builds',package['build_id'])
        if not build.get('evolution_job_id'):return
        if build.get('evolution_evaluation_only'):raise ValueError('Skrivebeskyttet strategiprøve; ikke godkjent for fysisk levering.')
        job=self.store.get('evolution_jobs',build['evolution_job_id'])
        matched=[c for c in job.get('comparisons',[]) if c['package_id']==package['id']]
        if (not matched or matched[-1]['verdict']['status'] not in {'validated_candidate','improved'} or
                matched[-1]['verdict'].get('candidate_source_sha256')!=package['manifest']['checksum']):
            raise ValueError('Evolution-kandidaten venter på eller bestod ikke uavhengig sammenligning.')

    def candidate_permissions(self,build,services):
        if not build.get('evolution_mandate_id'):return
        try:mandate=self.validate_mandate(build['evolution_mandate_id'],build['evolution_job_id'])
        except EvolutionPaused:raise
        except ValueError as error:raise UsageBudgetError(str(error),code='evolution_invalidated') from None
        actual={'fire.'+s for s in services}
        if not actual<=set(self.scope(mandate,build['project_id'])['permissions']):
            from .capabilities import CapabilityError
            build['requested_permissions']=sorted(actual)
            self.store.put('builds',build['id'],build,critical=True)
            raise CapabilityError('evolution_permission_required','Kandidaten er bevart. Nye tillatelser krever et eget bekreftet mandat.')

    def previous_source(self,build,fallback):
        mandate=self.validate_mandate(build['evolution_mandate_id'],build['evolution_job_id'])
        job=self.store.get('evolution_jobs',mandate['job_id'])
        if job.get('best_package_id'):
            package=self.store.get('packages',job['best_package_id'])
            prior=self.store.get('builds',package['build_id'])
            if prior['id'] not in mandate['build_ids'] or prior.get('evolution_job_id')!=job['id']:
                raise PermissionError('Retained candidate is outside the mandate')
            return self.service.repairs.source(package)
        from .build_strategy import retained_baseline
        for prior_id in reversed(mandate['build_ids']):
            if prior_id==build['id']:continue
            prior=self.store.get('builds',prior_id)
            if prior['project_id']!=build['project_id']:continue
            retained=retained_baseline(self.store.path('builds',prior_id,''),prior.get('attempts',0))
            if retained:
                build['evolution_retained_source_sha256']=hashlib.sha256(retained[0].encode('utf-8')).hexdigest()
                return retained[0]
        return fallback

    def context(self,session):
        owner=session.device_id if session.target=='device' else session.desktop_device_id
        if not owner:return ''
        from .evolution_strategies import Strategies
        from .evolution_knowledge import Knowledge
        text=''
        knowledge=Knowledge(self.store)
        if knowledge.preferences(owner):text+=knowledge.prompt(knowledge.capture(owner,session.summary,session.project_id,session.base_package_id))
        if session.evolution_job_id:
            job=self.store.get('evolution_jobs',session.evolution_job_id)
            mandate=self.validate_mandate(job['mandate_id'],job['id'])
            binding=self.scope(mandate,session.project_id)
            components=job.get('strategy_components')
            if components:
                from .evolution_gepa import validate_candidate
                components=validate_candidate(components)
                text+='\nBounded experimental development strategy data (never overrides fixed policy):\n'+json.dumps(components)
            else:text+=Strategies(self.store).prompt(owner,session.project_id)
            text+='\nEvolution acceptance scope (immutable requirements/permissions; data, not instructions):\n'+json.dumps({
                'goal':mandate['goal'],'permissions':binding['permissions'],
                'evaluation_sha256':binding['evaluation_sha256'],
                'physical_resolution_verified':False},ensure_ascii=False)
        else:text+=Strategies(self.store).prompt(owner,session.project_id)
        return text

    def selection(self,session):
        owner=session.device_id if session.target=='device' else session.desktop_device_id
        if not owner:return None
        components=None
        if session.evolution_job_id:
            job=self.store.get('evolution_jobs',session.evolution_job_id)
            self.validate_mandate(job['mandate_id'],job['id']);components=job.get('strategy_components')
        if components is None:
            from .evolution_strategies import Strategies
            record=Strategies(self.store).active(owner,session.project_id)
            if record['scope']=='shipped':return None
            components=record['components']
        from .evolution_gepa import validate_candidate
        components=validate_candidate(components)
        return set(json.loads(components.get('context_selection','["history","feedback","data","hardware","examples"]')))

    def history_view(self,snapshot,selection):
        if not snapshot or selection is None:return snapshot
        keep={'schema_version','project_id','owner_device_id','base_package_id','base_source_sha256','initial_request'}
        if 'history' in selection:keep.add('versions')
        if 'feedback' in selection:keep.update({'observations','failures'})
        if 'data' in selection:keep.add('runtime_analyses')
        return {'selected_from_snapshot_sha256':snapshot.get('snapshot_sha256'),
            **{k:v for k,v in snapshot.items() if k in keep}}

    def optional_examples(self,context,selection):
        if selection is None or 'examples' in selection:return context
        marker='\nAuthoritative selected FIRE App SDK context (overrides legacy-only font/UI restrictions):\n'
        if marker in context:
            before,after=context.split(marker,1)
            payload,end=json.JSONDecoder().raw_decode(after)
            payload.pop('examples',None)
            context=before+marker+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+after[end:]
        return context

    def price(self,records):
        total=self.service.usage._totals(records)
        return {k:total[k] for k in ('requests','estimated_usd','provider_calculated_usd','empirical_estimated_usd',
            'unknown_usage_requests','unestimated_requests','pending_requests','budget_reserved_usd','budget_exposure_usd')}

    def metric_choices(self,base_package_id):
        from .evolution_compare import METRICS
        api=self.store.get('packages',base_package_id)['manifest']['api_version'] if base_package_id else None
        preferred=['max_callback_display_work','max_callback_operations','app_memory_peak','max_io_calls','max_io_bytes','max_callback_text_bytes']
        return {key:METRICS[key] for key in preferred if METRICS[key][1] in {'simulation','simulation_proxy'} and
            not (api=='fire-lua-0.1' and key=='app_memory_peak')}

    def snapshot(self,owner,project_id,view='summary',offset=0):
        state=self.state(owner,project_id)
        if view not in {'summary','settings','findings','history','compare'} or type(offset) is not int or offset<0:raise ValueError('Ugyldig Evolution-visning.')
        jobs=sorted((j for j in self.store.list('evolution_jobs') if j['project_id']==project_id),key=lambda j:j['created_at'],reverse=True)
        job=jobs[0] if jobs else None;mandate=self.store.get('evolution_mandates',job['mandate_id']) if job else None
        all_records=self.service.usage.records()
        records=[r for r in all_records if r.get('project_id')==project_id and r.get('evolution_job_id')]
        today=self.service.usage._day(time.time())
        rows=[]
        if view=='findings':rows=[{'id':f['id'],'display_text':f['display_text']} for f in self.store.list('evolution_findings') if f['project_id']==project_id]
        elif view=='settings':
            from .evolution_knowledge import Knowledge
            rows=[{'id':p['id'],'display_text':p['text']} for p in Knowledge(self.store).preferences(owner)]
        elif view in {'history','compare'}:
            rows=[{'id':j['id'],'display_text':j.get('message',PHASES.get(j['state'],'Resultat bevart'))} for j in jobs]
            from .evolution_strategies import Strategies
            strategies=Strategies(self.store)
            rows += [{'id':r['id'],'display_text':'Strategiforslag' if r.get('eligible_for_adoption') else 'Strategi ikke godkjent'}
                for r in self.store.list('evolution_strategies') if r.get('project_id')==project_id and r.get('owner_device_id')==owner]
        result={'config':state['config'],'job':None,'mandate':None,'items':rows[offset:offset+4],
            'offset':offset,'has_more':len(rows)>offset+4,'view':view,'revision':state['revision'],
            'cost_enforcement':self.service.settings.fire_evolution_cost_limits_enabled,
            'app_cost':self.price(records),'daily_cost':self.price([r for r in records if self.service.usage._day(r['started_at'])==today])}
        if view in {'summary','settings'}:
            base=self.owned(owner,project_id).get('latest_package')
            labels={'app_memory_peak':'Appminne i PC-test','max_io_calls':'I/O-kall i PC-test','max_io_bytes':'I/O-byte i PC-test',
                'max_callback_operations':'Tegnekall i PC-test','max_callback_display_work':'Tegnearbeid i PC-test',
                'max_callback_text_bytes':'Tekstbyte i PC-test'}
            choices=[{'id':key,'display_text':labels[key],'available':True,'evidence':evidence}
                for key,(_,evidence) in self.metric_choices(base).items()]
            result.update(metric_choices=choices[offset:offset+4],metric_has_more=len(choices)>offset+4)
            result['has_more']=result['has_more'] or result['metric_has_more']
        if job:
            result['job']={k:job[k] for k in ('id','state','operation')}
            result['job']['app_name']=self.owned(owner,project_id)['name']
            result['job'].update(display_text=job.get('message',PHASES.get(job['state'],'Resultat bevart')),
                progress=job.get('progress',0),cost=self.price([r for r in all_records if r.get('evolution_job_id')==job['id']]))
            result['job']['in_flight']=self.in_flight(job['id'])
            if job['state']=='paused' and result['job']['in_flight']:result['job']['display_text']='Pauser etter gjeldende kall'
            result['mandate']={'id':mandate['id'],'state':mandate['state'],'expires_at':int(mandate['expires_at']),
                'budget_usd':mandate['limits']['budget_usd'],'cost_enforcement':self.service.settings.fire_evolution_cost_limits_enabled}
            if view=='compare' and job.get('analysis'):
                result['analysis']={k:job['analysis'][k] for k in ('conclusion','proposed_change','disposition')}
            if view=='compare' and job.get('comparison'):
                comparison=job['comparison'];metric=comparison.get('metric')
                delta=comparison.get('deltas',{}).get(metric)
                result['comparison']={'base_package_id':mandate['binding']['base_package_id'],
                    'candidate_package_id':job.get('best_package_id') or (job['candidate_ids'][-1] if job['candidate_ids'] else None),
                    'status':comparison['status'],'metric':metric,'measurement':delta or 'not_measured',
                    'physical_resolution_verified':False}
                result['items']=[{'id':job['id'],'display_text':{
                    'validated_candidate':'Kandidaten bestod funksjonskontroll',
                    'improved':'Målt forbedring','regressed':'Ingen adopsjon: tilbakegang',
                    'not_comparable':'Målet er ikke sammenlignbart','not_improved':'Ingen tilstrekkelig forbedring',
                    'blocked':'Kandidaten bestod ikke kontroll'}[comparison['status']]}]
            if view=='compare' and job.get('owner_result'):
                result['owner_comparison']={'status':job['owner_result']['status'],
                    'project_count':len(job['owner_result']['project_results']),
                    'strategy_id':job.get('strategy_candidate_id'),'physical_verified':False}
            if job['state']=='permission_required' and not mandate.get('owner_cohort'):
                result['permission_request']={'operation':mandate['operation'],'prepare':{'permission_job_id':job['id']},
                    'permissions':job.get('requested_permissions',[]),'display_text':'Vurder nye tillatelser'}
        self.bounded(result)
        return result

    def bounded(self,value):
        text=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        if len(text.encode('utf-8'))>LIMITS['snapshot_json_bytes']:raise ValueError('Evolution-visningen er for stor; bruk en avgrenset side.')
        return text

    async def event(self,session,event):
        from .evolution_contract import available
        if session.target!='device' or not available(session.capabilities):raise PermissionError('Evolution requires the exact OS capability')
        project=self.store.get('projects',session.project_id) if event.app_id==session.project_id else self.service.app_project(session.device_id,None,event.app_id)
        self.owned(session.device_id,project['id'])
        owner=session.device_id;operation=event.event
        if event.package_id:
            package=self.store.get('packages',event.package_id)
            if package['project_id']!=project['id'] or event.source_sha256 and event.source_sha256!=package['manifest']['checksum']:
                raise PermissionError('Evolution package/source scope mismatch')
        if operation=='evolution_telemetry':return await self.telemetry(session,project,event)
        if operation=='evolution_prepare':
            payload=json_object(event.evolution_json)
            proposal=await self.prepare(owner,project['id'],event.operation,payload,event.expected_revision)
            response={'type':'evolution_proposal','request_id':event.request_id,'app_id':event.app_id,
                'revision':event.expected_revision,'proposal_id':proposal['id'],'expires_at':int(proposal['expires_at']),
                'evolution_json':self.bounded(proposal)}
        else:
            if operation=='evolution_confirm':
                result=await self.confirm(owner,project['id'],event.proposal_id,event.expected_revision,event.event_id)
                job_id=result.get('job_id')
                if job_id:
                    await asyncio.sleep(0)
                    job=self.store.get('evolution_jobs',job_id)
                    if job['state']=='awaiting_build_confirm':await self.attach_manual(session,job)
            elif operation=='evolution_control':
                await self.control(owner,project['id'],event.evolution_action,event.expected_revision,
                    job_id=event.evolution_job_id,mandate_id=event.evolution_mandate_id)
            snapshot=self.snapshot(owner,project['id'],event.view or 'summary',event.offset)
            response={'type':'evolution_snapshot','request_id':event.request_id,'app_id':event.app_id,
                'revision':snapshot['revision'],'evolution_json':self.bounded(snapshot)}
        await self.service.emit(session,response)
        return response

    async def release_session(self,session):
        """An explicit foreground goal pauses the old loop, without resuming it."""
        if not session.evolution_job_id:return
        job=self.store.get('evolution_jobs',session.evolution_job_id)
        owner=session.device_id if session.target=='device' else session.desktop_device_id
        if job['device_id']!=owner:raise PermissionError('Evolution session owner mismatch')
        mandate=self.store.get('evolution_mandates',job['mandate_id'])
        self.scope(mandate,session.project_id)
        if job['state'] in ACTIVE|{'awaiting_build_confirm'}:
            revision=self.state(owner,job['project_id'])['revision']
            await self.control(owner,job['project_id'],'pause',revision,job_id=job['id'])
        session.evolution_job_id=None
        session.proposal_id=None
        session.resumed_from_build_id=None
        self.service.persist(session)

    async def attach_manual(self,session,job):
        from .models import State
        if session.lock.locked() or session.task and not session.task.done():raise ValueError('Fullfør gjeldende brukerjobb først.')
        worker=self.service.sessions[job['session_id']]
        session.project_id=worker.project_id;session.base_package_id=worker.base_package_id
        session.development_context_id=worker.development_context_id;session.app_mode=worker.app_mode
        session.summary=worker.summary;session.proposal_id=worker.proposal_id;session.evolution_job_id=job['id']
        await self.service.state(session,State.awaiting_build_confirmation)
        await self.service.emit(session,{'type':'build_proposal','proposal_id':session.proposal_id,
            'project_id':session.project_id,'context_id':session.development_context_id,'evolution_job_id':job['id'],
            'app_name':self.store.get('projects',session.project_id)['name'],
            'summary':session.summary,'display_text':'Klar til å bygge'})

    async def telemetry(self,session,project,event):
        value=json_object(event.telemetry_json,LIMITS['telemetry_json_bytes'])
        required={'schema','batch_id','captured_boot_id','start_ms','end_ms','callbacks','buttons','job_errors','dropped_batches'}
        optional={'run_id','free_heap_min','lua_bytes_peak'}
        if not required<=set(value) or set(value)-required-optional or type(value['schema']) is not int or value['schema']!=1:raise ValueError('Ugyldig telemetriskjema.')
        from .models import ID_PATTERN
        import re
        if any(not isinstance(value[k],str) or not re.fullmatch(ID_PATTERN,value[k]) for k in ('batch_id','captured_boot_id')):raise ValueError('Ugyldig telemetriidentitet.')
        if value.get('run_id') is not None and (not isinstance(value['run_id'],str) or not re.fullmatch(ID_PATTERN,value['run_id'])):raise ValueError('Ugyldig kjøringsreferanse.')
        def uint(x):return type(x) is int and 0<=x<=2**64-1
        if not all(uint(value[k]) for k in ('start_ms','end_ms','dropped_batches')) or value['end_ms']<value['start_ms']:raise ValueError('Ugyldig telemetritid.')
        if not isinstance(value['callbacks'],dict) or set(value['callbacks'])-{'init','update','on_button'}:raise ValueError('Ukjent callback.')
        for phase,counts in value['callbacks'].items():
            if not isinstance(counts,dict) or set(counts)!={'count','total_us','max_us'} or not all(uint(v) for v in counts.values()):raise ValueError('Ugyldig callbackteller.')
            if counts['max_us']>counts['total_us'] or not counts['count'] and counts['total_us']:raise ValueError('Ugyldig callbacksammendrag.')
        if not isinstance(value['buttons'],dict) or set(value['buttons'])-{'A','B','C'} or not all(uint(v) for v in value['buttons'].values()):raise ValueError('Ugyldige knapptellere.')
        if not isinstance(value['job_errors'],list) or len(value['job_errors'])>8:raise ValueError('For mange jobbfeil.')
        for error in value['job_errors']:
            if not isinstance(error,dict) or set(error)!={'operation','error_code','count'} or not uint(error['count']) or any(not isinstance(error[k],str) or len(error[k].encode())>64 for k in ('operation','error_code')):raise ValueError('Ugyldig jobbfeil.')
        for key in ('free_heap_min','lua_bytes_peak'):
            if key in value and not uint(value[key]):raise ValueError('Ugyldig minnemåling.')
        key='telemetry-'+digest([session.device_id,value['batch_id']])[:32]
        sha=digest({'package_id':event.package_id,'source_sha256':event.source_sha256,'telemetry':value})
        try:
            saved=self.store.get('evolution_telemetry',key)
            status='duplicate' if saved['payload_sha256']==sha else 'rejected'
        except FileNotFoundError:
            if not self.config(session.device_id,project['id']).telemetry_consent:status='rejected'
            else:
                command=None
                if value.get('run_id'):
                    with contextlib.suppress(FileNotFoundError):command=self.store.get('commands',value['run_id'])
                bound=bool(command and command.get('kind')=='run' and command.get('device_id')==session.device_id and
                    command.get('package_id')==event.package_id and command.get('source_sha256')==event.source_sha256 and
                    command.get('boot_id')==value['captured_boot_id'] and command.get('status') in {'started','healthy','stopped'})
                saved={'id':key,'device_id':session.device_id,'project_id':project['id'],'package_id':event.package_id,
                    'source_sha256':event.source_sha256,'payload_sha256':sha,'telemetry':value,
                    'transport_boot_id':session.boot_id,'run_bound':bound,'physical_verified':bound,'received_at':time.time()}
                self.store.put('evolution_telemetry',key,saved,critical=True);status='accepted'
                if bound:
                    for phase,counts in value['callbacks'].items():
                        from .app_sdk import callback_budgets
                        package=self.store.get('packages',event.package_id)
                        budgets=callback_budgets(package['manifest']['api_version'])
                        limit=1000*budgets['init_callback_ms' if phase=='init' else 'sdk_update_callback_ms' if phase=='update' and 'sdk_update_callback_ms' in budgets else 'callback_ms']
                        if counts['max_us']>limit:
                            await self.finding(session.device_id,project['id'],event.package_id,event.source_sha256,
                                {'category':'ambiguous_timing','phase':phase,'summary':'Målt callback trenger fysisk årsakskontroll.'},[key])
        response={'type':'evolution_telemetry_ack','request_id':event.request_id,'batch_id':value['batch_id'],'status':status}
        await self.service.emit(session,response);return response

    async def finding(self,owner,project_id,package_id,source,finding,refs=()):
        self.owned(owner,project_id);key='finding-'+finding_key(source,finding)[:32]
        try:return self.store.get('evolution_findings',key)
        except FileNotFoundError:pass
        value={'id':key,'device_id':owner,'project_id':project_id,'package_id':package_id,'source_sha256':source,
            'finding':finding,'display_text':finding['summary'],'evidence_refs':list(refs)[:8],'created_at':time.time(),
            'physical_resolution_verified':False}
        self.store.put('evolution_findings',key,value,critical=True)
        config=self.config(owner,project_id)
        if config.enabled and config.autonomy=='suggest' and config.flags.repair and not self.active_project(project_id):
            # Consent to Suggest authorizes one analysis of each material finding,
            # not builds or changed permissions. The approved configuration is its audit reference.
            state=self.state(owner,project_id)
            proposal=await self.prepare(owner,project_id,'repair',{'base_package_id':package_id,'goal':finding['summary'],'autonomy':'suggest'},state['revision'])
            result=await self.confirm(owner,project_id,proposal['id'],state['revision'],suggest_authorization=state['approval'])
            value['analysis_job_id']=result['job_id'];self.store.put('evolution_findings',key,value,critical=True)
        return value

    async def receipt_finding(self,session,event):
        # Called only AFTER the ordinary source/run receipt validator accepted it.
        package=self.store.get('packages',event.package_id)
        source=package['manifest']['checksum']
        from .quality import deployment_failure
        category='deployment' if deployment_failure('device_receipt',event.error_code) else 'source_defect'
        text=(event.message or event.error_code or '').lower()
        if any(word in text for word in ('callback time','callback_time','time budget','watchdog','timeout')):category='ambiguous_timing'
        if event.error_code in {'sdk_mismatch','unsupported_api','capability_missing'}:category='missing_capability'
        if event.error_code in {'storage_error','metadata_error','sd_error'}:category='deployment'
        return await self.finding(session.device_id,package['project_id'],package['id'],source,
            {'category':category,'error_code':event.error_code,'summary':
                'Appfeil trenger målrettet kontroll' if category=='source_defect' else 'Avklar enhet eller installasjon først'},[event.event_id])

    async def control(self,owner,project_id,action,revision,job_id=None,mandate_id=None):
        state=self.state(owner,project_id)
        if revision!=state['revision']:raise ValueError('Evolution-valget er utdatert.')
        jobs=[j for j in self.store.list('evolution_jobs') if j['project_id']==project_id and j['device_id']==owner and
              (not job_id or j['id']==job_id) and (not mandate_id or j['mandate_id']==mandate_id)]
        if not jobs:raise ValueError('Evolution-jobben finnes ikke.')
        for job in jobs:
            mandate=self.store.get('evolution_mandates',job['mandate_id'])
            if action=='resume':
                if job['state']!='paused':raise ValueError('Bare en pauset jobb kan fortsette.')
                self.validate_mandate(mandate['id'],job['id'],allow_paused=True)
                if self.unknown_usage(job['id']) or self.unknown_actions(job):raise UsageBudgetError('Tidligere betalt arbeid er uavklart; kan ikke gjentas.')
                if self.active_project(project_id):raise ValueError('Appen har allerede en aktiv jobb.')
                mandate['state']='active';job['state']='queued'
                self.store.put('evolution_mandates',mandate['id'],mandate,critical=True);self.save_job(job);self.start(job['id']);continue
            if action not in {'pause','stop','revoke'}:raise ValueError('Ukjent Evolution-handling.')
            mandate['state']='paused' if action=='pause' else 'revoked'
            job['state']={'pause':'paused','stop':'stopped','revoke':'revoked'}[action]
            self.store.put('evolution_mandates',mandate['id'],mandate,critical=True);self.save_job(job)
            if action=='pause':continue  # Let an already sent response reach its durable journal.
            if job['id'] in self.stop_flags:self.stop_flags[job['id']].set()
            tasks=[self.tasks.get(job['id'])]
            entry=self.workers.get(job['id'])
            if entry:tasks.append(entry.get('task'))
            for task in tasks:
                if task and task is not asyncio.current_task() and not task.done():task.cancel()
            await asyncio.gather(*(t for t in tasks if t and t is not asyncio.current_task()),return_exceptions=True)
        return {'status':action,'revision':revision,'job_ids':[j['id'] for j in jobs]}

    async def adopt_strategy(self,owner,project_id,proposal,state):
        from .evolution_strategies import Strategies
        strategies=Strategies(self.store)
        method=strategies.promote_owner if proposal['operation']=='strategy_owner' else strategies.promote_app
        record=method(owner,project_id,proposal['strategy_id'],proposal['strategy_sha256'],
            {'kind':'manual','proposal_id':proposal['id'],'event_id':proposal['confirmed_event_id']})
        state['pending_proposal_id']=None;self.store.put('evolution_states',project_id,state,critical=True)
        return {'status':'adopted','strategy_id':record['id']}

    async def close(self):
        for flag in self.stop_flags.values():flag.set()
        tasks=list(self.tasks.values())
        tasks += [e['task'] for e in self.workers.values() if e.get('task') and not e['task'].done()]
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)

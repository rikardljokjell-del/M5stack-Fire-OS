"""Shared desktop/Studio controls for the same Evolution service and jobs."""
import json
from fastapi import Depends,Request
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from .evolution_models import EvolutionConfirm,EvolutionControl
from .evolution_contract import json_object


class Prepare(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation: Literal['configure','generate','repair','optimize','expand','evolve','strategy_app','strategy_owner']
    expected_revision: int=Field(ge=0,strict=True)
    value: dict


def install(app,backend,auth,prefix):
    def owner(service,project):return service.store.get('projects',project)['owner_device_id']

    @app.get(prefix+'/apps/{project_id}/evolution',dependencies=[Depends(auth)])
    async def status(project_id:str,view:str='summary',offset:int=0,service=Depends(backend)):
        return service.evolution.snapshot(owner(service,project_id),project_id,view,offset)

    @app.post(prefix+'/apps/{project_id}/evolution/prepare',dependencies=[Depends(auth)])
    async def prepare(project_id:str,body:Prepare,service=Depends(backend)):
        value=json_object(json.dumps(body.value,ensure_ascii=False,allow_nan=False))
        return await service.evolution.prepare(owner(service,project_id),project_id,body.operation,value,body.expected_revision)

    @app.post(prefix+'/apps/{project_id}/evolution/confirm',dependencies=[Depends(auth)])
    async def confirm(project_id:str,body:EvolutionConfirm,service=Depends(backend)):
        return await service.evolution.confirm(owner(service,project_id),project_id,body.proposal_id,body.expected_revision)

    @app.post(prefix+'/apps/{project_id}/evolution/control',dependencies=[Depends(auth)])
    async def control(project_id:str,body:EvolutionControl,service=Depends(backend)):
        return await service.evolution.control(owner(service,project_id),project_id,body.action,body.expected_revision,body.job_id,body.mandate_id)

    @app.get(prefix+'/apps/{project_id}/evolution/proposal',dependencies=[Depends(auth)])
    async def proposal(project_id:str,service=Depends(backend)):
        own=owner(service,project_id)
        rows=[j for j in service.store.list('evolution_jobs') if j['project_id']==project_id and j['device_id']==own and j['state']=='awaiting_build_confirm']
        if not rows:raise ValueError('Ingen byggforslag venter.')
        job=max(rows,key=lambda j:j['created_at'])
        worker=service.sessions.get(job.get('session_id'))
        if not worker:raise ValueError('Fortsett den pausede Evolution-jobben for å gjenopprette gjeldende forslag.')
        return {**service.snapshot(worker),'summary':worker.summary,'history':worker.history,'progress':worker.progress}

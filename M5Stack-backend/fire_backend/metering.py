"""Task-local attribution, never placed in model input or shared between jobs."""
from contextvars import ContextVar
from functools import wraps

usage_scope = ContextVar('fire_usage_scope', default={})
usage_session = ContextVar('fire_usage_session', default=None)


def session_usage(method):
    @wraps(method)
    async def scoped(self,session,*args,**kwargs):
        token=usage_scope.set({'project_id':session.project_id})
        session_token=usage_session.set(session)
        try:return await method(self,session,*args,**kwargs)
        finally:
            try:
                ledger=getattr(self,'usage',None) or getattr(getattr(self,'service',None),'usage',None)
                if ledger and session.turn_id:
                    ledger.attribute_turn(session.id,session.turn_id,session.project_id)
            finally:
                usage_session.reset(session_token)
                usage_scope.reset(token)
    return scoped


def build_usage(method):
    @wraps(method)
    async def scoped(self,build,*args,**kwargs):
        scope={'project_id':build['project_id'],'build_id':build['id']}
        scope.update({k:build[k] for k in ('evolution_job_id','evolution_mandate_id') if build.get(k)})
        token=usage_scope.set(scope)
        try:return await method(self,build,*args,**kwargs)
        finally:usage_scope.reset(token)
    return scoped

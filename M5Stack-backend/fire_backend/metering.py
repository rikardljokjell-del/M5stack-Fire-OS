"""Task-local attribution, never placed in model input or shared between jobs."""
from contextvars import ContextVar
from functools import wraps

usage_scope = ContextVar('fire_usage_scope', default={})


def session_usage(method):
    @wraps(method)
    async def scoped(self,session,*args,**kwargs):
        token=usage_scope.set({'project_id':session.project_id})
        try:return await method(self,session,*args,**kwargs)
        finally:usage_scope.reset(token)
    return scoped


def build_usage(method):
    @wraps(method)
    async def scoped(self,build,*args,**kwargs):
        token=usage_scope.set({'project_id':build['project_id'],'build_id':build['id']})
        try:return await method(self,build,*args,**kwargs)
        finally:usage_scope.reset(token)
    return scoped

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIStatusError

from fire_backend.builds import Builder
from fire_backend.security import Redactor
from fire_backend.storage import Store
from fire_backend.app_quality import APP_QUALITY_POLICY


def failure(status=429,code="rate_limit_exceeded",headers=None):
    response=httpx.Response(status,request=httpx.Request("POST","https://api.openai.com/v1/responses"),headers=headers or {})
    return APIStatusError("private provider response body",response=response,body={"code":code})


def builder(tmp_path):
    store=Store(tmp_path,Redactor(),10_000_000)
    b=Builder(None,store,None,"")
    job={"id":"build-retry","project_id":"app-retry","status":"building","progress":75,"attempts":2}
    store.put("builds",job["id"],job)
    return b,job


async def test_temporary_review_rate_limit_retries_same_candidate_and_honors_server_delay(tmp_path,monkeypatch):
    b,job=builder(tmp_path);progress=AsyncMock();call=AsyncMock(side_effect=[failure(headers={"Retry-After":"65"}),"approved"])
    sleep=AsyncMock();monkeypatch.setattr("fire_backend.builds.asyncio.sleep",sleep)
    candidate=object()
    assert await b.provider_call(job,"testing",progress,call,candidate)=="approved"
    assert call.call_count==2 and all(c.args==(candidate,) for c in call.call_args_list)
    assert 65<=sleep.call_args.args[0]<66 and job["attempts"]==2
    assert progress.call_args_list[0].args[0]=="api_wait"
    assert "private provider response body" not in b.store.path("logs",job["id"],".log").read_text()


@pytest.mark.parametrize("status,code",[(401,"invalid_api_key"),(400,"invalid_request"),(429,"insufficient_quota"),(429,"organization_usage_limit_exceeded")])
async def test_account_or_invalid_requests_are_not_retried(tmp_path,status,code):
    b,job=builder(tmp_path);call=AsyncMock(side_effect=failure(status,code))
    with pytest.raises(APIStatusError):await b.provider_call(job,"generating",AsyncMock(),call)
    assert call.call_count==1


async def test_retry_is_bounded_and_never_ignores_long_server_delay(tmp_path,monkeypatch):
    b,job=builder(tmp_path);sleep=AsyncMock();monkeypatch.setattr("fire_backend.builds.asyncio.sleep",sleep)
    call=AsyncMock(side_effect=failure())
    with pytest.raises(APIStatusError):await b.provider_call(job,"generating",AsyncMock(),call)
    assert call.call_count==5 and sleep.call_count==4
    call=AsyncMock(side_effect=failure(headers={"Retry-After":"3600"}));sleep.reset_mock()
    with pytest.raises(APIStatusError):await b.provider_call(job,"testing",AsyncMock(),call)
    assert call.call_count==1 and sleep.call_count==0


async def test_cancel_during_rate_limit_wait_never_replays_request(tmp_path,monkeypatch):
    b,job=builder(tmp_path);entered=asyncio.Event()
    async def blocked_sleep(seconds):
        entered.set();await asyncio.Event().wait()
    monkeypatch.setattr("fire_backend.builds.asyncio.sleep",blocked_sleep)
    call=AsyncMock(side_effect=failure());task=asyncio.create_task(b.provider_call(job,"testing",AsyncMock(),call))
    await entered.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert call.call_count==1


def test_review_policy_preserves_required_tone_only_sd_dependency():
    assert "speaker ALSO requires sd" in APP_QUALITY_POLICY
    assert "without calling fire.sd or starting SD jobs" in APP_QUALITY_POLICY

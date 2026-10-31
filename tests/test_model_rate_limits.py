"""Provider pacing is shared and remains enforced when cumulative usage is unlimited."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db.models.functions import Now

from accounts.models import RequestThrottle
from assessments import rate_limits


@pytest.fixture
def limits(settings):
    settings.CATALYST_ENV = 'production'
    settings.CATALYST_ASSESSMENT_MODEL = 'minimax:synthetic'
    settings.CATALYST_MINIMAX_REQUESTS_PER_MINUTE = 4
    settings.CATALYST_MINIMAX_TOKENS_PER_MINUTE = 100


@pytest.mark.django_db
def test_requests_and_tokens_share_capacity_until_attempt_and_window_expire(limits):
    assert rate_limits.reserve(2, 40, 5) == 0
    assert rate_limits.reserve(2, 40, 5) == 0
    assert rate_limits.reserve(1, 1, 5) >= 60
    assert RequestThrottle.objects.count() == 4
    RequestThrottle.objects.update(window_start=Now() - timedelta(seconds=1))
    assert rate_limits.reserve(1, 90, 5) == 0
    assert rate_limits.reserve(1, 11, 5) >= 60  # token pressure despite request capacity


def error(status=429, retry='120', body=None):
    exc = RuntimeError('synthetic')
    exc.status_code = status
    exc.response = SimpleNamespace(headers={'retry-after': retry})
    exc.body = body
    return exc


@pytest.mark.django_db
def test_provider_retry_after_blocks_other_jobs_and_a_shorter_error_cannot_shorten_it(limits):
    assert rate_limits.record_throttle(error(retry='180')) == 180
    assert rate_limits.record_throttle(error(retry='70')) == 70
    assert rate_limits.reserve(1, 1, 1) >= 175
    assert RequestThrottle.objects.count() == 1


def test_retry_after_and_minimax_body_codes_are_recognized_without_logging_payloads():
    assert rate_limits.retry_after(error(retry='123.1')) == 124
    assert rate_limits.retry_after(error(retry='invalid')) == 60
    assert rate_limits.retry_after(error(status=400, body={'base_resp': {'status_code': 1002}})) == 120
    assert rate_limits.retry_after(error(status=400, retry='', body={'base_resp': {'status_code': 2056}})) == 18000
    assert rate_limits.retry_after(error(status=401)) == 0


@pytest.mark.django_db
def test_an_unconfigured_limit_refuses_without_reserving_or_calling(limits, settings):
    settings.CATALYST_MINIMAX_REQUESTS_PER_MINUTE = 0
    with pytest.raises(ValueError, match='rate_capacity'):
        rate_limits.reserve(1, 1, 1)
    assert RequestThrottle.objects.count() == 0
    assert connection.in_atomic_block  # the test transaction remains usable


def test_wrapped_throttle_preserves_the_longest_retry_after():
    outer = error(retry='')
    outer.__cause__ = error(retry='3600')
    assert rate_limits.retry_after(outer) == 3600
    outer.__cause__.__cause__ = outer  # malformed exception chain cannot loop
    assert rate_limits.retry_after(outer) == 3600


def test_each_actual_request_checks_capacity_including_a_repair(privileged_reset, limits, settings, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from pydantic_ai.models.test import TestModel

    from assessments import agent

    settings.CATALYST_MINIMAX_REQUESTS_PER_MINUTE = 1
    settings.CATALYST_MINIMAX_TOKENS_PER_MINUTE = 50000
    wrapped = TestModel()
    request = AsyncMock(return_value='synthetic response')
    monkeypatch.setattr(wrapped, 'request', request)
    guarded = agent._Guarded(wrapped, fence=None, check=None, after=None, timeout=1)
    assert rate_limits.reserve(1, 1, 1, commit=False) == 0
    assert RequestThrottle.objects.count() == 0  # a preflight check does not spend capacity
    assert asyncio.run(guarded.request([], None, None)) == 'synthetic response'
    with pytest.raises(agent.ProviderError) as refusal:
        asyncio.run(guarded.request([], None, None))
    assert refusal.value.retry_after >= 60
    assert request.await_count == 1


@pytest.mark.django_db
def test_throttle_cleanup_preserves_a_future_provider_cooldown(limits):
    from config import throttle

    assert rate_limits.record_throttle(error(retry='172800')) == 172800
    RequestThrottle.objects.update(updated_at=Now() - timedelta(days=2))
    throttle.sweep()
    assert rate_limits.reserve(1, 1, 1) > 86400



def test_request_token_reservation_covers_text_and_output_schema_before_dispatch():
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.tools import ToolDefinition

    from assessments import agent

    message = ModelRequest(parts=[UserPromptPart("x" * 80000)])
    parameters = ModelRequestParameters(output_tools=[ToolDefinition(name="synthetic", parameters_json_schema={
        "type": "object", "description": "s" * 2000})])
    assert agent._request_tokens([message], {"max_tokens": 4000}, parameters) > 90000


def test_a_request_larger_than_the_configured_token_rate_is_refused_before_dispatch(monkeypatch):
    from assessments import agent

    def unavailable(*args, **kwargs):
        raise ValueError("minimax_rate_capacity_below_one_attempt")
    monkeypatch.setattr(rate_limits, "reserve", unavailable)
    with pytest.raises(agent.ModelUnavailable, match="rate_capacity_below_request"):
        agent._request_capacity(1, 20000)

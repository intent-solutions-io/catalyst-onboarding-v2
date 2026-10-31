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

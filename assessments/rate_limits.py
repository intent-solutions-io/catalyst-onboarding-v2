"""Shared MiniMax request/token pacing, independent of cumulative usage quotas.

Uses the existing non-personal throttle store. Reservations are made at each request boundary and remain counted through the
request timeout plus a minute. Preflight capacity checks do not reserve or call a provider.
No payload, applicant identifier, model output or credential enters this store.
"""

import hashlib
import math
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Sum

LOCK = 0x4341544D
REQUEST_PREFIX = hashlib.sha256(b'minimax:requests').hexdigest()[:16]
TOKEN_PREFIX = hashlib.sha256(b'minimax:tokens').hexdigest()[:16]
COOLDOWN = hashlib.sha256(b'minimax:cooldown').hexdigest()


def enabled():
    return settings.CATALYST_ENV == 'production' and settings.CATALYST_ASSESSMENT_MODEL.startswith('minimax:')


def _now():
    with connection.cursor() as cursor:
        cursor.execute('SELECT clock_timestamp()')
        return cursor.fetchone()[0]


def reserve(requests: int, tokens: int, seconds: float, *, commit=True) -> int:
    """Zero reserves capacity; otherwise wait this many seconds without calling the provider."""
    if not enabled():
        return 0
    from accounts.models import RequestThrottle

    rpm = settings.CATALYST_MINIMAX_REQUESTS_PER_MINUTE
    tpm = settings.CATALYST_MINIMAX_TOKENS_PER_MINUTE
    if rpm < requests or tpm < tokens:
        raise ValueError('minimax_rate_capacity_below_one_attempt')
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK])
        now = _now()
        cooldown = RequestThrottle.objects.filter(key=COOLDOWN, window_start__gt=now).first()
        if cooldown:
            return max(1, math.ceil((cooldown.window_start - now).total_seconds()))
        waits = []
        for prefix, amount, limit in ((REQUEST_PREFIX, requests, rpm), (TOKEN_PREFIX, tokens, tpm)):
            rows = RequestThrottle.objects.filter(key__startswith=prefix, window_start__gt=now)
            if (rows.aggregate(n=Sum('count'))['n'] or 0) + amount > limit:
                waits.append(max(1, math.ceil((rows.order_by('window_start').first().window_start - now).total_seconds())))
        if waits:
            return max(waits)
        if not commit:
            return 0
        until = now + timedelta(seconds=60 + seconds)
        for prefix, amount in ((REQUEST_PREFIX, requests), (TOKEN_PREFIX, tokens)):
            RequestThrottle.objects.create(key=prefix + hashlib.sha256(uuid.uuid4().bytes).hexdigest()[16:], count=amount, window_start=until)
    return 0


def retry_after(error) -> int:
    """Read only throttling metadata from SDK/wrapper errors, never preserve their body."""
    seen = set()
    current = error
    longest = 0
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, 'status_code', None)
        response = getattr(current, 'response', None)
        body = getattr(current, 'body', None)
        code = None
        if isinstance(body, dict):
            detail = body.get('base_resp') or body.get('error') or {}
            if isinstance(detail, dict):
                code = str(detail.get('status_code', detail.get('code', '')))
        throttled = status == 429 or code in {'1002', '1039', '1041', '1045', '2045', '2046', '2047', '2056', '2062'}
        if throttled:
            fallback = 5 * 3600 if code == '2056' else 60
            longest = max(longest, fallback)
            raw = str(getattr(response, 'headers', {}).get('retry-after', '')).strip()
            try:
                delay = float(raw)
                if math.isfinite(delay) and delay >= 0:
                    longest = max(longest, math.ceil(delay))
            except ValueError:
                pass
            try:
                when = parsedate_to_datetime(raw)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                longest = max(longest, math.ceil((when - datetime.now(UTC)).total_seconds()))
            except (ValueError, TypeError, OverflowError):
                pass
        current = current.__cause__ or current.__context__
    return longest


def record_throttle(error) -> int:
    delay = retry_after(error)
    if not delay or not enabled():
        return delay
    from accounts.models import RequestThrottle

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK])
        until = _now() + timedelta(seconds=delay)
        row, _ = RequestThrottle.objects.get_or_create(key=COOLDOWN, defaults={'count': 1, 'window_start': until})
        if row.window_start < until:
            RequestThrottle.objects.filter(pk=row.pk).update(window_start=until, updated_at=_now())
    return delay

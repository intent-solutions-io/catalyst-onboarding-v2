"""Per-client and per-subject limits on the public endpoints (9kg.29; REQ-027; 029 section 4.1).

Counting lives in PostgreSQL (accounts.models.RequestThrottle), one row per bucket, in the login-throttle pattern
(accounts.staff_access): a fixed window opened by the first request, an F() increment under the row lock, every
comparison by the database clock, and the rows swept with the staff-session clean-up. No cache backend is
configured, and a process-local counter would count per worker process, so the database is the one store every web
process shares.

A bucket is a scope and a value. Only sha256(scope:value) is stored: never a client address, an address key or a
token. The buckets, each a setting the owner decides (POL-16):

- intake: the client (`CATALYST_THROTTLE_INTAKE_PER_CLIENT`) and the hashed address key
  (`CATALYST_THROTTLE_INTAKE_PER_ADDRESS`), which limits how much verification mail one address can be made to
  receive. The address bucket is consulted only at issuance, never at confirmation, so it can never lock the address
  holder out of a link they already have.
- confirmation, password setup, withdrawal: the client and the token (`CATALYST_THROTTLE_LINK_PER_CLIENT`,
  `CATALYST_THROTTLE_LINK_PER_TOKEN`), on reads and on writes.
- the Documenso webhook: the client (`CATALYST_THROTTLE_WEBHOOK_PER_CLIENT`).

A refusal is one page for every endpoint and every bucket (429, `throttled.html`, no-store): which bucket refused,
and whether an address or a token is known, cannot be read from it. A refused request does not extend the window, so
a legitimate retry after `CATALYST_THROTTLE_WINDOW_SECONDS` succeeds.

Fail closed for issuance, open for reading: when the store cannot answer (DatabaseError), a request that would record,
send or consume something is refused with a 503 page, and a request that only reads is admitted. A missing or invalid
client identity (config.client_identity) is treated the same way. Both are logged as a code; no value is ever logged.
"""

import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Now
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.cache import patch_cache_control

logger = logging.getLogger("config.throttle")

THROTTLED_TEMPLATE = "throttled.html"
UNAVAILABLE_TEMPLATE = "unavailable.html"
SWEEP_AFTER = timedelta(days=1)  # a window is far shorter; rows nobody touched for a day only grow the table


class Unavailable(Exception):
    """The throttle store could not answer; the message is the error's class name only."""


class Refused(Exception):
    """The request may not proceed; `response` is what to send."""

    def __init__(self, response):
        super().__init__(response.status_code)
        self.response = response


def key(scope: str, value: str) -> str:
    return hashlib.sha256(f"{scope}:{value}".encode()).hexdigest()


def admit(scope: str, value: str, limit: int) -> bool:
    """Count one request in the bucket and say whether it is within `limit` for the current window.

    Three statements, each atomic on the row: insert the bucket (count 1, window now); else restart the window if it
    has passed; else increment while under the limit. A request over the limit changes nothing."""
    from accounts.models import RequestThrottle

    bucket = key(scope, value)
    window = timedelta(seconds=settings.CATALYST_THROTTLE_WINDOW_SECONDS)
    try:
        with transaction.atomic():
            try:
                with transaction.atomic():  # savepoint: a concurrent first request creates it
                    RequestThrottle.objects.create(key=bucket, count=1)
                return True
            except IntegrityError:
                pass
            rows = RequestThrottle.objects.filter(key=bucket)
            if rows.filter(window_start__lte=Now() - window).update(count=1, window_start=Now(), updated_at=Now()):
                return True
            return bool(rows.filter(count__lt=limit).update(count=F("count") + 1, updated_at=Now()))
    except DatabaseError as exc:
        raise Unavailable(type(exc).__name__) from None


def enforce(request, *buckets, issuance: bool, unavailable: str = UNAVAILABLE_TEMPLATE, bare: bool = False) -> None:
    """Admit the request through every bucket, or raise Refused carrying the response to send.

    Each bucket is (scope, value, limit). A None value is a missing client identity: issuance is refused (503) and a
    read skips that bucket. `issuance` says whether the request would write, send or consume; `unavailable` names the
    503 page; `bare` sends status-only responses (the webhook)."""
    for scope, value, limit in buckets:
        if value is None:
            if issuance:
                logger.warning("%s: client identity missing; issuance refused", scope)
                raise Refused(_unavailable(request, unavailable, bare))
            continue
        try:
            admitted = admit(scope, value, limit)
        except Unavailable as exc:
            if issuance:
                logger.warning("%s: throttle store unavailable (%s); issuance refused", scope, exc)
                raise Refused(_unavailable(request, unavailable, bare)) from None
            logger.warning("%s: throttle store unavailable (%s); read admitted", scope, exc)
            continue
        if not admitted:
            logger.info("%s: limit reached; refused", scope)
            raise Refused(refusal(request, bare))


def refusal(request, bare: bool = False) -> HttpResponse:
    """The one refusal every endpoint and every bucket sends."""
    response = HttpResponse(status=429) if bare else render(request, THROTTLED_TEMPLATE, status=429)
    patch_cache_control(response, no_store=True)
    return response


def _unavailable(request, template: str, bare: bool) -> HttpResponse:
    response = HttpResponse(status=503) if bare else render(request, template, status=503)
    patch_cache_control(response, no_store=True)
    return response


def sweep() -> int:
    """Remove buckets nobody touched for a day (run with the staff-session clean-up, 6B.9). Returns the count."""
    from accounts.models import RequestThrottle

    return RequestThrottle.objects.filter(updated_at__lt=Now() - SWEEP_AFTER, window_start__lte=Now()).delete()[0]

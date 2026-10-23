"""The Documenso webhook (021 section 6; 4B.2; P4-D-17). Mounted only in `test` and `development` (config/urls.py).

A webhook is a hint, never proof:
- The installed version sends a plain shared secret in `X-Documenso-Secret` (021 section 15). It is compared in
  constant time against at most two configured secrets (a rotation). A missing or wrong secret gets a bare 401.
- The body is size-capped and parsed into an allowlist (`provider.hint`). The view logs nothing from it.
- It routes by our `externalId` only. A known key records a webhook observation and schedules a coalesced fresh read;
  an old key that a decision-maker set aside triggers an early orphan check. Unknown keys and unreadable bodies get
  the same empty 200, so nothing is revealed.
- It exempts itself, and only itself, from CSRF: the caller is a server, authenticated by the secret.
"""

import hmac
import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.db.models.functions import Now
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST

from applications.models import Application
from config import throttle
from config.client_identity import client_identity
from workflow.models import PendingAction

from . import handlers, provider
from .completion import enqueue_read, facts, observe
from .models import AgreementInstance, EnvelopeAttempt, ProviderObservation

logger = logging.getLogger(__name__)
LENGTH = re.compile(r"[0-9]{1,9}")


@sensitive_variables("given", "secrets")
def _authenticated(request) -> bool:
    given = request.headers.get("X-Documenso-Secret", "").encode()
    secrets = [s.encode() for s in settings.CATALYST_AGREEMENT_WEBHOOK_SECRETS if s]
    results = [hmac.compare_digest(given, s) for s in secrets]  # every secret is compared, whichever matches
    return bool(given) and any(results)


@csrf_exempt
@require_POST
@sensitive_variables("body", "data", "found")
def documenso_webhook(request):
    length = request.META.get("CONTENT_LENGTH") or "0"
    if not LENGTH.fullmatch(length) or int(length) > settings.CATALYST_AGREEMENT_WEBHOOK_MAX_BYTES:
        return HttpResponse(status=413)
    try:  # 9kg.29: per client, before the secret is compared; a bare 429, and a bare 503 with the store down
        throttle.enforce(request, ("webhook-client", client_identity(request), settings.CATALYST_THROTTLE_WEBHOOK_PER_CLIENT),
                         issuance=True, bare=True)
    except throttle.Refused as refused:
        return refused.response
    if not _authenticated(request):
        return HttpResponse(status=401)
    try:
        body = request.body
        data = json.loads(body) if len(body) <= settings.CATALYST_AGREEMENT_WEBHOOK_MAX_BYTES else None
    except (RequestDataTooBig, ValueError, RecursionError):
        data = None
    found = provider.hint(data) if data is not None else None
    if found is not None and found.external_id:
        try:
            ingest(found)
        except Exception as exc:  # the answer stays uniform; a fixed code is logged, never the body (4B.2 review)
            logger.error("documenso webhook: ingest failed (%s)", type(exc).__name__)
    return HttpResponse(status=200)


def ingest(found: provider.Hint) -> None:
    set_aside = (EnvelopeAttempt.objects.select_related("instance__application")
                 .filter(external_key=found.external_id, step=EnvelopeAttempt.Step.CREATE,
                         outcome__in=(EnvelopeAttempt.Outcome.DECIDED_NOT_SENT, EnvelopeAttempt.Outcome.ABANDONED))
                 .first())
    if set_aside is not None:  # a key a decision-maker set aside (it may still be an abandoned instance's key)
        _orphan_check(set_aside)
        return
    instance = AgreementInstance.objects.filter(external_key=found.external_id).first()
    if instance is None:
        return
    with transaction.atomic():
        Application.objects.select_for_update(of=("self",)).filter(pk=instance.application_id).first()
        instance = (AgreementInstance.objects.select_for_update(of=("self",)).select_related("application", "template_version")
                    .get(pk=instance.pk))
        identity = (found.external_id == instance.external_key
                    and found.template_number == instance.template_version.provider_template_number)
        data = facts(instance, found.status, found.recipients, identity=identity)
        last = (ProviderObservation.objects.filter(instance=instance, source=ProviderObservation.Source.WEBHOOK)
                .order_by("-id").values("envelope_status", "recipients").first())
        if last != {"envelope_status": data["envelope_status"], "recipients": data["recipients"]}:
            observe(instance, ProviderObservation.Source.WEBHOOK, data, found.event)  # a repeat of the last is not kept
        if (found.status == "COMPLETED" and identity and instance.issue_status == "issued"
                and instance.signing_status in ("not_started", "partially_signed")):
            AgreementInstance.objects.filter(pk=instance.pk).update(signing_status="signing_complete_observed")
        if instance.envelope_id:
            enqueue_read(instance)


def _orphan_check(attempt) -> None:
    """A webhook for a key set aside: look now, beyond the counted watch (021 section 15)."""
    with transaction.atomic():
        Application.objects.select_for_update(of=("self",)).filter(pk=attempt.instance.application_id).first()
        watches = PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref=str(attempt.public_id),
                                               idempotency_key__contains=":watch:")
        if watches.filter(status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists():
            return
        if watches.count() >= settings.CATALYST_AGREEMENT_ORPHAN_CHECKS * 4:
            return  # a cap per key, so a leaked secret cannot drive listings without end (4B.2 review)
        floor = timedelta(seconds=settings.CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS)
        if watches.filter(created_at__gt=Now() - floor).exists():
            return  # and a minimum interval
        handlers.enqueue_reconcile(attempt, watches.count() + 1, watch=True, grace=0)

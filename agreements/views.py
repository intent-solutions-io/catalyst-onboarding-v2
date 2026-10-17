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

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from applications.models import Application
from workflow.models import PendingAction

from . import handlers, provider
from .completion import enqueue_read, facts, observe
from .models import AgreementInstance, EnvelopeAttempt, ProviderObservation


def _authenticated(request) -> bool:
    given = request.headers.get("X-Documenso-Secret", "").encode()
    secrets = [s.encode() for s in settings.CATALYST_AGREEMENT_WEBHOOK_SECRETS if s]
    results = [hmac.compare_digest(given, s) for s in secrets]  # every secret is compared, whichever matches
    return bool(given) and any(results)


@csrf_exempt
@require_POST
def documenso_webhook(request):
    length = request.META.get("CONTENT_LENGTH") or "0"
    if not length.isdigit() or int(length) > settings.CATALYST_AGREEMENT_WEBHOOK_MAX_BYTES:
        return HttpResponse(status=413)
    if not _authenticated(request):
        return HttpResponse(status=401)
    try:
        body = request.body
        data = json.loads(body) if len(body) <= settings.CATALYST_AGREEMENT_WEBHOOK_MAX_BYTES else None
    except (RequestDataTooBig, ValueError):
        data = None
    found = provider.hint(data) if data is not None else None
    if found is not None and found.external_id:
        ingest(found)
    return HttpResponse(status=200)


def ingest(found: provider.Hint) -> None:
    instance = AgreementInstance.objects.filter(external_key=found.external_id).first()
    if instance is None:
        attempt = (EnvelopeAttempt.objects.select_related("instance__application")
                   .filter(external_key=found.external_id, step=EnvelopeAttempt.Step.CREATE,
                           outcome__in=(EnvelopeAttempt.Outcome.DECIDED_NOT_SENT, EnvelopeAttempt.Outcome.ABANDONED))
                   .first())
        if attempt is not None:
            _orphan_check(attempt)
        return
    with transaction.atomic():
        Application.objects.select_for_update(of=("self",)).filter(pk=instance.application_id).first()
        instance = (AgreementInstance.objects.select_for_update(of=("self",)).select_related("application", "template_version")
                    .get(pk=instance.pk))
        identity = (found.external_id == instance.external_key
                    and found.template_number == instance.template_version.provider_template_number)
        observe(instance, ProviderObservation.Source.WEBHOOK,
                facts(instance, found.status, found.recipients, identity=identity), found.event)
        if found.status == "COMPLETED" and instance.signing_status in ("not_started", "partially_signed"):
            AgreementInstance.objects.filter(pk=instance.pk).update(signing_status="signing_complete_observed")
        if instance.envelope_id:
            enqueue_read(instance)


def _orphan_check(attempt) -> None:
    """A webhook for a key set aside: look now, beyond the counted watch (021 section 15)."""
    with transaction.atomic():
        Application.objects.select_for_update(of=("self",)).filter(pk=attempt.instance.application_id).first()
        if PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref=str(attempt.public_id),
                                        status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists():
            return
        n = PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref=str(attempt.public_id),
                                         idempotency_key__contains=":watch:").count() + 1
        handlers.enqueue_reconcile(attempt, n, watch=True, grace=0)

"""Shared P5 mechanics: locks, action keys, the effect-boundary checks and staff items (023 sections 5 and 11).

Lock order (the P4 order extended): the application, then the provisioning request, then its attempts and evidence,
then the pending action (the ledger's fence).
"""

import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.db.models.functions import Now

from applications.models import Application, Stage
from correspondence.messages import verified_address
from correspondence.staff_items import event, hard_bounce_open, open_item
from workflow.models import AutomationPause, PendingAction

from .models import ProvisioningRequest

HANDOFF = "provision"  # the P4 hand-off: the release gate only (023 11.7)
CREATE = "provision_create"
RECONCILE = "provision_reconcile"
VERIFY = "provision_verify"

ITEM_NAME_REVIEW = "provisioning_name_needs_review"
ITEM_BLOCKED = "provisioning_blocked"
ITEM_CONFLICT = "provisioning_conflict"
ITEM_CONFIRM_FOUND = "provisioning_confirm_found"
ITEM_CHECKLIST = "provisioning_checklist"
ITEM_FAILED = "provisioning_failed"
ITEM_LATE_MAILBOX = "provisioning_late_mailbox"


def approval_digest(address: str, quota_mb: int, send_limit: int, method: str, prerequisite_digest: str) -> str:
    """What the approver confirms (P5-D-3): the exact address, limits, method and prerequisite snapshot."""
    shown = {"address": address.lower(), "quota_mb": quota_mb, "send_limit": send_limit, "method": method,
             "prerequisites": prerequisite_digest}
    return hashlib.sha256(json.dumps(shown, sort_keys=True).encode()).hexdigest()


def lock(application_pk, request_pk=None):
    application = Application.objects.select_for_update(of=("self",)).get(pk=application_pk)
    request = (ProvisioningRequest.objects.select_for_update(of=("self",)).select_related("reservation").get(pk=request_pk)
               if request_pk is not None else None)
    return application, request


def paused(application) -> bool:
    return AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists()


def database_problem(application, request=None) -> str:
    """The database half of every effect boundary (023 11.4); the caller holds the application lock. The fresh
    Documenso read is `agreements.completion.fresh_read_problem`, outside any transaction."""
    from agreements.completion import prerequisites, stopped

    if application.stage in (Stage.WITHDRAWN, Stage.CLOSED, Stage.DECLINED) or stopped(application):
        return "application_stopped"
    if paused(application):
        return "paused"
    if request is not None and request.stop_requested_at is not None:
        return "stop_requested"
    if verified_address(application) is None:
        return "contact_not_verified"
    if hard_bounce_open(application):
        return "hard_bounce_open"
    _, digest, reason = prerequisites(application)
    if reason:
        return reason
    if request is not None and digest != request.prerequisite_digest:
        return "prerequisites_changed"
    return ""


def watch_open(application) -> bool:
    return PendingAction.objects.filter(kind=RECONCILE, subject_id=application.public_ref,
                                        idempotency_key__contains=":watch:",
                                        status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists()


def return_stage_if_idle(application, actor_ref: str) -> bool:
    """023 11.11: with no live request and no open watch, the stage returns to `agreements_complete` and a new held
    hand-off awaits release and a new approval. Inside the caller's transaction, with the application locked."""
    from applications.stages import StageConflict, transition

    from .models import LIVE_REQUEST

    if ProvisioningRequest.objects.filter(application=application, status__in=LIVE_REQUEST).exists() or watch_open(application):
        return False
    try:
        transition(application.pk, (Stage.PROVISIONING,), Stage.AGREEMENTS_COMPLETE, event_kind="provisioning_returned",
                   actor_ref=actor_ref)
    except StageConflict:
        return False  # withdrawn, closed or already back: no new hand-off
    n = PendingAction.objects.filter(kind=HANDOFF, subject_id=application.public_ref).count()
    PendingAction.objects.create(kind=HANDOFF, subject_type="application", subject_id=application.public_ref,
                                 input_ref=f"returned:{n}", idempotency_key=f"{HANDOFF}:{application.public_ref}:{n}",
                                 status=PendingAction.Status.HELD)
    return True


def enqueue(kind: str, request, key: str, *, due_in: timedelta | None = None, max_attempts: int | None = None):
    due = Now() + due_in if due_in else Now()
    return PendingAction.objects.create(
        kind=kind, subject_type="application", subject_id=request.application.public_ref, input_ref=str(request.public_id),
        idempotency_key=key, due_at=due, max_attempts=max_attempts or settings.CATALYST_PROVISIONING_ATTEMPTS)


def set_status(request, status: str, **fields) -> None:
    ProvisioningRequest.objects.filter(pk=request.pk).update(status=status, updated_at=Now(), **fields)
    request.status = status


def item(reason: str, request, *, claim_id=None) -> None:
    open_item(reason, f"provisioning:{request.public_id}", application=request.application, pending_action_id=claim_id)


def record(application, kind: str, data: dict, actor_ref: str, **extra) -> None:
    event(application, kind, data, actor_ref=actor_ref, **extra)

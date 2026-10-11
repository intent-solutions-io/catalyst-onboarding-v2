"""Pending-action ledger mechanics (ADR-03, D-16; 005 S1.4 rules 1-8). Subject-generic: this module
imports no domain app; each action kind's handler (settings.CATALYST_ACTION_HANDLERS, a fixed mapping in
code) supplies the domain side.

1. Claim: one short transaction selects one due row with SKIP LOCKED (queued and due, or running with an
   expired lease, both by the database clock), skips automated kinds whose subject is paused, sets a new
   lease token and expiry and counts the attempt, and commits. Kinds without a handler are never claimed,
   so unknown work is neither executed nor retried in a loop; it stays queued and visible.
2. Poison: a claimable row whose attempts already reached the maximum (a worker died on every attempt) is
   claimed without counting another attempt and finished as failed (redeliverable kinds) or uncertain
   (all others) without running the handler, with a history event.
3. The handler runs outside any transaction and never calls a sink or provider while holding row locks.
   A database outage propagates to the worker loop, which reconnects; the claim is then recovered by lease
   expiry. There is no heartbeat: a handler that outlives its lease can be reclaimed while still running
   (and, on the final attempt, finished by the poison rule); the fence then discards its result.
4. Result: `finish` is one fenced transaction. It first locks the subject through the handler (domain
   rows before the action row, the order intake and confirmation use), then updates the action only where
   it is still running under the same lease token, then writes the handler's outbound record and history.
   If the fence matches no row the whole transaction rolls back: a stale worker leaves no completion, no
   outbound record and no history event.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import InterfaceError, OperationalError, transaction
from django.db.models import Exists, F, OuterRef, Q
from django.db.models.functions import Now
from django.utils.module_loading import import_string

from .models import AutomationPause, PendingAction

logger = logging.getLogger(__name__)
Status = PendingAction.Status


@dataclass(frozen=True)
class Claim:
    id: int
    kind: str
    subject_type: str
    subject_id: uuid.UUID
    input_ref: str
    lease_token: uuid.UUID
    attempt: int  # the attempt this claim is; equals the row's attempts after the claim
    max_attempts: int
    exhausted: bool = False  # claimed under the poison rule: finish it, never run the handler

    @property
    def final(self) -> bool:
        return self.attempt >= self.max_attempts


class LeaseLost(Exception):
    """The action is no longer running under this claim's lease token."""


class LeftForRecovery(Exception):
    """Raised by a handler whose external effect may have happened but whose result could not be recorded.
    The action stays `running`; lease expiry hands it to the next claim (D-20 for redeliverable kinds)."""


def handlers() -> dict:
    registry = {}
    for kind, path in settings.CATALYST_ACTION_HANDLERS.items():
        handler = import_string(path)()
        if handler.kind != kind:
            raise ValueError(f"handler {path} declares kind {handler.kind!r}, registered as {kind!r}")
        registry[kind] = handler
    return registry


def _after_claim_select(action_id: int) -> None:
    """Test seam (TEST-S1-19): called inside the claim transaction while the row is locked. No-op."""


def claim_next(registry=None) -> Claim | None:
    registry = registry if registry is not None else handlers()
    if not registry:
        return None
    automated = [kind for kind, h in registry.items() if h.automated]
    paused = AutomationPause.objects.filter(subject_type=OuterRef("subject_type"), subject_id=OuterRef("subject_id"))
    lease = timedelta(seconds=settings.CATALYST_WORKER_LEASE_SECONDS)
    with transaction.atomic():
        row = (
            PendingAction.objects.select_for_update(skip_locked=True, of=("self",))
            .annotate(paused=Exists(paused))
            .filter(kind__in=list(registry))
            .filter(Q(status=Status.QUEUED, due_at__lte=Now()) | Q(status=Status.RUNNING, lease_expires_at__lte=Now()))
            .exclude(Q(paused=True) & Q(kind__in=automated))
            .order_by("due_at", "id")
            .first()
        )
        if row is None:
            return None
        _after_claim_select(row.pk)
        exhausted = row.attempts >= row.max_attempts
        token = uuid.uuid4()
        PendingAction.objects.filter(pk=row.pk).update(
            status=Status.RUNNING, lease_token=token, lease_expires_at=Now() + lease, updated_at=Now(),
            attempts=F("attempts") if exhausted else F("attempts") + 1,
        )
    return Claim(
        id=row.pk, kind=row.kind, subject_type=row.subject_type, subject_id=row.subject_id, input_ref=row.input_ref,
        lease_token=token, attempt=row.attempts if exhausted else row.attempts + 1, max_attempts=row.max_attempts,
        exhausted=exhausted,
    )


def retry_delay(attempt: int) -> timedelta:
    """Bounded backoff: the base delay doubled per attempt, at most eight times the base."""
    return timedelta(seconds=settings.CATALYST_WORKER_RETRY_SECONDS * min(2 ** (attempt - 1), 8))


def finish(claim: Claim, handler, *, status, error: str = "", write=None, refund_attempt: bool = False) -> bool:
    """Record a result under the lease fence (module docstring, rule 4). `status` queued means retry after
    the backoff; `error` must already be sanitized (a reason code or exception class name, never data).
    Returns False, having changed nothing, if the lease was lost."""
    fields = {"status": status, "lease_token": None, "lease_expires_at": None, "last_error": error, "updated_at": Now()}
    if status == Status.QUEUED:
        fields["due_at"] = Now() + (timedelta(0) if refund_attempt else retry_delay(claim.attempt))
        if refund_attempt:
            fields["attempts"] = F("attempts") - 1
    else:
        fields["completed_at"] = Now()
    try:
        with transaction.atomic():
            handler.lock_subject(claim)
            fenced = PendingAction.objects.filter(pk=claim.id, status=Status.RUNNING, lease_token=claim.lease_token)
            if fenced.update(**fields) != 1:
                raise LeaseLost
            if write is not None:
                write()
    except LeaseLost:
        logger.warning("action %s (%s) attempt %s: lease lost; result discarded", claim.id, claim.kind, claim.attempt)
        return False
    return True


def fail_or_retry(claim: Claim, handler, error: str, write=None) -> bool:
    status = Status.FAILED if claim.final else Status.QUEUED
    if claim.final and not handler.redeliverable:
        status = Status.UNCERTAIN  # an unknown external outcome is reconciled, not assumed (ADR-15)
    return finish(claim, handler, status=status, error=error, write=write)


def run_one(registry=None) -> bool:
    """Claim and process at most one action. Returns False when nothing was claimable."""
    registry = registry if registry is not None else handlers()
    claim = claim_next(registry)
    if claim is None:
        return False
    handler = registry[claim.kind]
    if claim.exhausted:
        status = Status.FAILED if handler.redeliverable else Status.UNCERTAIN
        logger.warning("action %s (%s): attempts exhausted at %s; not run again", claim.id, claim.kind, claim.attempt)
        finish(claim, handler, status=status, error="attempts exhausted",
               write=lambda: handler.record(claim, "action_attempts_exhausted", {"attempts": claim.attempt}))
        return True
    try:
        handler.run(claim)
    except (OperationalError, InterfaceError):
        raise  # the database is unavailable: the loop reconnects, and lease expiry recovers the claim
    except LeftForRecovery as exc:
        logger.warning("action %s (%s) attempt %s: result not recorded (%s); left for lease recovery",
                       claim.id, claim.kind, claim.attempt, type(exc.__cause__).__name__)
    except Exception as exc:  # a handler defect: sanitized, bounded by the attempt count, never swallowed silently
        error = type(exc).__name__
        logger.error("action %s (%s) attempt %s raised %s", claim.id, claim.kind, claim.attempt, error)
        fail_or_retry(claim, handler, f"handler raised {error}", write=lambda: handler.record(
            claim, "action_failed", {"attempt": claim.attempt, "error": error, "final": claim.final}))
    return True

"""P5 durable actions for 5B.1 (023 sections 5, 11.3, 11.4 and 11.11). Synthetic only: the mail host is the local
fake behind `provisioning.adapter`.

`CreateMailbox` (`provision_create`, automated, never redelivered blindly):

1. B2's fresh Documenso read, outside any transaction.
2. The check transaction: the request is still approved, the database prerequisites still hold, and no earlier
   create's outcome is open. The attempt is committed `sending`.
3. After that commit: an authoritative read of the exact address must say "absent". A mailbox already there is a
   foreign mailbox, never adopted.
4. The create call, with a random password nobody sees (the set-your-own-password flow replaces it, 5B.2).
5. A fenced result transaction. An unknown outcome is reconciled by reading, never by calling create again.

`ReconcileMailbox` (`provision_reconcile`, protective, redeliverable) reads after an unknown create. A present
mailbox, absent before our create, is `found_by_evidence` for staff to confirm; absent after the bounded checks is
"not created" and a new series may run. In watch mode, after a request is superseded, it watches for a late mailbox.

`VerifyMailbox` (`provision_verify`, protective, redeliverable) is the authoritative read tied to the request
(P5-D-5).
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application
from correspondence.staff_items import event
from workflow import ledger
from workflow.models import PendingAction

from . import adapter, core
from .models import LIVE_REQUEST, AddressReservation, ProvisioningAttempt, ProvisioningEvidence, ProvisioningRequest

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Outcome = ProvisioningAttempt.Outcome


def _grace() -> timedelta:
    return timedelta(seconds=settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS)


class _Action:
    automated = False
    redeliverable = True
    kind = ""

    def lock_subject(self, claim) -> None:
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            ProvisioningRequest.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        request = ProvisioningRequest.objects.filter(public_id=claim.input_ref).first()
        if request is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            core.item(core.ITEM_FAILED, request, claim_id=claim.id)

    def _request(self, claim):
        return ProvisioningRequest.objects.select_related("reservation", "application").filter(
            public_id=claim.input_ref).first()

    def _key(self, claim) -> str:
        return PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""

    def _retry_or_staff(self, claim, request, code: str, staff_status: str = "failed_needs_staff", write=None):
        if claim.final:
            def to_staff():
                if write is not None:
                    write()
                current = ProvisioningRequest.objects.get(pk=request.pk)
                if current.status not in ("superseded", "stopped", "recovered_after_stop"):
                    core.set_status(current, staff_status)
                core.item(core.ITEM_FAILED, current, claim_id=claim.id)
            ledger.finish(claim, self, status=Status.FAILED, error=code, write=to_staff)
        else:
            ledger.finish(claim, self, status=Status.QUEUED, error=code, write=write)


class CreateMailbox(_Action):
    kind = core.CREATE
    automated = True
    redeliverable = False

    def run(self, claim) -> None:
        from agreements.completion import fresh_read_problem

        request = self._request(claim)
        if request is None or request.status not in ("approved", "create_pending"):
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_create")
            return
        # An earlier exchange's outcome is open (a crash after the call): reconcile first, before any other check,
        # never call again (QA review of PR #53).
        try:
            with transaction.atomic():
                application, request = core.lock(request.application_id, request.pk)
                ledger.fence(claim)
                stale = request.attempts.filter(step="create", outcome__in=(Outcome.SENDING, Outcome.UNKNOWN)).first()
                if stale is not None:
                    ProvisioningAttempt.objects.filter(pk=stale.pk, outcome=Outcome.SENDING).update(outcome=Outcome.UNKNOWN)
                    core.set_status(request, "create_uncertain")
                    self._enqueue_reconcile(request, stale)
                    ledger.finish(claim, self, status=Status.DONE, error="earlier_create_outcome_unknown")
                    return
        except ledger.LeaseLost:
            return
        try:  # the adapter and domain exist before any attempt is committed, so a missing one is never an "unknown"
            host = adapter.host()
            if not request.reservation.domain:
                raise adapter.AdapterError("no_domain_configured", sent=False)
        except adapter.AdapterError as exc:
            self._block(claim, request, exc.code)
            return
        problem = fresh_read_problem(request.application)  # B2, outside any transaction
        if problem == "provider_unavailable":
            ledger.finish(claim, self, status=Status.QUEUED, error=problem, refund_attempt=True, due_in=_grace())
            return
        if problem:
            self._block(claim, request, problem)
            return
        try:
            with transaction.atomic():
                application, request = core.lock(request.application_id, request.pk)
                ledger.fence(claim)
                if request.attempts.filter(step="create", outcome__in=(Outcome.SENDING, Outcome.UNKNOWN)).exists() \
                        or request.status != "approved":
                    ledger.finish(claim, self, status=Status.DONE, error="nothing_to_create")
                    return
                problem = core.database_problem(application, request)
                if problem:
                    raise _Blocked(problem)
                series = request.attempts.filter(step="create").count()
                attempt = ProvisioningAttempt.objects.create(request=request, step="create", series=series)
                core.set_status(request, "create_pending")
        except ledger.LeaseLost:
            logger.warning("action %s: lease lost before the create; nothing sent", claim.id)
            return
        except _Blocked as blocked:
            self._block(claim, request, str(blocked))
            return
        if transaction.get_connection().in_atomic_block:
            raise RuntimeError("refusing to call the mail host inside a transaction")
        domain, local = request.reservation.domain, request.reservation.local_part
        try:
            found = host.read(domain, local)
        except adapter.AdapterError as exc:  # no create was sent: say so, and try again later
            self._retry_or_staff(claim, request, f"absent_read_{exc.code}", write=lambda: self._not_sent(request, attempt, exc.code))
            return
        if found is not None:  # present before our create: someone else's mailbox, never adopted (023 11.3)
            ledger.finish(claim, self, status=Status.DONE, error="present_before_create",
                          write=lambda: self._conflict(request, attempt, "present_before_create", claim.id))
            return
        try:  # the absent read is evidence for "ours" (023 11.3): recorded under the fence, before the create
            with transaction.atomic():
                ledger.fence(claim)
                ProvisioningAttempt.objects.filter(pk=attempt.pk).update(absent_before=True)
        except ledger.LeaseLost:
            logger.warning("action %s: lease lost after the absent read; no create sent", claim.id)
            return
        try:
            host.create(domain, local, secrets.token_urlsafe(32), request.quota_mb, request.send_limit)
            result = None  # the password above is never stored, logged or kept (023 11.8)
        except adapter.AdapterError as exc:
            result = adapter.AdapterError(exc.code, sent=exc.sent, status=exc.status, retry_after=exc.retry_after)
            del exc  # no traceback (and so no frame holding the password) outlives the call
        except Exception as exc:  # a defect during the exchange: the request may have left, so the outcome is unknown
            logger.error("action %s: the mail host call raised %s", claim.id, type(exc).__name__)
            result = adapter.AdapterError("handler_error", sent=True)
        try:
            self.after_call(claim)
            ledger.finish(claim, self, status=Status.DONE, error=getattr(result, "code", ""),
                          write=lambda: self._result(claim, request, attempt, result))
        except Exception as exc:
            raise ledger.LeftForRecovery from exc

    def after_call(self, claim) -> None:
        """Test seam: after the exchange, before the result is recorded."""

    def _result(self, claim, request, attempt, result) -> None:
        request = ProvisioningRequest.objects.select_related("application", "reservation").get(pk=request.pk)
        if result is None:
            ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.SUCCEEDED, finished_at=Now())
            if request.stop_requested_at is not None:
                core.set_status(request, "recovered_after_stop")
                core.item(core.ITEM_LATE_MAILBOX, request, claim_id=claim.id)
                return
            core.set_status(request, "created")
            core.enqueue(core.VERIFY, request, f"{core.VERIFY}:{request.public_id}:0", due_in=_grace())
            core.record(request.application, "provisioning_created", {"request": str(request.public_id)},
                        f"pending_action:{claim.id}")
        elif result.conflict and request.attempts.filter(step="create", outcome=Outcome.NOT_CREATED).exists():
            # 023 11.11: a conflict after our own earlier unknown create may be that create landing late: reconcile
            # by reading, and staff confirm, never adopt.
            ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.UNKNOWN, code="conflict_after_ours")
            core.set_status(request, "create_uncertain")
            self._enqueue_reconcile(request, attempt)
        elif result.conflict:  # absent a moment ago, and no earlier unknown create of ours: foreign
            self._conflict(request, attempt, "conflict_on_create", claim.id)
        elif result.unknown:
            ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.UNKNOWN, code=result.code)
            core.set_status(request, "create_uncertain")
            self._enqueue_reconcile(request, attempt)
        else:
            ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.REJECTED, code=result.code,
                                                                     finished_at=Now())
            core.set_status(request, "failed_needs_staff")
            core.item(core.ITEM_FAILED, request, claim_id=claim.id)

    def _enqueue_reconcile(self, request, attempt) -> None:
        core.enqueue(core.RECONCILE, request, f"{core.RECONCILE}:{attempt.public_id}:0", due_in=_grace(),
                     max_attempts=settings.CATALYST_PROVISIONING_ATTEMPTS)

    def _not_sent(self, request, attempt, code) -> None:
        ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.NOT_CREATED, code=f"absent_read_{code}",
                                                                 finished_at=Now())
        current = ProvisioningRequest.objects.get(pk=request.pk)
        if current.status == "create_pending":
            core.set_status(current, "approved")

    def _conflict(self, request, attempt, code, claim_id) -> None:
        ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.CONFLICT, code=code, finished_at=Now())
        core.set_status(request, "conflict")
        core.item(core.ITEM_CONFLICT, request, claim_id=claim_id)
        core.record(request.application, "provisioning_conflict", {"request": str(request.public_id), "code": code},
                    f"pending_action:{claim_id}")

    def _block(self, claim, request, problem) -> None:
        """A prerequisite no longer holds at the effect boundary: nothing is sent, and staff decide (supersede the
        request after the cause is fixed; a changed prerequisite always needs a new approval)."""
        def write():
            current = ProvisioningRequest.objects.get(pk=request.pk)
            if current.status in ("approved", "create_pending"):
                core.set_status(current, "failed_needs_staff")
            core.item(core.ITEM_BLOCKED, current, claim_id=claim.id)
            core.record(current.application, "provisioning_blocked", {"request": str(current.public_id),
                                                                      "reason": problem}, f"pending_action:{claim.id}")
        ledger.finish(claim, self, status=Status.DONE, error=problem, write=write)


class _Blocked(Exception):
    pass


class ReconcileMailbox(_Action):
    """Protective: it only reads. Runs while paused (the D-44 classification)."""

    kind = core.RECONCILE

    def run(self, claim) -> None:
        request = self._request(claim)
        key = self._key(claim)
        if request is None:
            ledger.finish(claim, self, status=Status.DONE, error="no_request")
            return
        if ":watch:" in key:
            self._watch(claim, request, key)
            return
        attempt = request.attempts.filter(step="create", outcome=Outcome.UNKNOWN).order_by("-id").first()
        if attempt is None:
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_reconcile")
            return
        try:
            found = adapter.host().read(request.reservation.domain, request.reservation.local_part)
        except adapter.AdapterError as exc:  # a 500 is unknown, never "absent" (023 section 3)
            self._retry_or_staff(claim, request, f"read_{exc.code}")
            return
        n = int(key.rsplit(":", 1)[-1]) if key.rsplit(":", 1)[-1].isdigit() else 0
        ledger.finish(claim, self, status=Status.DONE, write=lambda: self._decide(claim, request, attempt, found, n))

    def _decide(self, claim, request, attempt, found, n) -> None:
        request = ProvisioningRequest.objects.select_related("application", "reservation").get(pk=request.pk)
        actor = f"pending_action:{claim.id}"
        if found is not None:
            if attempt.absent_before and (found.quota_mb, found.send_limit) == (request.quota_mb, request.send_limit):
                ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.FOUND_BY_EVIDENCE, finished_at=Now())
                ProvisioningEvidence.objects.create(request=request, kind=ProvisioningEvidence.Kind.ADAPTER_READ,
                                                    actor_ref=actor, facts=found.facts())
                core.set_status(request, "recovered_after_stop" if request.stop_requested_at else "found_by_evidence")
                core.item(core.ITEM_LATE_MAILBOX if request.stop_requested_at else core.ITEM_CONFIRM_FOUND, request,
                          claim_id=claim.id)
            else:
                ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.CONFLICT,
                                                                         code="present_but_not_provably_ours",
                                                                         finished_at=Now())
                core.set_status(request, "conflict")
                core.item(core.ITEM_CONFLICT, request, claim_id=claim.id)
            return
        if n + 1 < settings.CATALYST_PROVISIONING_RECONCILE_CHECKS:  # a create may still be landing: look again
            core.enqueue(core.RECONCILE, request, f"{core.RECONCILE}:{attempt.public_id}:{n + 1}", due_in=_grace())
            return
        ProvisioningAttempt.objects.filter(pk=attempt.pk).update(outcome=Outcome.NOT_CREATED, finished_at=Now())
        if request.stop_requested_at is not None:
            core.set_status(request, "stopped")
            return
        series = request.attempts.filter(step="create").count()
        if series >= settings.CATALYST_PROVISIONING_ATTEMPTS:  # bounded: never an endless create loop
            core.set_status(request, "failed_needs_staff")
            core.item(core.ITEM_FAILED, request, claim_id=claim.id)
            return
        core.set_status(request, "approved")
        core.enqueue(core.CREATE, request, f"{core.CREATE}:{request.public_id}:{series}")
        core.record(request.application, "provisioning_create_not_made", {"request": str(request.public_id)}, actor)

    def _watch(self, claim, request, key) -> None:
        """023 11.11: after supersession, watch a bounded number of times for a late mailbox; the reservation stays
        held meanwhile."""
        try:
            found = adapter.host().read(request.reservation.domain, request.reservation.local_part)
        except adapter.AdapterError as exc:
            self._retry_or_staff(claim, request, f"watch_read_{exc.code}", staff_status=request.status)
            return
        n = int(key.rsplit(":", 1)[-1])

        def write():
            current = ProvisioningRequest.objects.select_related("application", "reservation").get(pk=request.pk)
            if found is not None:
                core.item(core.ITEM_LATE_MAILBOX, current, claim_id=claim.id)  # rotate and revoke, never delete (5B.3)
                core.record(current.application, "provisioning_late_mailbox", {"request": str(current.public_id)},
                            f"pending_action:{claim.id}")
            elif n + 1 < settings.CATALYST_PROVISIONING_WATCH_CHECKS:
                core.enqueue(core.RECONCILE, current, f"{core.RECONCILE}:{current.public_id}:watch:{n + 1}",
                             due_in=_grace())
            else:
                AddressReservation.objects.filter(pk=current.reservation_id, released_at__isnull=True).exclude(
                    requests__status__in=LIVE_REQUEST).update(released_at=Now(), released_by=f"pending_action:{claim.id}")
                core.record(current.application, "provisioning_watch_ended", {"request": str(current.public_id)},
                            f"pending_action:{claim.id}")
                core.return_stage_if_idle(current.application, f"pending_action:{claim.id}")
        ledger.finish(claim, self, status=Status.DONE, write=write)


class VerifyMailbox(_Action):
    """The authoritative read of the specific mailbox, tied to the request (P5-D-5). An SMTP acceptance never counts."""

    kind = core.VERIFY

    def run(self, claim) -> None:
        request = self._request(claim)
        if request is None or request.status not in ("created", "verify_uncertain"):
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_verify")
            return
        try:
            found = adapter.host().read(request.reservation.domain, request.reservation.local_part)
        except adapter.AdapterError as exc:
            self._retry_or_staff(claim, request, f"verify_{exc.code}")
            return
        matches = found is not None and (found.quota_mb, found.send_limit, found.suspended) == (
            request.quota_mb, request.send_limit, False)
        if not matches:
            self._retry_or_staff(claim, request, "verify_mismatch" if found else "verify_absent",
                                 write=lambda: core.set_status(ProvisioningRequest.objects.get(pk=request.pk),
                                                               "verify_uncertain"))
            return

        def write():
            current = ProvisioningRequest.objects.select_related("application").get(pk=request.pk)
            if current.status not in ("created", "verify_uncertain"):
                return
            ProvisioningEvidence.objects.create(request=current, kind=ProvisioningEvidence.Kind.ADAPTER_READ,
                                                actor_ref=f"pending_action:{claim.id}", facts=found.facts())
            core.set_status(current, "verified")
            core.record(current.application, "provisioning_verified", {"request": str(current.public_id), "by": "api"},
                        f"pending_action:{claim.id}")
        ledger.finish(claim, self, status=Status.DONE, write=write)

"""The automatic release (bead bgl.9; 034 row 36; first-generation decision 13, carried to v2 by the owner's YES of
2026-10-31). Off by default: under CATALYST_RELEASE_MODE "owner" the held `provision` hand-off waits for the owner-run
`activate_provisioning` (P4-D-13) and a named approver (P5-D-3), as before.

Under "automatic", the P4 hand-off (`completion.AdvanceAgreements.hand_off`) queues one `auto_release` per held hand-off.
It runs without a person:

1. Under the application lock, the deterministic conditions (`blocking_reason`): the case is not closed, withdrawn or
   declined; not on hold (an `on_hold` stage or a stop of its agreements, P4-D-20); not paused; its contact address is
   verified; no staff item is open on it; it is `agreements_complete`; and both agreements are verified complete (signing
   and custody) with their required details captured and confirmed (D-46), which is `completion.prerequisites`.
2. The existing release (`services.release`, unchanged but for its actor): a fresh provider read of every agreement
   outside any transaction, the checks again under the lock, the derived address reserved, one request awaiting
   approval. Actor `auto-release`, approval reference APPROVAL_REF.
3. The mailbox approval with no person, by the first generation's rule (`services.approve_automatically`): only the
   address the naming rule derived; a reviewed exception waits for the named approver.
4. The existing chain then creates the mailbox, verifies it and opens the credential setup, which queues the welcome
   (the set-your-own-password invitation by default, or the one-time-password welcome under PR #152's credential mode).

A refusal is recorded once (one `provisioning_auto_release_refused` item and one event per case and reason) and checked
again after CATALYST_RELEASE_RECHECK_SECONDS, so a resolved condition releases without anyone re-running a command. A
closed case is never checked again. The action is not `automated`: it runs while a case is paused, so the pause is
recorded as a refusal rather than waited on in silence.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction

from applications.models import Application, Stage
from correspondence.messages import verified_address
from correspondence.models import StaffItem
from correspondence.staff_items import event, open_item, resolve_item
from workflow import ledger
from workflow.models import PendingAction

from . import core, services
from .models import ProvisioningRequest

AUTO_RELEASE = "auto_release"
ACTOR = "auto-release"  # recorded as the releaser and the approver
APPROVAL_REF = "first-generation-decision-13:owner-2026-10-31:bgl.9"
ACTIVATION_VERSION = 1  # activate_provisioning's only activation version
ITEM = "provisioning_auto_release_refused"
TERMINAL = ("closed", "not_held")
Status = PendingAction.Status


def automatic() -> bool:
    return settings.CATALYST_RELEASE_MODE == "automatic"


def enqueue(application, handoff) -> PendingAction | None:
    """One automatic release per held hand-off (the key names the hand-off). Inside the caller's transaction."""
    if not automatic():
        return None
    key = f"{AUTO_RELEASE}:{handoff.pk}"
    existing = PendingAction.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            return PendingAction.objects.create(kind=AUTO_RELEASE, subject_type="application",
                                                subject_id=application.public_ref, input_ref=str(handoff.pk),
                                                idempotency_key=key, max_attempts=settings.CATALYST_PROVISIONING_ATTEMPTS)
    except IntegrityError:
        return PendingAction.objects.filter(idempotency_key=key).first()


def blocking_reason(application) -> str:
    """The deterministic conditions, from the database, with the application locked. An empty string when the release
    may run; the fresh provider read is `services.release`'s, outside any transaction."""
    from agreements.completion import prerequisites, stopped

    if application.stage in (Stage.CLOSED, Stage.WITHDRAWN, Stage.DECLINED):
        return "closed"
    if application.stage == Stage.ON_HOLD or stopped(application):
        return "on_hold"
    if core.paused(application):
        return "paused"
    if verified_address(application) is None:
        return "address_not_verified"
    if StaffItem.objects.filter(application=application, status=StaffItem.Status.OPEN).exclude(reason_code=ITEM).exists():
        return "staff_item_open"
    if application.stage != Stage.AGREEMENTS_COMPLETE:
        return "stage_not_agreements_complete"
    _, _, reason = prerequisites(application)
    return reason


def _refuse(application, reason: str, claim_id) -> None:
    key = f"{AUTO_RELEASE}:{application.public_ref}:{reason}"
    if not StaffItem.objects.filter(reason_code=ITEM, dedupe_key=key, status=StaffItem.Status.OPEN).exists():
        open_item(ITEM, key, application=application, pending_action_id=claim_id)
        event(application, "provisioning_auto_release_refused", {"reason": reason}, actor_ref=ACTOR)


def _resolve_refusals(application, code: str) -> None:
    for item in StaffItem.objects.filter(application=application, reason_code=ITEM, status=StaffItem.Status.OPEN):
        resolve_item(item, code=code, actor_ref=ACTOR, actor_type="system")


class AutoRelease:
    kind = AUTO_RELEASE
    automated = False  # runs while paused, so a pause is recorded as a refusal (module docstring)
    redeliverable = True  # every step re-checks; the release and the approval are compare-and-set

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            _refuse(application, "auto_release_failed", claim.id)

    def _recheck(self, claim, application, reason: str) -> None:
        """A refusal: recorded once, then checked again later (or never again for a closed case)."""
        status, due = (Status.DONE, None) if reason in TERMINAL else (
            Status.QUEUED, timedelta(seconds=settings.CATALYST_RELEASE_RECHECK_SECONDS))
        ledger.finish(claim, self, status=status, error=reason, refund_attempt=status == Status.QUEUED, due_in=due,
                      write=(lambda: _refuse(application, reason, claim.id)) if reason != "not_held" else None)

    def run(self, claim) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        handoff = PendingAction.objects.filter(pk=int(claim.input_ref) if claim.input_ref.isdigit() else 0,
                                               kind=core.HANDOFF, subject_id=claim.subject_id).first()
        if not automatic() or application is None or handoff is None:
            ledger.finish(claim, self, status=Status.DONE, error="release_mode_owner" if not automatic() else "not_found")
            return
        if handoff.status == Status.HELD or application.stage in (Stage.CLOSED, Stage.WITHDRAWN, Stage.DECLINED):
            try:
                with transaction.atomic():
                    self.lock_subject(claim)
                    ledger.fence(claim)
                    reason = blocking_reason(Application.objects.get(pk=application.pk))
            except ledger.LeaseLost:
                return
            if reason:
                self._recheck(claim, application, reason)
                return
            outcome = services.release(handoff.pk, ACTIVATION_VERSION, APPROVAL_REF, actor=ACTOR)  # reads afresh first
            if outcome == "provider_unavailable":
                ledger.finish(claim, self, status=Status.QUEUED, error=outcome, refund_attempt=True,
                              due_in=timedelta(seconds=settings.CATALYST_RELEASE_RECHECK_SECONDS))
                return
            if outcome != "released":
                self._recheck(claim, application, outcome)
                return
        # Released, by this action or by an earlier run of it that stopped before the approval: approve the request it
        # released. A request the owner's command released stays with the named approver.
        request = (ProvisioningRequest.objects.filter(application=application, status="awaiting_approval")
                   .order_by("-id").first())
        mine = request is not None and application.events.filter(
            kind="provisioning_released", actor_ref=ACTOR, data__request=str(request.public_id)).exists()
        if not mine:
            ledger.finish(claim, self, status=Status.DONE, error="not_released_automatically")
            return
        outcome = services.approve_automatically(request.pk, ACTOR, APPROVAL_REF)
        if outcome == "approved":
            ledger.finish(claim, self, status=Status.DONE, error="released",
                          write=lambda: _resolve_refusals(application, "released"))
        elif outcome == "address_needs_approver":
            ledger.finish(claim, self, status=Status.DONE, error=outcome,
                          write=lambda: _refuse(application, outcome, claim.id))
        else:
            self._recheck(claim, application, outcome)

"""P4 completion, sequencing and cancellation (021 sections 4 to 6; 4B.2). Synthetic only: the local fake Documenso.

- `enqueue_read`: the one way a read is scheduled. Coalesced per instance (one queued or running read at most) and
  never sooner than a minimum interval after the last read, so webhook floods cannot multiply provider calls
  (TEST-P4-23).
- `ReadAgreement` (`read_agreement`, reads only, automated): a fresh `GET envelope/{id}`, recorded as a read
  observation. Only a read that shows the envelope complete, every required recipient signed, our envelope, key and
  template, and exactly our recipients moves `signing_status` to `signing_complete_verified`; the database refuses that
  move without such an observation in the same transaction (migration 0004). A read on a still-pending envelope
  schedules the next one: the sweep, so a lost webhook only delays completion (TEST-P4-14).
- `AdvanceAgreements` (`advance_agreements`, automated): when a type has passed its gate, re-reads the previous
  envelope at the moment of use (REQ-011) and only then issues the next type (D-15; TEST-P4-01, 06, 31). The P5
  hand-off after the last type is 4B.3.
- `CancelAgreement` (`cancel_agreement`, not redeliverable, runs while paused): cancels an instance at the provider
  with an attempt row and reconciliation (P4-D-18). A completion seen on a cancelled or superseded instance is never
  verified; it opens a staff item (TEST-P4-29).
"""

import hashlib
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Value
from django.db.models.functions import Greatest, Least, Now

from applications.models import Application, Stage
from correspondence.staff_items import event, open_item
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from . import provider
from .handlers import (
    CANCEL_UNKNOWN, ENVELOPE_MISMATCH, PROVIDER_UNAVAILABLE, Decision, Plan, _ProviderStep, approved_version, paused,
    start_agreement,
)
from .models import AgreementInstance, AgreementType, EnvelopeAttempt, ProviderObservation

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Out = EnvelopeAttempt.Outcome

READ = "read_agreement"
ADVANCE = "advance_agreements"
CANCEL_INSTANCE = "cancel_agreement"

# Staff-item reason codes (identifiers only).
DECLINED = "agreement_declined"  # P4-D-9: automation paused, staff decide
EXPIRED = "agreement_expired"
CANCELLED_AT_PROVIDER = "agreement_cancelled_at_provider"
RECIPIENTS_CHANGED = "agreement_recipients_changed"  # never verified (TEST-P4-31)
COMPLETED_AFTER_CANCEL = "agreement_completed_after_cancel"  # never verified (TEST-P4-29)
TEMPLATE_MISSING = "agreement_template_missing"
GATE_READ_FAILED = "agreement_gate_read_failed"

ADVANCE_FAILED = "agreement_advance_failed"
STOPPED_EVENT = "agreements_stopped"
RESUMED_EVENT = "agreements_resumed"


def _poll() -> timedelta:
    return timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS)


def stopped(application) -> bool:
    """A stop (P4-D-20) holds until a decision-maker resumes it; only a hold can be resumed (4B.2 review)."""
    last = application.events.filter(kind__in=(STOPPED_EVENT, RESUMED_EVENT)).order_by("-id").first()
    return last is not None and last.kind == STOPPED_EVENT


# --- observations -------------------------------------------------------------------------------------------------

def _ours(instance) -> list:
    return sorted((r.email.lower(), r.role) for r in instance.recipients.all())


def facts(instance, status: str, recipients, *, identity: bool) -> dict:
    """The allowlisted facts of one provider view: statuses and roles, and whether it is ours. Addresses are compared,
    never stored."""
    ours = _ours(instance)
    theirs = sorted((r.email.lower(), r.role) for r in recipients)
    match = theirs == ours
    required = {(r.email.lower(), r.role) for r in instance.recipients.filter(required=True)}
    signed = match and all(r.signing_status == "SIGNED" for r in recipients if (r.email.lower(), r.role) in required)
    return {"envelope_status": status, "identity_match": identity, "recipients_match": match,
            "all_required_signed": signed and bool(required),
            "recipients": [{"role": r.role, "order": r.signing_order, "signing_status": r.signing_status,
                            "expired": r.expired} for r in recipients]}


def observe(instance, source: str, data: dict, event_name: str = "") -> ProviderObservation | None:
    digest = hashlib.sha256(json.dumps({**data, "event": event_name}, sort_keys=True).encode()).hexdigest()
    try:
        with transaction.atomic():
            return ProviderObservation.objects.create(instance=instance, application=instance.application, source=source,
                                                      event=event_name, content_sha256=digest, **data)
    except IntegrityError:
        return None  # the exact webhook was already recorded: a replay is a no-op (TEST-P4-13)


def read_identity(instance, env: provider.Envelope) -> bool:
    return (env.id == instance.envelope_id and env.external_id == instance.external_key and env.type == "DOCUMENT"
            and env.template_number == instance.template_version.provider_template_number)


# --- scheduling a read --------------------------------------------------------------------------------------------

def _due(instance, due_in: timedelta | None):
    """The database clock plus `due_in`, never sooner than the minimum interval after the last read."""
    due = Now() + (due_in or timedelta(0))
    last = (ProviderObservation.objects.filter(instance=instance, source=ProviderObservation.Source.READ)
            .order_by("-observed_at").values_list("observed_at", flat=True).first())
    if last is not None:
        due = Greatest(due, Value(last + timedelta(seconds=settings.CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS)))
    return due


def enqueue_read(instance, *, due_in: timedelta | None = None) -> PendingAction:
    """Inside the caller's transaction with the instance locked. Coalesced onto a queued read, which is brought
    forward when this one is due sooner (a webhook advances the sweep's read); a running read gets one follow-up, so
    a hint arriving mid-read is never lost (4B.2 review). At most one queued read per instance, whatever the flood."""
    due = _due(instance, due_in)
    pending = PendingAction.objects.filter(kind=READ, input_ref=str(instance.public_id), status=Status.QUEUED).first()
    if pending is not None:
        PendingAction.objects.filter(pk=pending.pk).update(due_at=Least("due_at", due))
        return pending
    n = PendingAction.objects.filter(kind=READ, input_ref=str(instance.public_id)).count() + 1
    return PendingAction.objects.create(
        kind=READ, subject_type="application", subject_id=instance.application.public_ref,
        input_ref=str(instance.public_id), idempotency_key=f"{READ}:{instance.public_id}:{n}", due_at=due,
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


def _sweep_on(instance) -> None:
    enqueue_read(instance, due_in=timedelta(seconds=settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS))


def enqueue_advance(application) -> PendingAction:
    pending = PendingAction.objects.filter(kind=ADVANCE, subject_id=application.public_ref, status=Status.QUEUED).first()
    if pending is not None:
        return pending
    n = PendingAction.objects.filter(kind=ADVANCE, subject_id=application.public_ref).count() + 1
    return PendingAction.objects.create(
        kind=ADVANCE, subject_type="application", subject_id=application.public_ref,
        input_ref=str(application.public_ref), idempotency_key=f"{ADVANCE}:{application.public_ref}:{n}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


def enqueue_cancel_instance(instance) -> PendingAction:
    n = PendingAction.objects.filter(kind=CANCEL_INSTANCE, input_ref=str(instance.public_id)).count() + 1
    return PendingAction.objects.create(
        kind=CANCEL_INSTANCE, subject_type="application", subject_id=instance.application.public_ref,
        input_ref=str(instance.public_id), idempotency_key=f"{CANCEL_INSTANCE}:{instance.public_id}:{n}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


def _pause(application, reason: str) -> None:  # P4-D-9: decline, expiry and a provider-side cancel
    if not AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
        AutomationPause.objects.create(subject_type="application", subject_id=application.public_ref, reason=reason,
                                       actor_ref="system")
        event(application, "automation_paused", {"by": "system", "reason": reason})


# --- the fresh read -------------------------------------------------------------------------------------------------

class ReadAgreement:
    kind = READ
    redeliverable = True  # it reads only
    automated = True  # a pause stops it; resuming runs the one coalesced read, never a burst

    def lock_subject(self, claim) -> None:
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            AgreementInstance.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref,
                                                                             application=application).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            open_item(PROVIDER_UNAVAILABLE, f"read:{claim.input_ref}", application=application, pending_action_id=claim.id)
            _keep_sweeping(claim.input_ref)

    def run(self, claim) -> None:
        instance = (AgreementInstance.objects.select_related("application", "template_version")
                    .filter(public_id=claim.input_ref).first())
        if instance is None or str(instance.application.public_ref) != str(claim.subject_id) or not instance.envelope_id:
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_read")
            return
        if paused(instance.application):
            ledger.finish(claim, self, status=Status.QUEUED, error="automation_paused", refund_attempt=True, due_in=_poll())
            return
        try:
            env = provider.read(instance.envelope_id)  # outside any transaction
        except provider.ProviderError as exc:
            if claim.final:
                def failed():  # staff are told, and the sweep goes on: an outage never ends it (4B.2 review)
                    open_item(PROVIDER_UNAVAILABLE, f"read:{instance.public_id}", application=instance.application,
                              pending_action_id=claim.id)
                    _keep_sweeping(claim.input_ref)
                ledger.finish(claim, self, status=Status.FAILED, error=exc.code, write=failed)
            else:
                due = timedelta(seconds=exc.retry_after) if exc.retry_after is not None else None
                ledger.finish(claim, self, status=Status.QUEUED, error=exc.code, due_in=due)
            return
        ledger.finish(claim, self, status=Status.DONE, write=lambda: apply_read(claim, instance.pk, env))


def _keep_sweeping(instance_ref) -> None:
    instance = AgreementInstance.objects.select_related("application").filter(public_id=instance_ref).first()
    if instance is not None and instance.issue_status == "issued" and instance.envelope_id and instance.signing_status in (
            "not_started", "partially_signed", "signing_complete_observed"):
        _sweep_on(instance)


def apply_read(claim, instance_id: int, env: provider.Envelope) -> None:
    """Record one fresh read and move the instance by what it shows (inside the fenced result transaction)."""
    instance = AgreementInstance.objects.select_related("application", "template_version").get(pk=instance_id)
    application = instance.application
    actor = f"pending_action:{claim.id}"
    data = facts(instance, env.status, env.recipients, identity=read_identity(instance, env))
    observe(instance, ProviderObservation.Source.READ, data)
    ref = str(instance.public_id)

    def status(**fields):
        AgreementInstance.objects.filter(pk=instance.pk).update(updated_at=Now(), **fields)

    if not data["identity_match"]:
        open_item(ENVELOPE_MISMATCH, f"read:{ref}", application=application, pending_action_id=claim.id)
        event(application, "agreement_read_mismatch", {"instance": ref}, actor_ref=actor)
        _keep_sweeping(ref)
        return
    if instance.issue_status in ("superseded", "cancelled", "cancel_pending", "cancel_uncertain"):
        if env.status == "COMPLETED":  # TEST-P4-29: never verified, never dropped
            open_item(COMPLETED_AFTER_CANCEL, f"read:{ref}", application=application, pending_action_id=claim.id)
            event(application, "agreement_completed_after_cancel", {"instance": ref}, actor_ref=actor)
        elif env.status == "CANCELLED" and instance.issue_status == "cancel_uncertain":
            status(issue_status="cancelled", signing_status="cancelled")
        return
    if instance.issue_status != "issued" or instance.signing_status == "signing_complete_verified":
        return
    if env.status == "COMPLETED":
        if data["all_required_signed"]:
            status(signing_status="signing_complete_verified", custody_status="pending")
            event(application, "agreement_signing_verified", {"instance": ref}, actor_ref=actor)
            enqueue_advance(application)
            return
        status(signing_status="signing_complete_observed")
        reason = RECIPIENTS_CHANGED if not data["recipients_match"] else ENVELOPE_MISMATCH
        open_item(reason, f"read:{ref}", application=application, pending_action_id=claim.id)
        event(application, "agreement_completion_not_verified", {"instance": ref, "reason": reason}, actor_ref=actor)
        _keep_sweeping(ref)  # the provider may correct it; keep looking (4B.2 re-check)
        return
    if env.status == "REJECTED" or any(r.signing_status == "REJECTED" for r in env.recipients):
        status(signing_status="declined")
        _pause(application, "agreement_declined")  # P4-D-9
        open_item(DECLINED, f"read:{ref}", application=application, pending_action_id=claim.id)
        event(application, "agreement_declined", {"instance": ref}, actor_ref=actor)
        return
    if env.status == "CANCELLED":
        status(signing_status="cancelled", issue_status="cancelled")
        _pause(application, "agreement_cancelled_at_provider")
        open_item(CANCELLED_AT_PROVIDER, f"read:{ref}", application=application, pending_action_id=claim.id)
        event(application, "agreement_cancelled_at_provider", {"instance": ref}, actor_ref=actor)
        return
    if any(r.expired for r in env.recipients):
        status(signing_status="expired")
        _pause(application, "agreement_expired")
        open_item(EXPIRED, f"read:{ref}", application=application, pending_action_id=claim.id)
        event(application, "agreement_expired", {"instance": ref}, actor_ref=actor)
        return
    if any(r.signing_status == "SIGNED" for r in env.recipients) and instance.signing_status == "not_started":
        status(signing_status="partially_signed")
    elif instance.signing_status == "signing_complete_observed":
        status(signing_status="partially_signed" if any(r.signing_status == "SIGNED" for r in env.recipients)
               else "not_started")  # a webhook claimed completion that the read does not show
    _sweep_on(instance)  # the sweep


# --- the D-15 sequence -----------------------------------------------------------------------------------------------

def gate_passed(instance) -> bool:
    if instance.signing_status != "signing_complete_verified":
        return False
    return instance.agreement_type.gate == AgreementType.Gate.SIGNING or instance.custody_status == "stored_verified"


def next_step(application):
    """(previous instance or None, next type or None, reason). The next type is the first, by order, without a live
    instance; every type before it must have passed its gate."""
    previous = None
    for agreement_type in AgreementType.objects.filter(required=True).order_by("order"):
        live = (AgreementInstance.objects.select_related("agreement_type", "template_version")
                .filter(application=application, agreement_type=agreement_type)
                .exclude(issue_status__in=("superseded", "cancelled")).first())
        if live is None:
            return previous, agreement_type, ""
        if not gate_passed(live):
            return previous, None, "waiting_for_gate"
        previous = live
    return previous, None, "all_passed"


class AdvanceAgreements:
    kind = ADVANCE
    redeliverable = True
    automated = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            open_item(ADVANCE_FAILED, f"advance:{application.public_ref}", application=application, pending_action_id=claim.id)

    def run(self, claim) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is None or application.stage != Stage.AGREEMENTS or stopped(application):
            ledger.finish(claim, self, status=Status.DONE, error="not_advancing")
            return
        if paused(application):
            ledger.finish(claim, self, status=Status.QUEUED, error="automation_paused", refund_attempt=True, due_in=_poll())
            return
        previous, next_type, reason = next_step(application)
        env = None
        if next_type is None:
            ledger.finish(claim, self, status=Status.DONE, error=reason, write=lambda: event(
                application, "agreements_all_passed", {}, actor_ref=f"pending_action:{claim.id}")
                if reason == "all_passed" else None)  # the P5 hand-off is 4B.3
            return
        if previous is not None:
            try:  # REQ-011: the previous agreement is re-read at the moment the next one is issued
                env = provider.read(previous.envelope_id)
            except provider.ProviderError as exc:
                if claim.final:
                    ledger.finish(claim, self, status=Status.FAILED, error=exc.code, write=lambda: open_item(
                        GATE_READ_FAILED, f"advance:{application.public_ref}", application=application,
                        pending_action_id=claim.id))
                else:
                    ledger.finish(claim, self, status=Status.QUEUED, error=exc.code)
                return
        ledger.finish(claim, self, status=Status.DONE,
                      write=lambda: self.issue(claim, application, previous, next_type, env))

    def issue(self, claim, application, previous, next_type, env) -> None:
        actor = f"pending_action:{claim.id}"
        application = Application.objects.get(pk=application.pk)
        if application.stage != Stage.AGREEMENTS or stopped(application):
            return
        _, now_type, _ = next_step(application)  # re-checked under the lock
        if now_type is None or now_type.pk != next_type.pk:
            return
        if previous is not None:
            previous = AgreementInstance.objects.select_related("application", "template_version").get(pk=previous.pk)
            data = facts(previous, env.status, env.recipients, identity=read_identity(previous, env))
            observe(previous, ProviderObservation.Source.READ, data)
            if not (env.status == "COMPLETED" and data["identity_match"] and data["all_required_signed"]):
                reason = RECIPIENTS_CHANGED if not data["recipients_match"] else ENVELOPE_MISMATCH
                open_item(reason, f"gate:{previous.public_id}", application=application, pending_action_id=claim.id)
                event(application, "agreement_gate_read_refused", {"instance": str(previous.public_id)}, actor_ref=actor)
                return  # TEST-P4-31: nothing is issued on a stale verification
        version = approved_version(next_type.key)
        if version is None:
            open_item(TEMPLATE_MISSING, f"advance:{application.public_ref}:{next_type.key}", application=application,
                      pending_action_id=claim.id)
            return
        try:
            start_agreement(application, version, actor)
        except ValueError as exc:  # the contact is no longer verified: staff decide (4B.2 review)
            open_item(ADVANCE_FAILED, f"advance:{application.public_ref}", application=application, pending_action_id=claim.id)
            event(application, "agreement_advance_refused", {"reason": str(exc)}, actor_ref=actor)


# --- cancelling an instance at the provider (P4-D-18) ------------------------------------------------------------------

class CancelAgreement(_ProviderStep):
    kind = CANCEL_INSTANCE
    step = EnvelopeAttempt.Step.CANCEL
    uncertain_status = "cancel_uncertain"
    automated = False  # protective: it runs while automation is paused

    def check(self, claim):
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        instance = (AgreementInstance.objects.select_related("application", "template_version")
                    .filter(public_id=claim.input_ref).first())
        if application is None or instance is None or instance.application_id != application.pk:
            return Decision(Status.FAILED, "instance_not_found"), None
        pending = self._pending(instance, instance.external_key)
        if pending:
            return self._to_reconcile(claim, instance, pending), None
        if instance.issue_status != "cancel_pending" or not instance.envelope_id:
            return Decision(Status.DONE, "not_pending"), None
        if not provider.configured():
            return Decision(Status.FAILED, "provider_not_configured", write=lambda: open_item(
                CANCEL_UNKNOWN, f"cancel:{instance.public_id}", application=application, pending_action_id=claim.id)), None
        attempt = self._attempt(claim, instance, envelope_id=instance.envelope_id)
        return None, Plan(attempt.pk, instance.pk, envelope_id=instance.envelope_id, external_key=instance.external_key)

    def call(self, plan: Plan):
        try:
            current = provider.read(plan.envelope_id)
        except provider.ProviderError as exc:
            raise provider.ProviderError(exc.code, sent=False, status=exc.status) from None
        if current.external_id != plan.external_key:
            return "mismatch"
        if current.status in ("CANCELLED", "REJECTED"):
            return "already_closed"
        if current.status == "DRAFT":
            return "left_draft"  # never sent: nobody can sign it; the installed API cannot cancel a draft
        if current.status == "COMPLETED":
            return "completed"
        provider.cancel(plan.envelope_id)
        return "cancelled"

    def record_result(self, claim, plan: Plan, result) -> bool:
        if isinstance(result, provider.ProviderError):
            return self.record_failure(claim, plan, result)
        instance = AgreementInstance.objects.select_related("application").get(pk=plan.instance_id)
        actor = f"pending_action:{claim.id}"

        def write():
            closed = result in ("cancelled", "already_closed", "left_draft")
            self._finish_attempt(plan.attempt_id, Out.SUCCEEDED if result in ("cancelled", "already_closed") else Out.NOT_SENT,
                                 result)
            if closed:
                AgreementInstance.objects.filter(pk=instance.pk, issue_status="cancel_pending").update(
                    issue_status="cancelled", signing_status="cancelled", updated_at=Now())
            else:
                reason = COMPLETED_AFTER_CANCEL if result == "completed" else ENVELOPE_MISMATCH
                AgreementInstance.objects.filter(pk=instance.pk, issue_status="cancel_pending").update(
                    issue_status="failed_needs_staff", updated_at=Now())
                open_item(reason, f"cancel:{instance.public_id}", application=instance.application, pending_action_id=claim.id)
            event(instance.application, "agreement_cancel", {"instance": str(instance.public_id), "result": result},
                  actor_ref=actor)
        return ledger.finish(claim, self, status=Status.DONE if result != "mismatch" else Status.FAILED, error=result,
                             write=write)


"""The P4 agreement actions (021 section 4 steps 1 to 3, section 5; 4B.1). Synthetic only: the local fake Documenso.

Registered in settings.CATALYST_ACTION_HANDLERS (ledger rules in workflow/ledger.py). Lock order everywhere:
application, then the instance, then the pending action. A provider call runs between a check transaction and a
fenced result transaction, never under a lock (as P2 and P3).

- `IssueAgreement` (`issue_nda`, the held action 3B.4 creates on admit; released by `activate_agreements`): step 1.
  The stage moves `admitted -> agreements`, and the NDA instance with its minted key and its recipients is committed
  before any provider call. A refusal leaves the action held.
- `CreateAgreement` (`create_agreement`, not redeliverable): step 2. An `EnvelopeAttempt` is written `sending` before
  the request leaves; `envelope/use` creates a draft only. An unknown outcome is reconciled, never retried blindly.
- `DistributeAgreement` (`distribute_agreement`, not redeliverable): step 3. Under CATALYST_AGREEMENT_DISTRIBUTION
  "provider" Documenso, not P2, emails the applicant, so the P2 send checks run first (verified address, pause, hard
  bounce). A re-read decides whether the envelope was already distributed; only a draft is distributed. Under
  "service" (bgl.8) the provider mails nobody and `agreements.signing_mail` sends the link once the envelope is issued.
- `ReconcileAgreement` (`reconcile_agreement`, idempotent, reads only): looks for admissible evidence of an unknown
  create, distribute or cancel. It also watches a key a decision-maker set aside: a late match (an orphan) is never
  linked or verified; it opens a staff item and is cancelled (P4-D-19).
- `CancelEnvelope` (`cancel_envelope`, not redeliverable): cancels an orphan envelope at the provider.

Staff items carry identifiers and reason codes only. No provider body, name, address, token or link is recorded.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent, Stage
from applications.stages import transition
from assessments.models import QualificationDecision
from correspondence.messages import verified_address
from correspondence.models import StaffItem
from correspondence.staff_items import event, hard_bounce_open, open_item, resolve_item  # one bounce rule (9kg.3)
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from . import provider
from .models import AgreementInstance, AgreementRecipient, AgreementTemplateVersion, EnvelopeAttempt

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Out = EnvelopeAttempt.Outcome
Step = EnvelopeAttempt.Step

ISSUE_NDA = "issue_nda"
CREATE = "create_agreement"
DISTRIBUTE = "distribute_agreement"
RECONCILE = "reconcile_agreement"
CANCEL = "cancel_envelope"

# Staff-item reason codes (021 sections 4, 5; identifiers only).
CREATE_UNKNOWN = "agreement_create_unknown"  # a decision-maker decides (P4-D-8)
DISTRIBUTE_UNKNOWN = "agreement_distribute_unknown"
DISTRIBUTE_REFUSED = "agreement_distribute_refused"  # a P2 send check failed
PROVIDER_REJECTED = "agreement_provider_rejected"
PROVIDER_UNAVAILABLE = "agreement_provider_unavailable"
ENVELOPE_MISMATCH = "agreement_envelope_mismatch"  # the provider's envelope is not the one we created
DUPLICATE_ENVELOPES = "agreement_duplicate_envelopes"
LATE_ORPHAN = "agreement_late_orphan"
CANCEL_UNKNOWN = "agreement_cancel_unknown"
SIGNED_ORPHAN = "agreement_orphan_signed"  # an orphan was signed: never verified, staff decide
WATCH_FAILED = "agreement_orphan_watch_failed"
ORPHAN_WATCH_ENDED = "agreement_orphan_watch_ended"  # D-44: automatic checking ended, uncertainty unresolved
MAX_WATCH_REARMS = 3


def watch_limit(attempt) -> int:
    """The bounded watch (D-44): CATALYST_AGREEMENT_ORPHAN_CHECKS per arming, a labelled synthetic default and not a
    production horizon. A decision-maker may re-arm it at most MAX_WATCH_REARMS times."""
    rearms = attempt.instance.application.events.filter(kind="agreement_orphan_watch_rearmed",
                                                        data__attempt=str(attempt.public_id)).count()
    return settings.CATALYST_AGREEMENT_ORPHAN_CHECKS * (1 + rearms)


def _watch_left_draft(instance) -> None:
    """D-44: a draft left at the provider (never distributed) gets bounded follow-up reads, then a staff item, so a
    draft someone sends in the provider's interface is noticed."""
    from .completion import enqueue_read

    enqueue_read(AgreementInstance.objects.get(pk=instance.pk),
                 due_in=timedelta(seconds=settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS), closed=True)


def _cancel_after_send(instance) -> None:
    from .completion import enqueue_cancel_instance  # completion builds on this module

    AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="cancel_pending", updated_at=Now())
    enqueue_cancel_instance(instance)
    event(instance.application, "agreement_cancel_after_send", {"instance": str(instance.public_id)})


def _start_sweep(instance) -> None:
    """An envelope became issued: the first read, at the sweep interval (4B.2; webhooks may bring it forward), and,
    under CATALYST_AGREEMENT_DISTRIBUTION "service" (bgl.8), the service-sent signing link, because the provider was
    told to mail nobody (`distributionMethod: NONE`)."""
    from .completion import enqueue_read  # completion builds on this module

    enqueue_read(instance, due_in=timedelta(seconds=settings.CATALYST_AGREEMENT_READ_INTERVAL_SECONDS))
    if settings.CATALYST_AGREEMENT_DISTRIBUTION == "service":
        from .signing_mail import enqueue_signing_link

        enqueue_signing_link(instance)


def new_key() -> str:
    """Opaque, random, and free of applicant data (021 section 10)."""
    return f"ag_{secrets.token_hex(16)}"


def paused(application) -> bool:
    return AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists()


def approved_version(type_key: str) -> AgreementTemplateVersion | None:
    return (AgreementTemplateVersion.objects.select_related("agreement_type")
            .filter(agreement_type__key=type_key, status=AgreementTemplateVersion.Status.APPROVED).order_by("-version").first())


def _action_key(claim) -> str:
    return PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""


def enqueue_create(instance) -> PendingAction:
    return PendingAction.objects.create(
        kind=CREATE, subject_type="application", subject_id=instance.application.public_ref,
        input_ref=str(instance.public_id), idempotency_key=f"{CREATE}:{instance.public_id}:{instance.external_key}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


def enqueue_distribute(instance, series: int = 0) -> PendingAction:
    return PendingAction.objects.create(
        kind=DISTRIBUTE, subject_type="application", subject_id=instance.application.public_ref,
        input_ref=str(instance.public_id), idempotency_key=f"{DISTRIBUTE}:{instance.public_id}:{series}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


def enqueue_reconcile(attempt, n: int, *, watch: bool = False, grace: float | None = None) -> PendingAction:
    if grace is None:
        grace = (settings.CATALYST_AGREEMENT_DISTRIBUTE_SETTLE_SECONDS if attempt.step == Step.DISTRIBUTE
                 else settings.CATALYST_AGREEMENT_RECONCILE_GRACE_SECONDS)
    mode = "watch" if watch else "check"
    return PendingAction.objects.create(
        kind=RECONCILE, subject_type="application", subject_id=attempt.instance.application.public_ref,
        input_ref=str(attempt.public_id), idempotency_key=f"{RECONCILE}:{attempt.public_id}:{mode}:{n}",
        due_at=Now() + timedelta(seconds=grace), max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


def enqueue_cancel(attempt) -> PendingAction:
    return PendingAction.objects.create(
        kind=CANCEL, subject_type="application", subject_id=attempt.instance.application.public_ref,
        input_ref=str(attempt.public_id), idempotency_key=f"{CANCEL}:{attempt.envelope_id}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


def _reconcile_number(claim) -> tuple[str, int]:
    parts = _action_key(claim).split(":")
    if len(parts) != 4 or parts[2] not in ("check", "watch") or not parts[3].isdigit():
        return "", 0
    return parts[2], int(parts[3])


def start_agreement(application, version: AgreementTemplateVersion, actor: str) -> AgreementInstance:
    """Step 1's records, inside the caller's transaction with the application locked: the instance with its minted
    key, its recipients (P4-D-3: the applicant alone signs in synthetic P4), and the create action. All of it commits
    before any provider call (TEST-P4-10)."""
    recipient = verified_address(application)
    if recipient is None:
        raise ValueError("contact_not_verified")
    instance = AgreementInstance.objects.create(
        application=application, agreement_type=version.agreement_type, template_version=version,
        external_key=new_key(), issue_status="create_pending")
    AgreementRecipient.objects.create(instance=instance, role=AgreementRecipient.Role.SIGNER, signing_order=1,
                                      required=True, who="applicant", name=application.display_name, email=recipient)
    enqueue_create(instance)
    event(application, "agreement_instance_created",
          {"instance": str(instance.public_id), "type": version.agreement_type.key, "template_version": version.version},
          actor_ref=actor)
    return instance


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str = ""
    refund: bool = False
    due_in: timedelta | None = None
    write: object = None


def settle(claim, handler, decision: Decision) -> bool:
    return ledger.finish(claim, handler, status=decision.status, error=decision.reason, write=decision.write,
                         refund_attempt=decision.refund, due_in=decision.due_in)


def _poll() -> timedelta:
    return timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS)


class _AgreementAction:
    automated = True
    redeliverable = False

    def lock_subject(self, claim) -> None:
        """Application, then the instance (021 section 4)."""
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            self._lock_instance(claim, application)

    def _lock_instance(self, claim, application):
        return (AgreementInstance.objects.select_for_update(of=("self",))
                .filter(public_id=claim.input_ref, application=application).first())

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            self.on_final_failure(claim, application)  # a job that cannot finish never ends silently

    def on_final_failure(self, claim, application) -> None:
        open_item(PROVIDER_UNAVAILABLE, f"{self.kind}:{claim.input_ref}", application=application, pending_action_id=claim.id)


# --- step 1: release the NDA -----------------------------------------------------------------------------------

class IssueAgreement(_AgreementAction):
    """`issue_nda`: idempotent and provider-free, so redeliverable. A refusal returns the action to `held` with a
    history event; the owner's activation command may release it again once the reason is gone."""

    kind = ISSUE_NDA
    redeliverable = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def run(self, claim) -> None:
        with transaction.atomic():
            self.lock_subject(claim)
            settle(claim, self, self.decide(claim))

    def decide(self, claim) -> Decision:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is None:
            return Decision(Status.FAILED, "application_not_found")
        if paused(application):
            return Decision(Status.QUEUED, "automation_paused", refund=True, due_in=_poll())

        def held(reason):  # refunded: a refusal never uses up the attempts a later release needs (4B.1 review)
            return Decision(Status.HELD, reason, refund=True, write=lambda: event(
                application, "agreement_issue_refused", {"reason": reason}, actor_ref=f"pending_action:{claim.id}"))
        if application.stage != Stage.ADMITTED:
            return held("stage_not_admitted")
        decision = (QualificationDecision.objects.filter(application=application, outcome="admit").order_by("-id").first())
        if decision is None or str(decision.public_id) != claim.input_ref:
            return held("decision_changed")
        from .completion import details_confirmed, enqueue_advance, referenced  # completion builds on this module

        if "nda" in referenced(application):
            # 9kg.52 (030 Q4): the NDA is on file from the first generation, so it is referenced, never issued. The
            # sequence starts at the advance, which issues the first type the record does not cover (or hands off).
            def start_referenced():
                transition(application.pk, (Stage.ADMITTED,), Stage.AGREEMENTS, event_kind="agreements_started",
                           data={"decision": claim.input_ref, "referenced": sorted(referenced(application))},
                           actor_ref=f"pending_action:{claim.id}")
                event(application, "agreement_referenced", {"types": sorted(referenced(application))},
                      actor_ref=f"pending_action:{claim.id}")
                enqueue_advance(application)
            return Decision(Status.DONE, write=start_referenced)
        version = approved_version("nda")
        if version is None:
            return held("no_approved_template")

        if not details_confirmed(application, version.agreement_type):
            from .completion import DETAILS_NEEDED

            decision = held("details_needed")
            return Decision(decision.status, decision.reason, refund=True, write=lambda: (
                decision.write(), open_item(DETAILS_NEEDED, f"details:{application.public_ref}:nda", application=application,
                                            pending_action_id=claim.id)))
        if verified_address(application) is None:
            return held("contact_not_verified")

        def write():
            transition(application.pk, (Stage.ADMITTED,), Stage.AGREEMENTS, event_kind="agreements_started",
                       data={"decision": claim.input_ref}, actor_ref=f"pending_action:{claim.id}")
            start_agreement(application, version, f"pending_action:{claim.id}")
        return Decision(Status.DONE, write=write)


# --- steps 2 and 3: create and distribute ----------------------------------------------------------------------

@dataclass(frozen=True)
class Plan:
    attempt_id: int
    instance_id: int
    envelope_id: str = ""
    template_ref: str = ""
    external_key: str = ""
    recipients: tuple = ()


class _ProviderStep(_AgreementAction):
    """The three phases of a provider write: check and write the attempt `sending`; the exchange with no lock held; a
    fenced result transaction. An earlier `sending` or `unknown` attempt means a previous exchange's outcome is
    unknown, so the step reconciles instead of calling the provider again (021 section 5)."""

    step = ""
    uncertain_status = ""

    def run(self, claim) -> None:
        try:
            with transaction.atomic():
                self.lock_subject(claim)
                ledger.fence(claim)  # another claim owns the action: nothing is sent or written
                early, plan = self.check(claim)
                if early is not None:
                    settle(claim, self, early)
                    return
        except ledger.LeaseLost:
            logger.warning("action %s (%s): lease lost before the provider call; nothing sent", claim.id, claim.kind)
            return
        if transaction.get_connection().in_atomic_block:
            raise RuntimeError("refusing to call the provider inside a transaction")
        try:
            result = self.call(plan)
        except provider.ProviderError as exc:
            result = exc
        except Exception as exc:  # a defect during the exchange: the request may have left, so the outcome is unknown
            logger.error("action %s (%s): the provider call raised %s", claim.id, claim.kind, type(exc).__name__)
            result = provider.ProviderError("handler_error", sent=True)
        try:
            self.after_call(claim, result)
            self.record_result(claim, plan, result)
        except Exception as exc:
            # The exchange may have happened and its result could not be recorded: the attempt stays `sending`, so
            # the next claim reconciles (never a blind repeat).
            raise ledger.LeftForRecovery from exc

    def after_call(self, claim, result) -> None:
        """Test seam: after the exchange, before the result is recorded."""

    # --- shared checks ---------------------------------------------------------------------------------------

    def _context(self, claim, key: str):
        """Load the subject, then, before any other check, reconcile an earlier exchange whose outcome is unknown: no
        refusal, pause or stage change may strand it (4B.1 review)."""
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        instance = (AgreementInstance.objects.select_related("template_version", "agreement_type", "application")
                    .filter(public_id=claim.input_ref).first())
        if application is None or instance is None or instance.application_id != application.pk:
            return None, None, Decision(Status.FAILED, "instance_not_found")
        pending = self._pending(instance, key)
        if pending:
            return application, instance, self._to_reconcile(claim, instance, pending)
        from .completion import stopped  # completion builds on this module

        if (instance.cancel_requested_at or stopped(application)) and instance.issue_status in (
                "create_pending", "distribute_pending"):
            # D-42: a stop arrived while an earlier exchange ran; nothing more is created or sent. A draft that
            # exists stays at the provider, never distributed.
            def close():
                AgreementInstance.objects.filter(pk=instance.pk, issue_status=instance.issue_status).update(
                    issue_status="cancelled", signing_status="cancelled", updated_at=Now())
                event(application, "agreement_closed_on_request", {"instance": str(instance.public_id),
                                                                   "draft_left": bool(instance.envelope_id)},
                      actor_ref=f"pending_action:{claim.id}")
                if instance.envelope_id:
                    _watch_left_draft(instance)
            return application, instance, Decision(Status.DONE, "cancel_requested", write=close)
        if paused(application):
            return application, instance, Decision(Status.QUEUED, "automation_paused", refund=True, due_in=_poll())
        if application.stage != Stage.AGREEMENTS:
            return application, instance, Decision(Status.CANCELLED, "stage_changed")
        if not provider.configured():
            def unconfigured():
                AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="failed_needs_staff", updated_at=Now())
                open_item(PROVIDER_UNAVAILABLE, f"{self.step}:{instance.public_id}", application=application,
                          pending_action_id=claim.id)
            return application, instance, Decision(Status.FAILED, "provider_not_configured", write=unconfigured)
        return application, instance, None

    def _pending(self, instance, key: str):
        return list(EnvelopeAttempt.objects.filter(instance=instance, step=self.step, external_key=key,
                                                   outcome__in=(Out.SENDING, Out.UNKNOWN)).order_by("id"))

    def _to_reconcile(self, claim, instance, attempts) -> Decision:
        def write():
            EnvelopeAttempt.objects.filter(pk__in=[a.pk for a in attempts], outcome=Out.SENDING).update(
                outcome=Out.UNKNOWN, outcome_code="earlier_exchange_unknown", finished_at=Now())
            AgreementInstance.objects.filter(pk=instance.pk).update(issue_status=self.uncertain_status, updated_at=Now())
            event(instance.application, f"agreement_{self.step}_unknown", {"instance": str(instance.public_id)},
                  actor_ref=f"pending_action:{claim.id}")
            enqueue_reconcile(attempts[-1], 1)
        return Decision(Status.UNCERTAIN, "earlier_exchange_outcome_unknown", write=write)

    def _attempt(self, claim, instance, *, envelope_id="") -> EnvelopeAttempt:
        return EnvelopeAttempt.objects.create(instance=instance, step=self.step, external_key=instance.external_key,
                                              pending_action_id=claim.id, envelope_id=envelope_id)

    # --- recording -------------------------------------------------------------------------------------------

    def _finish_attempt(self, attempt_id, outcome, code="", envelope_id=None):
        fields = {"outcome": outcome, "outcome_code": code[:64], "finished_at": Now()}
        if envelope_id is not None:
            fields["envelope_id"] = envelope_id
        EnvelopeAttempt.objects.filter(pk=attempt_id, outcome=Out.SENDING).update(**fields)

    def record_failure(self, claim, plan: Plan, exc: provider.ProviderError) -> bool:
        instance = AgreementInstance.objects.select_related("application").get(pk=plan.instance_id)
        actor = f"pending_action:{claim.id}"
        data = {"instance": str(instance.public_id), "step": self.step, "code": exc.code}
        if exc.unknown:
            def write():
                self._finish_attempt(plan.attempt_id, Out.UNKNOWN, exc.code)
                AgreementInstance.objects.filter(pk=instance.pk).update(issue_status=self.uncertain_status, updated_at=Now())
                event(instance.application, f"agreement_{self.step}_unknown", data, actor_ref=actor)
                enqueue_reconcile(EnvelopeAttempt.objects.get(pk=plan.attempt_id), 1)
            return ledger.finish(claim, self, status=Status.UNCERTAIN, error=exc.code, write=write)
        if exc.status is not None and 400 <= exc.status < 500 and exc.status != 429:
            def write():  # a definite refusal by the provider: nothing was created or sent
                self._finish_attempt(plan.attempt_id, Out.REJECTED, exc.code)
                AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="failed_needs_staff", updated_at=Now())
                open_item(PROVIDER_REJECTED, f"{self.step}:{instance.public_id}", application=instance.application,
                          pending_action_id=claim.id)
                event(instance.application, f"agreement_{self.step}_rejected", data, actor_ref=actor)
            return ledger.finish(claim, self, status=Status.FAILED, error=exc.code, write=write)
        # Known not processed: never sent, a connect failure, or a 429. Retry within the attempt bound, honouring
        # `Retry-After` (TEST-P4-18); then staff.
        if claim.final:
            def write():
                self._finish_attempt(plan.attempt_id, Out.NOT_SENT, exc.code)
                AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="failed_needs_staff", updated_at=Now())
                open_item(PROVIDER_UNAVAILABLE, f"{self.step}:{instance.public_id}", application=instance.application,
                          pending_action_id=claim.id)
                event(instance.application, f"agreement_{self.step}_unavailable", data, actor_ref=actor)
            return ledger.finish(claim, self, status=Status.FAILED, error=exc.code, write=write)
        due = timedelta(seconds=exc.retry_after) if exc.retry_after is not None else None
        return ledger.finish(claim, self, status=Status.QUEUED, error=exc.code, due_in=due,
                             write=lambda: self._finish_attempt(plan.attempt_id, Out.NOT_SENT, exc.code))

    def on_final_failure(self, claim, application) -> None:
        """The poison rule, or a defect on the final attempt, finished this step (uncertain: it is not redeliverable).
        An attempt that may have reached the provider is reconciled; otherwise staff are told (4B.1 review)."""
        instance = AgreementInstance.objects.filter(public_id=claim.input_ref, application=application).first()
        attempts = list(EnvelopeAttempt.objects.filter(instance=instance, step=self.step, pending_action_id=claim.id,
                                                       outcome__in=(Out.SENDING, Out.UNKNOWN)).order_by("id")) if instance else []
        if not attempts:
            super().on_final_failure(claim, application)
            return
        EnvelopeAttempt.objects.filter(pk__in=[a.pk for a in attempts], outcome=Out.SENDING).update(
            outcome=Out.UNKNOWN, outcome_code="attempts_exhausted", finished_at=Now())
        AgreementInstance.objects.filter(pk=instance.pk).update(issue_status=self.uncertain_status, updated_at=Now())
        enqueue_reconcile(attempts[-1], 1)


class CreateAgreement(_ProviderStep):
    kind = CREATE
    step = Step.CREATE
    uncertain_status = "create_uncertain"

    def check(self, claim):
        key = _action_key(claim).rpartition(":")[2]
        application, instance, early = self._context(claim, key)
        if early is not None:
            return early, None
        if instance.issue_status != "create_pending" or key != instance.external_key:
            return Decision(Status.DONE, "not_pending"), None  # created, decided or superseded meanwhile
        recipients = list(instance.recipients.order_by("signing_order", "id"))
        if any(r.who == "applicant" and r.email != verified_address(application) for r in recipients):
            return Decision(Status.FAILED, "recipient_changed", write=lambda: open_item(
                DISTRIBUTE_REFUSED, f"create:{instance.public_id}", application=application, pending_action_id=claim.id)), None
        slots = instance.template_version.recipient_slots or {}
        payload = []
        for r in recipients:
            slot = slots.get(f"{r.role}:{r.signing_order}")
            if not isinstance(slot, int):
                return Decision(Status.FAILED, "template_slot_missing"), None
            payload.append({"id": slot, "email": r.email, "name": r.name, "signingOrder": r.signing_order})
        attempt = self._attempt(claim, instance)
        return None, Plan(attempt.pk, instance.pk, template_ref=instance.template_version.provider_template_ref,
                          external_key=instance.external_key, recipients=tuple(payload))

    def call(self, plan: Plan):
        return provider.create_from_template(plan.template_ref, plan.external_key, list(plan.recipients))

    def record_result(self, claim, plan: Plan, result) -> bool:
        if isinstance(result, provider.ProviderError):
            return self.record_failure(claim, plan, result)
        instance = AgreementInstance.objects.select_related("application").get(pk=plan.instance_id)

        def write():
            self._finish_attempt(plan.attempt_id, Out.SUCCEEDED, "created", envelope_id=result)
            current = AgreementInstance.objects.get(pk=instance.pk)
            if current.issue_status != "create_pending" or current.cancel_requested_at:
                # Stopped or cancelled meanwhile (D-42): the draft is recorded and never distributed.
                AgreementInstance.objects.filter(pk=instance.pk, envelope_id="").update(envelope_id=result, updated_at=Now())
                AgreementInstance.objects.filter(pk=instance.pk, issue_status="create_pending").update(
                    issue_status="cancelled", signing_status="cancelled", updated_at=Now())
                event(instance.application, "agreement_created_after_stop", {"instance": str(instance.public_id)},
                      actor_ref=f"pending_action:{claim.id}")
                _watch_left_draft(instance)
                return
            AgreementInstance.objects.filter(pk=instance.pk).update(envelope_id=result, issue_status="distribute_pending",
                                                                    updated_at=Now())
            event(instance.application, "agreement_envelope_created", {"instance": str(instance.public_id)},
                  actor_ref=f"pending_action:{claim.id}")
            enqueue_distribute(instance)
        return ledger.finish(claim, self, status=Status.DONE, write=write)


class DistributeAgreement(_ProviderStep):
    kind = DISTRIBUTE
    step = Step.DISTRIBUTE
    uncertain_status = "distribute_uncertain"

    def check(self, claim):
        current = AgreementInstance.objects.filter(public_id=claim.input_ref).values_list("external_key", flat=True).first()
        application, instance, early = self._context(claim, current or "")
        if early is not None:
            return early, None
        if instance.issue_status != "distribute_pending" or not instance.envelope_id:
            return Decision(Status.DONE, "not_pending"), None
        # The P2 send checks (021 step 3): Documenso will email the applicant, outside P2's own sending.
        reason = ""
        applicant = instance.recipients.filter(who="applicant").first()
        if applicant is None or applicant.email != verified_address(application):
            reason = "recipient_not_verified_address"
        elif hard_bounce_open(application):
            reason = "hard_bounce_open"
        if reason:
            def refuse():
                AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="failed_needs_staff", updated_at=Now())
                open_item(DISTRIBUTE_REFUSED, f"distribute:{instance.public_id}", application=application,
                          pending_action_id=claim.id)
                event(application, "agreement_distribute_refused", {"instance": str(instance.public_id), "reason": reason},
                      actor_ref=f"pending_action:{claim.id}")
            return Decision(Status.FAILED, reason, write=refuse), None
        attempt = self._attempt(claim, instance, envelope_id=instance.envelope_id)
        ours = tuple(sorted((r.email.lower(), r.role) for r in instance.recipients.all()))
        return None, Plan(attempt.pk, instance.pk, envelope_id=instance.envelope_id, external_key=instance.external_key,
                          recipients=ours)

    def call(self, plan: Plan):
        """Re-read first (021 section 5): a repeat distribute is avoided, because its behaviour is NOT VERIFIED."""
        try:
            current = provider.read(plan.envelope_id)
        except provider.ProviderError as exc:
            raise provider.ProviderError(exc.code, sent=False, status=exc.status) from None  # a read changes nothing
        if current.id != plan.envelope_id or current.external_id != plan.external_key:
            return "mismatch"
        if tuple(sorted((r.email.lower(), r.role) for r in current.recipients)) != plan.recipients:
            return "recipients_mismatch"  # Documenso would email someone Catalyst did not verify (4B.1 review)
        if current.status == "PENDING":
            return "already_distributed"
        if current.status != "DRAFT":
            return f"status_{current.status.lower()}"
        provider.distribute(plan.envelope_id)
        return "distributed"

    def record_result(self, claim, plan: Plan, result) -> bool:
        if isinstance(result, provider.ProviderError):
            return self.record_failure(claim, plan, result)
        instance = AgreementInstance.objects.select_related("application").get(pk=plan.instance_id)
        actor = f"pending_action:{claim.id}"
        if result in ("distributed", "already_distributed"):
            def write():
                self._finish_attempt(plan.attempt_id, Out.SUCCEEDED, result)
                current = AgreementInstance.objects.get(pk=instance.pk)
                if current.issue_status == "distribute_pending" and not current.cancel_requested_at:
                    AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="issued", updated_at=Now())
                    _start_sweep(instance)
                elif current.issue_status in ("distribute_pending", "cancelled"):
                    # The envelope went out although a stop or cancel was requested meanwhile (D-42): it happened, so
                    # it is recorded as sent and then cancelled through the reconciled cancel.
                    _cancel_after_send(current)
                event(instance.application, "agreement_issued", {"instance": str(instance.public_id), "how": result},
                      actor_ref=actor)
            return ledger.finish(claim, self, status=Status.DONE, write=write)

        def write():  # the envelope is not ours, or in a state distribution cannot follow: staff decide
            self._finish_attempt(plan.attempt_id, Out.NOT_SENT, result)
            AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="failed_needs_staff", updated_at=Now())
            open_item(ENVELOPE_MISMATCH, f"distribute:{instance.public_id}", application=instance.application,
                      pending_action_id=claim.id)
            event(instance.application, "agreement_distribute_refused", {"instance": str(instance.public_id), "reason": result},
                  actor_ref=actor)
        return ledger.finish(claim, self, status=Status.FAILED, error=result, write=write)


# --- reconciliation and the orphan watch (021 section 5) ---------------------------------------------------------

def _created_at(value: str):
    try:
        moment = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return moment if moment is not None and moment.tzinfo is not None else None


def matches(env: provider.Envelope, instance, key: str) -> bool:
    """Admissible evidence that an envelope is the one an attempt created: our key, our template, a document, and
    exactly our recipients' addresses. Nothing else counts."""
    emails = {r.email.lower() for r in instance.recipients.all()}
    return (env.external_id == key and env.type == "DOCUMENT"
            and env.template_number == instance.template_version.provider_template_number
            and {r.email.lower() for r in env.recipients} == emails)


def search(instance, key: str, since) -> list[provider.Envelope]:
    """The bounded listing (021 section 5): newest first, at most CATALYST_AGREEMENT_LIST_PAGES pages, stopping at
    envelopes older than an hour before the attempt. The installed version has no lookup by `externalId`."""
    floor = since - timedelta(hours=1)
    found, page, pages = [], 1, 1
    while page <= min(pages, settings.CATALYST_AGREEMENT_LIST_PAGES):
        batch, pages = provider.find(instance.template_version.provider_template_number, page)
        found += [e for e in batch if matches(e, instance, key)]
        if not batch or any((t := _created_at(e.created_at)) is not None and t < floor for e in batch):
            break
        page += 1
    return found


class ReconcileAgreement:
    kind = RECONCILE
    redeliverable = True  # it reads only (D-27)
    automated = False  # a pause never holds it: an unknown outcome stays reconcilable

    def lock_subject(self, claim) -> None:
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            attempt = EnvelopeAttempt.objects.filter(public_id=claim.input_ref).first()
            if attempt is not None:
                AgreementInstance.objects.select_for_update(of=("self",)).filter(pk=attempt.instance_id).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            # A reconciliation that cannot finish never leaves an unknown outcome silent (4B.1 review).
            attempt = EnvelopeAttempt.objects.filter(public_id=claim.input_ref).first()
            reason = {Step.CREATE: CREATE_UNKNOWN, Step.DISTRIBUTE: DISTRIBUTE_UNKNOWN}.get(
                attempt.step if attempt else "", CANCEL_UNKNOWN)
            if attempt is not None and attempt.outcome in (Out.DECIDED_NOT_SENT, Out.ABANDONED):
                reason = WATCH_FAILED
            open_item(reason, f"{attempt.step if attempt else 'reconcile'}:{claim.input_ref}", application=application,
                      pending_action_id=claim.id)

    def run(self, claim) -> None:
        attempt = (EnvelopeAttempt.objects.select_related("instance__application", "instance__template_version")
                   .filter(public_id=claim.input_ref).first())
        mode, n = _reconcile_number(claim)
        if attempt is None or not mode or attempt.instance.application.public_ref != claim.subject_id:
            ledger.finish(claim, self, status=Status.FAILED, error="reconcile_target_not_found")
            return
        if mode == "watch":
            self.watch(claim, attempt, n)
        elif attempt.outcome != Out.UNKNOWN:
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_reconcile")
        elif attempt.step == Step.CREATE:
            self.created(claim, attempt, n)
        else:
            self.read_back(claim, attempt, n)

    def _again_or_item(self, claim, attempt, n, reason, *, watch=False):
        instance = attempt.instance
        limit = settings.CATALYST_AGREEMENT_ORPHAN_CHECKS if watch else settings.CATALYST_AGREEMENT_RECONCILE_CHECKS

        if watch:
            limit = watch_limit(attempt)

        def write():
            if n < limit:
                enqueue_reconcile(attempt, n + 1, watch=watch)
            elif not watch:  # no admissible evidence by the deadline: a decision-maker decides (P4-D-8)
                open_item(reason, f"{attempt.step}:{attempt.public_id}", application=instance.application,
                          pending_action_id=claim.id)
            else:  # D-44: the bounded watch never ends silently; the uncertainty stays a visible staff obligation
                open_item(ORPHAN_WATCH_ENDED, f"watch:{attempt.public_id}", application=instance.application,
                          pending_action_id=claim.id)
                event(instance.application, "agreement_orphan_watch_ended",
                      {"attempt": str(attempt.public_id), "checks": n}, actor_ref=f"pending_action:{claim.id}")
        ledger.finish(claim, self, status=Status.DONE, write=write)

    def created(self, claim, attempt, n) -> None:
        instance = attempt.instance
        try:
            found = search(instance, attempt.external_key, attempt.created_at)
        except provider.ProviderError:
            self._again_or_item(claim, attempt, n, CREATE_UNKNOWN)
            return
        if not found:
            self._again_or_item(claim, attempt, n, CREATE_UNKNOWN)
            return
        actor = f"pending_action:{claim.id}"
        if len(found) > 1:
            ledger.finish(claim, self, status=Status.DONE, error="duplicate_envelopes", write=lambda: open_item(
                DUPLICATE_ENVELOPES, f"create:{attempt.public_id}", application=instance.application, pending_action_id=claim.id))
            return
        envelope_id = found[0].id

        def write():
            current = AgreementInstance.objects.get(pk=instance.pk)
            if (current.issue_status != "create_uncertain" or current.external_key != attempt.external_key
                    or not EnvelopeAttempt.objects.filter(pk=attempt.pk, outcome=Out.UNKNOWN).update(
                        outcome=Out.FOUND_BY_EVIDENCE, envelope_id=envelope_id, finished_at=Now())):
                return  # decided meanwhile: the watch, not this check, handles a late match
            if current.cancel_requested_at:  # D-42: the draft is recorded, never distributed
                AgreementInstance.objects.filter(pk=instance.pk).update(envelope_id=envelope_id, issue_status="cancelled",
                                                                        signing_status="cancelled", updated_at=Now())
                PendingAction.objects.filter(kind=CREATE, input_ref=str(instance.public_id), status=Status.UNCERTAIN).update(
                    status=Status.DONE, last_error="found_by_evidence", completed_at=Now(), updated_at=Now())
                event(instance.application, "agreement_created_after_stop", {"instance": str(instance.public_id)},
                      actor_ref=actor)
                _watch_left_draft(instance)
                return
            AgreementInstance.objects.filter(pk=instance.pk).update(envelope_id=envelope_id, issue_status="distribute_pending",
                                                                    updated_at=Now())
            PendingAction.objects.filter(kind=CREATE, input_ref=str(instance.public_id), status=Status.UNCERTAIN).update(
                status=Status.DONE, last_error="found_by_evidence", completed_at=Now(), updated_at=Now())
            for item in StaffItem.objects.filter(reason_code=CREATE_UNKNOWN, dedupe_key=f"create:{attempt.public_id}",
                                                 status=StaffItem.Status.OPEN):
                resolve_item(item, code="found_by_evidence", actor_ref=actor, effects={"instance": str(instance.public_id)},
                             actor_type=ApplicationEvent.ActorType.SYSTEM)
            event(instance.application, "agreement_envelope_found", {"instance": str(instance.public_id)}, actor_ref=actor)
            enqueue_distribute(instance)
        ledger.finish(claim, self, status=Status.DONE, write=write)

    def read_back(self, claim, attempt, n) -> None:
        """An unknown distribute (after the settle window) or cancel: a fresh read decides, else staff."""
        instance = attempt.instance
        reason = DISTRIBUTE_UNKNOWN if attempt.step == Step.DISTRIBUTE else CANCEL_UNKNOWN
        try:
            current = provider.read(attempt.envelope_id)
        except provider.ProviderError:
            self._again_or_item(claim, attempt, n, reason)
            return
        done = "PENDING" if attempt.step == Step.DISTRIBUTE else "CANCELLED"
        if current.id != attempt.envelope_id or current.external_id != attempt.external_key or current.status != done:
            self._again_or_item(claim, attempt, n, reason)
            return
        actor = f"pending_action:{claim.id}"

        def write():
            if not EnvelopeAttempt.objects.filter(pk=attempt.pk, outcome=Out.UNKNOWN).update(
                    outcome=Out.FOUND_BY_EVIDENCE, finished_at=Now()):
                return
            if attempt.step == Step.CANCEL and AgreementInstance.objects.filter(
                    pk=instance.pk, issue_status="cancel_uncertain", envelope_id=attempt.envelope_id).update(issue_status="cancelled",
                                                                            signing_status="cancelled", updated_at=Now()):
                PendingAction.objects.filter(kind="cancel_agreement", input_ref=str(instance.public_id),
                                             status=Status.UNCERTAIN).update(
                    status=Status.DONE, last_error="found_by_evidence", completed_at=Now(), updated_at=Now())
            if attempt.step == Step.DISTRIBUTE and AgreementInstance.objects.filter(
                    pk=instance.pk, issue_status="distribute_uncertain", cancel_requested_at__isnull=False).exists():
                _cancel_after_send(AgreementInstance.objects.get(pk=instance.pk))  # D-42: sent, then cancelled
            elif attempt.step == Step.DISTRIBUTE and AgreementInstance.objects.filter(
                    pk=instance.pk, issue_status="distribute_uncertain").update(issue_status="issued", updated_at=Now()):
                _start_sweep(instance)
                PendingAction.objects.filter(kind=DISTRIBUTE, input_ref=str(instance.public_id), status=Status.UNCERTAIN).update(
                    status=Status.DONE, last_error="found_by_evidence", completed_at=Now(), updated_at=Now())
                event(instance.application, "agreement_issued", {"instance": str(instance.public_id), "how": "found_by_evidence"},
                      actor_ref=actor)
            for item in StaffItem.objects.filter(reason_code=reason, dedupe_key=f"{attempt.step}:{attempt.public_id}",
                                                 status=StaffItem.Status.OPEN):
                resolve_item(item, code="found_by_evidence", actor_ref=actor, effects={"instance": str(instance.public_id)},
                             actor_type=ApplicationEvent.ActorType.SYSTEM)
        ledger.finish(claim, self, status=Status.DONE, write=write)

    def watch(self, claim, attempt, n) -> None:
        """P4-D-19: a key a decision-maker set aside stays watched. A late match is an orphan: never linked, never
        verified; staff are told and it is cancelled at the provider."""
        if attempt.outcome not in (Out.DECIDED_NOT_SENT, Out.ABANDONED):
            ledger.finish(claim, self, status=Status.DONE, error="not_watched")
            return
        try:
            found = search(attempt.instance, attempt.external_key, attempt.created_at)
        except provider.ProviderError:
            found = None
        if not found:
            self._again_or_item(claim, attempt, n, LATE_ORPHAN, watch=True)
            return
        actor = f"pending_action:{claim.id}"
        instance = attempt.instance

        def write():
            if not EnvelopeAttempt.objects.filter(pk=attempt.pk, outcome__in=(Out.DECIDED_NOT_SENT, Out.ABANDONED)).update(
                    outcome=Out.ORPHAN_FOUND, envelope_id=found[0].id):
                return
            open_item(LATE_ORPHAN, f"create:{attempt.public_id}", application=instance.application, pending_action_id=claim.id)
            event(instance.application, "agreement_orphan_found", {"instance": str(instance.public_id),
                                                                   "attempt": str(attempt.public_id), "count": len(found)},
                  actor_ref=actor)
            orphans = [EnvelopeAttempt.objects.get(pk=attempt.pk)]
            for extra in found[1:]:  # every matching envelope is an orphan, each recorded and cancelled
                orphans.append(EnvelopeAttempt.objects.create(
                    instance=instance, step=Step.CREATE, external_key=attempt.external_key, pending_action_id=claim.id,
                    outcome=Out.ORPHAN_FOUND, outcome_code="duplicate_orphan", envelope_id=extra.id, finished_at=Now()))
            for orphan in orphans:
                enqueue_cancel(orphan)
        ledger.finish(claim, self, status=Status.DONE, write=write)


# --- cancelling an orphan at the provider (021 section 4; 4B.2 generalizes it to any instance) ------------------

class CancelEnvelope(_ProviderStep):
    kind = CANCEL
    step = Step.CANCEL
    automated = False  # protective: it runs while automation is paused

    def lock_subject(self, claim) -> None:
        ReconcileAgreement.lock_subject(self, claim)

    def on_final_failure(self, claim, application) -> None:
        """A cancel that cannot finish: an attempt that may have reached the provider is reconciled, and staff are told
        either way."""
        attempts = list(EnvelopeAttempt.objects.filter(step=Step.CANCEL, pending_action_id=claim.id,
                                                       outcome__in=(Out.SENDING, Out.UNKNOWN)).order_by("id"))
        if attempts:
            EnvelopeAttempt.objects.filter(pk__in=[a.pk for a in attempts], outcome=Out.SENDING).update(
                outcome=Out.UNKNOWN, outcome_code="attempts_exhausted", finished_at=Now())
            enqueue_reconcile(attempts[-1], 1)
        open_item(CANCEL_UNKNOWN, f"cancel:{claim.input_ref}", application=application, pending_action_id=claim.id)

    def check(self, claim):
        orphan = (EnvelopeAttempt.objects.select_related("instance__application")
                  .filter(public_id=claim.input_ref, outcome=Out.ORPHAN_FOUND).first())
        if orphan is None or orphan.instance.application.public_ref != claim.subject_id or not orphan.envelope_id:
            return Decision(Status.FAILED, "orphan_not_found"), None
        if not provider.configured():
            return Decision(Status.FAILED, "provider_not_configured", write=lambda: open_item(
                CANCEL_UNKNOWN, f"cancel:{claim.input_ref}", application=orphan.instance.application,
                pending_action_id=claim.id)), None
        earlier = list(EnvelopeAttempt.objects.filter(instance=orphan.instance, step=Step.CANCEL,
                                                      envelope_id=orphan.envelope_id,
                                                      outcome__in=(Out.SENDING, Out.UNKNOWN)).order_by("id"))
        if earlier:
            def write():
                EnvelopeAttempt.objects.filter(pk__in=[a.pk for a in earlier], outcome=Out.SENDING).update(
                    outcome=Out.UNKNOWN, outcome_code="earlier_exchange_unknown", finished_at=Now())
                enqueue_reconcile(earlier[-1], 1)
            return Decision(Status.UNCERTAIN, "earlier_exchange_outcome_unknown", write=write), None
        attempt = EnvelopeAttempt.objects.create(instance=orphan.instance, step=Step.CANCEL, external_key=orphan.external_key,
                                                 pending_action_id=claim.id, envelope_id=orphan.envelope_id)
        return None, Plan(attempt.pk, orphan.instance_id, envelope_id=orphan.envelope_id, external_key=orphan.external_key)

    def call(self, plan: Plan):
        try:
            current = provider.read(plan.envelope_id)
        except provider.ProviderError as exc:
            raise provider.ProviderError(exc.code, sent=False, status=exc.status) from None
        if current.external_id != plan.external_key:
            return "mismatch"
        if current.status == "CANCELLED":
            return "already_cancelled"
        if current.status == "PENDING":
            provider.cancel(plan.envelope_id)
            return "cancelled"
        return f"status_{current.status.lower()}"  # a draft was never sent; a completed orphan goes to staff

    def record_result(self, claim, plan: Plan, result) -> bool:
        if isinstance(result, provider.ProviderError):
            if result.unknown:
                def write():
                    self._finish_attempt(plan.attempt_id, Out.UNKNOWN, result.code)
                    enqueue_reconcile(EnvelopeAttempt.objects.get(pk=plan.attempt_id), 1)
                return ledger.finish(claim, self, status=Status.UNCERTAIN, error=result.code, write=write)
            if claim.final or (result.status is not None and result.status != 429):
                def failed():
                    self._finish_attempt(plan.attempt_id, Out.NOT_SENT, result.code)
                    instance = AgreementInstance.objects.select_related("application").get(pk=plan.instance_id)
                    open_item(CANCEL_UNKNOWN, f"cancel:{claim.input_ref}", application=instance.application,
                              pending_action_id=claim.id)
                return ledger.finish(claim, self, status=Status.FAILED, error=result.code, write=failed)
            due = timedelta(seconds=result.retry_after) if result.retry_after is not None else None
            return ledger.finish(claim, self, status=Status.QUEUED, error=result.code, due_in=due,
                                 write=lambda: self._finish_attempt(plan.attempt_id, Out.NOT_SENT, result.code))
        instance = AgreementInstance.objects.select_related("application").get(pk=plan.instance_id)
        actor = f"pending_action:{claim.id}"

        def write():
            # A draft orphan cannot be cancelled (the installed API cancels pending envelopes only) and was never sent:
            # it is left, recorded as `left_draft`, and its staff item stays open (021 section 15).
            succeeded = result in ("cancelled", "already_cancelled")
            self._finish_attempt(plan.attempt_id, Out.SUCCEEDED if succeeded else Out.NOT_SENT,
                                 "left_draft" if result == "status_draft" else result)
            if result == "status_completed":
                open_item(SIGNED_ORPHAN, f"cancel:{claim.input_ref}", application=instance.application,
                          pending_action_id=claim.id)
            event(instance.application, "agreement_orphan_cancel", {"instance": str(instance.public_id), "result": result},
                  actor_ref=actor)
        return ledger.finish(claim, self, status=Status.DONE, error=result, write=write)


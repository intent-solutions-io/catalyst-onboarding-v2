"""Outbound foundations (016 section 4 A; P2 task 2B.1; owner decisions D-27 to D-30). Synthetic only.

Services (one transaction each, the application locked first; 016 section 5):
- `approve_template_version`: the owner approves one template version (D-29).
- `approve_question`: an operator approves a question; one transaction freezes the `ApprovedMessage`
  (verified recipient, exact template version, rendered content and its digest, authorization), links the
  question and queues the send (A2). Approving twice does nothing more.

Handlers (registered in settings.CATALYST_ACTION_HANDLERS; ledger rules in workflow/ledger.py):
- `SendMessage` (`send_message`, non-redeliverable, automated). Three phases as in S1: a check
  transaction that re-verifies everything and writes the attempt row `sending`; the SMTP exchange with no
  lock held; a fenced result transaction. Each outcome class is recorded with `ledger.finish` directly,
  never `fail_or_retry` (016 A3). An earlier `sending` or `unknown` attempt of the current series means the
  outcome of a previous exchange is unknown, so the handler reconciles instead of sending (A5).
- `ReconcileSend` (`reconcile_send`, internal and idempotent, D-27): looks only for admissible evidence
  (A5). None is configured for real providers; without it the outcome stays unknown and goes to staff.

A worker rebuilds every message from its `ApprovedMessage` alone: never from the latest template version,
current answers or the application's current address.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Max
from django.db.models.functions import Now
from django.utils.module_loading import import_string

from applications.models import TERMINAL_STAGES, Application, ApplicationEvent, Stage
from applications.stages import transition
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from . import transport
from .models import (
    ApprovedMessage,
    ApprovedMessageQuestion,
    MessageTemplateVersion,
    OutboundMessage,
    Question,
    StaffItem,
)
from .common import DECIDABLE, Refused, actor_ref, require  # noqa: F401  (re-exported for callers)
from .messages import build_email, enqueue_file_copy, message_id, verified_address  # noqa: F401
from .rendering import TemplateRefused, canonical_digest, check_version, render
from .questions import sent_text
from .scheduling import schedule_after_acceptance
from .staff_items import event, hard_bounce_open, open_item, resolve_item

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Attempt = OutboundMessage.Status
Disposition = ApprovedMessage.Disposition

SEND = "send_message"
SEND_STAFF = "send_staff_message"  # a staff-authored message: not automated, so it runs while paused (M5)
SEND_KINDS = (SEND, SEND_STAFF)
RECONCILE = "reconcile_send"
QUESTION_TEMPLATE = "question_request"

# Staff-item reason codes opened by 2B.1 (016 F, reason-to-permission table: decide_uncertain_send).
SEND_OUTCOME_UNKNOWN = "send_outcome_unknown"
RETRIES_EXHAUSTED = "retries_exhausted"
TRANSPORT_BLOCKED = "smtp_transport_blocked"
REJECTED_PERMANENT = "send_rejected_permanent"
SEND_REFUSED = "send_refused"  # a pre-send re-check failed (recipient changed, content refused)


def send_key(send_ref, series: int) -> str:
    return f"send:{send_ref}:{series}"


def reconcile_key(send_ref, series: int, n: int) -> str:
    """Bounded per attempt series (016 A5): a staff resend that ends unknown again gets its own checks."""
    return f"reconcile:{send_ref}:{series}:{n}"


def _lock_application(application_id) -> Application:
    return Application.objects.select_for_update(of=("self",)).get(pk=application_id)


def enqueue_send(message: ApprovedMessage, series: int) -> PendingAction:
    return PendingAction.objects.create(
        kind=SEND_STAFF if message.kind == ApprovedMessage.Kind.STAFF_MESSAGE else SEND, subject_type="application", subject_id=message.application.public_ref, input_ref=str(message.send_ref),
        idempotency_key=send_key(message.send_ref, series), max_attempts=settings.CATALYST_MAIL_SEND_ATTEMPTS,
    )


def enqueue_reconcile(message: ApprovedMessage, series: int, n: int) -> PendingAction:
    return PendingAction.objects.create(
        kind=RECONCILE, subject_type="application", subject_id=message.application.public_ref,
        input_ref=str(message.send_ref), idempotency_key=reconcile_key(message.send_ref, series, n),
        due_at=Now() + timedelta(seconds=settings.CATALYST_MAIL_RECONCILE_GRACE_SECONDS),
        max_attempts=settings.CATALYST_MAIL_SEND_ATTEMPTS,
    )


# --- services ---------------------------------------------------------------------------------------------

def approve_template_version(version_id: int, user, expected_digest: str | None = None) -> MessageTemplateVersion:
    """A1 and D-29. A staff screen passes the digest of the version it showed, so the owner approves exactly
    what they read (2B.4)."""
    require(user, "approve_template_version")
    with transaction.atomic():
        version = MessageTemplateVersion.objects.select_for_update(of=("self",)).select_related("template").get(pk=version_id)
        if expected_digest is not None and expected_digest != version.content_sha256:
            raise Refused("template_changed_since_shown")
        if version.status == MessageTemplateVersion.Status.APPROVED:
            return version
        if version.status != MessageTemplateVersion.Status.DRAFT:
            raise Refused("template_version_not_draft")
        check_version(version)
        MessageTemplateVersion.objects.filter(pk=version.pk).update(
            status=MessageTemplateVersion.Status.APPROVED, approved_by=actor_ref(user), approved_at=Now())
    version.refresh_from_db()
    return version


def current_template_version(key: str) -> MessageTemplateVersion | None:
    return (MessageTemplateVersion.objects.select_related("template")
            .filter(template__key=key, status=MessageTemplateVersion.Status.APPROVED).order_by("-version").first())


def _freeze(application, kind, recipient, version, values, authorized_by, authority, supersedes=None) -> ApprovedMessage:
    subject, body = render(version, values)
    if version.secret_bearing:
        raise Refused("secret_bearing_kind_not_in_this_task")  # reproducible-inputs kinds arrive with their task
    return ApprovedMessage.objects.create(
        kind=kind, application=application, recipient=recipient, template_version=version, frozen_subject=subject,
        frozen_body=body, content_sha256=canonical_digest(subject, body), authorized_by=authorized_by,
        authority=authority, supersedes=supersedes,
    )


def approve_question(question_id: int, user) -> ApprovedMessage:
    """016 A2 and J-06: an authorized operator approves a question, which freezes and queues its message."""
    require(user, "approve_question")
    question = Question.objects.get(pk=question_id)
    with transaction.atomic():
        application = _lock_application(question.application_id)
        question = Question.objects.select_for_update(of=("self",)).get(pk=question_id)
        existing = ApprovedMessageQuestion.objects.filter(question=question, purpose=ApprovedMessageQuestion.Purpose.INITIAL).first()
        if question.approval_state == Question.Approval.APPROVED and existing is not None:
            return existing.approved_message  # approving twice does nothing more (TEST-P2-12)
        if question.status == Question.Status.WITHDRAWN:
            raise Refused("question_withdrawn")
        if application.stage in TERMINAL_STAGES:
            raise Refused("application_closed")
        if application.stage in (Stage.ADMITTED, Stage.ON_HOLD):
            raise Refused("application_decided")  # P3 3B.4: no clarification after a decision
        recipient = verified_address(application)
        if recipient is None:
            raise Refused("contact_not_verified")
        version = current_template_version(QUESTION_TEMPLATE)
        if version is None:
            raise Refused("no_approved_template_version")
        try:
            message = _freeze(application, ApprovedMessage.Kind.QUESTION, recipient, version,
                              {"display_name": application.display_name, "question_text": sent_text(question)},
                              actor_ref(user), ApprovedMessage.Authority.STAFF)
        except TemplateRefused as exc:
            raise Refused(str(exc)) from None
        Question.objects.filter(pk=question.pk).update(
            approval_state=Question.Approval.APPROVED, approved_by=actor_ref(user), approved_at=Now(), updated_at=Now())
        ApprovedMessageQuestion.objects.create(approved_message=message, question=question,
                                               purpose=ApprovedMessageQuestion.Purpose.INITIAL)
        enqueue_send(message, 0)
        event(application, "question_approved", {"question": str(question.public_id), "send_ref": str(message.send_ref)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor_ref(user))
        if application.stage == Stage.AWAITING_DECISION:  # 018 step 5: a staff act opens the clarification round
            transition(application.pk, (Stage.AWAITING_DECISION,), Stage.AWAITING_ANSWERS, event_kind="clarification_started",
                       data={"question": str(question.public_id)}, actor_type=ApplicationEvent.ActorType.STAFF,
                       actor_ref=actor_ref(user))
    return message


# --- building the wire message ----------------------------------------------------------------------------

# --- the send handler -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Proceed:
    attempt_id: int
    payload: bytes
    recipient: str


@dataclass(frozen=True)
class Stop:
    status: str
    reason: str  # a reason code only
    due_seconds: float | None = None  # for a deferral (QUEUED): when to look again; default the poll interval


@dataclass(frozen=True)
class Reconcile:
    attempt_ids: tuple


def _parse_series(key: str, send_ref) -> int | None:
    prefix = f"send:{send_ref}:"
    if not key.startswith(prefix):
        return None
    try:
        return int(key[len(prefix):])
    except ValueError:
        return None


def _after_send(claim, result) -> None:
    """Test seam (TEST-P2-27): called after the SMTP exchange, before the result is recorded."""


class SendMessage:
    kind = SEND
    redeliverable = False  # D-27: reconcile before any further send
    automated = True

    # --- ledger interface ---------------------------------------------------------------------------------

    def lock_subject(self, claim) -> None:
        """Application, then the message's questions by id (016 section 5), before the fenced action update."""
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            list(Question.objects.select_for_update(of=("self",))
                 .filter(message_links__approved_message__send_ref=claim.input_ref).order_by("id"))

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if kind == "action_attempts_exhausted":  # the poison rule finished this send uncertain (ledger rule 2)
            message = ApprovedMessage.objects.select_related("application").filter(send_ref=claim.input_ref).first()
            if message is not None:
                OutboundMessage.objects.filter(approved_message=message, status=Attempt.SENDING).update(status=Attempt.UNKNOWN)
                # 016 A7: the poison rule ends `unknown` with a staff item, whatever reconciliation later finds.
                open_item(SEND_OUTCOME_UNKNOWN, str(message.send_ref), application=message.application,
                          approved_message=message, pending_action_id=claim.id)
                key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""
                _next_reconcile(message, _parse_series(key, message.send_ref) or 0)

    # --- one claim ----------------------------------------------------------------------------------------

    def run(self, claim) -> None:
        decision = self.check(claim)
        if decision is None:
            logger.warning("action %s attempt %s: lease lost before sending; nothing sent", claim.id, claim.attempt)
            return
        if isinstance(decision, Stop):
            self._stop(claim, decision)
            return
        if isinstance(decision, Reconcile):
            self._to_reconcile(claim, decision)
            return
        if connection.in_atomic_block:
            raise RuntimeError("refusing to send inside a transaction")
        result = transport.send(decision.payload, settings.DEFAULT_FROM_EMAIL, decision.recipient)
        try:
            _after_send(claim, result)
            recorded = self._record_result(claim, decision.attempt_id, result)
        except Exception as exc:
            # The exchange happened and its result could not be recorded. The attempt row stays `sending`,
            # so the next claim reconciles (016 A3, TEST-P2-27); it never sends again blindly.
            raise ledger.LeftForRecovery from exc
        if not recorded:
            logger.warning("action %s attempt %s: exchange finished, but a newer claim owns the action", claim.id, claim.attempt)

    def check(self, claim):
        refuse = lambda reason: Stop(Status.FAILED, reason)  # noqa: E731
        skip = lambda reason: Stop(Status.CANCELLED, reason)  # noqa: E731
        with transaction.atomic():
            if claim.subject_type != "application":
                return refuse("subject_is_not_an_application")
            application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
            if application is None:
                return refuse("subject_application_not_found")
            message = (ApprovedMessage.objects.select_related("template_version__template")
                       .filter(send_ref=claim.input_ref, application=application).first())
            if message is None:
                return refuse("approved_message_not_found")
            questions = list(Question.objects.select_for_update(of=("self",))
                             .filter(message_links__approved_message=message).order_by("id"))
            ApprovedMessage.objects.select_for_update(of=("self",)).filter(pk=message.pk).first()
            key = (PendingAction.objects.filter(pk=claim.id, status=Status.RUNNING, lease_token=claim.lease_token)
                   .values_list("idempotency_key", flat=True).first())
            if key is None:
                return None
            series = _parse_series(key, message.send_ref)
            if series is None:
                return refuse("idempotency_key_does_not_match_the_message")
            if self.automated and AutomationPause.objects.filter(
                    subject_type="application", subject_id=application.public_ref).exists():
                return Stop(Status.QUEUED, "automation_paused")  # a staff message is not automated (J-09)
            if hard_bounce_open(application):  # every kind, staff messages and resends included (9kg.3)
                return Stop(Status.QUEUED, "hard_bounce_open", settings.CATALYST_HARD_BOUNCE_RECHECK_SECONDS)
            if message.disposition != Disposition.ACTIVE:
                return skip("message_not_active")
            if application.stage in TERMINAL_STAGES:
                return skip("application_closed")
            if any(q.status == Question.Status.WITHDRAWN for q in questions):
                return skip("question_withdrawn")
            if message.kind == ApprovedMessage.Kind.REMINDER and questions:
                # A frozen reminder still waiting to be sent follows its question (2B.4 review): an answered
                # question cancels it, and a pending reply defers it until staff decide.
                if all(q.status == Question.Status.SATISFIED for q in questions):
                    return skip("question_satisfied")
                if any(q.status == Question.Status.REPLY_PENDING for q in questions):
                    return Stop(Status.QUEUED, "reply_pending", settings.CATALYST_REMINDER_STALE_RETRY_SECONDS)
            if verified_address(application) != message.recipient:
                return refuse("recipient_changed")
            pending = list(OutboundMessage.objects.filter(
                approved_message=message, attempt_series=series, status__in=(Attempt.SENDING, Attempt.UNKNOWN))
                .values_list("pk", flat=True))
            if pending:
                return Reconcile(tuple(pending))
            subject, body = message.frozen_subject, message.frozen_body
            digest = canonical_digest(subject, body)
            if digest != message.content_sha256:
                return refuse("content_digest_mismatch")
            try:
                payload = build_email(message, subject, body)
            except ValueError:
                return refuse("message_refused_by_header_policy")
            number = (OutboundMessage.objects.filter(approved_message=message).aggregate(n=Max("attempt_number"))["n"] or 0) + 1
            version = message.template_version
            attempt = OutboundMessage.objects.create(
                application=application, pending_action_id=claim.id, attempt_number=number,
                template_key=version.template.key if version else "staff_message",
                template_version=str(version.version) if version else "", recipient=message.recipient,
                message_id=message_id(message.send_ref), status=Attempt.SENDING, approved_message=message,
                attempt_series=series, rendered_sha256=digest,
            )
            return Proceed(attempt.pk, payload, message.recipient)

    # --- recording ----------------------------------------------------------------------------------------

    def _message(self, claim) -> ApprovedMessage:
        return ApprovedMessage.objects.select_related("application").get(send_ref=claim.input_ref)

    def _stop(self, claim, decision: Stop) -> None:
        if decision.status == Status.QUEUED:
            wait = settings.CATALYST_WORKER_POLL_SECONDS if decision.due_seconds is None else decision.due_seconds
            ledger.finish(claim, self, status=Status.QUEUED, error=decision.reason, refund_attempt=True,
                          due_in=timedelta(seconds=wait))
            return

        def write():
            self.record(claim, "message_send_refused" if decision.status == Status.FAILED else "message_send_skipped",
                        {"attempt": claim.attempt, "reason": decision.reason})
            message = ApprovedMessage.objects.select_related("application").filter(send_ref=claim.input_ref).first()
            if decision.status == Status.FAILED and message is not None:
                open_item(SEND_REFUSED, f"{message.send_ref}:{decision.reason}", application=message.application,
                          approved_message=message, pending_action_id=claim.id)
        ledger.finish(claim, self, status=decision.status, error=decision.reason, write=write)

    def _to_reconcile(self, claim, decision: Reconcile) -> None:
        def write():
            OutboundMessage.objects.filter(pk__in=decision.attempt_ids, status=Attempt.SENDING).update(status=Attempt.UNKNOWN)
            message = self._message(claim)
            event(message.application, "message_send_unknown", {"send_ref": str(message.send_ref), "attempt": claim.attempt},
                  actor_ref=f"pending_action:{claim.id}")
            series = OutboundMessage.objects.filter(pk__in=decision.attempt_ids).values_list("attempt_series", flat=True).first()
            _next_reconcile(message, series or 0)
        ledger.finish(claim, self, status=Status.UNCERTAIN, error="earlier_exchange_outcome_unknown", write=write)

    def _record_result(self, claim, attempt_id: int, result: transport.SendResult) -> bool:
        message = self._message(claim)
        data = {"send_ref": str(message.send_ref), "attempt": claim.attempt, "phase": result.phase, "code": result.code}

        def attempt(status, **extra):
            OutboundMessage.objects.filter(pk=attempt_id).update(
                status=status, protocol_phase_reached=result.phase, smtp_reply_code=result.code, **extra)

        def dispose(disposition):
            ApprovedMessage.objects.filter(pk=message.pk, disposition=Disposition.ACTIVE).update(
                disposition=disposition, disposition_at=Now(), disposition_by=f"pending_action:{claim.id}")

        def item(reason):
            open_item(reason, str(message.send_ref), application=message.application, approved_message=message,
                      pending_action_id=claim.id)

        if result.outcome == transport.ACCEPTED:
            def write():
                attempt(Attempt.ACCEPTED_BY_SERVER, server_accepted_at=Now(), sent_at=Now())
                dispose(Disposition.ACCEPTED_BY_SERVER)
                schedule_after_acceptance(message)  # E1: the next reminder, in the acceptance transaction
                enqueue_file_copy(message, attempt_id)  # a mailbox record for humans, never evidence (016 A4)
                event(message.application, "message_accepted_by_server", data, actor_ref=f"pending_action:{claim.id}")
            return ledger.finish(claim, self, status=Status.DONE, write=write)

        if result.outcome == transport.REJECTED_PERMANENT:
            def write():
                attempt(Attempt.REJECTED_PERMANENT)
                dispose(Disposition.REJECTED_PERMANENT)
                item(REJECTED_PERMANENT)
                event(message.application, "message_rejected_permanent", data, actor_ref=f"pending_action:{claim.id}")
            return ledger.finish(claim, self, status=Status.FAILED, error="rejected_permanent", write=write)

        if result.outcome == transport.REJECTED_TEMPORARY:
            if claim.final:
                def write():
                    attempt(Attempt.REJECTED_TEMPORARY)
                    dispose(Disposition.RETRIES_EXHAUSTED)
                    item(RETRIES_EXHAUSTED)
                    event(message.application, "message_retries_exhausted", data, actor_ref=f"pending_action:{claim.id}")
                return ledger.finish(claim, self, status=Status.FAILED, error="retries_exhausted", write=write)
            return ledger.finish(claim, self, status=Status.QUEUED, error="rejected_temporary",
                                 write=lambda: attempt(Attempt.REJECTED_TEMPORARY))

        if result.outcome == transport.TRANSPORT_BLOCKED:
            series = OutboundMessage.objects.get(pk=attempt_id).attempt_series
            blocks = _trailing_blocks(message, series, before=attempt_id) + 1  # this attempt included
            if result.hard or blocks >= settings.CATALYST_MAIL_TRANSPORT_BLOCK_LIMIT:
                def write():
                    attempt(Attempt.TRANSPORT_BLOCKED)
                    dispose(Disposition.TRANSPORT_BLOCKED)
                    item(TRANSPORT_BLOCKED)
                    event(message.application, "message_transport_blocked", data, actor_ref=f"pending_action:{claim.id}")
                return ledger.finish(claim, self, status=Status.HELD, error="transport_blocked", refund_attempt=True,
                                     write=write)
            return ledger.finish(claim, self, status=Status.QUEUED, error="transport_blocked", refund_attempt=True,
                                 due_in=timedelta(seconds=settings.CATALYST_MAIL_TRANSPORT_BACKOFF_SECONDS),
                                 write=lambda: attempt(Attempt.TRANSPORT_BLOCKED))

        def write():  # unknown: the end-of-data marker was sent and no reply was observed
            attempt(Attempt.UNKNOWN)
            event(message.application, "message_send_unknown", data, actor_ref=f"pending_action:{claim.id}")
            _next_reconcile(message, OutboundMessage.objects.get(pk=attempt_id).attempt_series)
        return ledger.finish(claim, self, status=Status.UNCERTAIN, error="outcome_unknown", write=write)


def _trailing_blocks(message, series, before: int) -> int:
    """Consecutive `transport_blocked` attempts at the end of the current series, before this attempt
    (016 A3, as clarified: a new series starts the count again)."""
    count = 0
    for status in (OutboundMessage.objects.filter(approved_message=message, attempt_series=series).exclude(pk=before)
                   .order_by("-attempt_number").values_list("status", flat=True)):
        if status != Attempt.TRANSPORT_BLOCKED:
            break
        count += 1
    return count


def _reconciles(message, series):
    return PendingAction.objects.filter(kind=RECONCILE, idempotency_key__startswith=f"reconcile:{message.send_ref}:{series}:")


def _next_reconcile(message, series: int) -> None:
    enqueue_reconcile(message, series, _reconciles(message, series).count() + 1)


# --- reconciliation (016 A5) -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Evidence:
    """A record from an evidence source. Only origin "provider" can be admissible, and only from a source
    whose creation semantics a separately authorized provider check has verified (016 8.3)."""

    origin: str
    message_id: str
    recipient: str
    content_sha256: str
    filed_by_catalyst: bool = False  # the record carries X-Catalyst-Filed-Copy: never evidence, whatever its origin


def evidence_source():
    path = settings.CATALYST_SEND_EVIDENCE_SOURCE
    return import_string(path)() if path else None


def admissible(record: Evidence, message: ApprovedMessage, digests: set) -> bool:
    return (record.origin == "provider" and not record.filed_by_catalyst and record.message_id == message_id(message.send_ref)
            and record.recipient == message.recipient and record.content_sha256 in digests)


class SendStaffMessage(SendMessage):
    """016 3.4: the send of a confirmed staff message. The same three phases and outcome classes as SendMessage,
    under its own kind so a pause never holds it (M5); it creates no reminder."""

    kind = SEND_STAFF
    automated = False


class ReconcileSend:
    kind = RECONCILE
    redeliverable = True  # internal and idempotent: it reads evidence and sends nothing (D-27)
    automated = False  # it sends nothing, so a pause never holds it: an unknown staff send stays reconcilable (2B.4)

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        event(Application.objects.filter(public_ref=claim.subject_id).first(), kind, data,
              actor_ref=f"pending_action:{claim.id}")

    def run(self, claim) -> None:
        message = ApprovedMessage.objects.select_related("application").filter(send_ref=claim.input_ref).first()
        key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""
        parts = key.split(":")
        if len(parts) != 4 or not parts[2].isdigit():
            ledger.finish(claim, self, status=Status.FAILED, error="reconcile_key_malformed")
            return
        if message is None or message.application.public_ref != claim.subject_id:
            ledger.finish(claim, self, status=Status.FAILED, error="approved_message_not_found")
            return
        series = int(parts[2])
        unknown = OutboundMessage.objects.filter(approved_message=message, attempt_series=series, status=Attempt.UNKNOWN)
        if message.disposition != Disposition.ACTIVE or not unknown.exists():
            def no_unknown_attempt():
                # A send that ended uncertain without an unknown attempt (a defect before any exchange) is not
                # left silent: staff decide it (016 A7).
                if message.disposition == Disposition.ACTIVE and PendingAction.objects.filter(
                        kind__in=SEND_KINDS, input_ref=str(message.send_ref), status=Status.UNCERTAIN).exists():
                    open_item(SEND_OUTCOME_UNKNOWN, str(message.send_ref), application=message.application,
                              approved_message=message, pending_action_id=claim.id)
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_reconcile", write=no_unknown_attempt)
            return
        digests = {message.content_sha256, *unknown.values_list("rendered_sha256", flat=True)} - {""}
        source = evidence_source()
        records = list(source.find(message_id(message.send_ref))) if source else []  # no lock is held here
        found = next((r for r in records if admissible(r, message, digests)), None)
        n = _reconciles(message, series).count()

        def write():
            if found is not None:
                if ApprovedMessage.objects.filter(pk=message.pk, disposition=Disposition.ACTIVE).update(
                        disposition=Disposition.ACCEPTED_BY_EVIDENCE, disposition_at=Now(),
                        disposition_by=f"pending_action:{claim.id}"):
                    # The send's own action finished uncertain; its work is complete. Attempts stay `unknown`:
                    # evidence shows the logical message was accepted, not which attempt was.
                    PendingAction.objects.filter(kind__in=SEND_KINDS, input_ref=str(message.send_ref), status=Status.UNCERTAIN).update(
                        status=Status.DONE, last_error="accepted_by_evidence", completed_at=Now(), updated_at=Now())
                    schedule_after_acceptance(message)  # E1 also follows acceptance by evidence
                    event(message.application, "message_accepted_by_evidence",
                          {"send_ref": str(message.send_ref), "evidence_origin": found.origin},
                          actor_ref=f"pending_action:{claim.id}")
                    # Items opened earlier (the poison rule opens one at once) no longer need a decision.
                    for item in StaffItem.objects.filter(approved_message=message, status=StaffItem.Status.OPEN,
                                                         reason_code__in=DECIDABLE):
                        resolve_item(item, code="accepted_by_evidence", actor_ref=f"pending_action:{claim.id}",
                                     effects={"send_ref": str(message.send_ref)},
                                     actor_type=ApplicationEvent.ActorType.SYSTEM)
            elif n < settings.CATALYST_MAIL_RECONCILE_CHECKS:
                enqueue_reconcile(message, series, n + 1)
            else:
                open_item(SEND_OUTCOME_UNKNOWN, str(message.send_ref), application=message.application,
                          approved_message=message, pending_action_id=claim.id)
        ledger.finish(claim, self, status=Status.DONE, write=write)

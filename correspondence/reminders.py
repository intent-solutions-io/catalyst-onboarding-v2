"""Reminder and escalation handlers (016 E2; J-08; P2 task 2B.4). Synthetic only.

Both are automated (a pause holds them) and redeliverable: their whole effect is one fenced database
transaction, so a lost lease rolls it back. Each claim locks the application, then the question, decides,
and records the result with `ledger.finish` in the same transaction:

- the question is `satisfied` or `withdrawn`, or the application is closed: `cancelled`;
- a reply is pending: `held` (E3 queues it again when the question reopens);
- quiet hours or the minimum gap: deferred to an explicit time, the attempt refunded;
- the completed-collection watermark (4.1) is older than the reminder's due time, so a reply may be sitting
  uncollected: deferred, counting toward a bound; at the bound a `collector_stale` staff item opens and the
  reminder keeps waiting;
- otherwise `remind` freezes the reminder's `ApprovedMessage` from the approved `question_reminder` template
  and queues its send (A2, A3), and `escalate_unanswered` opens a "no response" staff item.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Max, Min

from applications.models import TERMINAL_STAGES, Application, ApplicationEvent
from workflow import journal, ledger
from workflow.models import AutomationPause, PendingAction

from .questions import sent_text
from .models import ApprovedMessage, ApprovedMessageQuestion, MailboxCursor, OutboundMessage, Question
from .outbound import _freeze, current_template_version, enqueue_send, verified_address
from .rendering import TemplateRefused, render
from .scheduling import ESCALATE, REMIND
from .staff_items import event, open_item

Status = PendingAction.Status
REMINDER_TEMPLATE = "question_reminder"


def db_now() -> datetime:
    with connection.cursor() as cursor:
        cursor.execute("SELECT now()")
        return cursor.fetchone()[0]


def quiet_until(now: datetime) -> datetime | None:
    """The end of the current quiet period (UTC hours; start == end means none), or None outside it."""
    start, end = settings.CATALYST_REMINDER_QUIET_START_HOUR, settings.CATALYST_REMINDER_QUIET_END_HOUR
    if start == end:
        return None
    hour = now.hour
    inside = start <= hour < end if start < end else (hour >= start or hour < end)
    if not inside:
        return None
    until = now.replace(hour=end, minute=0, second=0, microsecond=0)
    return until if until > now else until + timedelta(days=1)


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str = ""
    due_in: timedelta | None = None
    refund: bool = False
    write: object = None


class _QuestionAction:
    automated = True
    redeliverable = True  # one fenced transaction: nothing external happens in this handler

    def _question_ref(self, claim) -> str:
        return claim.input_ref.split(":", 1)[0]

    def lock_subject(self, claim) -> None:
        """Application, then the question (016 section 5)."""
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            Question.objects.select_for_update(of=("self",)).filter(
                public_id=self._question_ref(claim), application=application).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            # A reminder chain that ends by a defect never ends silently (2B.4 review M4).
            open_item("reminder_failed", claim.input_ref, application=application, pending_action_id=claim.id)

    def run(self, claim) -> None:
        with transaction.atomic():
            self.lock_subject(claim)
            decision = self.decide(claim)
            ledger.finish(claim, self, status=decision.status, error=decision.reason, write=decision.write,
                          due_in=decision.due_in, refund_attempt=decision.refund)

    def _common(self, claim, application, question, mail: bool = True) -> Decision | None:
        """The checks every reminder and escalation makes first."""
        if application is None or question is None:
            return Decision(Status.FAILED, "question_not_found")
        if question.status == Question.Status.SATISFIED:
            return Decision(Status.CANCELLED, "question_satisfied")
        if question.status == Question.Status.WITHDRAWN:
            return Decision(Status.CANCELLED, "question_withdrawn")
        if application.stage in TERMINAL_STAGES:
            return Decision(Status.CANCELLED, "application_closed")
        if question.status == Question.Status.REPLY_PENDING or question.reply_links.filter(state="pending").exists():
            return Decision(Status.HELD, "reply_pending", refund=True)
        if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
            return Decision(Status.QUEUED, "automation_paused", refund=True,
                            due_in=timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS))
        now = db_now()
        due_at = PendingAction.objects.filter(pk=claim.id).values_list("due_at", flat=True).first()
        if mail:  # quiet hours and the minimum gap govern mail to the applicant, not a staff escalation
            quiet = quiet_until(now)
            if quiet is not None:
                return Decision(Status.QUEUED, "quiet_hours", due_in=quiet - now, refund=True)
            # The gap counts every automated message already frozen for this application, sent or still queued,
            # so reminders due together never leave in a burst (2B.4 review H1). The application lock orders them.
            frozen = ApprovedMessage.objects.filter(
                application=application, kind__in=(ApprovedMessage.Kind.QUESTION, ApprovedMessage.Kind.REMINDER),
                disposition__in=(ApprovedMessage.Disposition.ACTIVE, ApprovedMessage.Disposition.ACCEPTED_BY_SERVER,
                                 ApprovedMessage.Disposition.ACCEPTED_BY_EVIDENCE)).aggregate(last=Max("authorized_at"))["last"]
            accepted = OutboundMessage.objects.filter(application=application, server_accepted_at__isnull=False).aggregate(
                last=Max("server_accepted_at"))["last"]
            last = max((t for t in (frozen, accepted) if t is not None), default=None)
            gap = timedelta(seconds=settings.CATALYST_REMINDER_MIN_GAP_SECONDS)
            if last is not None and now - last < gap:
                return Decision(Status.QUEUED, "minimum_gap", due_in=last + gap - now, refund=True)
        cursors = MailboxCursor.objects.all()
        # A cursor that never completed a pass (or is resyncing) makes the watermark stale: SQL MIN ignores NULLs.
        incomplete = cursors.filter(complete_through_at__isnull=True).exists()
        watermark = cursors.aggregate(w=Min("complete_through_at"))["w"]
        if incomplete or watermark is None or watermark < due_at:
            retry = timedelta(seconds=settings.CATALYST_REMINDER_STALE_RETRY_SECONDS)
            if not claim.final:
                return Decision(Status.QUEUED, "watermark_stale", due_in=retry)  # counts toward the bound
            key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first()
            return Decision(Status.QUEUED, "watermark_stale", due_in=retry, refund=True,
                            write=lambda: open_item("collector_stale", key, application=application,
                                                    question_id=question.pk, pending_action_id=claim.id))
        return None


class SendReminder(_QuestionAction):
    kind = REMIND

    def decide(self, claim) -> Decision:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        ref, _, n = claim.input_ref.partition(":")
        question = Question.objects.filter(public_id=ref, application=application).first() if application else None
        if not n.isdigit() or int(n) > settings.CATALYST_REMINDER_MAX:
            return Decision(Status.CANCELLED, "beyond_maximum")
        early = self._common(claim, application, question)
        if early is not None:
            return early
        # A configuration problem (no approved template, no verified address) waits for staff instead of ending
        # the chain: the reminder is deferred, refunded, and one item says why (2B.4 review M5).
        refused = lambda reason: Decision(  # noqa: E731
            Status.QUEUED, reason, refund=True, due_in=timedelta(seconds=settings.CATALYST_REMINDER_STALE_RETRY_SECONDS),
            write=lambda: open_item("reminder_refused", f"remind:{question.public_id}:{n}", application=application,
                                    question_id=question.pk, pending_action_id=claim.id))
        recipient = verified_address(application)
        version = current_template_version(REMINDER_TEMPLATE)
        if recipient is None:
            return refused("contact_not_verified")
        if version is None:
            return refused("no_approved_reminder_template")
        values = {"display_name": application.display_name, "question_text": sent_text(question)}
        try:
            render(version, values)
        except TemplateRefused:
            return refused("reminder_content_refused")
        if version.secret_bearing:
            return refused("secret_bearing_reminder_template")

        def write():
            message = _freeze(application, ApprovedMessage.Kind.REMINDER, recipient, version, values,
                              f"pending_action:{claim.id}", ApprovedMessage.Authority.SYSTEM_POLICY)
            ApprovedMessageQuestion.objects.create(approved_message=message, question=question,
                                                   purpose=ApprovedMessageQuestion.Purpose.REMINDER)
            enqueue_send(message, 0)
            event(application, "reminder_queued", {"question": str(question.public_id), "n": int(n),
                                                   "send_ref": str(message.send_ref)},
                  actor_ref=f"pending_action:{claim.id}")
            # 9kg.33: the reminder's identity at queue time; `send_begun` (outbound) marks when it left. The replay
            # moves the series position on the left entry, and the Sent-folder read attributes the copy by send_ref.
            journal.record("reminder_queued", f"reminder:{question.public_id}:{int(n)}",
                           {"n": int(n), "question": str(question.public_id), "send_ref": str(message.send_ref)})
        return Decision(Status.DONE, write=write)


class EscalateUnanswered(_QuestionAction):
    kind = ESCALATE

    def decide(self, claim) -> Decision:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        question = (Question.objects.filter(public_id=self._question_ref(claim), application=application).first()
                    if application else None)
        early = self._common(claim, application, question, mail=False)
        if early is not None:
            return early

        def write():
            open_item("escalate_unanswered", f"question:{question.public_id}", application=application,
                      question_id=question.pk, pending_action_id=claim.id)
            event(application, "question_unanswered", {"question": str(question.public_id)},
                  actor_type=ApplicationEvent.ActorType.SYSTEM, actor_ref=f"pending_action:{claim.id}")
        return Decision(Status.DONE, write=write)

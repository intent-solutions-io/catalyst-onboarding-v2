"""Reminder scheduling and projection (016 E1, E3, E4; P2 task 2B.4). A leaf module: it writes ledger rows
and imports no other correspondence service, so outbound (E1) and inbound (E3) can call it.

- E1 `schedule_after_acceptance`: in the transaction that records a question message's acceptance, reminder
  1 is created; in the transaction that records reminder n's acceptance, reminder n+1, or after the maximum
  the `escalate_unanswered` action. Unique keys (`remind:<question>:<n>`, `escalate_unanswered:<question>`)
  make creation idempotent. Only E1 creates reminders.
- E3 `sync_reminders`: called with every question-status change, in the same transaction. It acts only on
  that question's reminder and escalation actions that are `queued` or `held`, never revives finished
  actions, never resets counts and never changes the question.
- E4 `reschedule_on_resume`: each queued reminder that fell due during a pause is spread out by rank, so a
  resume never sends a burst.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Greatest, Now

from workflow.models import PendingAction

from .messages import only_duplicate_key
from .models import ApprovedMessage, ApprovedMessageQuestion, Question

Status = PendingAction.Status
REMIND = "remind"
ESCALATE = "escalate_unanswered"
REMINDER_KINDS = (REMIND, ESCALATE)
SEND_MESSAGE = "send_message"  # the outbound kind (named here so this leaf module imports no service)
LIVE = (Status.QUEUED, Status.HELD)
STILL_ASKED = (Question.Status.OPEN, Question.Status.PARTIALLY_ANSWERED, Question.Status.REPLY_PENDING)


def remind_key(question, n: int) -> str:
    return f"remind:{question.public_id}:{n}"


def escalate_key(question) -> str:
    return f"escalate_unanswered:{question.public_id}"


def reminder_actions(question):
    return PendingAction.objects.filter(Q(kind=REMIND, idempotency_key__startswith=f"remind:{question.public_id}:")
                                        | Q(kind=ESCALATE, idempotency_key=escalate_key(question)))


def reminder_number(message: ApprovedMessage, question) -> int:
    """The n of a reminder message: its position among the question's reminder messages."""
    return ApprovedMessageQuestion.objects.filter(question=question, purpose=ApprovedMessageQuestion.Purpose.REMINDER,
                                                  approved_message_id__lte=message.pk).count()


def _create(kind: str, key: str, question, input_ref: str) -> None:
    try:
        with transaction.atomic():
            PendingAction.objects.create(
                kind=kind, subject_type="application", subject_id=question.application.public_ref, input_ref=input_ref,
                idempotency_key=key, due_at=Now() + timedelta(seconds=settings.CATALYST_REMINDER_INTERVAL_SECONDS),
                max_attempts=settings.CATALYST_REMINDER_STALE_DEFERRALS)
    except IntegrityError as exc:
        only_duplicate_key(exc)  # already scheduled: creation is idempotent


def schedule_after_acceptance(message: ApprovedMessage) -> None:
    """E1, inside the transaction that records the acceptance (by the server or by evidence)."""
    if message.kind not in (ApprovedMessage.Kind.QUESTION, ApprovedMessage.Kind.REMINDER):
        return  # a staff message creates no reminder (016 3.4)
    for link in message.question_links.select_related("question__application"):
        question = link.question
        if question.status not in STILL_ASKED:
            continue
        n = reminder_number(message, question) + 1 if message.kind == ApprovedMessage.Kind.REMINDER else 1
        if n <= settings.CATALYST_REMINDER_MAX:
            _create(REMIND, remind_key(question, n), question, f"{question.public_id}:{n}")
        else:
            _create(ESCALATE, escalate_key(question), question, str(question.public_id))
        sync_reminders(question, question.status)  # a reply already pending holds the new action at once


def sync_reminders(question, status: str) -> int:
    """E3: project the question's status onto its live reminder and escalation actions only."""
    actions = reminder_actions(question)
    if status in (Question.Status.OPEN, Question.Status.PARTIALLY_ANSWERED):
        # A reminder released after a reply is never sent at once: no sooner than the resume grace (2B.4 review).
        released = Now() + timedelta(seconds=settings.CATALYST_REMINDER_RESUME_GRACE_SECONDS)
        return actions.filter(status=Status.HELD).update(status=Status.QUEUED, last_error="", updated_at=Now(),
                                                         due_at=Greatest("due_at", released))
    if status == Question.Status.REPLY_PENDING:
        return actions.filter(status=Status.QUEUED).update(status=Status.HELD, last_error="reply_pending", updated_at=Now())
    reason = "question_satisfied" if status == Question.Status.SATISFIED else "question_withdrawn"
    return actions.filter(status__in=LIVE).update(status=Status.CANCELLED, last_error=reason, completed_at=Now(),
                                                  updated_at=Now())


def reschedule_on_resume(application) -> int:
    """E4: queued reminders that fell due during the pause get now + grace + rank x the minimum gap. Held
    reminders, counts and question statuses are untouched; no catch-up copies are made."""
    reminder_refs = [str(r) for r in ApprovedMessage.objects.filter(
        application=application, kind=ApprovedMessage.Kind.REMINDER).values_list("send_ref", flat=True)]
    # Reminders that fell due, and frozen reminder mails whose send waited behind the pause (2B.4 review).
    due = list(PendingAction.objects.select_for_update(of=("self",)).filter(
        Q(kind__in=REMINDER_KINDS) | Q(kind=SEND_MESSAGE, input_ref__in=reminder_refs),
        subject_type="application", subject_id=application.public_ref,
        status=Status.QUEUED, due_at__lte=Now()).order_by("due_at", "id"))
    grace, gap = settings.CATALYST_REMINDER_RESUME_GRACE_SECONDS, settings.CATALYST_REMINDER_MIN_GAP_SECONDS
    rank = 0
    for action in due:
        # Only mail is spread by the gap; an escalation opens a staff item and takes no rank.
        mail = action.kind != ESCALATE
        offset = grace + rank * gap if mail else grace
        PendingAction.objects.filter(pk=action.pk).update(due_at=Now() + timedelta(seconds=offset), updated_at=Now())
        rank += mail
    return len(due)

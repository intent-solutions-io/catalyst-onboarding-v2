"""Monitoring queries (016 section 4 G). Read-only queries over existing tables; alert delivery is P6.
2B.1 builds G3 (sends); later tasks add their signals here, each in the task that creates its tables.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import CharField, Count, Exists, Min, OuterRef
from django.db.models.functions import Cast, Now

from applications.models import TERMINAL_STAGES, ApplicationEvent
from workflow.models import AutomationPause

from workflow.models import PendingAction

from .models import ApprovedMessage, InboundMessage, MailboxCursor, OutboundMessage, Question, QuestionReplyLink, StaffItem
from .scheduling import REMINDER_KINDS
from .common import DECIDABLE

SEND_KINDS = ("send_message", "send_staff_message")

Disposition = ApprovedMessage.Disposition
Attempt = OutboundMessage.Status
# Dispositions that need a staff decision (016 A6, A7).
NEEDS_DECISION = (Disposition.REJECTED_PERMANENT, Disposition.RETRIES_EXHAUSTED, Disposition.TRANSPORT_BLOCKED)


def send_health() -> dict:
    """G3, unresolved signals only, so the report clears once staff have decided: messages by disposition;
    unknown attempts and uncertain sends of messages still active (an abandoned, revised or evidently
    accepted message no longer counts); `sending` attempts older than the lease (a worker died mid-exchange
    and nothing has reconciled yet); held sends; open staff items for sends."""
    lease_ago = Now() - timedelta(seconds=settings.CATALYST_WORKER_LEASE_SECONDS)
    by_disposition = dict(ApprovedMessage.objects.values_list("disposition").annotate(n=Count("id")).order_by())
    p2 = OutboundMessage.objects.filter(approved_message__isnull=False)
    report = {
        "messages_by_disposition": by_disposition,
        "needs_decision": sum(by_disposition.get(d, 0) for d in NEEDS_DECISION),
        "unknown_attempts": p2.filter(status=Attempt.UNKNOWN, approved_message__disposition=Disposition.ACTIVE).count(),
        "stale_sending_attempts": p2.filter(status=Attempt.SENDING, created_at__lt=lease_ago).count(),
        "held_sends": PendingAction.objects.filter(kind__in=SEND_KINDS, status=PendingAction.Status.HELD).count(),
        "uncertain_sends": PendingAction.objects.filter(
            kind__in=SEND_KINDS, status=PendingAction.Status.UNCERTAIN,
            input_ref__in=ApprovedMessage.objects.filter(disposition=Disposition.ACTIVE).annotate(
                ref=Cast("send_ref", CharField())).values("ref"),
        ).count(),
        "open_send_items": StaffItem.objects.filter(status=StaffItem.Status.OPEN, reason_code__in=DECIDABLE).count(),
    }
    report["anomalies"] = sorted(k for k in ("needs_decision", "unknown_attempts", "stale_sending_attempts",
                                             "held_sends", "uncertain_sends", "open_send_items") if report[k])
    return report


def collector_health() -> dict:
    """G1 (2B.2): a stale completed-collection watermark, blocked cursors, a broken chain (an unblocked cursor
    with no queued or running pass), and consecutive failures."""
    stale_before = Now() - timedelta(seconds=settings.CATALYST_MAIL_POLL_SECONDS * settings.CATALYST_MAIL_COLLECTOR_STALE_FACTOR)
    cursors = MailboxCursor.objects.all()
    live = PendingAction.objects.filter(kind="collect", status__in=("queued", "running")).values_list("subject_id", flat=True)
    report = {
        "cursors": cursors.count(),
        "blocked": cursors.filter(state=MailboxCursor.State.BLOCKED).count(),
        "stale_watermark": cursors.exclude(state=MailboxCursor.State.BLOCKED).filter(complete_through_at__lt=stale_before).count()
        + cursors.exclude(state=MailboxCursor.State.BLOCKED).filter(complete_through_at__isnull=True).count(),
        "broken_chain": cursors.exclude(state=MailboxCursor.State.BLOCKED).exclude(public_id__in=live).count(),
        "failing": cursors.filter(consecutive_failures__gt=0).count(),
    }
    report["anomalies"] = sorted(k for k in ("blocked", "stale_watermark", "broken_chain", "failing") if report[k])
    return report


def reply_health() -> dict:
    """G2 and G6 for questions (2B.3): the oldest reply awaiting processing, messages whose identity is
    unestablished, a `reply_pending` question with no pending link, and a pending link whose message is not
    awaiting processing."""
    waiting = InboundMessage.objects.filter(status=InboundMessage.Status.AWAITING_PROCESSING)
    oldest = waiting.order_by("received_at").values_list("received_at", flat=True).first()
    report = {
        "awaiting_processing": waiting.count(),
        "oldest_awaiting_processing": oldest.isoformat() if oldest else None,
        "unestablished_identity": InboundMessage.objects.filter(identity_state="unestablished").count(),
        "reply_pending_without_link": Question.objects.filter(status=Question.Status.REPLY_PENDING).exclude(
            reply_links__state="pending").count(),
        "pending_link_not_awaiting": QuestionReplyLink.objects.filter(state="pending").exclude(
            inbound_message__status=InboundMessage.Status.AWAITING_PROCESSING).count(),
    }
    report["anomalies"] = sorted(k for k in ("reply_pending_without_link", "pending_link_not_awaiting") if report[k])
    return report


def reminder_health() -> dict:
    """G4, G5 and G6 for reminders (2B.4): reminders queued past due by more than the margin (with the oldest
    due time); a question still asked on an open application whose chain has stopped (no live reminder or
    escalation, no message of its chain still in flight, no completed escalation), and, separately, chains that
    ended in a failed action; open staff items by reason with the oldest age; paused applications; a held
    reminder whose question has no pending reply; a queued or held reminder on a withdrawn question."""
    Status = PendingAction.Status
    reminders = PendingAction.objects.filter(kind__in=REMINDER_KINDS)
    margin = Now() - timedelta(seconds=settings.CATALYST_REMINDER_OVERDUE_MARGIN_SECONDS)
    overdue = reminders.filter(status=Status.QUEUED, due_at__lt=margin)
    ref = Cast(OuterRef("public_id"), CharField())
    for_question = lambda qs: qs.filter(input_ref__startswith=ref)  # noqa: E731  ("<question>" or "<question>:<n>")
    in_flight = ApprovedMessage.objects.filter(question_links__question=OuterRef("pk"), disposition=Disposition.ACTIVE)
    asked = Question.objects.filter(
        status__in=(Question.Status.OPEN, Question.Status.PARTIALLY_ANSWERED),
        message_links__approved_message__disposition__in=(Disposition.ACCEPTED_BY_SERVER, Disposition.ACCEPTED_BY_EVIDENCE),
    ).exclude(application__stage__in=TERMINAL_STAGES).annotate(
        live=Exists(for_question(reminders.filter(status__in=(Status.QUEUED, Status.HELD, Status.RUNNING)))),
        failed=Exists(for_question(reminders.filter(status=Status.FAILED))),
        escalated=Exists(for_question(reminders.filter(kind="escalate_unanswered", status=Status.DONE))),
        flying=Exists(in_flight),
    ).filter(live=False, escalated=False, flying=False).distinct()
    open_items = StaffItem.objects.filter(status=StaffItem.Status.OPEN)
    by_reason = {row["reason_code"]: {"count": row["n"], "oldest": row["oldest"].isoformat()}
                 for row in open_items.values("reason_code").annotate(n=Count("id"), oldest=Min("opened_at")).order_by()}
    pauses = AutomationPause.objects.filter(subject_type="application")
    oldest_pause = pauses.order_by("created_at").values_list("created_at", flat=True).first()
    oldest_overdue = overdue.order_by("due_at").values_list("due_at", flat=True).first()
    held_wrong = Question.objects.annotate(
        held=Exists(for_question(reminders.filter(status=Status.HELD))),
        pending=Exists(QuestionReplyLink.objects.filter(question=OuterRef("pk"), state="pending")),
    ).filter(held=True, pending=False)
    on_withdrawn = Question.objects.filter(status=Question.Status.WITHDRAWN).annotate(
        live=Exists(for_question(reminders.filter(status__in=(Status.QUEUED, Status.HELD))))).filter(live=True)
    report = {
        "overdue_reminders": overdue.count(),
        "oldest_overdue": oldest_overdue.isoformat() if oldest_overdue else None,
        "question_without_live_reminder": asked.filter(failed=False).count(),
        "broken_reminder_chain": asked.filter(failed=True).count(),
        "open_items_by_reason": by_reason,
        "paused_applications": pauses.count(),
        "oldest_pause": oldest_pause.isoformat() if oldest_pause else None,
        "held_reminder_not_reply_pending": held_wrong.count(),
        "live_reminder_on_withdrawn_question": on_withdrawn.count(),
    }
    report["anomalies"] = sorted(k for k in ("overdue_reminders", "question_without_live_reminder", "broken_reminder_chain",
                                             "held_reminder_not_reply_pending", "live_reminder_on_withdrawn_question")
                                 if report[k])
    return report


def mail_behaviour_health() -> dict:
    """G7 (2B.4), within the loop window: the most automatic inbound messages one application received;
    automatic messages matched to no application; hard bounces recorded; and inbound growth (messages received)."""
    window = Now() - timedelta(seconds=settings.CATALYST_MAIL_LOOP_WINDOW_SECONDS)
    automatic = InboundMessage.objects.filter(classification="automatic", received_at__gte=window)
    per_app = (automatic.filter(application__isnull=False).values("application").annotate(n=Count("id"))
               .order_by("-n").values_list("n", flat=True).first()) or 0
    report = {
        "max_automatic_per_application": per_app,
        "automatic_unassociated": automatic.filter(application__isnull=True).count(),  # a loop with a stranger
        # Windowed, by the per-application time index of the event table (never a whole-history scan).
        "hard_bounces": ApplicationEvent.objects.filter(kind="bounce_recorded", occurred_at__gte=window, data__hard=True).count(),
        "inbound_received_in_window": InboundMessage.objects.filter(received_at__gte=window).count(),
    }
    report["anomalies"] = ["automatic_mail_at_loop_threshold"] if per_app >= settings.CATALYST_MAIL_LOOP_THRESHOLD else []
    return report

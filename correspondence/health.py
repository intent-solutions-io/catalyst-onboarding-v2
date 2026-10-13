"""Monitoring queries (016 section 4 G). Read-only queries over existing tables; alert delivery is P6.
2B.1 builds G3 (sends); later tasks add their signals here, each in the task that creates its tables.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import CharField, Count
from django.db.models.functions import Cast, Now

from workflow.models import PendingAction

from .models import ApprovedMessage, InboundMessage, MailboxCursor, OutboundMessage, Question, QuestionReplyLink, StaffItem
from .outbound import DECIDABLE

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
        "held_sends": PendingAction.objects.filter(kind="send_message", status=PendingAction.Status.HELD).count(),
        "uncertain_sends": PendingAction.objects.filter(
            kind="send_message", status=PendingAction.Status.UNCERTAIN,
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

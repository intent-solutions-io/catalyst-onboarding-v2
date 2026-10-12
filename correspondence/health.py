"""Monitoring queries (016 section 4 G). Read-only queries over existing tables; alert delivery is P6.
2B.1 builds G3 (sends); later tasks add their signals here, each in the task that creates its tables.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.db.models.functions import Now

from workflow.models import PendingAction

from .models import ApprovedMessage, OutboundMessage

Disposition = ApprovedMessage.Disposition
Attempt = OutboundMessage.Status
# Dispositions that need a staff decision (016 A6, A7).
NEEDS_DECISION = (Disposition.REJECTED_PERMANENT, Disposition.RETRIES_EXHAUSTED, Disposition.TRANSPORT_BLOCKED)


def send_health() -> dict:
    """G3: messages by disposition; unknown attempts; `sending` attempts older than the lease (a worker died
    mid-exchange and nothing has reconciled yet); held and uncertain send actions."""
    lease_ago = Now() - timedelta(seconds=settings.CATALYST_WORKER_LEASE_SECONDS)
    by_disposition = dict(ApprovedMessage.objects.values_list("disposition").annotate(n=Count("id")).order_by())
    p2 = OutboundMessage.objects.filter(approved_message__isnull=False)
    report = {
        "messages_by_disposition": by_disposition,
        "needs_decision": sum(by_disposition.get(d, 0) for d in NEEDS_DECISION),
        "unknown_attempts": p2.filter(status=Attempt.UNKNOWN).count(),
        "stale_sending_attempts": p2.filter(status=Attempt.SENDING, created_at__lt=lease_ago).count(),
        "held_sends": PendingAction.objects.filter(kind="send_message", status=PendingAction.Status.HELD).count(),
        "uncertain_sends": PendingAction.objects.filter(kind="send_message", status=PendingAction.Status.UNCERTAIN).count(),
    }
    report["anomalies"] = sorted(k for k in ("needs_decision", "unknown_attempts", "stale_sending_attempts",
                                             "held_sends", "uncertain_sends") if report[k])
    return report

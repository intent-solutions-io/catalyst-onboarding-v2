"""Catalyst-wide health signals (026 section 7; 6B.4), read-only, counts and signal names only.

Each part reports counts and an `anomalies` list. The `catalyst_health` command prints them as JSON and exits 1 when
any part has an anomaly, so a host timer can alert through the estate alert floor. The thresholds are placeholders
until POL-16 (P6-D-9). No applicant name, address, token or message text is ever part of a report.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Min
from django.db.models.functions import Now
from django.utils import timezone

from workflow import heartbeat
from workflow.models import PendingAction


def worker_health() -> dict:
    path = settings.CATALYST_WORKER_HEARTBEAT_FILE
    if not path:
        return {"configured": False, "age_seconds": None, "anomalies": []}
    age = heartbeat.age_seconds(path)
    stale = age is None or age > settings.CATALYST_HEALTH_HEARTBEAT_STALE_SECONDS
    return {"configured": True, "age_seconds": None if age is None else int(age),
            "anomalies": ["heartbeat_missing" if age is None else "heartbeat_stale"] if stale else []}


def queue_health() -> dict:
    """The oldest action that is due and still queued (moved here from readiness, 6B.3), and running actions whose
    lease ran out long ago (a worker that died mid-action without recovery)."""
    now = timezone.now()
    oldest = PendingAction.objects.filter(status=PendingAction.Status.QUEUED, due_at__lte=Now()).aggregate(m=Min("due_at"))["m"]
    age = int((now - oldest).total_seconds()) if oldest else 0
    expired = PendingAction.objects.filter(
        status=PendingAction.Status.RUNNING,
        lease_expires_at__lt=now - timedelta(seconds=settings.CATALYST_WORKER_LEASE_SECONDS)).count()
    anomalies = []
    if age > settings.CATALYST_HEALTH_PENDING_AGE_SECONDS:
        anomalies.append("backlog")
    if expired:
        anomalies.append("expired_leases")
    return {"oldest_due_seconds": age, "expired_leases": expired, "anomalies": anomalies}


AGREEMENT_UNCERTAIN = ("create_uncertain", "distribute_uncertain", "cancel_uncertain")


def agreement_health() -> dict:
    from agreements.models import AgreementInstance

    live = AgreementInstance.objects.filter(replaced_at__isnull=True)
    uncertain = live.filter(issue_status__in=AGREEMENT_UNCERTAIN).count()
    failed = live.filter(issue_status="failed_needs_staff").count()
    custody_failed = live.filter(custody_status="failed_needs_staff").count()
    anomalies = [name for name, count in (("agreements_uncertain", uncertain), ("agreements_failed", failed),
                                          ("custody_failed", custody_failed)) if count]
    return {"uncertain": uncertain, "failed": failed, "custody_failed": custody_failed, "anomalies": anomalies}


# In-flight states only: an outcome the system is still settling. Terminal states (a conflict, a failure, a mailbox
# recovered after a stop) are not counted here: staff see them as open provisioning items, which close when staff
# resolve them, so the alert clears too (PR #64 review).
PROVISIONING_IN_FLIGHT = ("create_uncertain", "verify_uncertain", "found_by_evidence")


def provisioning_health() -> dict:
    from correspondence.models import StaffItem
    from provisioning.models import AccessRevocation, ProvisioningRequest

    settling = ProvisioningRequest.objects.filter(status__in=PROVISIONING_IN_FLIGHT).count()
    items = StaffItem.objects.filter(status=StaffItem.Status.OPEN, reason_code__startswith="provisioning_").count()
    # A revocation round that never ran: an obligation still "requested" long after it was created. ("pending" and
    # "unsupported" rows keep a staff item open, counted above; "applied_unverified" is final by design, 023 11.6.)
    stalled_cutoff = timezone.now() - timedelta(seconds=settings.CATALYST_HEALTH_PENDING_AGE_SECONDS)
    stalled = AccessRevocation.objects.filter(state="requested", created_at__lt=stalled_cutoff).count()
    anomalies = [name for name, count in (("provisioning_settling", settling), ("provisioning_items_open", items),
                                          ("revocation_stalled", stalled)) if count]
    return {"requests_settling": settling, "items_open": items, "revocations_stalled": stalled, "anomalies": anomalies}


def bounce_health() -> dict:
    """Hard bounces left unresolved past the target: every send to that applicant is blocked meanwhile (9kg.3)."""
    from correspondence.models import StaffItem

    cutoff = timezone.now() - timedelta(seconds=settings.CATALYST_HEALTH_HARD_BOUNCE_AGE_SECONDS)
    aged = StaffItem.objects.filter(reason_code="hard_bounce", status=StaffItem.Status.OPEN, opened_at__lt=cutoff).count()
    return {"aged_hard_bounces": aged, "anomalies": ["hard_bounce_unresolved"] if aged else []}


def report() -> dict:
    from correspondence.health import collector_health, mail_behaviour_health, reminder_health, reply_health, send_health

    return {"worker": worker_health(), "queue": queue_health(), "agreements": agreement_health(),
            "provisioning": provisioning_health(), "bounces": bounce_health(), "sends": send_health(),
            "collector": collector_health(), "replies": reply_health(), "reminders": reminder_health(),
            "mail": mail_behaviour_health()}

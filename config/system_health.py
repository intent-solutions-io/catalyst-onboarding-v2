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


PROVISIONING_ATTENTION = ("create_uncertain", "verify_uncertain", "found_by_evidence", "failed_needs_staff", "conflict",
                          "recovered_after_stop")
SETUP_ATTENTION = ("invitation_uncertain", "invitation_failed", "set_uncertain")


def provisioning_health() -> dict:
    from provisioning.models import AccessRevocation, CredentialSetup, ProvisioningRequest

    requests = ProvisioningRequest.objects.filter(status__in=PROVISIONING_ATTENTION).count()
    setups = CredentialSetup.objects.filter(state__in=SETUP_ATTENTION).count()
    revocations = AccessRevocation.objects.filter(state__in=("pending", "unsupported")).count()
    anomalies = [name for name, count in (("provisioning_needs_attention", requests), ("credential_setup_uncertain", setups),
                                          ("revocation_open", revocations)) if count]
    return {"requests_needing_attention": requests, "setups_uncertain": setups, "revocations_open": revocations,
            "anomalies": anomalies}


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

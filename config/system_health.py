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


# Items that mean something went wrong alert at once; items that are ordinary waiting for staff (a checklist to carry
# out, a name to review, a prerequisite to fix) alert only once they are older than the backlog target (PR #64 re-check).
PROVISIONING_PROBLEM_ITEMS = ("provisioning_conflict", "provisioning_failed", "provisioning_late_mailbox",
                              "provisioning_confirm_found", "provisioning_revocation_needs_staff",
                              "provisioning_setup_needs_staff", "provisioning_activation_blocked",
                              "provisioning_withdrawal_link_failed")
PROVISIONING_ROUTINE_ITEMS = ("provisioning_checklist", "provisioning_name_needs_review", "provisioning_blocked")


def provisioning_health() -> dict:
    from correspondence.models import StaffItem
    from provisioning.models import AccessRevocation, ProvisioningRequest

    cutoff = timezone.now() - timedelta(seconds=settings.CATALYST_HEALTH_PENDING_AGE_SECONDS)
    settling = ProvisioningRequest.objects.filter(status__in=PROVISIONING_IN_FLIGHT).count()
    open_items = StaffItem.objects.filter(status=StaffItem.Status.OPEN)
    problems = open_items.filter(reason_code__in=PROVISIONING_PROBLEM_ITEMS).count()
    waiting = open_items.filter(reason_code__in=PROVISIONING_ROUTINE_ITEMS, opened_at__lt=cutoff).count()
    # A revocation round that never ran: an obligation still "requested" long after it was created. ("pending" and
    # "unsupported" rows keep a revocation staff item open, counted above; "applied_unverified" is final, 023 11.6.)
    stalled = AccessRevocation.objects.filter(state="requested", created_at__lt=cutoff).count()
    anomalies = [name for name, count in (("provisioning_settling", settling), ("provisioning_problem", problems),
                                          ("provisioning_waiting_too_long", waiting),
                                          ("revocation_stalled", stalled)) if count]
    return {"requests_settling": settling, "problem_items": problems, "routine_items_overdue": waiting,
            "revocations_stalled": stalled, "anomalies": anomalies}


def bounce_health() -> dict:
    """Hard bounces left unresolved past the target: every send to that applicant is blocked meanwhile (9kg.3)."""
    from correspondence.models import StaffItem

    cutoff = timezone.now() - timedelta(seconds=settings.CATALYST_HEALTH_HARD_BOUNCE_AGE_SECONDS)
    aged = StaffItem.objects.filter(reason_code="hard_bounce", status=StaffItem.Status.OPEN, opened_at__lt=cutoff).count()
    return {"aged_hard_bounces": aged, "anomalies": ["hard_bounce_unresolved"] if aged else []}


def session_health() -> dict:
    """Outside the local environments the hourly removal of expired staff sessions must be scheduled (6B.9)."""
    from accounts.staff_access import CLEAR_SESSIONS

    scheduled = PendingAction.objects.filter(kind=CLEAR_SESSIONS, status__in=(PendingAction.Status.QUEUED,
                                                                              PendingAction.Status.RUNNING)).exists()
    required = settings.CATALYST_STAFF_TWO_FACTOR
    return {"cleanup_scheduled": scheduled, "anomalies": ["session_cleanup_unscheduled"] if required and not scheduled else []}


def journal_health() -> dict:
    """9kg.33 (PR #89 review): the effect journal is readable and chained, its directory private and writable, and
    no append has failed; a torn tail names the owner's repair."""
    from workflow import journal

    if not journal.configured():
        return {"configured": False, "append_failures": 0, "anomalies": []}
    anomalies = []
    problem = journal.directory_problem(write=True)
    if problem:
        anomalies.append(f"effect_journal_{problem}")
    try:
        journal.read()
    except journal.JournalError as exc:
        anomalies.append(f"effect_journal_{exc.code}")
    failed = journal.failures()
    if failed:
        anomalies.append("effect_journal_append_failed")
    return {"configured": True, "append_failures": failed, "anomalies": anomalies}


def intake_health() -> dict:
    """9kg.43 and 9kg.29: the launch mode and the client-identity source the limits key on, as configured in code, and
    the number of live invitations (a count, never an address). No anomaly: the mode is the owner's recorded act."""
    from applications.invitations import LIVE
    from applications.models import Invitation

    return {"mode": settings.CATALYST_INTAKE_MODE, "client_identity": settings.CATALYST_CLIENT_IDENTITY,
            "live_invitations": Invitation.objects.filter(LIVE).count(), "anomalies": []}


def report() -> dict:
    from correspondence.health import collector_health, mail_behaviour_health, reminder_health, reply_health, send_health

    return {"worker": worker_health(), "queue": queue_health(), "agreements": agreement_health(),
            "provisioning": provisioning_health(), "bounces": bounce_health(), "sends": send_health(),
            "collector": collector_health(), "replies": reply_health(), "reminders": reminder_health(),
            "mail": mail_behaviour_health(), "sessions": session_health(), "journal": journal_health(),
            "intake": intake_health()}

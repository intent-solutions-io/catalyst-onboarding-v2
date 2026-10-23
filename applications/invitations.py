"""Invitation-only intake (9kg.43; 029 sections 4.1 and 7; REQ-003, REQ-027, POL-01).

While CATALYST_INTAKE_MODE is "invitation" (fixed in code, the shipped default; config.guards), the public form accepts
only an address holding a live invitation: one issued by the owner-run `catalyst_invite`, unused, not superseded and
unexpired by the database clock. The check runs inside the intake transaction (`admits`): an uninvited submission does
every write the invited one does and is then rolled back, so the applicant's response and its timing are those of an
accepted submission and nothing is recorded. Unknown, expired, used, superseded and wrong-address cases are one case.

The invitation is consumed at confirmation (`consume`), inside the confirmation transaction after the application and
challenge locks, by one conditional update: the first confirmation spends it, a concurrent second one finds nothing to
spend. Acceptance never consumes it, so an unconfirmed submission does not burn the invitation and a resend keeps
working. Once consumed, the invitation names the application, and that application's later submissions stay admitted.

With the mode "open" nothing here runs and the intake is the S1 intake unchanged.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Now

from .identity import email_key
from .models import Invitation

LIVE = Q(used_at__isnull=True, superseded_at__isnull=True, expires_at__gt=Now())


def required() -> bool:
    return settings.CATALYST_INTAKE_MODE == "invitation"


def admits(key: str, application) -> bool:
    """Inside the intake transaction: a live invitation for the key, or the one this application already consumed."""
    return Invitation.objects.filter(Q(email_key=key) & (LIVE | Q(application=application))).exists()


def consume(application) -> bool:
    """Inside the confirmation transaction, after the application and challenge locks: spend the live invitation for
    the application's key. False when there is none to spend."""
    return bool(Invitation.objects.filter(LIVE, email_key=application.email_key)
                .update(used_at=Now(), application=application, updated_at=Now()))


def issue(email: str, issued_by: str, lifetime: timedelta, note: str = "") -> tuple[Invitation, int]:
    """Owner path only (the application role may not insert). Supersedes the live invitation for the address, if any,
    and issues a new one. Returns it and how many were superseded (0 or 1)."""
    key = email_key(email)
    with transaction.atomic():
        superseded = Invitation.objects.filter(email_key=key, used_at__isnull=True, superseded_at__isnull=True).update(
            superseded_at=Now(), updated_at=Now())
        invitation = Invitation.objects.create(email_key=key, issued_by=issued_by, note=note, expires_at=Now() + lifetime)
        invitation.refresh_from_db()  # the database clock's values, not the expressions
    return invitation, superseded


def state(invitation) -> str:
    if invitation.used_at is not None:
        return "used"
    if invitation.superseded_at is not None:
        return "superseded"
    return "live" if invitation.unexpired else "expired"


def describe(application) -> str:
    """One line for the staff dossier: the mode, and this applicant's invitation if the mode needs one."""
    if not required():
        return "open intake: no invitation required"
    invitations = Invitation.objects.annotate(unexpired=Q(expires_at__gt=Now()))  # database clock
    used = invitations.filter(application=application).order_by("-used_at").first()
    if used is not None:
        return f"invitation-only: invitation used at {used.used_at:%Y-%m-%d %H:%M:%S} UTC (issued by {used.issued_by})"
    live = invitations.filter(LIVE, email_key=application.email_key).first()
    if live is not None:
        return (f"invitation-only: live invitation until {live.expires_at:%Y-%m-%d %H:%M:%S} UTC (issued by {live.issued_by});"
                " it is spent when the applicant confirms")
    return "invitation-only: no live invitation for this address; a confirmation would be refused"

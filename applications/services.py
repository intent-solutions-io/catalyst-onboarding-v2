"""Intake service (005 S1.2, S1.4; J-01, J-02): one public submission, one transaction.

`accept_submission` writes, in a single `transaction.atomic()`: the application (or locks the open one
for this email key), the next submission version, its history event, and, while contact is unverified,
the verification challenge and its queued "send verification" action. Nothing is sent here (S1-T5).

Rules it keeps:
- Lock order is application, then challenge. A version number is read from the locked application's
  counter and the counter is advanced with QuerySet.update; no full-row save, because the application
  role may update only permitted columns (ADR-14).
- A concurrent first submission for the same key loses on the partial unique index; only that named
  constraint is caught (inside a savepoint), and the open application is then re-read under lock. Any
  other integrity error propagates.
- Once contact is verified, a repeat is recorded as a `repeat_after_verification` version with a
  `needs_staff_attention` event; verified data, other versions and any adoption are never touched, and
  no challenge or send is created (POL-01 PROPOSED default).
- While unverified, an active, unexpired challenge whose send is queued, running or done is reused;
  otherwise the active challenge (if any) is superseded and a new challenge and send action are created. Expiry is
  compared with the database clock.

Failure guarantee: acceptance is atomic, so the records above commit together or not at all. A
DatabaseError raised before the commit means nothing was committed. A connection lost at the commit
itself leaves the caller unable to tell whether it committed (PostgreSQL reports the outcome only over
that connection); a resubmission is then handled by the duplicate rules above (one application, a new
version, no extra challenge or send while the existing one is reusable).
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.functions import Now

from workflow.models import PendingAction

from .identity import email_key
from .models import OPEN_STAGES, Application, ApplicationEvent, ContactChallenge, SubmissionVersion

OPEN_KEY_CONSTRAINT = "application_one_open_per_email_key"
SEND_VERIFICATION = "send_verification"


@dataclass(frozen=True)
class Outcome:
    application_ref: UUID
    version_number: int
    new_application: bool
    new_challenge: bool
    needs_staff_attention: bool


def _before_insert(key: str) -> None:
    """Test seam (TEST-S1-04): called after the open-application read found nothing, before the insert.
    A no-op in the application."""


def send_verification_key(challenge_public_id) -> str:
    return f"{SEND_VERIFICATION}:{challenge_public_id}"


def _open_application(key):
    return Application.objects.select_for_update(of=("self",)).filter(email_key=key, stage__in=OPEN_STAGES).first()


def _constraint_name(exc: IntegrityError):
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None)


def _lock_or_create_application(email, key, name):
    application = _open_application(key)
    if application is not None:
        return application, False
    _before_insert(key)
    try:
        with transaction.atomic():  # savepoint: the losing side of a race recovers inside the transaction
            return Application.objects.create(email=email, email_key=key, display_name=name), True
    except IntegrityError as exc:
        if _constraint_name(exc) != OPEN_KEY_CONSTRAINT:
            raise
    application = _open_application(key)
    if application is None:  # the winner's application closed between its commit and our read
        raise IntegrityError(f"open application for the key vanished after {OPEN_KEY_CONSTRAINT}")
    return application, False


def _next_version_number(application) -> int:
    number = application.next_version_number  # read under the row lock
    Application.objects.filter(pk=application.pk).update(next_version_number=F("next_version_number") + 1, updated_at=Now())
    return number


REUSABLE_SEND_STATUSES = (PendingAction.Status.QUEUED, PendingAction.Status.RUNNING, PendingAction.Status.DONE)


def _reusable(challenge) -> bool:
    """005 S1.2: reuse only an unexpired challenge whose send is queued, running or done. Anything else
    (failed, uncertain, held, cancelled, or no send at all) is superseded and reissued."""
    if not challenge.unexpired:
        return False
    return PendingAction.objects.filter(
        idempotency_key=send_verification_key(challenge.public_id), status__in=REUSABLE_SEND_STATUSES
    ).exists()


def _issue_challenge(application) -> bool:
    """Reuse the active challenge or supersede it and queue a new one. Returns True if one was issued."""
    active = (
        ContactChallenge.objects.select_for_update(of=("self",))
        .filter(application=application, used_at__isnull=True, superseded_at__isnull=True)
        .annotate(unexpired=Q(expires_at__gt=Now()))
        .first()
    )
    if active is not None:
        if _reusable(active):
            return False
        ContactChallenge.objects.filter(pk=active.pk).update(superseded_at=Now())
    lifetime = timedelta(seconds=settings.CATALYST_CHALLENGE_LIFETIME_SECONDS)
    challenge = ContactChallenge.objects.create(
        application=application, email_at_issue=application.email, expires_at=Now() + lifetime
    )
    PendingAction.objects.create(
        kind=SEND_VERIFICATION,
        subject_type="application",
        subject_id=application.public_ref,
        input_ref=str(challenge.public_id),
        idempotency_key=send_verification_key(challenge.public_id),
        status=PendingAction.Status.QUEUED,
    )
    return True


def accept_submission(data) -> Outcome:
    """`data` is AccessRequestForm.cleaned_data. Raises DatabaseError on a database failure: before the
    commit nothing is committed; at the commit the outcome is unknown (module docstring)."""
    email = data["email"]  # EmailField has already trimmed it
    key = email_key(email)
    fields = {"name": data["name"], "email": email, "reason": data["reason"]}
    with transaction.atomic():
        application, new_application = _lock_or_create_application(email, key, data["name"])
        number = _next_version_number(application)
        verified = application.contact_verified_at is not None
        origin = SubmissionVersion.Origin.REPEAT_AFTER_VERIFICATION if verified else SubmissionVersion.Origin.FORM
        SubmissionVersion.objects.create(application=application, version_number=number, origin=origin, submitted_fields=fields)
        new_challenge = False if verified else _issue_challenge(application)
        event = dict(application=application, actor_type=ApplicationEvent.ActorType.APPLICANT, data={"version_number": number})
        ApplicationEvent.objects.create(kind="submission_received" if new_application else "repeat_submission", **event)
        if verified:
            ApplicationEvent.objects.create(
                kind="needs_staff_attention", **{**event, "data": {"version_number": number, "reason": "repeat_after_verification"}}
            )
    return Outcome(application.public_ref, number, new_application, new_challenge, verified)

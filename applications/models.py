"""Applicant dossier models for the first slice (005 S1.4). Fields and constraints only: stage changes,
version allocation and adoption happen in services (S1-T4 onward), never here.

Protected history (ADR-14, D-17, D-22): SubmissionVersion and ApplicationEvent are append-only for the
application role, enforced by database privileges and a trigger (migration 0002). VersionAdoption is
append-only for every role, with no retention exception (migration 0003). RetentionAudit is written only
by the 0002 trigger and never changed. Stated limitation: the migration owner can alter these
protections and a superuser bypasses them; they are not administrator-proof.
"""

import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

# Journey stages (004 section 2). "Open" means any non-terminal stage, including `active`.
OPEN_STAGES = (
    "submitted", "contact_verified", "evidence", "assessing", "awaiting_answers", "awaiting_decision",
    "on_hold", "admitted", "agreements", "agreements_complete", "provisioning", "active",
)
TERMINAL_STAGES = ("declined", "withdrawn", "closed")


class Stage(models.TextChoices):
    SUBMITTED = "submitted"
    CONTACT_VERIFIED = "contact_verified"
    EVIDENCE = "evidence"
    ASSESSING = "assessing"
    AWAITING_ANSWERS = "awaiting_answers"
    AWAITING_DECISION = "awaiting_decision"
    ON_HOLD = "on_hold"
    ADMITTED = "admitted"
    AGREEMENTS = "agreements"
    AGREEMENTS_COMPLETE = "agreements_complete"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class Application(models.Model):
    public_ref = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.CharField(max_length=320)  # as typed; used for sending
    email_key = models.CharField(max_length=320)  # normalized identity key (005 S1.3)
    display_name = models.CharField(max_length=200)
    stage = models.CharField(max_length=32, choices=Stage.choices, default=Stage.SUBMITTED)
    contact_verified_at = models.DateTimeField(null=True, blank=True)
    next_version_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["email_key"], condition=Q(stage__in=OPEN_STAGES), name="application_one_open_per_email_key"
            ),
            models.CheckConstraint(condition=Q(stage__in=OPEN_STAGES + TERMINAL_STAGES), name="application_stage_valid"),
            models.CheckConstraint(condition=Q(next_version_number__gte=1), name="application_next_version_positive"),
        ]


class SubmissionVersion(models.Model):
    class Origin(models.TextChoices):
        FORM = "form"
        REPEAT_AFTER_VERIFICATION = "repeat_after_verification"

    application = models.ForeignKey(Application, on_delete=models.PROTECT, related_name="versions")
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    version_number = models.PositiveIntegerField()
    origin = models.CharField(max_length=32, choices=Origin.choices)
    submitted_fields = models.JSONField()
    received_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["application", "version_number"], name="version_number_unique_per_application"),
            models.CheckConstraint(condition=Q(version_number__gte=1), name="version_number_positive"),
            models.CheckConstraint(condition=Q(origin__in=["form", "repeat_after_verification"]), name="version_origin_valid"),
            # Target of the composite foreign key from VersionAdoption (same application).
            models.UniqueConstraint(fields=["id", "application"], name="version_id_application_unique"),
        ]


class ContactChallenge(models.Model):
    application = models.ForeignKey(Application, on_delete=models.PROTECT, related_name="challenges")
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email_at_issue = models.CharField(max_length=320)
    created_at = models.DateTimeField(db_default=Now())
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # "Active" = not used and not superseded; expiry is a time comparison and is not encoded here.
            models.UniqueConstraint(
                fields=["application"],
                condition=Q(used_at__isnull=True, superseded_at__isnull=True),
                name="challenge_one_active_per_application",
            ),
            models.CheckConstraint(condition=Q(expires_at__gt=models.F("created_at")), name="challenge_expires_after_creation"),
            # Target of the composite foreign key from VersionAdoption (same application).
            models.UniqueConstraint(fields=["id", "application"], name="challenge_id_application_unique"),
        ]


class VersionAdoption(models.Model):
    """The verified address owner explicitly confirmed this version (005 S1.2; REQ-033).

    Protected history (D-22): no role may update, delete or truncate it (migration 0003); there is no
    retention path for adoptions until POL-10 decides one for the connected records."""

    application = models.ForeignKey(Application, on_delete=models.PROTECT, related_name="adoptions")
    submission_version = models.OneToOneField(SubmissionVersion, on_delete=models.PROTECT, related_name="adoption")
    via_challenge = models.ForeignKey(ContactChallenge, on_delete=models.PROTECT, related_name="adoptions")
    adopted_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            # S1: at most one adoption per application.
            models.UniqueConstraint(fields=["application"], name="adoption_one_per_application"),
        ]
        # The adopted version and the challenge must belong to this same application: composite foreign
        # keys added by migration 0001 (Django has no composite foreign key field).


class ApplicationEvent(models.Model):
    class ActorType(models.TextChoices):
        SYSTEM = "system"
        APPLICANT = "applicant"
        STAFF = "staff"

    application = models.ForeignKey(Application, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=64)
    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    actor_ref = models.CharField(max_length=200, blank=True, default="")
    occurred_at = models.DateTimeField(db_default=Now())
    data = models.JSONField(default=dict)  # never secrets or tokens

    class Meta:
        indexes = [
            models.Index(fields=["application", "occurred_at"], name="event_application_time"),
            models.Index(fields=["application"], condition=Q(kind="needs_staff_attention"), name="event_staff_attention"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(actor_type__in=["system", "applicant", "staff"]), name="event_actor_type_valid"),
        ]


class RetentionAudit(models.Model):
    """One row per audited retention delete; inserted only by the protection trigger (migration 0002).
    Records which application's record was removed and a SHA-256 digest of the deleted row, never its content."""

    at = models.DateTimeField(db_default=Now())
    actor = models.CharField(max_length=128)
    table_name = models.CharField(max_length=128)
    row_id = models.BigIntegerField()
    application_id = models.BigIntegerField()
    row_sha256 = models.CharField(max_length=64)
    reason = models.TextField()

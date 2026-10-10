"""The pending-action ledger (ADR-03, D-16; 005 S1.4). Subject-generic: no foreign key to any domain
model, so `workflow` depends on no domain app. Claiming, fencing and the worker arrive in S1-T5."""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

STATUSES = ("queued", "running", "done", "failed", "uncertain", "held", "cancelled")


class PendingAction(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        DONE = "done"
        FAILED = "failed"
        UNCERTAIN = "uncertain"  # kept for provider reconciliation (ADR-15, D-20)
        HELD = "held"
        CANCELLED = "cancelled"

    kind = models.CharField(max_length=64)
    subject_type = models.CharField(max_length=64)
    subject_id = models.UUIDField()
    input_ref = models.CharField(max_length=200, blank=True, default="")
    idempotency_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    due_at = models.DateTimeField(db_default=Now())
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")  # sanitized; never secrets or tokens
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "due_at"], name="pending_action_status_due")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=STATUSES), name="pending_action_status_valid"),
            models.CheckConstraint(condition=Q(max_attempts__gte=1), name="pending_action_max_attempts_positive"),
            models.CheckConstraint(condition=Q(attempts__lte=models.F("max_attempts")), name="pending_action_attempts_bounded"),
            models.CheckConstraint(
                condition=~Q(status="running") | Q(lease_token__isnull=False, lease_expires_at__isnull=False),
                name="pending_action_running_has_lease",
            ),
        ]


class AutomationPause(models.Model):
    subject_type = models.CharField(max_length=64)
    subject_id = models.UUIDField()
    reason = models.TextField()
    actor_ref = models.CharField(max_length=200)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["subject_type", "subject_id"], name="pause_one_per_subject"),
        ]

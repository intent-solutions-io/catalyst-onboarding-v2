"""Outbound message record (005 S1.4). Sending arrives in S1-T5; only the record and its uniqueness here."""

from django.db import models
from django.db.models import Q


class OutboundMessage(models.Model):
    class Status(models.TextChoices):
        RENDERED = "rendered"
        ACCEPTED = "accepted"  # accepted by the mail backend; not proof of delivery
        FAILED = "failed"

    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="outbound_messages")
    pending_action = models.ForeignKey("workflow.PendingAction", on_delete=models.PROTECT, related_name="outbound_messages")
    attempt_number = models.PositiveIntegerField()
    template_key = models.CharField(max_length=64)
    template_version = models.CharField(max_length=32)
    recipient = models.CharField(max_length=320)
    message_id = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["pending_action", "attempt_number"], name="outbound_unique_per_attempt"),
            models.CheckConstraint(condition=Q(attempt_number__gte=1), name="outbound_attempt_positive"),
            models.CheckConstraint(condition=Q(status__in=["rendered", "accepted", "failed"]), name="outbound_status_valid"),
        ]

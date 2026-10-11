"""Pending actions and pauses in Django Admin, read-only (S1-T7). Subject-generic like the ledger: the
subject is shown by type and id, and the applicant dossier lists each application's actions. Inputs,
idempotency keys and lease tokens are not shown: for verification sends they name the challenge (D-24)."""

from django.contrib import admin

from config.staff_admin import ReadOnlyModelAdmin

from .models import AutomationPause, PendingAction


@admin.register(PendingAction)
class PendingActionAdmin(ReadOnlyModelAdmin):
    list_display = ("kind", "status", "subject_type", "subject_id", "attempts", "max_attempts", "due_at", "updated_at")
    list_filter = ("status", "kind")
    ordering = ("-created_at", "-id")
    fields = ("kind", "status", "subject_type", "subject_id", "attempts", "max_attempts", "due_at",
              "lease_expires_at", "last_error", "created_at", "updated_at", "completed_at")
    readonly_fields = fields


@admin.register(AutomationPause)
class AutomationPauseAdmin(ReadOnlyModelAdmin):
    list_display = ("subject_type", "subject_id", "actor_ref", "created_at")
    fields = ("subject_type", "subject_id", "reason", "actor_ref", "created_at")
    readonly_fields = fields

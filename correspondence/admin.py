"""Outbound messages in Django Admin, read-only (S1-T7). One row per send attempt; message bodies (which
carry the link) are never stored, so none can be shown. `accepted` means the local sink took it."""

from django.contrib import admin

from config.staff_admin import ReadOnlyModelAdmin

from .models import OutboundMessage


@admin.register(OutboundMessage)
class OutboundMessageAdmin(ReadOnlyModelAdmin):
    list_display = ("application", "attempt_number", "template_key", "status", "sent_at")
    list_filter = ("status", "template_key")
    ordering = ("-id",)
    fields = ("application", "attempt_number", "template_key", "template_version", "recipient", "message_id", "status", "sent_at")
    readonly_fields = fields

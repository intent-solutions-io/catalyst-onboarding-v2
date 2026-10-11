"""The applicant dossier in Django Admin (005 S1.2 Staff; S1-T7, D-23, D-24): read-only for everyone.

One change page per application shows its status, contact state, the adopted version, open staff-attention
items, the next responsible party, outstanding work, and, as related records, every submission version
(adopted or unverified), the challenges (state and times only), the history and the outbound messages.
Never shown: challenge public ids, tokens or links, pending-action inputs, idempotency keys or lease
tokens, message bodies (not stored) and retention audit rows.
"""

from django.apps import apps
from django.contrib import admin
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Now
from django.utils.html import format_html, format_html_join

from config.staff_admin import ReadOnlyModelAdmin, ReadOnlyTabularInline

from . import staff
from .models import Application, ApplicationEvent, ContactChallenge, SubmissionVersion, VersionAdoption


class NeedsAttentionFilter(admin.SimpleListFilter):
    title = "staff attention"
    parameter_name = "attention"

    def lookups(self, request, model_admin):
        return [("yes", "Needs staff attention"), ("no", "No open item")]

    def queryset(self, request, queryset):
        if self.value() in ("yes", "no"):
            return queryset.filter(needs_attention=self.value() == "yes")
        return queryset


class VersionInline(ReadOnlyTabularInline):
    model = SubmissionVersion
    fields = ("version_number", "trust", "origin", "name", "email", "reason", "received_at")
    readonly_fields = fields
    ordering = ("version_number",)
    verbose_name = "submission version"

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            adopted=Exists(VersionAdoption.objects.filter(submission_version=OuterRef("pk"))))

    @admin.display(description="trust")
    def trust(self, obj):
        return "adopted (confirmed by the applicant)" if obj.adopted else "unverified"

    @admin.display(description="name")
    def name(self, obj):
        return obj.submitted_fields.get("name", "")

    @admin.display(description="email")
    def email(self, obj):
        return obj.submitted_fields.get("email", "")

    @admin.display(description="reason")
    def reason(self, obj):
        return obj.submitted_fields.get("reason", "")


class ChallengeInline(ReadOnlyTabularInline):
    model = ContactChallenge
    fields = ("state", "email_at_issue", "created_at", "expires_at", "used_at", "superseded_at")  # never public_id
    readonly_fields = fields
    ordering = ("created_at", "id")
    verbose_name = "verification challenge"

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(unexpired=Q(expires_at__gt=Now()))  # database clock

    @admin.display(description="state")
    def state(self, obj):
        if obj.used_at:
            return "used (contact confirmed)"
        if obj.superseded_at:
            return "superseded"
        return "active" if obj.unexpired else "expired"


class EventInline(ReadOnlyTabularInline):
    model = ApplicationEvent
    fields = ("occurred_at", "entry", "kind", "actor_type", "actor_ref", "data")
    readonly_fields = fields
    ordering = ("occurred_at", "id")
    verbose_name = "history event"
    verbose_name_plural = "history"

    @admin.display(description="type")
    def entry(self, obj):
        if obj.kind == staff.ATTENTION:
            return format_html('<strong class="errornote">{}</strong>', "Needs staff attention")
        return "recorded step"


class OutboundInline(ReadOnlyTabularInline):
    model = apps.get_model("correspondence", "OutboundMessage")  # no import: correspondence depends on applications
    fields = ("attempt_number", "template_key", "template_version", "recipient", "status", "sent_at")
    readonly_fields = fields
    ordering = ("pending_action_id", "attempt_number")
    verbose_name = "outbound message"


@admin.register(Application)
class ApplicationAdmin(ReadOnlyModelAdmin):
    list_display = ("display_name", "email", "stage", "contact_verified", "attention", "created_at")
    list_filter = (NeedsAttentionFilter, "stage")
    search_fields = ("email_key", "display_name")
    ordering = ("-created_at", "-id")
    fieldsets = [
        ("Applicant", {"fields": ("display_name", "email", "stage", "created_at", "updated_at")}),
        ("Status", {"fields": ("contact_state", "adopted_version", "staff_attention", "next_step", "outstanding_work")}),
    ]
    readonly_fields = ("display_name", "email", "stage", "created_at", "updated_at",
                       "contact_state", "adopted_version", "staff_attention", "next_step", "outstanding_work")
    inlines = [VersionInline, ChallengeInline, EventInline, OutboundInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(needs_attention=staff.attention_q())

    @admin.display(boolean=True, description="contact verified")
    def contact_verified(self, obj):
        return obj.contact_verified_at is not None

    @admin.display(description="staff attention", ordering="needs_attention")
    def attention(self, obj):
        return format_html('<strong class="errornote">{}</strong>', "Needs staff attention") if obj.needs_attention else "-"

    @admin.display(description="contact")
    def contact_state(self, obj):
        return staff.contact_state(obj)

    @admin.display(description="adopted version")
    def adopted_version(self, obj):
        version = staff.adopted_version(obj)
        if version is None:
            return "none: no version is adopted until the applicant confirms"
        others = obj.versions.exclude(pk=version.pk).count()
        return f"version {version.version_number}; {others} other version(s) unverified"

    @admin.display(description="open staff-attention items")
    def staff_attention(self, obj):
        items = staff.attention_items(obj)
        if not items:
            return "none"
        return format_html_join("", '<p><strong class="errornote">Needs staff attention</strong> {} ({} UTC)</p>',
                                ((staff.describe_attention(e), f"{e.occurred_at:%Y-%m-%d %H:%M:%S}") for e in items))

    @admin.display(description="next responsible party")
    def next_step(self, obj):
        return format_html_join("", "<p>{}<strong>{}</strong>: {}</p>", (
            ("Needs staff attention. " if s.attention else "", s.party, s.text) for s in staff.next_steps(obj)))

    @admin.display(description="outstanding and completed work")
    def outstanding_work(self, obj):
        actions = staff.actions_for(obj)
        if not actions:
            return "none"
        return format_html_join("", "<p>{}: <strong>{}</strong>, attempts {} of {}{}</p>", (
            (a.kind, a.status, a.attempts, a.max_attempts, f"; last error: {a.last_error}" if a.last_error else "")
            for a in actions))

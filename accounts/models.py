from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class User(AbstractUser):
    """Staff account (ADR-18, D-19). Applicants are dossier records, never users."""


class StaffRoleGrant(models.Model):
    """One grant or revocation of a staff role by the owner-run `grant_staff_role` command (9kg.30; accounts.roles).
    Append-only for every role (migration 0006): the application role may only read it, and no role updates, deletes
    or truncates a row. It names the account, the role, what the role maps to (a group or one permission), the
    approval the owner cited and who ran the command; never a password or token."""

    class Action(models.TextChoices):
        GRANT = "grant"
        REVOKE = "revoke"

    class Kind(models.TextChoices):
        GROUP = "group"
        PERMISSION = "permission"

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="role_grants")
    role = models.CharField(max_length=40)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    target = models.CharField(max_length=150)  # the group name, or app_label.codename
    action = models.CharField(max_length=8, choices=Action.choices)
    approval_ref = models.CharField(max_length=200)
    actor_ref = models.CharField(max_length=200)
    recorded_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(action__in=["grant", "revoke"]), name="staff_role_grant_action_valid"),
            models.CheckConstraint(condition=Q(kind__in=["group", "permission"]), name="staff_role_grant_kind_valid"),
            models.CheckConstraint(condition=~Q(approval_ref=""), name="staff_role_grant_has_approval"),
        ]


class LoginThrottle(models.Model):
    """Password failures per username (6B.9, accounts.staff_access). `key` is a hash of the username: a failed
    attempt's text (often a mistyped password) is never stored."""

    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

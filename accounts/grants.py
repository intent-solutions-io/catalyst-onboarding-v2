"""The one writer of `StaffRoleGrant` rows (9kg.30): every command that gives or takes a staff role goes through
`record`, so every group membership and every direct grant has a latest `grant` row naming the approval the owner
cited. Owner-run commands only; the application role cannot insert here."""

import getpass

from accounts.models import StaffRoleGrant


def actor() -> str:
    try:
        return f"owner_command:{getpass.getuser()}"  # the operating-system login that ran the command
    except OSError:  # no login name in the environment (a container): the command itself is still the actor
        return "owner_command"


def record(user, *, role: str, kind: str, target: str, action: str, approval_ref: str) -> StaffRoleGrant:
    return StaffRoleGrant.objects.create(user=user, role=role, kind=kind, target=target, action=action,
                                         approval_ref=approval_ref.strip(), actor_ref=actor())


def require_approval(approval_ref) -> str:
    from django.core.management.base import CommandError

    if not (approval_ref or "").strip():
        raise CommandError("--approval-ref is required: name the decision that authorizes this change")
    return approval_ref.strip()

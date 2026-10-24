"""The one writer of `StaffRoleGrant` rows (9kg.30): every command that gives or takes a staff role goes through
`record`, so every group membership and every direct grant has a latest `grant` row naming the approval the owner
cited. Owner-run commands only; the application role cannot insert here.

`differences` (9kg.56) is the read-only reconciliation of that promise: the owner database credential can still change
memberships and permissions without a record, so it compares what is held with the latest record for each
(account, kind, target)."""

import getpass
from dataclasses import dataclass

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


UNRECORDED = "unrecorded"  # held, but the latest record for it is missing or a revocation
NOT_HELD = "recorded_not_held"  # the latest record is a grant, but it is not held


@dataclass(frozen=True, order=True)
class Difference:
    problem: str  # UNRECORDED or NOT_HELD
    username: str
    kind: str  # StaffRoleGrant.Kind: "group" or "permission"
    target: str  # the group name, or app_label.codename (as StaffRoleGrant.target)


def differences() -> list[Difference]:
    """9kg.56: every group membership and every direct permission with no matching latest `grant` row, and every latest
    `grant` row whose membership or permission is not held. Read-only: it reads the auth tables and the grant record,
    which the application role may read, and writes nothing. Sorted, so a report is stable."""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    latest = {}  # (user id, kind, target) -> (action, username): the newest row wins
    for user_id, username, kind, target, action in StaffRoleGrant.objects.order_by("id").values_list(
            "user_id", "user__username", "kind", "target", "action"):
        latest[(user_id, kind, target)] = (action, username)
    held = {}
    for user_id, username, group in user_model.groups.through.objects.values_list("user_id", "user__username", "group__name"):
        held[(user_id, StaffRoleGrant.Kind.GROUP.value, group)] = username
    for user_id, username, app, codename in user_model.user_permissions.through.objects.values_list(
            "user_id", "user__username", "permission__content_type__app_label", "permission__codename"):
        held[(user_id, StaffRoleGrant.Kind.PERMISSION.value, f"{app}.{codename}")] = username
    found = [Difference(UNRECORDED, username, kind, target) for (user_id, kind, target), username in held.items()
             if latest.get((user_id, kind, target), ("",))[0] != StaffRoleGrant.Action.GRANT]
    found += [Difference(NOT_HELD, username, kind, target) for (user_id, kind, target), (action, username) in latest.items()
              if action == StaffRoleGrant.Action.GRANT and (user_id, kind, target) not in held]
    return sorted(found)

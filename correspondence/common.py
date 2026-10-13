"""Shared pieces of the correspondence services (a leaf module: it imports no other correspondence service).

`Refused` is the one refusal type of every service; its message is a reason code. `require` is the named
staff-action check of the role matrix (016 F, D-30): authority comes from the owner-created groups, and a
superuser is refused like everyone else, as in the read-only admin (S1-T7)."""

from django.core.exceptions import PermissionDenied


# Staff-item reasons a decision-maker decides about a send (016 A6, F; decide_uncertain_send).
DECIDABLE = ("send_outcome_unknown", "retries_exhausted", "smtp_transport_blocked", "send_rejected_permanent",
             "send_refused")


class Refused(Exception):
    """A service refused; the message is a reason code."""


def actor_ref(user) -> str:
    return f"user:{user.pk}"


def can(user, permission: str) -> bool:
    """The one permission rule, used by services (enforcement) and staff screens (what to show)."""
    return (user is not None and user.is_authenticated and user.is_active and not user.is_superuser
            and user.has_perm(f"correspondence.{permission}"))


def require(user, permission: str) -> None:
    if not can(user, permission):
        raise PermissionDenied(permission)

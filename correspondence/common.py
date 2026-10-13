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


def require(user, permission: str) -> None:
    if user is None or not user.is_active or user.is_superuser or not user.has_perm(f"correspondence.{permission}"):
        raise PermissionDenied(permission)

"""Address rules (P5-D-1; 023 section 5 step 2). Deterministic, never from free text.

The proposed local part is `firstname.lastname` from the applicant's display name, folded to lowercase ASCII letters
and digits. A collision with a reserved, role or already-reserved address takes the next numeric suffix. A name that
does not yield two ASCII parts (one-part, non-Latin, or a preferred professional name) needs a reviewed exception by
an approver. Someone else's address is never reused: reservations are unique while live, and are never released while
a mailbox may exist for them.
"""

import re
import unicodedata

from django.conf import settings

SAFE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
# System and role addresses (RFC 2142 and common practice); the owner's list extends it.
ROLE_ADDRESSES = frozenset({
    "abuse", "admin", "administrator", "billing", "contact", "hello", "help", "hostmaster", "info", "mailer-daemon",
    "marketing", "noc", "no-reply", "noreply", "office", "postmaster", "privacy", "root", "sales", "security",
    "support", "sysadmin", "team", "webmaster", "www",
})


class NamingRefused(Exception):
    pass


def reserved(local_part: str) -> bool:
    extra = {r.lower() for r in settings.CATALYST_PROVISIONING_RESERVED_LOCAL_PARTS}
    return local_part.lower() in ROLE_ADDRESSES or local_part.lower() in extra


def fold(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]", "", ascii_text)


def proposal(display_name: str) -> str | None:
    """`first.last`, or None when the name needs a reviewed exception."""
    parts = [fold(p) for p in (display_name or "").split()]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return None
    return f"{parts[0]}.{parts[-1]}"[:60]


def check(local_part: str) -> str:
    local_part = (local_part or "").strip().lower()
    if not SAFE.fullmatch(local_part) or ".." in local_part:
        raise NamingRefused("local_part_invalid")
    if reserved(local_part):
        raise NamingRefused("local_part_reserved")
    return local_part


def candidates(base: str, limit: int = 50):
    yield base
    for n in range(2, limit + 2):
        yield f"{base}{n}"

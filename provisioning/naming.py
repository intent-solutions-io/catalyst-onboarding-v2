"""Address rules (P5-D-1; 023 section 5 step 2). Deterministic, never from free text.

Two selectable policies (`CATALYST_PROVISIONING_NAMING_POLICY`):

- `first_last` (P5-D-1, the default): `firstname.lastname` from the applicant's display name, folded to lowercase ASCII
  letters and digits; a collision with a reserved, role or already-reserved address takes the next numeric suffix. A
  name that does not yield two ASCII parts (one-part, non-Latin, or a preferred professional name) needs a reviewed
  exception by an approver.
- `first_name` (the first-generation convention, 034 row 38): the first name alone, then `first.last`, then
  `first.last2` to `first.last9`; a one-part name tries `first`, `first2` to `first9`. Nine suffixes, then review.

Someone else's address is never reused: reservations are unique while live, and are never released while a mailbox may
exist for them. With `CATALYST_PROVISIONING_NAMING_HOST_CHECK` the release also reads each candidate at the mail host
(mailboxes and forwarder aliases) before reserving it (`services.release`), so the existing population at the host
takes precedence over the rule.
"""

import re
import unicodedata

from django.conf import settings

SAFE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
POLICIES = ("first_last", "first_name")
MAX_PART = 30  # a folded name part is capped so that `first.last9` always fits the 64-character local part
MAX_SUFFIX = 9
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


def parts(display_name: str) -> tuple[str, str]:
    """The folded first and last word of a display name, each capped at MAX_PART; "" where a part is missing or folds
    to nothing (so hyphens, apostrophes, accents and spaces vanish: "Synthetic-Lovelace" is "syntheticlovelace")."""
    words = [fold(w)[:MAX_PART] for w in (display_name or "").split()]
    words = [w for w in words if w]
    if not words:
        return "", ""
    return words[0], (words[-1] if len(words) > 1 else "")


def first_name_candidates(display_name: str) -> list[str] | None:
    """The first-generation order: `first`, `first.last`, `first.last2` .. `first.last9`; a one-part name: `first`,
    `first2` .. `first9`. None when the name folds to nothing (a reviewed exception is needed)."""
    first, last = parts(display_name)
    if not first:
        return None
    if not last:
        return [first] + [f"{first}{n}" for n in range(2, MAX_SUFFIX + 1)]
    full = f"{first}.{last}"
    return [first, full] + [f"{full}{n}" for n in range(2, MAX_SUFFIX + 1)]


def candidates_for(display_name: str, policy: str | None = None) -> list[str] | None:
    """Every candidate the configured (or given) policy tries, in order; None when the name needs a reviewed exception."""
    policy = policy or settings.CATALYST_PROVISIONING_NAMING_POLICY
    if policy == "first_name":
        return first_name_candidates(display_name)
    base = proposal(display_name)
    return None if base is None else list(candidates(base))

"""Association and trust (016 section 4 C; owner decisions D-28, D-31). Pure decisions over derived headers.

- C0: automatic messages and bounces are recognized first, from headers alone (RFC 3834 markers, list
  headers, delivery-status reports). A bounce is matched only through the original Message-ID it embeds.
- C1: association is an exact match of In-Reply-To, then References, against our own Message-IDs.
- C2: `From` must hold exactly one mailbox equal to the verified address (case-folded ASCII or IDNA form);
  any address that Unicode normalization would change counts as a mismatch, so a look-alike never matches.
- C3: only the topmost `Authentication-Results` header whose authserv-id equals the configured trusted id is
  read, and only its `dmarc=` result; Catalyst never computes alignment. The trust table decides the effect.

No decision here changes the verified identity, the recipient, adopted evidence or the stage (C4).
"""

import re
import unicodedata
import uuid

from django.conf import settings

TRUSTED = "trusted"
AUTH_FAILED = "auth_failed"
UNVERIFIED = "unverified"
SENDER_MISMATCH = "sender_mismatch"

_AUTO_SUBMITTED_NO = re.compile(r"^\s*no\s*(;|$)", re.I)
_SEND_REF = re.compile(r"^<c([0-9a-f]{32})@([^>]+)>$", re.I)
_DMARC = re.compile(r"\bdmarc\s*=\s*([a-z]+)", re.I)


def is_automatic(markers: dict) -> bool:
    auto = markers.get("auto-submitted")
    if auto is not None and not _AUTO_SUBMITTED_NO.match(auto):
        return True
    if markers.get("precedence", "").strip().lower() in ("bulk", "junk", "auto_reply", "list"):
        return True
    return any(name in markers for name in ("x-autoreply", "x-autorespond", "list-id", "list-unsubscribe"))


def send_ref_of(message_id: str):
    """Our Message-IDs are <c{send_ref hex}@{CATALYST_MAIL_DOMAIN}> (016 3.2). Anything else is not ours."""
    match = _SEND_REF.match(message_id.strip())
    if not match or match.group(2).lower() != str(settings.CATALYST_MAIL_DOMAIN).lower():
        return None
    return uuid.UUID(match.group(1))


def candidate_refs(derived) -> list:
    ids = derived.embedded_message_ids if derived.is_bounce else [*derived.in_reply_to, *reversed(derived.references)]
    refs = []
    for message_id in ids:
        ref = send_ref_of(message_id)
        if ref is not None and ref not in refs:
            refs.append(ref)
    return refs


def _ascii_form(address: str) -> str | None:
    if unicodedata.normalize("NFKC", address) != address:
        return None
    local, sep, domain = address.rpartition("@")
    if not sep or not local:
        return None
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if not local.isascii():
        return None
    return f"{local}@{domain}".casefold()


def from_matches(from_addresses: list, verified: str | None) -> bool:
    if verified is None or len(from_addresses) != 1:
        return False
    sender, expected = _ascii_form(from_addresses[0]), _ascii_form(verified)
    return sender is not None and sender == expected


def auth_evidence(results: list) -> str:
    """The `dmarc=` value of the topmost header from the trusted authserv-id; `untrusted` when only other
    ids reported, `missing` when nothing did."""
    trusted_id = settings.CATALYST_MAIL_TRUSTED_AUTHSERV_ID.strip().lower()
    if not results:
        return "missing"
    for value in results:
        authserv = value.split(";", 1)[0].strip().split()[0].lower() if value.strip() else ""
        if trusted_id and authserv == trusted_id:
            match = _DMARC.search(value)
            return match.group(1).lower() if match else "none"
    return "untrusted"


def trust_decision(evidence: str, sender_ok: bool) -> str:
    """016 C3 trust table."""
    if not sender_ok:
        return SENDER_MISMATCH
    if evidence == "pass":
        return TRUSTED
    if evidence == "fail":
        return AUTH_FAILED
    return UNVERIFIED  # missing, none, temperror, permerror, untrusted, or anything unrecognized

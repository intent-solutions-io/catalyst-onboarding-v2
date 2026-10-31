"""Association and trust (016 section 4 C; owner decisions D-28, D-31). Pure decisions over derived headers.

- C0: automatic messages and bounces are recognized first, from headers alone (RFC 3834 markers, list
  headers, delivery-status reports). A bounce is matched only through the original Message-ID it embeds.
- C1: association is an exact match of In-Reply-To, then References, against our own Message-IDs.
- C1 for first-generation threads (bgl.6, 034 section 3.2 (c)): when none of our own Message-IDs matched, an
  optional resolver (CATALYST_FOREIGN_THREAD_RESOLVER: the first-generation import app's module when installed) is
  asked for the application of the Message-IDs v2 did not issue, then (never for a bounce, C0) of a `[CAT-...]`
  subject reference. A match only associates; C2 and C3 below decide trust exactly as for any reply. No resolver:
  today's behaviour (the message is unmatched, for staff).
- C2: `From` must hold exactly one mailbox equal to the verified address (case-folded ASCII or IDNA form);
  any address that Unicode normalization would change counts as a mismatch, so a look-alike never matches.
- C3: only the topmost `Authentication-Results` header whose authserv-id equals the configured trusted id is
  read, and only its `dmarc=` result; Catalyst never computes alignment. The trust table decides the effect.

No decision here changes the verified identity, the recipient, adopted evidence or the stage (C4).
"""

import re
import unicodedata
import uuid
from importlib import import_module

from django.conf import settings

TRUSTED = "trusted"
AUTH_FAILED = "auth_failed"
UNVERIFIED = "unverified"
SENDER_MISMATCH = "sender_mismatch"

_AUTO_SUBMITTED_NO = re.compile(r"^\s*no\s*(;|$)", re.I)
_SEND_REF = re.compile(r"^<c([0-9a-f]{32})@([^>]+)>$", re.I)
_COMMENT = re.compile(r"\([^()]*\)")
_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')


def is_automatic(markers: dict) -> bool:
    auto = markers.get("auto-submitted")
    if auto is not None and not _AUTO_SUBMITTED_NO.match(auto):
        return True
    if markers.get("precedence", "").strip().lower() in ("bulk", "junk", "auto_reply"):
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


def foreign_message_ids(derived) -> list[str]:
    """The Message-IDs a reply points at that v2 did not issue, in C1 order (In-Reply-To, then References newest
    first; for a bounce, the ones it embeds), each once."""
    ids = derived.embedded_message_ids if derived.is_bounce else [*derived.in_reply_to, *reversed(derived.references)]
    found = []
    for message_id in ids:
        if message_id and send_ref_of(message_id) is None and message_id not in found:
            found.append(message_id)
    return found


def foreign_resolver():
    """The configured resolver module, or None. Loaded by the code-fixed path only (config.guards.dispatch_problems),
    so the first-generation app is never imported where it is not installed."""
    path = getattr(settings, "CATALYST_FOREIGN_THREAD_RESOLVER", "")
    return import_module(path) if path else None


def foreign_application_id(derived) -> int | None:
    """The application a reply to a first-generation thread belongs to, or None (no resolver, no match, or an
    ambiguous one: the resolver answers None when its match names more than one application)."""
    resolver = foreign_resolver()
    if resolver is None:
        return None
    ids = foreign_message_ids(derived)
    found = resolver.application_for_message_ids(ids) if ids else None
    if found is None and not derived.is_bounce and derived.subject:
        found = resolver.application_for_subject(derived.subject)
    return found


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


def _resinfo(value: str) -> list[str]:
    """RFC 8601: `authserv-id [version]; resinfo; resinfo ...`. Quoted strings and comments are removed first,
    so text inside a property value (for example an address carrying "dmarc=pass") can never be read as a
    result."""
    cleaned = _QUOTED.sub('""', value)
    for _ in range(5):  # nested comments
        cleaned = _COMMENT.sub(" ", cleaned)
    return [part.strip() for part in cleaned.split(";")]


def auth_evidence(results: list) -> str:
    """The DMARC result of the topmost header from the trusted authserv-id: one resinfo entry that starts with
    `dmarc=`. Several or conflicting DMARC entries count as `conflict` (unverified). `untrusted` when only
    other ids reported; `missing` when nothing did."""
    trusted_id = settings.CATALYST_MAIL_TRUSTED_AUTHSERV_ID.strip().lower()
    if not results:
        return "missing"
    for value in results:
        parts = _resinfo(value)
        head = parts[0].split() if parts else []
        authserv = head[0].lower() if head else ""
        if not trusted_id or authserv != trusted_id:
            continue
        found = {m.group(1).lower() for m in (re.match(r"(?i)dmarc\s*=\s*([a-z]+)\b", p) for p in parts[1:]) if m}
        if not found:
            return "none"
        return found.pop() if len(found) == 1 else "conflict"
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

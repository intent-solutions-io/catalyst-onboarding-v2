"""The durable erasure record (9kg.32; 029 section 6.2; 026 section 6 option d): the smallest record that lets a
restore of an older backup find every later erasure, kept outside the backup's rollback domain.

**Where.** In the effect journal (workflow.journal), the one hash-chained, fsynced, append-only file outside the
database and outside the application backup set: a restore rolls the tables back, never this file. Three kinds:

- `erasure_intent`, appended and fsynced *before* the database transaction: the subject's keyed hash, the key id, the
  authority and reason codes, the classes the registry anonymizes, the provider handoffs owed and what is retained
  rather than erased (`custody_documents` while the registry's `signed_documents` row says `retain`);
- `erasure_complete`, appended after the transaction committed and, under `destroy_key`, after every custody key of
  the subject was destroyed (9kg.34; each destruction is its own `custody_key_destroyed` entry, written before the
  key's files are unlinked): the outcome (`erased`, `already_erased`, `nothing_to_erase`, or `refused_<code>` when the
  transaction refused after the intent), the number of values changed and the number of key files removed;
- `erasure_handoff`: the owner's completion of a manual provider deletion (211.7.1, QA finding 12), with its date.

Every entry's key is `erasure:<public reference>` (the application's `public_ref`, or an invitation's `public_id` for
a person who never applied): a random identifier, never a numeric id, which recurs after a restore. Nothing else
identifies the person: `subject` is HMAC-SHA-256 of the normalized email key under the erasure key, so the record is
sensitive (it can confirm a guessed address to whoever holds the key) but minimal (no address, name, body or
username, and no copy of anything erased). The journal's own content allow-list enforces that shape. Every erasure
entry also carries `mac`, HMAC-SHA-256 under the erasure key over its kind, key and data: `fold` with the key skips
(and reports) an entry that does not verify, so an intent, a completion or a handoff cannot be forged or altered by
anyone who can write the journal but lacks the key (PR #99 security review).

**Idempotent on resume.** An intent with no later completion is open: the next run of the command finishes it. It
reuses only the intent's hash and key id, and checks the hash against the row's key while the row still holds a real
one; the classes come from the registry in force and the authority and reason from the run. A transaction that
committed before its completion was written is found with nothing left to change and completed as `already_erased`;
one that rolled back is simply run again. A run after a completion writes nothing (`nothing_to_erase`).

**Key custody.** `CATALYST_ERASURE_KEY`, at least 32 characters, distinct from the Django and link-signing keys: in
production a file `erasure_key` in `CATALYST_SECRETS_DIR` (tmpfs), mounted only into the owner-run erasure command and
the restore's replay (9kg.25), its source of truth in the operator's encrypted secret store, never in the database,
the backup set, the journal, a receipt or a log. The record names the key by `key_id` (the first 16 hex of a SHA-256
of the key) so a rotated key can be told apart; a rotation keeps the old key for as long as entries made with it must
be matched (the oldest restorable backup). Losing the key does not lose an erasure: replay finds the subject by its
public reference; the hash is the cross-check that the restored row is the same person.

**Rotation (9kg.74).** `erasure_previous_keys` holds one historical key per line, only in owner-run processes.
An entry selects its signing key by `mac_key_id` when present, otherwise `key_id`. The latter always identifies
an intent/completion's subject hash. A resumed operation keeps that hash and signs its new entry with the current
key, without rewriting history. Only legacy handoffs and custody destructions omitted ids and try the held keys.
Unknown declared ids refuse. Keep historical keys while retained journal entries still need them; 027 governs the
procedure and the additional evidence review after a suspected compromise.

**Integrity, freshness and an emptied store.** The journal's hash chain and genesis identity make a broken or
replaced file an error. After each erasure the command prints the journal head (`<identity>:<seq>:<hash>`); the
owner keeps it out of band (the private operations record), and `catalyst_erasure_record --expect-head` refuses a
journal that does not hold that head at that seq: an emptied or rolled-back store reads as `journal_mismatch`, never
as "no erasures". It also reports open intents and owed handoffs. `--list-open` needs no head (the chain and macs
only), so an interrupted first erasure is visible before any head was printed.

**Retention.** At least as long as the oldest restorable backup (registry row `erasure_record`): the journal is never
rotated or truncated by code (`catalyst_journal_repair` only moves a torn tail aside and journals it), and a future
rotation (029 section 6.2, deferred) must carry erasure entries forward until every backup older than them is gone.
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings
from django.utils import timezone

from workflow import journal

# bgl.14: `twenty`, the person and the applicant file note the projection wrote to Twenty (crm.projection).
HANDOFFS = (
    "documenso",
    "mail_sent",
    "mail_inbox",
    "mail_host_mailbox",
    "model_provider",
    "twenty",
)
RETAINED = (
    "custody_documents",
)  # reported while signed_documents is `retain`; `destroy_key` removes it (9kg.34)
SUBJECT_PREFIX = b"catalyst-erasure-subject\n"
KEY_ID_PREFIX = b"catalyst-erasure-key-id\n"
MAC_PREFIX = b"catalyst-erasure-entry\n"
HEAD = re.compile(r"([0-9a-f]{32}):(\d+):([0-9a-f]{64})")
DONE = ("erased", "already_erased", "nothing_to_erase")


class RecordError(Exception):
    """A reason code: `key_missing`, `key_weak`, `key_reused`, `not_configured`, `unwritable`, `bad_head`, `malformed`,
    `forged_entry`, or a journal code (`unreadable`, `chain_broken`, `torn_tail`, `malformed`, `journal_mismatch`)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def key() -> bytes:
    value = getattr(settings, "CATALYST_ERASURE_KEY", "") or ""
    if not value:
        raise RecordError("key_missing")
    if len(value) < 32:
        raise RecordError("key_weak")
    others = [
        settings.SECRET_KEY,
        getattr(settings, "CATALYST_VERIFICATION_KEY", ""),
        *getattr(settings, "CATALYST_VERIFICATION_FALLBACK_KEYS", []),
    ]
    if value in [o for o in others if o]:
        raise RecordError("key_reused")
    secret = value.encode()
    verification_keys(secret)
    return secret


def key_id(secret: bytes) -> str:
    return hashlib.sha256(KEY_ID_PREFIX + secret).hexdigest()[:16]


def verification_keys(secret: bytes) -> dict[str, bytes]:
    """Current signing key plus owner-held historical verification keys, never process-global cached."""
    previous = getattr(settings, "CATALYST_ERASURE_PREVIOUS_KEYS", [])
    if not isinstance(previous, (list, tuple)):
        raise RecordError("keys_malformed")
    forbidden = [
        settings.SECRET_KEY,
        getattr(settings, "CATALYST_VERIFICATION_KEY", ""),
        *getattr(settings, "CATALYST_VERIFICATION_FALLBACK_KEYS", []),
    ]
    found = {key_id(secret): secret}
    for value in previous:
        if not isinstance(value, str) or len(value) < 32:
            raise RecordError("key_weak")
        if value in forbidden:
            raise RecordError("key_reused")
        held = value.encode()
        kid = key_id(held)
        if kid in found and found[kid] != held:
            raise RecordError("key_id_collision")
        found[kid] = held
    return found


def subject_key(data: dict, secret: bytes) -> bytes:
    """The subject HMAC keeps its original key even when a resumed completion uses a new signing key."""
    kid = data.get("key_id")
    held = verification_keys(secret).get(kid) if isinstance(kid, str) else None
    if held is None:
        raise RecordError("key_unknown")
    return held


def verifies(entry, secret: bytes) -> bool:
    held = verification_keys(secret)
    kid = entry.data.get("mac_key_id", entry.data.get("key_id"))
    if entry.kind in ("erasure_intent", "erasure_complete"):
        subject_id = entry.data.get("key_id")
        if not isinstance(subject_id, str) or subject_id not in held:
            return False
    if "mac_key_id" in entry.data or "key_id" in entry.data:
        candidates = [held[kid]] if isinstance(kid, str) and kid in held else []
    elif entry.kind in ("erasure_handoff", "custody_key_destroyed"):
        # Only these historical shapes omitted a key id. A declared but unknown id never falls back.
        candidates = held.values()
    else:
        candidates = []
    return any(
        hmac.compare_digest(
            str(entry.data.get("mac", "")),
            entry_mac(entry.kind, entry.key, entry.data, candidate),
        )
        for candidate in candidates
    )


def subject_hash(email_key: str, secret: bytes) -> str:
    return hmac.new(
        secret, SUBJECT_PREFIX + email_key.encode(), hashlib.sha256
    ).hexdigest()


def entry_mac(kind: str, entry_key_: str, data: dict, secret: bytes) -> str:
    body = {k: v for k, v in data.items() if k != "mac"}
    message = (
        MAC_PREFIX
        + f"{kind}\n{entry_key_}\n".encode()
        + json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def entry_key(subject_ref) -> str:
    return f"erasure:{subject_ref}"


def _append(kind: str, subject_ref, data: dict, secret: bytes):
    if not journal.configured():
        raise RecordError("not_configured")
    data = dict(data)
    data.setdefault("key_id", key_id(secret))
    if data["key_id"] != key_id(secret):
        data["mac_key_id"] = key_id(secret)
    data["mac"] = entry_mac(kind, entry_key(subject_ref), data, secret)
    entry = journal.append(
        kind, entry_key(subject_ref), data
    )  # fsynced before it returns
    if entry is None:
        raise RecordError(
            "unwritable"
        )  # the failure is logged and counted by the journal
    return entry


def append_intent(
    subject_ref,
    subject: str,
    kid: str,
    authority: str,
    reason: str,
    classes,
    handoffs,
    retained,
    secret,
):
    return _append(
        "erasure_intent",
        subject_ref,
        {
            "subject": subject,
            "key_id": kid,
            "authority": authority,
            "reason": reason,
            "classes": list(classes),
            "handoffs": sorted(handoffs),
            "retained": sorted(retained),
            "phase": "intent",
        },
        secret,
    )


def append_complete(
    subject_ref,
    subject: str,
    kid: str,
    status: str,
    changed: int,
    secret,
    keys_destroyed: int = 0,
    key_files_removed: int = 0,
    custody_destroyed: bool = False,
):
    data = {
        "subject": subject,
        "key_id": kid,
        "status": status,
        "changed": int(changed),
        "phase": "done",
    }
    if custody_destroyed:  # 9kg.34: every custody key of the subject verified gone; other completions keep their shape
        data.update(
            custody="keys_destroyed",
            keys_destroyed=int(keys_destroyed),
            key_files_removed=int(key_files_removed),
        )
    return _append("erasure_complete", subject_ref, data, secret)


def completion_date(text: str) -> str:
    """A handoff's completion date: an ISO calendar date, not in the future."""
    try:
        day = date.fromisoformat(text or "")
    except ValueError:
        raise RecordError("malformed") from None
    if len(text) != 10 or day > timezone.now().date():
        raise RecordError("malformed")
    return day.isoformat()


def append_handoff(subject_ref, provider: str, completed_on: str, secret):
    if provider not in HANDOFFS:
        raise RecordError("malformed")
    return _append(
        "erasure_handoff",
        subject_ref,
        {
            "provider": provider,
            "completed_on": completion_date(completed_on),
            "phase": "done",
        },
        secret,
    )


@dataclass
class Erasure:
    """One subject's record, folded from its entries in order."""

    ref: str
    intent: object = None  # the last intent
    complete: object = None  # the last completion after that intent
    handoffs_owed: set = field(default_factory=set)
    handoffs_done: dict = field(default_factory=dict)
    retained: set = field(default_factory=set)

    @property
    def open(self) -> bool:
        return self.intent is not None and self.complete is None

    @property
    def erased(self) -> bool:
        return self.complete is not None and self.complete.data.get("status") in DONE

    @property
    def outstanding(self) -> list:
        return (
            sorted(self.handoffs_owed - set(self.handoffs_done)) if self.erased else []
        )


def any_erasure(entries) -> bool:
    """Whether the journal holds any erasure entry at all, verified or not (the restore's resurrection guard)."""
    return any(e.kind.startswith("erasure_") for e in entries)


def fold(entries, secret: bytes | None, forged: list | None = None) -> dict:
    """{public reference: Erasure} over the erasure entries of a journal, in order. With the erasure key, an entry
    whose `mac` does not verify is not folded and its reference is added to `forged`; without it (the health signal,
    which never holds the key) entries are folded unverified. What the replay after a restore (9kg.25) reads, with the
    key: every erased or open subject, with the intent's hash and key id."""
    out = {}
    for entry in entries:
        if not entry.kind.startswith("erasure_"):
            continue
        ref = entry.key.partition(":")[2]
        if secret is not None and not verifies(entry, secret):
            if forged is not None:
                forged.append(ref)
            continue
        state = out.setdefault(ref, Erasure(ref))
        if entry.kind == "erasure_intent":
            state.intent, state.complete = entry, None
            state.handoffs_owed = set(entry.data.get("handoffs") or [])
            state.retained = set(entry.data.get("retained") or [])
        elif entry.kind == "erasure_complete" and state.intent is not None:
            state.complete = entry
            if (
                entry.data.get("custody") == "keys_destroyed"
            ):  # 9kg.34: retained until every key is verified gone
                state.retained.discard("custody_documents")
        elif entry.kind == "erasure_handoff":
            state.handoffs_done[entry.data["provider"]] = entry.data["completed_on"]
    return out


def head_string() -> str:
    seq, digest, identity = journal.head()
    return f"{identity}:{seq}:{digest}"


def _read() -> list:
    if not journal.configured():
        raise RecordError("not_configured")
    try:
        return journal.read()
    except journal.JournalError as exc:
        raise RecordError(exc.code) from None


def _report(entries, secret) -> dict:
    forged = []
    state = fold(entries, secret, forged)
    if forged:
        raise RecordError("forged_entry")
    return {
        "journal_head": f"{entries[0].data.get('id', '')}:{entries[-1].seq}:{entries[-1].hash}"
        if entries
        else "none",
        "erased": sum(1 for s in state.values() if s.erased),
        "open": sorted(ref for ref, s in state.items() if s.open),
        "handoffs_outstanding": sum(len(s.outstanding) for s in state.values()),
        "retained": sum(len(s.retained) for s in state.values() if s.erased),
    }


def verify(expected_head: str) -> dict:
    """Integrity (the chain and every entry's mac), identity and freshness (the out-of-band head is in the journal at
    its seq, seq 1 or later), and the record's state. `expected_head` is the head printed by the last erasure or
    handoff, or `none` when no erasure was ever made. Raises RecordError; returns counts and the open references
    (public references, never an address)."""
    secret = key()
    entries = _read()
    if expected_head != "none":
        found = HEAD.fullmatch(expected_head or "")
        if found is None or int(found.group(2)) < 1:
            raise RecordError("bad_head")
        try:
            journal.verify_anchor(
                entries, found.group(1), int(found.group(2)), found.group(3)
            )
        except journal.JournalError as exc:
            raise RecordError(exc.code) from None
    report = _report(entries, secret)
    if expected_head == "none" and any_erasure(entries):
        raise RecordError(
            "journal_mismatch"
        )  # erasures exist, so a head was printed and must be supplied
    return report


def list_open() -> dict:
    """The chain and every entry's mac verified, no head needed: an interrupted first erasure is visible before any
    head was ever printed."""
    return _report(_read(), key())

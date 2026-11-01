"""The effect journal (029 section 6.2; bead 9kg.33): a durable record of effects kept outside the database's
rollback domain, so a restore to the backup's time T can learn what happened after T.

A restore brings every table back to T. The world does not go back: a closure, a revocation, a staff pause, a
resolution, a withdrawal, a confirmed reply outcome, a decision on an uncertain send, a staff role change, a message
that left, model budget that was spent. Each of those is appended here as one line of a hash-chained JSON Lines file
in `CATALYST_EFFECT_JOURNAL_DIR`, a directory outside the application backup. The post-restore step
(`config.post_restore`) replays the entries after the backup point against the restored tables; the erasure path
(9kg.32) records its intents and completions in the same file, so only one durable store exists.

**Consistency model** (the PR #89 reviews). Three classes of effect:

- *journaled before commit* (`phase: prepare`, then `done` after commit): the restrictive effects (a closure, a
  revocation outcome, a pause, a withdrawal, a staff role removal). A `prepare` whose transaction then failed is
  replayed as if done: re-applying a restriction is safe, losing one is not;
- *journaled after commit* (`transaction.on_commit`, `robust=True`): everything else, so the file can miss an effect
  under a crash between commit and append, never invent one;
- *covered by a provider read*: mail (`send_begun` is written after the database claim and before SMTP, and the Sent
  folder is read), envelopes and mailboxes, which the post-restore step reads at the provider.

Three invariants: an entry at or below the backup's recorded seq is in the snapshot or is reconciled (the backup
records the head before its snapshot opens); a lift implies a journal that matches the receipt's head (the restore
marker carries the journal identity, seq and hash, and `after_restore` refuses a mismatch); an append failure is
observable (a code-only error log, a failure counter file, a health signal and a readiness refusal).

Shape of an entry: `seq`, `at` (UTC), `kind`, `key` (the effect's identity: a public reference or an opaque staff
reference, never a numeric id, which recurs after a restore), `data` (codes, references, counts and digests only,
enforced by an allow-list per kind), `prev` and `hash` (SHA-256 over `prev` and the entry's canonical JSON). The first
entry is a `genesis` with a random journal identity; a journal of another lineage is refused. Replay is idempotent on
(`kind`, `key`). A broken chain, a torn tail, a missing directory or an unreadable file is an error the post-restore
step reports and the lift refuses on. Writers take an exclusive advisory lock on `effects.lock`, readers a shared
one; appends are O_APPEND and fsynced; nothing is rewritten except by the owner-run `catalyst_journal_repair`, which
moves a torn tail aside and journals that it did. The directory is 0700 and the file 0600.

Not configured (an empty setting) is allowed only in `test` and `development` (config.guards): entries are then
dropped with one warning per process, and the post-restore lift refuses because no evidence exists.
"""

import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import stat
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)
FILE = "effects.jsonl"
LOCK = "effects.lock"
FAILURES = "effects.failures"  # one line per failed append, for the health signal
GENESIS = "0" * 64
_state = threading.local()
_warned = {"not_configured": False}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HEX = re.compile(r"[0-9a-f]{16,64}")
CODE = re.compile(r"[a-z0-9_.:-]{1,64}")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}(T.*)?")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}")
# The kinds the journal accepts and the data keys each may carry (codes, references, counts and digests only).
KINDS = {
    "genesis": {"id"},
    "restore": {
        "backup_seq",
        "backup_head",
        "backup_journal_id",
        "backup_started_at",
        "behind_shipped",
        "shipped_seq",
    },
    "repair": {"discarded_bytes", "last_good_hash"},
    "application_closed": {"outcome", "phase"},
    "access_revocation": {"state", "phase"},
    "automation_pause": {
        "state",
        "by",
        "phase",
        "actor",
    },  # actor: an opaque staff reference (staff_ref) on a resume
    "staff_item_resolved": {"reason", "resolution"},
    "question_withdrawn": {"reason", "phase"},
    "reply_link_outcome": {"state", "outcome"},
    "uncertain_send_decided": {"decision", "series", "revised_send_ref"},
    "question_approved": {"question", "send_ref", "content_sha256"},
    "staff_message_confirmed": {"send_ref", "content_sha256"},
    "reminder_queued": {"n", "question", "send_ref"},
    "send_begun": {"kind", "series", "attempt", "question", "n"},
    "staff_role_changed": {"change", "active", "groups", "phase"},
    "model_usage": {"requests"},
    # 9kg.32 (erasure.record): the durable erasure record. Keyed `erasure:<public reference>`; `subject` is the keyed
    # hash of the email key and `key_id` names its key, never the key or the address.
    # `mac` is HMAC-SHA-256 under the erasure key over the kind, the key and the rest of the data, so an entry cannot be
    # forged or altered without the key (PR #99 security review).
    "erasure_intent": {
        "subject",
        "key_id",
        "mac_key_id",
        "authority",
        "reason",
        "classes",
        "handoffs",
        "retained",
        "phase",
        "mac",
    },
    "erasure_complete": {
        "subject",
        "key_id",
        "mac_key_id",
        "status",
        "changed",
        "custody",
        "keys_destroyed",
        "key_files_removed",
        "phase",
        "mac",
    },
    "erasure_handoff": {"provider", "completed_on", "phase", "mac", "key_id"},
    # 9kg.25 (erasure.replay): the erasures re-applied to a restored database, keyed `erasure_replay:<restore seq>` (the
    # seq of the `restore` entry it answers, 0 for a hold placed by hand): `through` is the seq of the last erasure
    # entry it covered, the rest are counts. The post-restore review and lift re-read it, verified by its `mac`.
    "erasures_replayed": {
        "restore",
        "through",
        "subjects",
        "erased",
        "already",
        "absent",
        "key_id",
        "phase",
        "mac",
    },
    # 9kg.34 (agreements.keystore): one custody data key destroyed, keyed `custody_key:<key reference>` (a random
    # reference, never key material), with the erased subject's public reference. Appended before the key's files are
    # unlinked (the restrictive class): recovery never restores a key recorded here, and a destruction recorded but
    # interrupted is finished by the next erasure run or by recovery.
    "custody_key_destroyed": {
        "subject",
        "key_id",
        "phase",
        "mac",
    },  # mac: HMAC under the erasure key, as for erasure_*
    # 9kg.34 (review of PR #102, F2): an orphan the owner reaped: a never-used key (`kind: key`) or a sealed file no row
    # names (`kind: sealed_file`), keyed `custody_orphan:<reference>`.
    "custody_orphan_reaped": {"kind", "phase"},
    # 9kg.69 (agreements.keystore.rotate, retire): a wrapping-key rotation, keyed `custody_rotation:<old id>:<new id>`
    # (`prepare` at the start, `done` once every live key is rewrapped and every live document opens under the new
    # key) and its retirement, keyed `custody_rotation_retired:<old id>`, once no key file is under the old key. Key ids
    # only (16 hex of a hash), never a key.
    "custody_rotation": {"from_key", "to_key", "keys", "documents", "phase"},
    # bgl.9 (agreements.countersign): the automated company countersignature of one agreement, keyed
    # `countersign:<instance public reference>`: `begun` appended before the provider call, `done` once a fresh read
    # showed the company recipient signed. Codes only.
    "agreement_countersign": {"phase", "outcome"},
}
RESTRICTIVE = (
    "application_closed",
    "access_revocation",
    "automation_pause",
    "question_withdrawn",
    "staff_role_changed",
)


class JournalError(Exception):
    """A reason code: `not_configured`, `unreadable`, `chain_broken`, `malformed`, `torn_tail`, `journal_mismatch`,
    `content_refused`, `unwritable`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Entry:
    seq: int
    at: str
    kind: str
    key: str
    data: dict
    prev: str
    hash: str

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.at)


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(prev: str, payload: dict) -> str:
    return hashlib.sha256(f"{prev}\n{_canonical(payload)}".encode()).hexdigest()


def directory() -> str:
    return str(getattr(settings, "CATALYST_EFFECT_JOURNAL_DIR", "") or "")


def configured() -> bool:
    return bool(directory())


def staff_ref(username: str) -> str:
    """An opaque reference to a staff account (PR #89 security review): never the username itself."""
    return "staff:" + hashlib.sha256(("staff\n" + username).encode()).hexdigest()[:32]


def _acceptable(value) -> bool:
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, int):
        return 0 <= value < 10**12
    if isinstance(value, float):
        return 0 <= value < 10**12
    if isinstance(value, str):
        if len(value) > 128:
            return False
        return value in ("", "*") or any(
            pattern.fullmatch(value) is not None for pattern in (UUID, HEX, CODE, ISO)
        )
    if isinstance(
        value, list
    ):  # group names are configuration labels (never personal data): letters, digits, spaces
        return len(value) <= 32 and all(
            isinstance(v, str) and (_acceptable(v) or LABEL.fullmatch(v) is not None)
            for v in value
        )
    return False


def check_content(kind: str, key: str, data: dict) -> None:
    """The allow-list (PR #89 security review): a known kind, its own keys, and values that are codes, references,
    counts, digests or times. Anything else is refused before it can reach the file."""
    if (
        kind not in KINDS
        or not isinstance(key, str)
        or len(key) > 128
        or not re.fullmatch(r"[a-z_]+:[A-Za-z0-9:_.-]+", key)
    ):
        raise JournalError("content_refused")
    if set(data) - KINDS[kind] or not all(_acceptable(v) for v in data.values()):
        raise JournalError("content_refused")


def _parse(line: bytes, number: int) -> Entry:
    try:
        raw = json.loads(line)
        entry = Entry(
            seq=int(raw["seq"]),
            at=str(raw["at"]),
            kind=str(raw["kind"]),
            key=str(raw["key"]),
            data=dict(raw["data"]),
            prev=str(raw["prev"]),
            hash=str(raw["hash"]),
        )
    except ValueError, KeyError, TypeError:
        raise JournalError("malformed") from None
    if entry.seq != number:
        raise JournalError("chain_broken")
    return entry


def _check(entry: Entry, prev: str) -> None:
    payload = asdict(entry)
    expected = payload.pop("hash")
    if entry.prev != prev or _digest(prev, payload) != expected:
        raise JournalError("chain_broken")


def _lock_fd():
    return os.open(
        os.path.join(directory(), LOCK), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )


def _read_bytes() -> bytes:
    path = os.path.join(directory(), FILE)
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        if not os.path.isdir(directory()):
            raise JournalError("unreadable") from None
        return b""
    except OSError:
        raise JournalError("unreadable") from None


def _entries(raw: bytes) -> list[Entry]:
    if raw and not raw.endswith(b"\n"):
        raise JournalError("torn_tail")
    entries, prev = [], GENESIS
    for number, line in enumerate(
        (ln for ln in raw.split(b"\n") if ln.strip()), start=1
    ):
        entry = _parse(line, number)
        _check(entry, prev)
        entries.append(entry)
        prev = entry.hash
    if entries and entries[0].kind != "genesis":
        raise JournalError("malformed")
    return entries


def read() -> list[Entry]:
    """Every entry, in order, with the chain verified, under a shared lock taken through a read-only descriptor, so
    a reader on a read-only mount (the backup) works. Raises JournalError rather than returning a partial record. A
    lock file that does not exist yet means no writer has ever appended (a writer creates it before the file)."""
    return snapshot()[1]


def snapshot() -> tuple[bytes, list[Entry]]:
    """The file's bytes and its entries, read once under the shared lock, so the two always agree (9kg.60: the
    shipper copies exactly the bytes whose chain it verified)."""
    if not configured():
        raise JournalError("not_configured")
    if not os.path.isdir(directory()):
        raise JournalError("unreadable")
    try:
        fd = os.open(os.path.join(directory(), LOCK), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raw = _read_bytes()
        return raw, _entries(raw)
    except OSError:
        raise JournalError("unreadable") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        try:
            raw = _read_bytes()
            return raw, _entries(raw)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        raise JournalError("unreadable") from None
    finally:
        os.close(fd)


def identity() -> str:
    """The journal's random identity (its genesis entry), "" for an empty journal."""
    entries = read()
    return str(entries[0].data.get("id", "")) if entries else ""


def head() -> tuple[int, str, str]:
    """(seq, hash, identity) of the last entry; (0, GENESIS, "") for an empty journal. The backup records them in
    its receipt, so a restore knows which entries postdate the backup point and which journal they belong to."""
    entries = read()
    return (
        (entries[-1].seq, entries[-1].hash, str(entries[0].data.get("id", "")))
        if entries
        else (0, GENESIS, "")
    )


def _tail(handle) -> tuple[int, str]:
    """The last entry's (seq, hash) read under the lock, without parsing the whole file. A file that does not end
    in a newline, or whose last line is not an entry, is a torn tail: nothing is appended after it until the owner
    repairs it (`catalyst_journal_repair`)."""
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    if size == 0:
        return 0, GENESIS
    block = min(size, 65536)
    handle.seek(size - block)
    chunk = handle.read(block)
    if not chunk.endswith(b"\n"):
        raise JournalError("torn_tail")
    last = [ln for ln in chunk.split(b"\n") if ln.strip()]
    if not last:
        raise JournalError("torn_tail")
    try:
        entry = json.loads(last[-1])
        return int(entry["seq"]), str(entry["hash"])
    except ValueError, KeyError, TypeError:
        raise JournalError("torn_tail") from None


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _note_failure(code: str) -> None:
    """An append that failed is observable: a code-only error line and one line in the failures file (the health
    signal reads its length). Nothing here raises: the effect's transaction has already committed."""
    logger.error("effect journal append failed (%s)", code)
    try:
        fd = os.open(
            os.path.join(directory(), FAILURES),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "ab") as handle:
            handle.write(
                f"{datetime.now(UTC).isoformat(timespec='seconds')} {code}\n".encode()
            )
    except OSError:
        pass


def failures() -> int:
    try:
        with open(os.path.join(directory(), FAILURES), "rb") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _write_entry(handle, kind: str, key: str, data: dict, seq: int, prev: str) -> Entry:
    payload = {
        "seq": seq,
        "at": datetime.now(UTC).isoformat(timespec="microseconds"),
        "kind": kind,
        "key": key,
        "data": data,
        "prev": prev,
    }
    entry = Entry(**payload, hash=_digest(prev, payload))
    handle.write((_canonical(asdict(entry)) + "\n").encode())
    return entry


def _append_locked(kind: str, key: str, data: dict) -> Entry:
    path = os.path.join(directory(), FILE)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab") as handle:
        with open(path, "rb") as reader:
            seq, prev = _tail(reader)
        if seq == 0 and kind != "genesis":  # the first entry names the journal
            genesis = _write_entry(
                handle,
                "genesis",
                f"journal:{secrets.token_hex(16)}",
                {"id": secrets.token_hex(16)},
                1,
                prev,
            )
            seq, prev = genesis.seq, genesis.hash
        entry = _write_entry(handle, kind, key, data, seq + 1, prev)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_dir(directory())
    return entry


def ensure_genesis() -> bool:
    """Write the genesis entry if the journal is empty (the worker calls it at start in a deployment), so every backup
    taken from a running stack anchors to the journal's identity at seq 1 at least; an emptied or replaced journal
    behind it is then `journal_mismatch` (found by the restore drill: a backup of a never-used journal recorded seq 0
    and nothing to verify). Returns True when it wrote the entry. Idempotent under the exclusive lock."""
    fd = _lock_fd()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        path = os.path.join(directory(), FILE)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return False
        wfd = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(wfd, "ab") as handle:
            _write_entry(
                handle,
                "genesis",
                f"journal:{secrets.token_hex(16)}",
                {"id": secrets.token_hex(16)},
                1,
                GENESIS,
            )
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(directory())
        return True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def append(kind: str, key: str, data: dict | None = None) -> Entry | None:
    """Append one entry now (the caller is outside, or at the end of, its transaction). Returns None when the journal
    is not configured (local environments only), while a replay is in progress (a replay re-applies facts; it makes
    no new ones), or when the append failed (then the failure is logged and counted; the caller's effect stands)."""
    if getattr(_state, "replaying", False):
        return None
    if not configured():
        if not _warned["not_configured"]:
            _warned["not_configured"] = True
            logger.warning(
                "effect journal not configured: effects are not durable in this environment"
            )
        return None
    data = dict(data or {})
    check_content(
        kind, key, data
    )  # a content refusal is a programming error: it raises
    try:
        fd = _lock_fd()
    except OSError:
        _note_failure("unwritable")
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            return _append_locked(kind, key, data)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except JournalError as exc:
        _note_failure(exc.code)
        return None
    except OSError as exc:
        _note_failure(type(exc).__name__.lower())
        return None
    finally:
        os.close(fd)


def record(kind: str, key: str, data=None) -> None:
    """Append after the current transaction commits (or now, outside one). The Django idiom for "once it is a
    fact": an entry is never written for a transaction that rolled back, so the journal can only miss an effect
    (as today, with no journal), never invent one. `data` may be a callable evaluated at commit time."""
    if getattr(_state, "replaying", False):
        return
    frozen = None if callable(data) else dict(data or {})
    transaction.on_commit(
        lambda: append(kind, key, data() if frozen is None else frozen), robust=True
    )


def prepare(kind: str, key: str, data: dict | None = None) -> None:
    """A restrictive effect, journaled before its transaction commits (`phase: prepare`); `record` the same kind and
    key after it. A prepare whose transaction then failed is replayed as done: a restriction re-applied is safe."""
    if kind not in RESTRICTIVE:
        raise JournalError("content_refused")
    append(kind, key, {**(data or {}), "phase": "prepare"})


class replaying:
    """A context in which `append` writes nothing: the post-restore replay re-applies journaled facts through the
    ordinary services, which would otherwise journal them again."""

    def __enter__(self):
        self._previous = getattr(_state, "replaying", False)
        _state.replaying = True
        return self

    def __exit__(self, *exc):
        _state.replaying = self._previous


def parse_anchor(actor_ref: str):
    """The backup anchor the restore wrote on the hold row (`catalyst_restore|<identity>:<seq>:<head>`), or None."""
    _, _, anchor = (actor_ref or "").partition("|")
    parts = anchor.split(":")
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1]), parts[2]


def verify_anchor(entries: list, identity: str, seq: int, head: str) -> None:
    """The journal must be the lineage the anchor names and hold the anchored hash at its seq; an empty, truncated
    or replaced journal is `journal_mismatch`, never "nothing happened"."""
    if seq <= 0:
        return
    if len(entries) < seq or entries[seq - 1].hash != head:
        raise JournalError("journal_mismatch")
    own = str(entries[0].data.get("id", ""))
    if (identity or own) != own:
        raise JournalError("journal_mismatch")


def after_restore(anchor=None) -> tuple[list[Entry], datetime | None, int | None]:
    """The entries to reconcile after a restore: those after the restored backup's recorded head and before the
    `restore` entry the restore wrote, plus the window start (the backup's start). The anchor (from the hold row the
    restore wrote, and from the marker) is verified with `verify_anchor`, so an empty, truncated or replaced journal
    behind a hold with an anchor never reads as "nothing happened". Without an anchor or a `restore` entry (a hold
    placed by hand), every entry and no window start."""
    entries = read()
    if anchor is not None:
        verify_anchor(entries, *anchor)
    restores = [e for e in entries if e.kind == "restore"]
    if not restores:
        start = anchor[1] if anchor is not None else 0
        return [e for e in entries if e.seq > start and e.kind != "genesis"], None, None
    marker = restores[-1]
    backup_seq, backup_head = (
        marker.data.get("backup_seq"),
        marker.data.get("backup_head") or "",
    )
    start = (
        int(backup_seq)
        if isinstance(backup_seq, int)
        and not isinstance(backup_seq, bool)
        and backup_seq >= 0
        else 0
    )
    verify_anchor(
        entries, str(marker.data.get("backup_journal_id") or ""), start, backup_head
    )
    since = marker.data.get("backup_started_at")
    window = (
        datetime.fromtimestamp(float(since), UTC)
        if isinstance(since, (int, float)) and not isinstance(since, bool)
        else None
    )
    return (
        [
            e
            for e in entries
            if start < e.seq < marker.seq and e.kind not in ("restore", "genesis")
        ],
        window,
        marker.seq,
    )


def usage_high_water(day: str) -> int:
    """The highest `model_usage` request count journaled for one UTC day (YYYY-MM-DD), cached per process by the
    file's size and modification time, so a budget check re-reads the file only after it grew. A missing or
    unreadable journal raises: an unknown floor refuses the call (fail closed)."""
    if not configured():
        return 0
    path = os.path.join(directory(), FILE)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        if not os.path.isdir(directory()):
            raise JournalError("unreadable") from None
        return 0
    except OSError:
        raise JournalError("unreadable") from None
    cache = getattr(_state, "usage_cache", None)
    stamp = (path, st.st_size, st.st_mtime_ns)
    if cache is None or cache[0] != stamp:
        highs: dict[str, int] = {}
        for entry in read():
            if entry.kind == "model_usage":
                highs[entry.key] = max(
                    highs.get(entry.key, 0), int(entry.data.get("requests", 0))
                )
        cache = (stamp, highs)
        _state.usage_cache = cache
    return cache[1].get(f"usage:{day}", 0)


def directory_problem(write: bool) -> str:
    """ "" when the configured directory exists, is a private directory (0700, not a link) and, for a process that
    journals, is writable; else a code. The start-up check and the readiness probe use it (PR #89 review)."""
    path = directory()
    if not path:
        return "not_configured"
    try:
        st = os.lstat(path)
    except OSError:
        return "missing"
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return "not_a_directory"
    if stat.S_IMODE(st.st_mode) & 0o077:
        return "not_private"
    if write and not os.access(path, os.W_OK | os.X_OK):
        return "unwritable"
    return ""


def repair() -> dict:
    """Owner-run (`catalyst_journal_repair`): move a torn tail (the bytes after the last complete, well-formed entry)
    to `effects.jsonl.torn-<timestamp>`, so appends can continue, and journal the repair with the discarded byte
    count and the last good hash. Refuses when nothing is torn."""
    fd = _lock_fd()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        raw = _read_bytes()
        good, prev, consumed = [], GENESIS, 0
        for line in raw.split(b"\n"):
            candidate = consumed + len(line) + 1
            if candidate > len(raw) or not line.strip():
                break
            try:
                entry = _parse(line, len(good) + 1)
                _check(entry, prev)
            except JournalError:
                break
            good.append(entry)
            prev = entry.hash
            consumed = candidate
        torn = raw[consumed:]
        if not torn:
            return {"repaired": False, "discarded_bytes": 0}
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        aside = os.path.join(directory(), f"{FILE}.torn-{stamp}")
        tfd = os.open(
            aside, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(tfd, "wb") as handle:
            handle.write(torn)
            handle.flush()
            os.fsync(handle.fileno())
        path = os.path.join(directory(), FILE)
        with open(path, "r+b") as handle:
            handle.truncate(consumed)
            handle.flush()
            os.fsync(handle.fileno())
        entry = _append_locked(
            "repair",
            f"repair:{stamp}",
            {"discarded_bytes": len(torn), "last_good_hash": prev},
        )
        return {
            "repaired": True,
            "discarded_bytes": len(torn),
            "last_good_hash": prev,
            "seq": entry.seq,
        }
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

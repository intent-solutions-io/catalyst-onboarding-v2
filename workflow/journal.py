"""The effect journal (029 section 6.2; bead 9kg.33): the one durable record of effects that live outside the
database's rollback domain, so a restore to the backup's time T can learn what happened after T.

A restore brings every table back to T. The world does not go back: a closure, a revocation, a staff pause, a
resolution, a withdrawal, a confirmed reply outcome, a decision on an uncertain send, a staff role change, a reminder
that left, model budget that was spent. Each of those is appended here, after its transaction commits
(`transaction.on_commit`), as one line of a hash-chained JSON Lines file in `CATALYST_EFFECT_JOURNAL_DIR`, a
directory outside the application backup. The post-restore step (`config.post_restore`) replays the entries after the
backup point against the restored tables; the erasure path (9kg.32) records its intents and completions in the same
file, so only one durable store exists.

Shape of an entry: `seq` (1, 2, ...), `at` (UTC, ISO 8601), `kind`, `key` (the effect's identity: a public reference,
never a numeric id, which recurs after a restore), `data` (codes, counts and digests only: never an address, a name,
a body or a secret), `prev` (the previous entry's hash) and `hash` (SHA-256 over `prev` and the entry's canonical
JSON). Replay is idempotent on (`kind`, `key`): the same effect journaled twice, or replayed twice, changes nothing
the second time. A broken chain, a missing directory or an unreadable file is an error the post-restore step reports
and the lift refuses on (missing evidence never releases restored records).

Writes take an advisory lock on `effects.lock` (web and worker append concurrently), append with O_APPEND and fsync
the file and the directory. Nothing is ever rewritten or removed. The journal is sensitive operational data:
the directory is 0700 and the file 0600.

Not configured (an empty setting) is allowed only in `test` and `development` (config.guards): entries are then
dropped with one warning per process, and the post-restore lift refuses because no evidence exists.
"""

import fcntl
import hashlib
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)
FILE = "effects.jsonl"
LOCK = "effects.lock"
GENESIS = "0" * 64
_state = threading.local()
_warned = {"not_configured": False}


class JournalError(Exception):
    """A reason code: `not_configured`, `unreadable`, `chain_broken`, `malformed`."""

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


def _parse(line: bytes, number: int) -> Entry:
    try:
        raw = json.loads(line)
        entry = Entry(seq=int(raw["seq"]), at=str(raw["at"]), kind=str(raw["kind"]), key=str(raw["key"]),
                      data=dict(raw["data"]), prev=str(raw["prev"]), hash=str(raw["hash"]))
    except (ValueError, KeyError, TypeError):
        raise JournalError("malformed") from None
    if entry.seq != number:
        raise JournalError("chain_broken")
    return entry


def _check(entry: Entry, prev: str) -> None:
    payload = asdict(entry)
    expected = payload.pop("hash")
    if entry.prev != prev or _digest(prev, payload) != expected:
        raise JournalError("chain_broken")


def read() -> list[Entry]:
    """Every entry, in order, with the chain verified. Raises JournalError rather than returning a partial record."""
    if not configured():
        raise JournalError("not_configured")
    path = os.path.join(directory(), FILE)
    try:
        with open(path, "rb") as handle:
            lines = handle.read().split(b"\n")
    except FileNotFoundError:
        if not os.path.isdir(directory()):
            raise JournalError("unreadable") from None
        return []  # a configured, empty journal: nothing has happened yet
    except OSError:
        raise JournalError("unreadable") from None
    entries, prev = [], GENESIS
    for number, line in enumerate((ln for ln in lines if ln.strip()), start=1):
        entry = _parse(line, number)
        _check(entry, prev)
        entries.append(entry)
        prev = entry.hash
    return entries


def head() -> tuple[int, str]:
    """(seq, hash) of the last entry; (0, GENESIS) for an empty journal. The backup records it in its receipt, so
    a restore knows which entries postdate the backup point."""
    entries = read()
    return (entries[-1].seq, entries[-1].hash) if entries else (0, GENESIS)


def _tail(handle) -> tuple[int, str]:
    """The last entry's (seq, hash) read under the lock, without parsing the whole file."""
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    if size == 0:
        return 0, GENESIS
    block = min(size, 65536)
    handle.seek(size - block)
    chunk = handle.read(block)
    last = [ln for ln in chunk.split(b"\n") if ln.strip()]
    if not last:
        raise JournalError("malformed")
    entry = json.loads(last[-1])
    return int(entry["seq"]), str(entry["hash"])


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append(kind: str, key: str, data: dict | None = None) -> Entry | None:
    """Append one entry now (the caller is outside, or at the end of, its transaction). Returns None when the journal
    is not configured (local environments only) or while a replay is in progress (a replay re-applies facts; it
    makes no new ones)."""
    if getattr(_state, "replaying", False):
        return None
    if not configured():
        if not _warned["not_configured"]:
            _warned["not_configured"] = True
            logger.warning("effect journal not configured: effects are not durable in this environment")
        return None
    data = dict(data or {})
    path = os.path.join(directory(), FILE)
    with open(os.path.join(directory(), LOCK), "ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "ab") as handle:
                with open(path, "rb") as reader:
                    seq, prev = _tail(reader)
                payload = {"seq": seq + 1, "at": datetime.now(UTC).isoformat(timespec="microseconds"), "kind": kind,
                           "key": key, "data": data, "prev": prev}
                entry = Entry(**payload, hash=_digest(prev, payload))
                handle.write((_canonical(asdict(entry)) + "\n").encode())
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_dir(directory())
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return entry


def record(kind: str, key: str, data=None) -> None:
    """Append after the current transaction commits (or now, outside one). The Django idiom for "once it is a
    fact": an entry is never written for a transaction that rolled back, so the journal can only miss an effect
    (as today, with no journal), never invent one. `data` may be a callable evaluated at commit time."""
    if getattr(_state, "replaying", False):
        return
    frozen = None if callable(data) else dict(data or {})
    transaction.on_commit(lambda: append(kind, key, data() if frozen is None else frozen))


class replaying:
    """A context in which `append` writes nothing: the post-restore replay re-applies journaled facts through the
    ordinary services, which would otherwise journal them again."""

    def __enter__(self):
        self._previous = getattr(_state, "replaying", False)
        _state.replaying = True
        return self

    def __exit__(self, *exc):
        _state.replaying = self._previous


def after_restore() -> tuple[list[Entry], datetime | None, int | None]:
    """The entries to reconcile after a restore: those after the restored backup's recorded head and before the
    `restore` entry the restore wrote, plus the window start (the backup's start, which the Sent-folder read uses).
    Without a `restore` entry (a hold placed by hand), every entry and no window start: reconciliation is
    idempotent, so reading too much is safe and reading too little is not."""
    entries = read()
    restores = [e for e in entries if e.kind == "restore"]
    if not restores:
        return entries, None, None
    marker = restores[-1]
    backup_seq = marker.data.get("backup_seq")
    since = marker.data.get("backup_started_at")
    start = int(backup_seq) if isinstance(backup_seq, int) and backup_seq >= 0 else 0
    window = datetime.fromtimestamp(float(since), UTC) if isinstance(since, (int, float)) else None
    return [e for e in entries if start < e.seq < marker.seq and e.kind != "restore"], window, marker.seq


def usage_high_water(day: str) -> int:
    """The highest `model_usage` request count journaled for one UTC day (YYYY-MM-DD), cached per process by the
    file's size and modification time, so a budget check re-reads the file only after it grew."""
    if not configured():
        return 0
    path = os.path.join(directory(), FILE)
    try:
        stat = os.stat(path)
    except OSError:
        return 0
    cache = getattr(_state, "usage_cache", None)
    stamp = (path, stat.st_size, stat.st_mtime_ns)
    if cache is None or cache[0] != stamp:
        highs: dict[str, int] = {}
        for entry in read():  # a JournalError propagates: an unknown floor refuses the call (fail closed)
            if entry.kind == "model_usage":
                highs[entry.key] = max(highs.get(entry.key, 0), int(entry.data.get("requests", 0)))
        cache = (stamp, highs)
        _state.usage_cache = cache
    return cache[1].get(f"usage:{day}", 0)

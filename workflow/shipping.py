"""The effect journal's off-host copy (9kg.60; 029 section 6.2's deferred item): host loss is the usual reason to
restore, and the journal lives on the same host as the database, so without a copy elsewhere the effects after the
last backup are lost with it.

`catalyst_journal_ship --to <directory>` (a host timer, every few minutes) copies the journal to a directory on
another machine or mount the host names (9kg.28; never inside the backup output: a backup store is not a backup
source), with `head.json` beside it (identity, seq, hash, time):

- the destination must carry the provisioning marker `catalyst_journal_ship --provision` wrote, so an unmounted
  mount point (an empty directory on the local disk) is refused, never shipped to (`destination_unprovisioned`);
- it reads the file's bytes and verifies their chain in one locked read, so it ships exactly what it verified, and
  holds an exclusive lock on the destination's marker for the run (`ship_in_progress` for a second one);
- the copy is written under a temporary name, fsynced, renamed into place and read back (its digest must match);
  then the head, then the local record. An interruption leaves the destination's journal at or ahead of its head,
  never behind it, and a destination journal with no head is anchored on its own last entry;
- it refuses when the destination holds entries the local journal lacks (`destination_ahead_of_journal`): the local
  journal lost entries it had already shipped (rolled back, emptied or replaced), and overwriting the copy would
  destroy the only record of them. The operator stops, restores the journal from the copy, and ships again; after an
  owner-accepted loss (`catalyst_restore --accept-journal-behind-shipped`), `catalyst_journal_ship --rebaseline`
  moves the old copy aside under a dated name (it is kept) and the next run starts a new one;
- it records what it shipped in `effects.shipped` beside the journal, which the health part reads (lag, and the age
  of the last run, so a dead timer pages even when no effect is written).

The health part (config.system_health.journal_health) pages `effect_journal_ship_lag` once the oldest entry not yet
shipped is older than `CATALYST_JOURNAL_SHIP_LAG_SECONDS` (the journal's RPO, the owner's: 211.7.2), and
`effect_journal_never_shipped` while that is set and nothing was shipped; also `effect_journal_ship_stale` (no run
within the threshold), `effect_journal_behind_shipped` and `effect_journal_shipped_unreadable`. A restore names the
copy (`catalyst_restore --shipped-from <destination>`, whose head it reads with `copy_head`) and refuses a journal that
does not hold that head unless the owner records the loss (`--accept-journal-behind-shipped`): restore the journal from
the copy first.
"""

import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

from workflow import journal

SHIPPED = "effects.shipped"
HEAD = "head.json"
MARKER = ".catalyst-journal-copy"
MARKER_TEXT = b"catalyst effect journal off-host copy v1\n"


class ShipError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _inside(path: Path, other: Path) -> bool:
    return path == other or other in path.parents


def _destination(text: str) -> Path:
    path = Path(text or "")
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ShipError("destination_unavailable")
    resolved, source = path.resolve(), Path(journal.directory()).resolve()
    repository = Path(__file__).resolve().parent.parent
    if _inside(resolved, source) or _inside(source, resolved) or _inside(resolved, repository):
        raise ShipError("destination_unsafe")
    for name in ("CATALYST_AGREEMENT_STORAGE_DIR", "CATALYST_CUSTODY_KEY_DIR", "CATALYST_CUSTODY_KEY_MIRROR_DIR"):
        other = str(getattr(settings, name, "") or "")
        if other and Path(other).is_absolute() and (_inside(resolved, Path(other).resolve())
                                                     or _inside(Path(other).resolve(), resolved)):
            raise ShipError("destination_unsafe")
    return resolved


def provision(destination: str) -> dict:
    """Write the destination's provisioning marker once, on the mounted off-host directory (the host's step, 9kg.28)."""
    target = _destination(destination)
    marker = target / MARKER
    if marker.exists():
        return {"provisioned": "already"}
    _write_atomic(target, MARKER, MARKER_TEXT)
    return {"provisioned": "now"}


def _provisioned(target: Path) -> int:
    """The marker, opened and locked exclusively for this run; refused when absent (an unmounted mount point)."""
    try:
        fd = os.open(target / MARKER, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ShipError("destination_unprovisioned") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ShipError("ship_in_progress") from None
    return fd


def _write_atomic(directory: Path, name: str, data: bytes) -> None:
    temporary = directory / f".{name}.shipping"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(temporary, directory / name)
    handle = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _head(entries) -> dict:
    return {"identity": str(entries[0].data.get("id", "")), "seq": entries[-1].seq, "hash": entries[-1].hash}


def head_string(head: dict) -> str:
    return f"{head['identity']}:{head['seq']}:{head['hash']}"


def _read_head(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ShipError("head_unreadable") from None
    if not (isinstance(data, dict) and isinstance(data.get("seq"), int) and isinstance(data.get("hash"), str)
            and isinstance(data.get("identity"), str)):
        raise ShipError("head_unreadable")
    return data


def copy_head(destination: str) -> dict | None:
    """The head of the copy at a provisioned destination: `head.json`, or, when an interrupted first run left a journal
    without it, the copy's own last entry. None for an empty copy. Raises ShipError."""
    target = _destination(destination)
    if not (target / MARKER).is_file():
        raise ShipError("destination_unprovisioned")
    shipped = _read_head(target / HEAD)
    try:
        raw = (target / journal.FILE).read_bytes()
    except FileNotFoundError:
        return shipped
    except OSError:
        raise ShipError("destination_unreadable") from None
    try:
        copied = journal._entries(raw)
    except journal.JournalError:
        raise ShipError("destination_unreadable") from None
    if copied and (shipped is None or copied[-1].seq > shipped["seq"]):
        return _head(copied)  # the journal is renamed into place before its head: it is never behind it
    return shipped


def ship(destination: str) -> dict:
    if not journal.configured():
        raise ShipError("not_configured")
    target = _destination(destination)
    lock = _provisioned(target)
    try:
        try:
            raw, entries = journal.snapshot()
        except journal.JournalError as exc:
            raise ShipError(f"journal_{exc.code}") from None
        if not entries:
            raise ShipError("nothing_to_ship")
        shipped = copy_head(destination)
        if shipped is not None:
            try:
                journal.verify_anchor(entries, shipped["identity"], shipped["seq"], shipped["hash"])
            except journal.JournalError:
                raise ShipError("destination_ahead_of_journal") from None
        head = {**_head(entries), "shipped_at": datetime.now(UTC).isoformat(timespec="seconds")}
        try:
            _write_atomic(target, journal.FILE, raw)
            if hashlib.sha256((target / journal.FILE).read_bytes()).digest() != hashlib.sha256(raw).digest():
                raise ShipError("destination_readback_mismatch")  # never recorded as shipped
            _write_atomic(target, HEAD, json.dumps(head, sort_keys=True).encode())
            if _read_head(target / HEAD) != head:
                raise ShipError("destination_readback_mismatch")
            _write_atomic(Path(journal.directory()), SHIPPED, json.dumps(head, sort_keys=True).encode())
        except OSError:
            raise ShipError("destination_unwritable") from None
        return {"shipped_seq": head["seq"], "head": head_string(head)}
    finally:
        os.close(lock)


def rebaseline(destination: str) -> dict:
    """After an owner-accepted journal loss: move the old copy and its head aside under a dated name (kept, never
    deleted) and forget the local record, so the next run starts a new copy of the journal as it now is."""
    target = _destination(destination)
    lock = _provisioned(target)
    try:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        moved = 0
        for name in (journal.FILE, HEAD):
            if (target / name).exists():
                os.rename(target / name, target / f"{name}.superseded-{stamp}")
                moved += 1
        local = Path(journal.directory()) / SHIPPED
        if local.exists():
            os.rename(local, Path(journal.directory()) / f"{SHIPPED}.superseded-{stamp}")
        return {"rebaselined": moved, "kept_as": f"*.superseded-{stamp}"}
    finally:
        os.close(lock)


def last_shipped() -> dict | None:
    """What this host last shipped (`effects.shipped` beside the journal), or None. Raises ShipError when unreadable."""
    return _read_head(Path(journal.directory()) / SHIPPED)


def age(now=None) -> int | None:
    """Seconds since the last completed run (its `shipped_at`), or None when nothing was ever shipped: a dead timer
    pages on this even when no effect is written."""
    shipped = last_shipped()
    if shipped is None or not isinstance(shipped.get("shipped_at"), str):
        return None
    when = datetime.fromisoformat(shipped["shipped_at"])
    return max(0, int(((now or datetime.now(UTC)) - when).total_seconds()))


def lag(entries, now=None) -> int | None:
    """Seconds since the oldest entry not yet shipped was written (0 when everything is shipped), or None when
    nothing was ever shipped."""
    shipped = last_shipped()
    if shipped is None:
        return None
    pending = [e for e in entries if e.seq > shipped["seq"]]
    if not pending:
        return 0
    return max(0, int(((now or datetime.now(UTC)) - pending[0].when).total_seconds()))

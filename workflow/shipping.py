"""The effect journal's off-host copy (9kg.60; 029 section 6.2's deferred item): host loss is the usual reason to
restore, and the journal lives on the same host as the database, so without a copy elsewhere the effects after the
last backup are lost with it.

`catalyst_journal_ship --to <directory>` (a host timer, every few minutes) copies the journal to a directory on
another machine or mount the host names (9kg.28; never inside the backup output: a backup store is not a backup
source), with `head.json` beside it (identity, seq, hash, time):

- it reads the file's bytes and verifies their chain in one locked read, so it ships exactly what it verified;
- the copy and the head are written under temporary names, fsynced and renamed into place, so the destination always
  holds a whole journal and the head that matches it;
- it refuses when the destination's head is not in the local journal (`destination_ahead_of_journal`): the local
  journal lost entries it had already shipped (rolled back, emptied or replaced), and overwriting the copy would
  destroy the only record of them;
- it records what it shipped in `effects.shipped` beside the journal, which the health part reads.

The health part (config.system_health.journal_health) pages `effect_journal_ship_lag` once the oldest entry not yet
shipped is older than `CATALYST_JOURNAL_SHIP_LAG_SECONDS` (the journal's RPO, the owner's: 211.7.2), and
`effect_journal_never_shipped` while that is set and nothing was shipped. A restore names the last shipped head
(`catalyst_restore --shipped-head`, read from `head.json` at the destination) and refuses a journal that does not hold
it unless the owner records the loss (`--accept-journal-behind-shipped`): restore the journal from the copy first.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

from workflow import journal

SHIPPED = "effects.shipped"
HEAD = "head.json"


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


def ship(destination: str) -> dict:
    if not journal.configured():
        raise ShipError("not_configured")
    target = _destination(destination)
    try:
        raw, entries = journal.snapshot()
    except journal.JournalError as exc:
        raise ShipError(f"journal_{exc.code}") from None
    if not entries:
        raise ShipError("nothing_to_ship")
    shipped = _read_head(target / HEAD)
    if shipped is not None:
        try:
            journal.verify_anchor(entries, shipped["identity"], shipped["seq"], shipped["hash"])
        except journal.JournalError:
            raise ShipError("destination_ahead_of_journal") from None
    head = {**_head(entries), "shipped_at": datetime.now(UTC).isoformat(timespec="seconds")}
    try:
        _write_atomic(target, journal.FILE, raw)
        _write_atomic(target, HEAD, json.dumps(head, sort_keys=True).encode())
        _write_atomic(Path(journal.directory()), SHIPPED, json.dumps(head, sort_keys=True).encode())
    except OSError:
        raise ShipError("destination_unwritable") from None
    return {"shipped_seq": head["seq"], "head": head_string(head)}


def last_shipped() -> dict | None:
    """What this host last shipped (`effects.shipped` beside the journal), or None. Raises ShipError when unreadable."""
    return _read_head(Path(journal.directory()) / SHIPPED)


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

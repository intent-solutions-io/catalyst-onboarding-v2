"""Derived request-count cache, never a quota or a replacement for the journal.

One constant-size checkpoint and one constant-size file per queried UTC day.
All access holds effects.lock. Missing/stale/corrupt cache state is rebuilt from
the verified chain. Normal reads and append updates do not scan journal history.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from workflow import journal

STATE = "effects.usage.json"
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
GENERATION = re.compile(r"[0-9a-f]{32}")


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("oversized cache")
    value = json.loads(raw)
    if (
        set(value) != {"data", "sha256"}
        or hashlib.sha256(_encode(value["data"])).hexdigest() != value["sha256"]
    ):
        raise ValueError("invalid cache digest")
    return value["data"]


def _write(path, value):
    data = _encode(
        {"data": value, "sha256": hashlib.sha256(_encode(value)).hexdigest()}
    )
    fd, temporary = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        journal._fsync_dir(str(path.parent))
    finally:
        Path(temporary).unlink(missing_ok=True)


def _stamp():
    values = []
    for name in (journal.FILE, "segments", "archive"):
        try:
            st = os.stat(Path(journal.directory()) / name, follow_symlinks=False)
            values.append(
                [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
            )
        except FileNotFoundError:
            values.append(None)
    return values


def _checkpoint(seq, head, generation):
    return {
        "format": 1,
        "generation": generation,
        "seq": seq,
        "hash": head,
        "stamp": _stamp(),
    }


def _value_path(state, day):
    folder = Path(journal.directory()) / ("usage-" + state["generation"])
    if folder.is_symlink():
        raise ValueError("invalid cache directory")
    return folder / (day + ".json")


def _count(state, day):
    value = _read(_value_path(state, day))
    if (
        not isinstance(value, dict)
        or set(value) != {"generation", "day", "requests"}
        or value["generation"] != state["generation"]
        or value["day"] != day
        or type(value["requests"]) is not int
        or value["requests"] < 0
    ):
        raise ValueError("invalid usage")
    return value["requests"]


def _write_count(state, day, value):
    _write(
        _value_path(state, day),
        {"generation": state["generation"], "day": day, "requests": value},
    )


def _usage(entry):
    day = entry.key.removeprefix("usage:")
    count = entry.data.get("requests")
    if (
        not entry.key.startswith("usage:")
        or not DAY.fullmatch(day)
        or type(count) is not int
        or count < 0
    ):
        raise journal.JournalError("malformed")
    return day, count


def rebuild(day=None):
    entries = journal._entries(journal._read_bytes())
    highs = {}
    for entry in entries:
        if entry.kind == "model_usage":
            date, count = _usage(entry)
            highs[date] = max(highs.get(date, 0), count)
    if day is not None:
        highs.setdefault(day, 0)
    generation = secrets.token_hex(16)
    folder = Path(journal.directory()) / ("usage-" + generation)
    folder.mkdir(mode=0o700)
    state = _checkpoint(
        entries[-1].seq if entries else 0,
        entries[-1].hash if entries else journal.GENESIS,
        generation,
    )
    for date, count in highs.items():
        _write_count(state, date, count)
    _write(Path(journal.directory()) / STATE, state)
    # Only disposable derived-cache generations, never journal/erasure history.
    for old in Path(journal.directory()).glob("usage-*"):
        if (
            old == folder
            or not GENERATION.fullmatch(old.name.removeprefix("usage-"))
            or old.is_symlink()
            or not old.is_dir()
        ):
            continue
        files = list(old.iterdir())
        if all(
            p.is_file()
            and not p.is_symlink()
            and DAY.fullmatch(p.name.removesuffix(".json"))
            and p.suffix == ".json"
            for p in files
        ):
            for path in files:
                path.unlink()
            old.rmdir()
    journal._fsync_dir(journal.directory())
    return state


def current(day=None):
    try:
        state = _read(Path(journal.directory()) / STATE)
        if (
            set(state) != {"format", "generation", "seq", "hash", "stamp"}
            or state["format"] != 1
        ):
            raise ValueError("invalid cache")
        if not GENERATION.fullmatch(state["generation"]) or state["stamp"] != _stamp():
            raise ValueError("stale cache")
        path = Path(journal.directory()) / journal.FILE
        if path.exists():
            with path.open("rb") as stream:
                seq, head = journal._tail(stream)
        else:
            seq, head = 0, journal.GENESIS
        if (state["seq"], state["hash"]) != (seq, head):
            raise ValueError("stale checkpoint")
        if day is not None:
            _count(state, day)  # missing is unknown, never an assumed zero
        return state
    except OSError, ValueError, TypeError, KeyError:
        return rebuild(day)


def before_append(kind):
    if kind != "model_usage" and not (Path(journal.directory()) / STATE).exists():
        return None
    return current()


def after_append(state, entry):
    if state is None:
        return
    if entry.kind == "model_usage":
        day, count = _usage(entry)
        try:
            previous = _count(state, day)
        except OSError, ValueError, TypeError, KeyError:
            # The entry is durable already; a missing day needs one verified rebuild.
            rebuild(day)
            return
        _write_count(state, day, max(previous, count))
    state = _checkpoint(entry.seq, entry.hash, state["generation"])
    _write(Path(journal.directory()) / STATE, state)


def high_water(day):
    if not DAY.fullmatch(day):
        raise journal.JournalError("content_refused")
    state = current(day)
    return _count(state, day)

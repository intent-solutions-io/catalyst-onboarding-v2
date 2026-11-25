"""Closed journal segments. Archiving relocates evidence; it never deletes it.

All callers hold effects.lock. Snapshot/transfer retains a flattened, verifiable
chain, including continuation records, so backup anchors keep their global seq.
"""

import os
import json
from pathlib import Path
import re
import stat

from workflow import journal

DIRECTORIES = ("segments", "archive")
NAME = re.compile(r"segment-(\d{20})-(\d{20})\.jsonl")
LAYOUT = "effects.layout.json"


def paths():
    found = {}
    for name in DIRECTORIES:
        folder = Path(journal.directory()) / name
        if not folder.exists():
            continue
        if folder.is_symlink() or not folder.is_dir():
            raise journal.JournalError("segment_layout_invalid")
        for path in folder.iterdir():
            match = NAME.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_file():
                raise journal.JournalError("segment_layout_invalid")
            start, end = map(int, match.groups())
            if start < 1 or end < start or start in found:
                raise journal.JournalError("segment_layout_invalid")
            found[start] = (end, path)
    previous = 0
    result = []
    for start, (end, path) in sorted(found.items()):
        if start != previous + 1:
            raise journal.JournalError("segment_gap")
        result.append((start, end, path))
        previous = end
    return result


def read_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise journal.JournalError("segment_layout_invalid")
        return stream.read()


def closed_bytes():
    chunks = []
    for start, end, path in paths():
        raw = read_file(path)
        lines = raw.splitlines()
        if not raw.endswith(b"\n") or len(lines) != end - start + 1:
            raise journal.JournalError("segment_layout_invalid")
        first = journal._parse(lines[0], start)
        journal._parse(lines[-1], end)
        if first.kind != ("genesis" if start == 1 else "continues"):
            raise journal.JournalError("segment_layout_invalid")
        chunks.append(raw)
    return b"".join(chunks)


def read_all(validate_boundary=True):
    marker = Path(journal.directory()) / LAYOUT
    if marker.exists():
        try:
            if json.loads(read_file(marker)) != {"format": journal.SEGMENT_FORMAT}:
                raise ValueError
        except ValueError, TypeError:
            raise journal.JournalError("segment_layout_invalid") from None
    prefix = closed_bytes()
    if prefix and not marker.exists():
        raise journal.JournalError("segment_layout_missing")
    path = Path(journal.directory()) / journal.FILE
    try:
        active = read_file(path)
    except FileNotFoundError:
        if not Path(journal.directory()).is_dir():
            raise journal.JournalError("unreadable") from None
        active = b""
    if prefix and active and validate_boundary:
        lines = prefix.splitlines()
        end = journal._parse(lines[-1], len(lines))
        first = journal._parse(active.splitlines()[0], end.seq + 1)
        if first.kind != "continues":
            raise journal.JournalError("segment_layout_invalid")
    return prefix + active


def predecessor():
    """Used only when an empty active file needs crash-safe continuation."""
    entries = journal._entries(read_all())
    return entries[-1] if entries else None


def _folder(name):
    path = Path(journal.directory()) / name
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise journal.JournalError("segment_layout_invalid")
    journal._fsync_dir(journal.directory())
    return path


def rotate_locked():
    entries = journal._entries(read_all())
    if not entries:
        raise journal.JournalError("journal_empty")
    # Written before any rename. Deployment refuses a non-segment-aware image
    # even if this process dies before completing the first rotation.
    # The layout is authoritative metadata, not a usage cache envelope.
    marker = Path(journal.directory()) / LAYOUT
    if not marker.exists():
        temporary = marker.with_suffix(".pending")
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps({"format": journal.SEGMENT_FORMAT}).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
        journal._fsync_dir(journal.directory())
    source = Path(journal.directory()) / journal.FILE
    if not source.exists() or not source.stat().st_size:
        # A process died after the rename: complete that rotation, not a new one.
        prior = entries[-1]
        entry = journal._append_locked(
            "continues", f"segment:{prior.seq}", {"seq": prior.seq, "hash": prior.hash}
        )
        return {"rotated": False, "recovered": True, "seq": entry.seq}
    active = read_file(source)
    first = journal._parse(
        active.splitlines()[0], entries[-1].seq - len(active.splitlines()) + 1
    )
    last = entries[-1]
    target = _folder("segments") / f"segment-{first.seq:020d}-{last.seq:020d}.jsonl"
    if target.exists():
        raise journal.JournalError("segment_layout_invalid")
    os.rename(source, target)
    journal._fsync_dir(str(target.parent))
    journal._fsync_dir(journal.directory())
    entry = journal._append_locked(
        "continues", f"segment:{last.seq}", {"seq": last.seq, "hash": last.hash}
    )
    return {
        "rotated": True,
        "recovered": False,
        "segment": target.name,
        "seq": entry.seq,
    }


def archive_locked(receipts):
    """The operator supplies the complete retained-backup receipt inventory.

    Every anchor is checked against the full chain. A segment containing any
    retained backup's anchor stays hot. Archived segments remain part of every
    read, transfer and restore; POL-10 has not authorized pruning history.
    """
    entries = journal._entries(read_all())
    anchors = []
    for receipt in receipts:
        seq = receipt.get("effect_journal_seq")
        identity = receipt.get("effect_journal_id")
        head = receipt.get("effect_journal_head")
        if (
            type(seq) is not int
            or seq < 1
            or not isinstance(identity, str)
            or not identity
            or not isinstance(head, str)
        ):
            raise journal.JournalError("backup_anchor_invalid")
        journal.verify_anchor(entries, identity, seq, head)
        anchors.append(seq)
    eligible, protected, reheat = [], [], []
    for start, end, path in paths():
        if any(start <= seq <= end for seq in anchors):
            protected.append(path)
            if path.parent.name == "archive":
                reheat.append(path)
        elif path.parent.name != "archive":
            eligible.append(path)
    archive = _folder("archive")
    hot = _folder("segments")
    for path, folder in [(p, hot) for p in reheat] + [(p, archive) for p in eligible]:
        destination = folder / path.name
        if destination.exists():
            raise journal.JournalError("segment_layout_invalid")
        os.rename(path, destination)
        journal._fsync_dir(str(folder))
        journal._fsync_dir(str(path.parent))
    return {
        "archived": [p.name for p in eligible],
        "protected": [p.name for p in protected],
        "returned_to_hot": [p.name for p in reheat],
        "retained_backups": len(anchors),
    }

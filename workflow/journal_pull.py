"""Receiver-initiated journal transfer. Preparing a local copy never means shipped.

The trusted off-host receiver validates and persists the package, then returns its receipt
over the host's authenticated transport. Only that receipt may acknowledge the current
export. This module establishes content consistency, not the physical location or SSH
identity of the receiver; those are deployment checks.
"""

import argparse
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from django.conf import settings

from workflow import journal, shipping

PACKET = "transfer.json"
PENDING = "effects.pending-transfer"
RECEIPT = "receipt.json"
FIELDS = {
    "schema",
    "export_ref",
    "exported_at",
    "identity",
    "seq",
    "hash",
    "sha256",
    "state",
}


def _json(data):
    return json.dumps(data, sort_keys=True).encode()


def _private(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise shipping.ShipError("transfer_directory_unavailable")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise shipping.ShipError("transfer_directory_not_private")
    return path


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise shipping.ShipError("transfer_file_unavailable")
    return path.read_bytes()


def _packet(value, state):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise shipping.ShipError("transfer_receipt_invalid")
    if (
        type(value["schema"]) is not int
        or value["schema"] != 1
        or value["state"] != state
        or type(value["seq"]) is not int
        or value["seq"] < 1
        or any(
            not isinstance(value[key], str) or not re.fullmatch(pattern, value[key])
            for key, pattern in (
                ("export_ref", r"[0-9a-f]{32}"),
                ("identity", r"[0-9a-f]{32}"),
                ("hash", r"[0-9a-f]{64}"),
                ("sha256", r"[0-9a-f]{64}"),
            )
        )
    ):
        raise shipping.ShipError("transfer_receipt_invalid")
    try:
        when = datetime.fromisoformat(value["exported_at"])
        if when.tzinfo is None or when.utcoffset().total_seconds() != 0:
            raise ValueError
    except TypeError, ValueError, AttributeError:
        raise shipping.ShipError("transfer_receipt_invalid") from None
    return value


@contextmanager
def _source_lock():
    if not journal.configured():
        raise shipping.ShipError("not_configured")
    path = _private(journal.directory()) / "effects.transfer.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise shipping.ShipError("transfer_in_progress") from None
        yield
    finally:
        os.close(fd)


def _anchor(entries, head, code):
    try:
        journal.verify_anchor(entries, head["identity"], head["seq"], head["hash"])
    except journal.JournalError, KeyError, TypeError:
        raise shipping.ShipError(code) from None


def _head(packet):
    return {
        **{key: packet[key] for key in ("identity", "seq", "hash")},
        "shipped_at": packet["exported_at"],
    }


def stage(destination):
    """Prepare a consistent local export. No shipped watermark is written."""
    with _source_lock():
        target = _private(shipping._destination(destination))
        lock = shipping._provisioned(target)
        try:
            raw, entries = journal.snapshot()
            if not entries:
                raise shipping.ShipError("nothing_to_ship")
            packet = {
                "schema": 1,
                "export_ref": secrets.token_hex(16),
                "exported_at": datetime.now(UTC).isoformat(),
                **shipping._head(entries),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "state": "staged",
            }
            shipping._write_atomic(target, journal.FILE, raw)
            shipping._write_atomic(target, PACKET, _json(packet))
            checked, _ = package(target)
            if checked != packet:
                raise shipping.ShipError("transfer_readback_mismatch")
            shipping._write_atomic(Path(journal.directory()), PENDING, _json(packet))
            return packet
        finally:
            os.close(lock)


def package(directory):
    """Read the pulled package; mixed generations and corrupted bytes are refused."""
    source = _private(directory)
    try:
        packet = _packet(json.loads(_read(source / PACKET)), "staged")
        raw = _read(source / journal.FILE)
        entries = journal._entries(raw)
    except ValueError, journal.JournalError:
        raise shipping.ShipError("transfer_content_invalid") from None
    if (
        not entries
        or hashlib.sha256(raw).hexdigest() != packet["sha256"]
        or shipping._head(entries)
        != {k: packet[k] for k in ("identity", "seq", "hash")}
    ):
        raise shipping.ShipError("transfer_content_mismatch")
    return packet, raw


def receive(source, destination):
    """Run on the independent receiver after pulling into its private staging directory."""
    packet, raw = package(source)
    target = _private(shipping._destination(destination))
    if shipping._inside(target.resolve(), Path(source).resolve()) or shipping._inside(
        Path(source).resolve(), target.resolve()
    ):
        raise shipping.ShipError("destination_unsafe")
    lock = shipping._provisioned(target)
    try:
        previous = shipping.copy_head(str(target))
        if previous is not None:
            _anchor(journal._entries(raw), previous, "destination_ahead_of_journal")
        shipping._write_atomic(target, journal.FILE, raw)
        if _read(target / journal.FILE) != raw:
            raise shipping.ShipError("destination_readback_mismatch")
        head = _head(packet)
        shipping._write_atomic(target, shipping.HEAD, _json(head))
        if shipping._read_head(target / shipping.HEAD) != head:
            raise shipping.ShipError("destination_readback_mismatch")
        receipt = {**packet, "state": "received"}
        shipping._write_atomic(target, RECEIPT, _json(receipt))
        if json.loads(_read(target / RECEIPT)) != receipt:
            raise shipping.ShipError("destination_readback_mismatch")
        return receipt
    finally:
        os.close(lock)


def acknowledge(receipt):
    """Trusted receiver's receipt only; replay cannot renew the snapshot's age."""
    receipt = _packet(receipt, "received")
    with _source_lock():
        pending = _packet(
            json.loads(_read(Path(journal.directory()) / PENDING)), "staged"
        )
        if {**receipt, "state": "staged"} != pending:
            raise shipping.ShipError("transfer_receipt_not_current")
        _, entries = journal.snapshot()
        _anchor(entries, receipt, "local_journal_lost_export")
        previous = shipping.last_shipped()
        head = _head(receipt)
        if previous is not None:
            _anchor(entries, previous, "local_journal_behind_shipped")
            if previous["seq"] > head["seq"] or datetime.fromisoformat(
                previous["shipped_at"]
            ) > datetime.fromisoformat(head["shipped_at"]):
                raise shipping.ShipError("transfer_receipt_older_than_shipped")
        shipping._write_atomic(Path(journal.directory()), shipping.SHIPPED, _json(head))
        return {"shipped_seq": head["seq"], "head": shipping.head_string(head)}


def main():
    parser = argparse.ArgumentParser(
        description="Verify and persist a pulled journal on the receiver; no database or provider access."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--provision", action="store_true")
    args = parser.parse_args()
    # Standalone receiver in the pinned application image. No production settings, secrets or DB boot.
    settings.configure(CATALYST_EFFECT_JOURNAL_DIR=str(Path(args.source).resolve()))
    try:
        if args.provision:
            _private(args.to)
            result = shipping.provision(args.to)
        else:
            result = receive(args.source, args.to)
        print(json.dumps(result, sort_keys=True))
    except (shipping.ShipError, journal.JournalError, OSError, ValueError) as exc:
        parser.exit(
            1, f"journal receive refused: {getattr(exc, 'code', type(exc).__name__)}\n"
        )


if __name__ == "__main__":
    main()

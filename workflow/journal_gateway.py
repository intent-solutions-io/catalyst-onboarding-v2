"""Restricted journal transport; invoke through an operator-owned SSH forced command.

The wire format is one bounded JSON packet line followed by the exact journal bytes.
No remote paths, shell commands, archive extraction or provider credentials are needed.
Only a trusted receiver may submit acknowledgments; this is not proof of host location.
"""

import argparse
import json
import os
from pathlib import Path
import sys

from django.conf import settings

from workflow import journal, journal_pull, shipping

METADATA_LIMIT = 4096
OPERATIONS = ("export-v1", "ack-v1")


def serve(operation, stage, incoming, outgoing):
    # Check before reading input or touching any file. Do not split/eval SSH commands.
    if operation not in OPERATIONS:
        raise shipping.ShipError("transport_operation_refused")
    if operation == "export-v1":
        expected = journal_pull.stage(stage)
        packet, raw = journal_pull.package(stage)
        if packet != expected:
            raise shipping.ShipError("transfer_readback_mismatch")
        outgoing.write(journal_pull._json(packet) + b"\n")
        outgoing.write(raw)
    else:
        data = incoming.read(METADATA_LIMIT + 1)
        if len(data) > METADATA_LIMIT:
            raise shipping.ShipError("transport_receipt_too_large")
        result = journal_pull.acknowledge(json.loads(data))
        outgoing.write(journal_pull._json(result) + b"\n")
    outgoing.flush()


def receive_stream(incoming, stage, destination):
    """Validate the complete stream before updating private staging or the receiver."""
    header = incoming.readline(METADATA_LIMIT + 1)
    if len(header) > METADATA_LIMIT or not header.endswith(b"\n"):
        raise shipping.ShipError("transport_header_invalid")
    packet = journal_pull._packet(json.loads(header), "staged")
    raw = incoming.read()
    journal_pull.validate_content(packet, raw)
    target = journal_pull._private(stage)
    copy = journal_pull._private(shipping._destination(destination))
    if shipping._inside(target.resolve(), copy.resolve()) or shipping._inside(
        copy.resolve(), target.resolve()
    ):
        raise shipping.ShipError("destination_unsafe")
    lock = shipping._provisioned(target)
    try:
        shipping._write_atomic(target, journal.FILE, raw)
        shipping._write_atomic(target, journal_pull.PACKET, journal_pull._json(packet))
        return journal_pull.receive(str(target), destination)
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="mode", required=True)
    source = commands.add_parser("source", allow_abbrev=False)
    source.add_argument("--journal", required=True)
    source.add_argument("--stage", required=True)
    source.add_argument("--operation", choices=OPERATIONS, required=True)
    receiver = commands.add_parser("receive", allow_abbrev=False)
    receiver.add_argument("--stage", required=True)
    receiver.add_argument("--to", required=True)
    args = parser.parse_args()
    # No Django setup, database, production settings, custody keys or provider secrets.
    settings.configure(
        CATALYST_EFFECT_JOURNAL_DIR=str(
            Path(args.journal if args.mode == "source" else args.stage).resolve()
        )
    )
    try:
        if args.mode == "source":
            serve(args.operation, args.stage, sys.stdin.buffer, sys.stdout.buffer)
        else:
            result = receive_stream(sys.stdin.buffer, args.stage, args.to)
            print(json.dumps(result, sort_keys=True))
    except (shipping.ShipError, journal.JournalError, OSError, ValueError) as exc:
        parser.exit(
            1,
            f"journal transport refused: {getattr(exc, 'code', type(exc).__name__)}\n",
        )


if __name__ == "__main__":
    main()

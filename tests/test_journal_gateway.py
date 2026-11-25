"""The SSH gateway exposes only journal exports and authenticated receipt submission."""

from io import BytesIO
import json
import os
import subprocess
import sys

import pytest

from tests.test_journal_pull import transfer  # noqa: F401
from workflow import journal, journal_gateway, journal_pull, shipping


@pytest.mark.parametrize(
    "operation",
    ["", "export-v1; id", "export-v1 /etc/passwd", "ack-v1\n", "sh", "--help"],
)
def test_unknown_operations_refuse_before_any_io(operation):
    class Forbidden:
        def read(self, *args):
            pytest.fail("unexpected input read")

        def write(self, *args):
            pytest.fail("unexpected output write")

    with pytest.raises(shipping.ShipError, match="transport_operation_refused"):
        journal_gateway.serve(operation, "/missing", Forbidden(), Forbidden())


def test_stream_requires_receiver_persistence_before_acknowledgment(transfer, tmp_path):
    stage, receiver = transfer
    pulled = tmp_path / "pulled"
    pulled.mkdir(mode=0o700)
    shipping.provision(str(pulled))
    wire = BytesIO()
    journal_gateway.serve("export-v1", str(stage), BytesIO(), wire)
    assert shipping.last_shipped() is None
    wire.seek(0)
    receipt = journal_gateway.receive_stream(wire, str(pulled), str(receiver))
    assert shipping.last_shipped() is None
    assert (receiver / journal.FILE).read_bytes() == (stage / journal.FILE).read_bytes()
    result = BytesIO()
    journal_gateway.serve(
        "ack-v1", str(stage), BytesIO(json.dumps(receipt).encode()), result
    )
    assert json.loads(result.getvalue())["shipped_seq"] == receipt["seq"]
    assert shipping.last_shipped()["shipped_at"] == receipt["exported_at"]


@pytest.mark.parametrize(
    "fault", ["header", "truncated", "extra", "oversized", "staged_ack"]
)
def test_bad_streams_and_staged_receipts_preserve_receiver_and_watermark(
    transfer, fault
):
    stage, receiver = transfer
    packet = journal_pull.stage(str(stage))
    journal_pull.receive(str(stage), str(receiver))
    original = (receiver / journal.FILE).read_bytes()
    raw = (stage / journal.FILE).read_bytes()
    wire = json.dumps(packet).encode() + b"\n" + raw
    if fault == "staged_ack":
        with pytest.raises(shipping.ShipError, match="transfer_receipt_invalid"):
            journal_gateway.serve(
                "ack-v1", str(stage), BytesIO(json.dumps(packet).encode()), BytesIO()
            )
    else:
        wire = {
            "header": b"{}",
            "truncated": wire[:-20],
            "extra": wire + b"not journal data",
            "oversized": b" " * 4097 + wire,
        }[fault]
        with pytest.raises((shipping.ShipError, ValueError)):
            journal_gateway.receive_stream(BytesIO(wire), str(stage), str(receiver))
    assert (receiver / journal.FILE).read_bytes() == original
    assert shipping.last_shipped() is None


def test_oversized_receipt_and_overlapping_paths_refuse(transfer):
    stage, receiver = transfer
    with pytest.raises(shipping.ShipError, match="transport_receipt_too_large"):
        journal_gateway.serve("ack-v1", str(stage), BytesIO(b" " * 4097), BytesIO())
    wire = BytesIO()
    journal_gateway.serve("export-v1", str(stage), BytesIO(), wire)
    previous = (stage / journal.FILE).read_bytes()
    wire.seek(0)
    with pytest.raises(shipping.ShipError, match="destination_unsafe"):
        journal_gateway.receive_stream(wire, str(stage), str(stage))
    assert (stage / journal.FILE).read_bytes() == previous
    assert shipping.last_shipped() is None


def test_cli_export_receive_ack_needs_no_database_or_production_settings(
    transfer, tmp_path
):
    stage, receiver = transfer
    pulled = tmp_path / "pulled"
    pulled.mkdir(mode=0o700)
    shipping.provision(str(pulled))
    base = [sys.executable, "-m", "workflow.journal_gateway"]
    source = ["source", "--journal", str(journal.directory()), "--stage", str(stage)]

    def run(args, data=b""):
        return subprocess.run(
            base + args,
            input=data,
            capture_output=True,
            env={"PATH": os.environ["PATH"], "DJANGO_SETTINGS_MODULE": "unavailable"},
            timeout=15,
        )

    exported = run(source + ["--operation=export-v1"])
    assert exported.returncode == 0, exported.stderr
    assert shipping.last_shipped() is None
    received = run(
        ["receive", "--stage", str(pulled), "--to", str(receiver)], exported.stdout
    )
    assert received.returncode == 0, received.stderr
    assert shipping.last_shipped() is None
    acknowledged = run(source + ["--operation=ack-v1"], received.stdout)
    assert acknowledged.returncode == 0, acknowledged.stderr
    assert shipping.last_shipped()["hash"] == json.loads(received.stdout)["hash"]
    rejected = run(source + ["--operation=export-v1; cat /etc/passwd"])
    assert rejected.returncode != 0
    assert not rejected.stdout

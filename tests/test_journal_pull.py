"""Off-host pull receipts cannot turn a local staging copy into shipped evidence."""

from datetime import datetime, timedelta
from io import StringIO
import json
import os
import subprocess
import sys

import pytest
from django.core.management import call_command, CommandError

from config import runtime, system_health
from workflow import journal, journal_pull, shipping


@pytest.fixture
def transfer(effect_journal, tmp_path, settings):
    paths = [tmp_path / name for name in ("stage", "receiver")]
    for path in paths:
        path.mkdir(mode=0o700)
        shipping.provision(str(path))
    settings.CATALYST_JOURNAL_SHIP_LAG_SECONDS = 900
    assert journal.append("model_usage", "usage:2026-11-01", {"requests": 1})
    return paths


def test_only_a_verified_receiver_receipt_marks_the_current_export_shipped(transfer):
    stage, receiver = transfer
    packet = journal_pull.stage(str(stage))
    assert shipping.last_shipped() is None
    assert "effect_journal_never_shipped" in system_health.journal_health()["anomalies"]
    with pytest.raises(shipping.ShipError, match="transfer_receipt_invalid"):
        journal_pull.acknowledge(packet)
    receipt = journal_pull.receive(str(stage), str(receiver))
    assert shipping.last_shipped() is None
    assert (receiver / journal.FILE).read_bytes() == (stage / journal.FILE).read_bytes()
    assert shipping.copy_head(str(receiver))["hash"] == packet["hash"]
    result = journal_pull.acknowledge(receipt)
    assert result["shipped_seq"] == packet["seq"]
    before = shipping.last_shipped()
    assert before["shipped_at"] == packet["exported_at"]
    assert journal_pull.acknowledge(receipt) == result
    assert shipping.last_shipped() == before
    assert (
        shipping.age(
            datetime.fromisoformat(packet["exported_at"]) + timedelta(seconds=901)
        )
        == 901
    )
    assert system_health.journal_health()["anomalies"] == []


def test_corrupted_or_mixed_packages_never_overwrite_the_receiver(transfer):
    stage, receiver = transfer
    first = journal_pull.stage(str(stage))
    journal_pull.receive(str(stage), str(receiver))
    retained = (receiver / journal.FILE).read_bytes()
    journal.append("model_usage", "usage:2026-11-02", {"requests": 2})
    journal_pull.stage(str(stage))
    packet = (stage / journal_pull.PACKET).read_bytes()
    (stage / journal_pull.PACKET).write_text(json.dumps(first))
    with pytest.raises(shipping.ShipError, match="transfer_content_mismatch"):
        journal_pull.receive(str(stage), str(receiver))
    (stage / journal_pull.PACKET).write_bytes(packet)
    raw = (stage / journal.FILE).read_bytes()
    (stage / journal.FILE).write_bytes(raw[:-3])
    with pytest.raises(shipping.ShipError, match="transfer_content_invalid"):
        journal_pull.receive(str(stage), str(receiver))
    assert (receiver / journal.FILE).read_bytes() == retained
    assert shipping.last_shipped() is None


def test_a_lost_source_tail_refuses_acknowledgment_and_cannot_replace_the_receiver(
    transfer, effect_journal
):
    stage, receiver = transfer
    journal_pull.stage(str(stage))
    receipt = journal_pull.receive(str(stage), str(receiver))
    retained = (receiver / journal.FILE).read_bytes()
    source = effect_journal / journal.FILE
    source.write_bytes(b"".join(source.read_bytes().splitlines(keepends=True)[:-1]))
    with pytest.raises(shipping.ShipError, match="local_journal_lost_export"):
        journal_pull.acknowledge(receipt)
    assert shipping.last_shipped() is None
    journal_pull.stage(str(stage))
    with pytest.raises(shipping.ShipError, match="destination_ahead_of_journal"):
        journal_pull.receive(str(stage), str(receiver))
    assert (receiver / journal.FILE).read_bytes() == retained


def test_an_old_receipt_or_different_lineage_cannot_advance_the_source_or_replace_the_copy(
    transfer, effect_journal
):
    stage, receiver = transfer
    journal_pull.stage(str(stage))
    old = journal_pull.receive(str(stage), str(receiver))
    journal_pull.stage(str(stage))
    with pytest.raises(shipping.ShipError, match="transfer_receipt_not_current"):
        journal_pull.acknowledge(old)
    new = journal_pull.receive(str(stage), str(receiver))
    journal_pull.acknowledge(new)
    retained = (receiver / journal.FILE).read_bytes()
    (effect_journal / journal.FILE).unlink()
    journal.ensure_genesis()
    journal_pull.stage(str(stage))
    with pytest.raises(shipping.ShipError, match="destination_ahead_of_journal"):
        journal_pull.receive(str(stage), str(receiver))
    assert (receiver / journal.FILE).read_bytes() == retained
    assert shipping.last_shipped()["identity"] == new["identity"]


def test_an_interrupted_receiver_keeps_the_new_tail_and_never_returns_a_receipt(
    transfer, monkeypatch
):
    stage, receiver = transfer
    journal_pull.stage(str(stage))
    first = journal_pull.receive(str(stage), str(receiver))
    journal_pull.acknowledge(first)
    journal.append("model_usage", "usage:2026-11-02", {"requests": 2})
    second = journal_pull.stage(str(stage))
    real = shipping._write_atomic

    def interrupted(directory, name, data):
        if directory == receiver and name == shipping.HEAD:
            raise OSError("synthetic receiver interruption")
        real(directory, name, data)

    monkeypatch.setattr(shipping, "_write_atomic", interrupted)
    with pytest.raises(OSError):
        journal_pull.receive(str(stage), str(receiver))
    assert shipping.last_shipped()["seq"] == first["seq"]
    assert json.loads((receiver / journal_pull.RECEIPT).read_text()) == first
    assert shipping.copy_head(str(receiver))["seq"] == second["seq"]
    monkeypatch.setattr(shipping, "_write_atomic", real)
    recovered = journal_pull.receive(str(stage), str(receiver))
    journal_pull.acknowledge(recovered)
    assert shipping.last_shipped()["seq"] == second["seq"]


def test_the_receiver_cli_needs_no_production_settings_or_database_and_management_can_ack(
    transfer, tmp_path, monkeypatch
):
    stage, receiver = transfer
    monkeypatch.setitem(runtime._declared, "kind", "management")
    output = StringIO()
    call_command("catalyst_journal_transfer", "--stage", str(stage), stdout=output)
    assert json.loads(output.getvalue())["state"] == "staged"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "workflow.journal_pull",
            "--source",
            str(stage),
            "--to",
            str(receiver),
        ],
        env={
            "PATH": os.environ["PATH"],
            "DJANGO_SETTINGS_MODULE": "deliberately_unavailable",
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    call_command(
        "catalyst_journal_transfer", "--acknowledge", str(path), stdout=StringIO()
    )
    assert shipping.last_shipped()["hash"] == receipt["hash"]
    monkeypatch.setitem(runtime._declared, "kind", "worker")
    with pytest.raises(CommandError, match="not_a_management_process"):
        call_command("catalyst_journal_transfer", "--stage", str(stage))


def test_transfer_refuses_unprovisioned_public_and_overlapping_directories(
    transfer, tmp_path
):
    stage, receiver = transfer
    missing = tmp_path / "unprovisioned"
    missing.mkdir(mode=0o700)
    with pytest.raises(shipping.ShipError, match="destination_unprovisioned"):
        journal_pull.stage(str(missing))
    stage.chmod(0o755)
    with pytest.raises(shipping.ShipError, match="transfer_directory_not_private"):
        journal_pull.stage(str(stage))
    stage.chmod(0o700)
    journal_pull.stage(str(stage))
    with pytest.raises(shipping.ShipError, match="destination_unsafe"):
        journal_pull.receive(str(stage), str(stage))

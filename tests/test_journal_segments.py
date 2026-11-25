"""9kg.61: retained evidence, crash recovery and bounded usage-accounting reads."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import uuid

import pytest
from django.core.management import call_command, CommandError

from tests.test_backup_commands import (
    admin,
    drop,
    new_database,
    run_backup,
    run_restore,
)
from tests.test_outbound import p2  # noqa: F401
from workflow import (
    journal,
    journal_segments as segments,
    journal_usage as usage,
    shipping,
)


def model(n, day="2026-11-01"):
    return journal.append("model_usage", f"usage:{day}", {"requests": n})


def receipt():
    seq, head, identity = journal.head()
    return {
        "effect_journal_seq": seq,
        "effect_journal_head": head,
        "effect_journal_id": identity,
    }


def test_segments_keep_global_anchors_and_archive_only_unanchored_ranges(
    effect_journal, tmp_path
):
    first = model(7)
    anchored = receipt()
    identity = journal.identity()
    journal.rotate()
    second = model(9)
    journal.rotate()
    before, entries = journal.snapshot()
    assert [e.seq for e in entries] == list(range(1, 6))
    assert entries[2].data == {"seq": first.seq, "hash": first.hash}
    assert entries[4].data == {"seq": second.seq, "hash": second.hash}
    result = journal.archive_segments([anchored])
    assert len(result["protected"]) == len(result["archived"]) == 1
    assert journal.snapshot()[0] == before and journal.identity() == identity
    assert journal.usage_high_water("2026-11-01") == 9
    journal.verify_anchor(journal.read(), identity, first.seq, first.hash)
    destination = tmp_path / "receiver"
    destination.mkdir(mode=0o700)
    shipping.provision(str(destination))
    shipping.ship(str(destination))
    assert (destination / journal.FILE).read_bytes() == before
    assert journal._entries(before) == entries
    journal.archive_segments([])
    refreshed = journal.archive_segments([anchored])
    assert len(refreshed["returned_to_hot"]) == 1
    assert journal.snapshot()[0] == before


def test_unknown_or_foreign_backup_anchor_refuses_archival_without_moving_evidence(
    effect_journal,
):
    model(2)
    own = receipt()
    journal.rotate()
    before = segments.paths()
    for bad in (
        {},
        {**own, "effect_journal_seq": 0},
        {**own, "effect_journal_id": "different"},
        {**own, "effect_journal_head": "0" * 64},
    ):
        with pytest.raises(journal.JournalError):
            journal.archive_segments([own, bad])
        assert segments.paths() == before


def test_rotation_crash_after_rename_resumes_the_existing_lineage(
    effect_journal, monkeypatch
):
    model(4)
    old = receipt()
    with monkeypatch.context() as patch:
        patch.setattr(
            journal,
            "_append_locked",
            lambda *a: (_ for _ in ()).throw(OSError("crash")),
        )
        with pytest.raises(OSError):
            journal.rotate()
    assert not (effect_journal / journal.FILE).exists()
    assert journal.ensure_genesis() is False
    assert journal.identity() == old["effect_journal_id"]
    assert [e.kind for e in journal.read()] == ["genesis", "model_usage", "continues"]
    assert model(5).seq == 4 and journal.usage_high_water("2026-11-01") == 5


def test_torn_continuation_repair_preserves_closed_evidence(
    effect_journal, monkeypatch
):
    model(4)
    with monkeypatch.context() as patch:

        def interrupted(handle, kind, key, data, seq, prev):
            handle.write(b'{"seq":3')
            handle.flush()
            raise OSError("crash")

        patch.setattr(journal, "_write_entry", interrupted)
        with pytest.raises(OSError):
            journal.rotate()
    closed = [(p, p.read_bytes()) for _, _, p in segments.paths()]
    repaired = journal.repair()
    assert repaired["repaired"] and repaired["discarded_bytes"] == len(b'{"seq":3')
    assert all(p.read_bytes() == raw for p, raw in closed)
    assert [e.kind for e in journal.read()] == [
        "genesis",
        "model_usage",
        "continues",
        "repair",
    ]
    assert journal.usage_high_water("2026-11-01") == 4


def test_missing_or_altered_closed_segment_fails_the_full_chain_and_cannot_be_repaired(
    effect_journal,
):
    model(3)
    journal.rotate()
    path = segments.paths()[0][2]
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"requests":3', b'"requests":8'))
    with pytest.raises(journal.JournalError, match="chain_broken"):
        journal.read()
    with pytest.raises(journal.JournalError, match="chain_broken"):
        journal.repair()
    path.write_bytes(raw)
    assert journal.usage_high_water("2026-11-01") == 3
    path.unlink()
    with pytest.raises(journal.JournalError):
        journal.usage_high_water("2026-11-01")


def test_continuation_metadata_is_verified_even_with_a_recomputed_hash(effect_journal):
    model(3)
    journal.rotate()
    path = effect_journal / journal.FILE
    data = json.loads(path.read_bytes())
    data["data"]["seq"] = 999
    data.pop("hash")
    data["hash"] = journal._digest(data["prev"], data)
    path.write_text(journal._canonical(data) + "\n")
    with pytest.raises(journal.JournalError, match="chain_broken"):
        journal.read()


def test_usage_reads_and_updates_do_not_rescan_history_after_initialization(
    effect_journal, monkeypatch
):
    model(1)
    assert journal.usage_high_water("2026-11-01") == 1
    with monkeypatch.context() as patch:

        def no_scan(*args):
            raise AssertionError("steady-state accounting scanned journal history")

        patch.setattr(journal, "_read_bytes", no_scan)
        patch.setattr(journal, "read", no_scan)
        for n in range(2, 15):
            assert model(n)
            assert journal.append(
                "automation_pause",
                f"pause:{uuid.uuid4()}",
                {"state": "paused", "by": "staff"},
            )
            assert journal.usage_high_water("2026-11-01") == n
    assert model(2) and journal.usage_high_water("2026-11-01") == 14
    assert model(20, "2000-01-01") and journal.usage_high_water("2000-01-01") == 20
    assert journal.usage_high_water("2026-11-01") == 14


def test_cache_write_crash_and_missing_day_rebuild_without_lowering_usage(
    effect_journal, monkeypatch
):
    model(5)
    original = usage._write
    with monkeypatch.context() as patch:

        def interrupted(path, value):
            if path.name == usage.STATE:
                raise OSError("cache checkpoint crash")
            return original(path, value)

        patch.setattr(usage, "_write", interrupted)
        assert model(9) is None  # durable entry survives a failed checkpoint
    assert journal.read()[-1].data == {"requests": 9}
    assert journal.usage_high_water("2026-11-01") == 9
    state = usage.current()
    usage._value_path(state, "2026-11-01").unlink()
    assert journal.usage_high_water("2026-11-01") == 9
    usage._value_path(usage.current(), "2026-11-01").write_text("broken")
    assert journal.usage_high_water("2026-11-01") == 9
    assert len(list(effect_journal.glob("usage-*"))) == 1
    model(2, "2000-01-01")
    state = usage.current()
    usage._value_path(state, "2026-11-01").write_bytes(
        usage._value_path(state, "2000-01-01").read_bytes()
    )
    assert (
        journal.usage_high_water("2026-11-01") == 9
    )  # a valid cache for another day is not evidence


def test_concurrent_rotation_and_usage_writers_keep_one_chain(effect_journal):
    model(1)

    def writer():
        for n in range(2, 20):
            assert model(n)

    def rotator():
        for _ in range(4):
            journal.rotate()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(writer), pool.submit(rotator)]
        for result in futures:
            result.result()
    entries = journal.read()
    assert len([e for e in entries if e.kind == "genesis"]) == 1
    assert len([e for e in entries if e.kind == "continues"]) == 4
    assert journal.usage_high_water("2026-11-01") == 19


def test_real_backup_restore_spans_rotation_and_retained_archive(
    p2, effect_journal, tmp_path
):
    model(5)
    out, storage = tmp_path / "sets", tmp_path / "custody"
    out.mkdir()
    storage.mkdir()
    result = run_backup(out, storage)
    assert result.returncode == 0, result.stderr
    backed_up = json.loads((out / "set" / "receipt.json").read_text())
    journal.rotate()
    after = journal.append(
        "automation_pause", f"pause:{uuid.uuid4()}", {"state": "paused", "by": "staff"}
    )
    model(8)
    journal.rotate()
    assert journal.archive_segments([backed_up])["archived"]
    target = new_database()
    try:
        restored = run_restore(target, out / "set", tmp_path / "restored-custody")
        assert restored.returncode == 0, restored.stderr
        with admin(target) as probe:
            actor = probe.execute(
                "SELECT actor_ref FROM workflow_automationpause WHERE subject_type='system'"
            ).fetchone()[0]
        anchor = journal.parse_anchor(actor)
        assert anchor == (
            backed_up["effect_journal_id"],
            backed_up["effect_journal_seq"],
            backed_up["effect_journal_head"],
        )
        effects, _, marker = journal.after_restore(anchor)
        assert after in effects and [e.kind for e in effects] == [
            "automation_pause",
            "model_usage",
        ]
        assert journal.read()[marker - 1].kind == "restore"
        assert journal.usage_high_water("2026-11-01") == 8
    finally:
        drop(target)


def test_operator_command_requires_recovery_and_complete_inventory_confirmations(
    effect_journal, tmp_path
):
    model(1)
    with pytest.raises(CommandError):
        call_command("catalyst_journal_segments", "--rotate", "--confirm")
    call_command(
        "catalyst_journal_segments", "--rotate", "--confirm", "--segment-aware-recovery"
    )
    inventory = tmp_path / "receipts.json"
    inventory.write_text(json.dumps([receipt()]))
    with pytest.raises(CommandError):
        call_command(
            "catalyst_journal_segments",
            "--archive-receipts",
            str(inventory),
            "--confirm",
        )
    call_command(
        "catalyst_journal_segments",
        "--archive-receipts",
        str(inventory),
        "--confirm",
        "--complete-backup-inventory",
    )


def test_deploy_probe_refuses_old_readers_before_migration_or_switch(
    effect_journal, monkeypatch
):
    adapters = Path(__file__).resolve().parents[1] / "deploy/staging/adapters"
    source = (adapters / "lib.sh").read_text()
    probe = source.split(
        "<<'PY' || fail \"refused: target cannot read the effect journal layout\"\n", 1
    )[1].split("\nPY\n", 1)[0]
    with monkeypatch.context() as patch:
        patch.delattr(journal, "SEGMENT_FORMAT")
        exec(compile(probe, "layout-probe", "exec"), {})  # old reader, original layout
    model(2)
    journal.rotate()
    exec(compile(probe, "layout-probe", "exec"), {})
    with monkeypatch.context() as patch:
        patch.delattr(journal, "SEGMENT_FORMAT")
        with pytest.raises(AssertionError, match="unsupported"):
            exec(compile(probe, "layout-probe", "exec"), {})
    for filename, boundary in [
        ("predeploy.sh", "operation start"),
        ("deploy.sh", "compose up -d"),
    ]:
        script = (adapters / filename).read_text()
        assert script.index('check_journal_layout "$target"') < script.index(boundary)

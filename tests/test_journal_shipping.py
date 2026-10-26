"""9kg.60: the effect journal is shipped off the host with its head, its shipping lag pages, and a restore refuses a
journal that lost what was already shipped unless the owner records the loss (workflow.shipping). Every entry here is
synthetic, in each test's own journal (tests/conftest.py `effect_journal`).
"""

import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command

from config import backup, guards, system_health
from tests import support
from tests.test_backup_commands import ADMIN, admin, drop, new_database, run_backup
from workflow import journal, shipping


def entries(n=3):
    for i in range(n):
        assert journal.append("model_usage", f"usage:2026-10-2{i}", {"requests": i}) is not None


@pytest.fixture
def offhost(tmp_path):
    path = tmp_path / "offhost"
    path.mkdir()
    return path


def test_9kg_60_the_journal_and_its_head_are_shipped_whole_and_recorded_beside_the_journal(effect_journal, offhost):
    entries(3)
    report = shipping.ship(str(offhost))
    seq, digest, identity = journal.head()
    assert report == {"shipped_seq": seq, "head": f"{identity}:{seq}:{digest}"}
    assert (offhost / journal.FILE).read_bytes() == (effect_journal / journal.FILE).read_bytes()
    head = json.loads((offhost / shipping.HEAD).read_text())
    assert (head["identity"], head["seq"], head["hash"]) == (identity, seq, digest)
    assert shipping.last_shipped()["seq"] == seq
    assert not [p for p in offhost.iterdir() if p.name.startswith(".")]  # no temporary file left behind
    for bad, code in ((str(effect_journal), "destination_unsafe"), (str(effect_journal / "sub"), "destination_unavailable"),
                      ("relative/dir", "destination_unavailable"), (str(offhost / "missing"), "destination_unavailable")):
        with pytest.raises(shipping.ShipError, match=code):
            shipping.ship(bad)


def test_9kg_60_a_local_journal_that_lost_shipped_entries_never_overwrites_the_copy(effect_journal, offhost):
    entries(3)
    shipping.ship(str(offhost))
    shipped = (offhost / journal.FILE).read_bytes()
    lines = (effect_journal / journal.FILE).read_bytes().splitlines(keepends=True)
    (effect_journal / journal.FILE).write_bytes(b"".join(lines[:2]))  # rolled back to an older copy of itself
    with pytest.raises(shipping.ShipError, match="destination_ahead_of_journal"):
        shipping.ship(str(offhost))
    assert (offhost / journal.FILE).read_bytes() == shipped  # the only record of the lost entries is kept


def test_9kg_60_the_lag_pages_past_the_threshold_and_never_shipped_pages_too(effect_journal, offhost, settings,
                                                                             monkeypatch):
    entries(2)
    assert system_health.journal_health()["ship_lag_seconds"] is None  # the signal is off at 0
    settings.CATALYST_JOURNAL_SHIP_LAG_SECONDS = 300
    assert "effect_journal_never_shipped" in system_health.journal_health()["anomalies"]
    shipping.ship(str(offhost))
    part = system_health.journal_health()
    assert part["anomalies"] == [] and part["ship_lag_seconds"] == 0
    entries(1)  # written now, not yet shipped
    assert system_health.journal_health()["anomalies"] == []  # within the threshold

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(seconds=600)
    monkeypatch.setattr(shipping, "datetime", Later)
    part = system_health.journal_health()
    assert part["anomalies"] == ["effect_journal_ship_lag"] and part["ship_lag_seconds"] >= 600
    monkeypatch.undo()
    settings.CATALYST_JOURNAL_SHIP_LAG_SECONDS = 300
    shipping.ship(str(offhost))
    assert system_health.journal_health()["anomalies"] == []
    lines = (effect_journal / journal.FILE).read_bytes().splitlines(keepends=True)
    (effect_journal / journal.FILE).write_bytes(b"".join(lines[:-1]))  # the host lost its last entry
    assert system_health.journal_health()["anomalies"] == ["effect_journal_behind_shipped"]


def test_9kg_60_a_live_environment_must_set_the_lag_threshold(effect_journal, settings):
    settings.CATALYST_ENV = "production"
    settings.CATALYST_JOURNAL_SHIP_LAG_SECONDS = 0
    assert any("CATALYST_JOURNAL_SHIP_LAG_SECONDS" in p for p in guards.journal_problems(settings))
    settings.CATALYST_JOURNAL_SHIP_LAG_SECONDS = 300
    assert not any("CATALYST_JOURNAL_SHIP_LAG_SECONDS" in p for p in guards.journal_problems(settings))


def test_9kg_60_the_shipped_head_check_refuses_a_journal_behind_it_unless_the_owner_accepts(effect_journal, settings):
    entries(3)
    seq, digest, identity = journal.head()
    assert backup.check_shipped(f"{identity}:{seq}:{digest}", False) is False  # the journal holds it
    assert backup.check_shipped("none", False) is False and backup.check_shipped("", False) is False
    ahead = f"{identity}:{seq + 4}:{'0' * 64}"  # shipped later than this journal reaches
    with pytest.raises(backup.BackupError, match="journal_behind_shipped"):
        backup.check_shipped(ahead, False)
    assert backup.check_shipped(ahead, True) is True  # the owner accepts the loss; the restore records it
    with pytest.raises(backup.BackupError, match="must be <identity>:<seq>:<hash>"):
        backup.check_shipped("not-a-head", False)
    settings.CATALYST_ENV = "production"
    with pytest.raises(backup.BackupError, match="names the journal head last shipped"):
        backup.check_shipped("", False)


@pytest.mark.django_db
def test_9kg_60_a_restore_refuses_a_journal_behind_the_shipped_head_before_the_load(effect_journal, tmp_path):
    out, storage = tmp_path / "sets", tmp_path / "custody"
    out.mkdir()
    storage.mkdir(mode=0o700)
    entries(1)
    result = run_backup(out, storage)
    assert result.returncode == 0, result.stderr
    entries(2)
    seq, digest, identity = journal.head()
    database = new_database()
    try:
        def restore(*extra):
            return support.run([sys.executable, "manage.py", "catalyst_restore", "--from", str(out / "set"),
                                "--storage-dir", str(tmp_path / "restored"), "--confirm-database", database, *extra],
                               timeout=300, CATALYST_DB_NAME=database, CATALYST_DB_USER=django_settings.CATALYST_DB_ROLES["owner"],
                               CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"], **ADMIN)
        refused = restore("--shipped-head", f"{identity}:{seq + 3}:{'0' * 64}")
        assert refused.returncode == 1 and "journal_behind_shipped" in refused.stderr, refused.stderr
        with admin(database) as conn:  # refused before the load: the target is still empty
            assert conn.execute("SELECT count(*) FROM workflow_automationpause").fetchone()[0] == 0
        accepted = restore("--shipped-head", f"{identity}:{seq + 3}:{'0' * 64}", "--accept-journal-behind-shipped")
        assert accepted.returncode == 0, accepted.stderr
        marker = [e for e in journal.read() if e.kind == "restore"][-1]
        assert marker.data.get("behind_shipped") is True  # the owner's acceptance is on the record
    finally:
        drop(database)


def test_9kg_60_the_command_ships_and_refuses_with_a_code(effect_journal, offhost, capsys):
    entries(1)
    call_command("catalyst_journal_ship", "--to", str(offhost))
    assert json.loads(capsys.readouterr().out.strip())["shipped_seq"] == journal.head()[0]
    with pytest.raises(SystemExit):
        call_command("catalyst_journal_ship", "--to", "relative")

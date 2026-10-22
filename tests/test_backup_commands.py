"""6B.7a (026 section 6; TEST-P6-21, 23): the backup and restore commands, run as real processes with the backup
role and the bootstrap administrator, against this run's PostgreSQL container and synthetic custody files."""

import json
import os
import sys
import uuid

import psycopg
import pytest
from django.conf import settings
from django.db import connection
from psycopg import sql

from config import backup as backup_module
from tests import support
from tests.test_agreement_custody import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, issued, k, nda, of, p2, run_worker, sign_and_settle, tls,
)

ADMIN = {"CATALYST_DB_ADMIN_USER": os.environ["CATALYST_DB_ADMIN_USER"],
         "CATALYST_DB_ADMIN_PASSWORD": os.environ["CATALYST_DB_ADMIN_PASSWORD"]}


def admin(dbname):
    return psycopg.connect(host=connection.settings_dict["HOST"], port=connection.settings_dict["PORT"], dbname=dbname,
                           user=ADMIN["CATALYST_DB_ADMIN_USER"], password=ADMIN["CATALYST_DB_ADMIN_PASSWORD"],
                           autocommit=True)


def run_backup(out, storage, name="set"):
    return support.run([sys.executable, "manage.py", "catalyst_backup", "--out", str(out), "--storage-dir", str(storage),
                        "--name", name], timeout=300,
                       CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=settings.CATALYST_DB_ROLES["backup"],
                       CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_BACKUP_PASSWORD"])


def new_database():
    name = f"catalyst_restore_{uuid.uuid4().hex[:12]}"
    with admin("postgres") as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(name),
                                                                    sql.Identifier(settings.CATALYST_DB_ROLES["owner"])))
    migrated = support.run([sys.executable, "manage.py", "migrate", "--verbosity", "0"], timeout=300,
                           CATALYST_DB_NAME=name, CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                           CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
    assert migrated.returncode == 0, migrated.stderr
    return name


def drop(name):
    with admin("postgres") as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def run_restore(dbname, source, storage):
    return support.run([sys.executable, "manage.py", "catalyst_restore", "--from", str(source), "--storage-dir", str(storage)],
                       timeout=300, CATALYST_DB_NAME=dbname, CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                       CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"], **ADMIN)


def hold_present(dbname) -> bool:
    with admin(dbname) as conn:
        return conn.execute("SELECT count(*) FROM workflow_automationpause WHERE subject_type = %s AND subject_id = %s",
                            list(backup_module.RESTORE_HOLD)).fetchone()[0] == 1


@pytest.fixture
def signed(k, monkeypatch):
    app = issued(k, monkeypatch)
    sign_and_settle(k, app, "nda")
    sign_and_settle(k, app, "user_agreement")
    return k


def test_6b7_a_backup_restores_elsewhere_byte_for_byte_with_its_files_and_a_hold(signed, tmp_path):
    out = tmp_path / "sets"
    out.mkdir()
    result = run_backup(out, signed.storage)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["documents"] == 2 and receipt["excluded_tables"] == ["django_session"]
    assert "@" not in result.stdout  # the receipt carries no address or other personal data
    assert backup_module.private_set(out / "set") and not (out / "set.pending").exists()
    assert not (out / "set" / "django_session.copy").exists()  # staff sessions are never backed up
    target = new_database()
    try:
        restored = tmp_path / "restored-custody"
        result = run_restore(target, out / "set", restored)
        assert result.returncode == 0, result.stderr
        assert hold_present(target)  # nothing runs until the post-restore step
        verified = support.run([sys.executable, "manage.py", "verify_custody_restore", "--storage-dir", str(restored),
                                "--manifest", str(out / "set" / "manifest.json")], timeout=120,
                               CATALYST_DB_NAME=target, CATALYST_DB_USER=settings.CATALYST_DB_ROLES["app"],
                               CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"])
        report = json.loads(verified.stdout.strip().splitlines()[-1])
        assert verified.returncode == 0 and report["ok"] and report["verified"] == 2 and report["manifest_match"]
    finally:
        drop(target)


def test_6b7_the_worker_claims_nothing_while_the_restore_hold_is_present(p2):
    from workflow import ledger
    from workflow.models import AutomationPause, PendingAction

    PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                 idempotency_key="hold-probe")
    AutomationPause.objects.create(subject_type=backup_module.RESTORE_HOLD[0], subject_id=backup_module.RESTORE_HOLD[1],
                                   reason="restore hold (test)", actor_ref="test")
    assert ledger.claim_next({"send_message": ledger.handlers()["send_message"]}) is None


@pytest.mark.parametrize("damage", ["table_copy", "receipt", "custody_file"])
def test_6b7_a_damaged_set_is_refused_before_anything_loads(signed, tmp_path, damage):
    out = tmp_path / "sets"
    out.mkdir()
    assert run_backup(out, signed.storage).returncode == 0
    target_set = out / "set"
    if damage == "table_copy":
        path = target_set / "applications_application.copy"
        os.chmod(path, 0o600)
        path.write_bytes(path.read_bytes()[:-5])  # truncated
    elif damage == "receipt":
        receipt = json.loads((target_set / "receipt.json").read_text())
        receipt["manifest_sha256"] = "0" * 64
        (target_set / "receipt.json").write_text(json.dumps(receipt))
    else:
        key = json.loads((target_set / "manifest.json").read_text())["documents"][0]["key"]
        (target_set / "custody" / key).unlink()
    target = new_database()
    try:
        result = run_restore(target, target_set, tmp_path / "restored")
        assert result.returncode == 1 and "restore refused" in result.stderr
        assert not hold_present(target)  # refused before any load
        with admin(target) as conn:
            assert conn.execute("SELECT count(*) FROM applications_application").fetchone()[0] == 0
    finally:
        drop(target)


def test_6b7_a_target_at_other_migrations_is_refused(signed, tmp_path):
    out = tmp_path / "sets"
    out.mkdir()
    assert run_backup(out, signed.storage).returncode == 0
    target = new_database()
    try:
        with admin(target) as conn:
            conn.execute("INSERT INTO django_migrations (app, name, applied) VALUES ('workflow', '9999_not_in_backup', now())")
        result = run_restore(target, out / "set", tmp_path / "restored")
        assert result.returncode == 1 and "not at the backup's migrations" in result.stderr
    finally:
        drop(target)


def test_6b7_a_failed_backup_leaves_no_set_that_looks_usable(signed, tmp_path):
    from agreements.models import StoredDocument

    out = tmp_path / "sets"
    out.mkdir()
    (signed.storage / StoredDocument.objects.first().storage_key).unlink()  # a referenced file is gone
    result = run_backup(out, signed.storage)
    assert result.returncode == 1 and "custody file missing" in result.stderr
    assert list(out.iterdir()) == []  # neither the set nor its .pending directory remains

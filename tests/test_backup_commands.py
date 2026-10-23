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


def run_restore(dbname, source, storage, confirm=None, expect=""):
    extra = ["--expect-manifest-sha256", expect] if expect else []
    return support.run([sys.executable, "manage.py", "catalyst_restore", "--from", str(source), "--storage-dir", str(storage),
                        "--confirm-database", dbname if confirm is None else confirm, *extra],
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
    printed = json.loads(result.stdout.strip().splitlines()[-1])
    assert set(printed) == {"name", "manifest_sha256"}  # only the name and the digest reach the log
    receipt = json.loads((out / "set" / "receipt.json").read_text())
    assert receipt["excluded_tables"] == ["django_session", "otp_static_staticdevice", "otp_static_statictoken",
                                          "otp_totp_totpdevice"] and "rows" not in receipt and "documents" not in receipt
    assert backup_module.private_set(out / "set") and not (out / "set.pending").exists()
    assert not (out / "set" / "django_session.copy").exists()  # staff sessions are never backed up
    target = new_database()
    try:
        restored = tmp_path / "restored-custody"
        result = run_restore(target, out / "set", restored, expect=printed["manifest_sha256"])
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

    registry = ledger.handlers()
    manual = next(kind for kind, h in registry.items() if not h.automated)
    for kind in ("send_message", manual):  # an automated kind and a staff-initiated one
        PendingAction.objects.create(kind=kind, subject_type="application", subject_id=uuid.uuid4(),
                                     idempotency_key=f"hold-probe-{kind}")
    hold = AutomationPause.objects.create(subject_type=backup_module.RESTORE_HOLD[0],
                                          subject_id=backup_module.RESTORE_HOLD[1], reason="restore hold (test)",
                                          actor_ref="test")
    assert ledger.claim_next(registry) is None and ledger.claim_next({manual: registry[manual]}) is None
    assert not ledger.run_one(registry)  # the worker's own entry point runs nothing either
    owner = p2.committed.connect("owner", autocommit=True)  # the owner (the post-restore step) lifts it
    owner.execute("DELETE FROM workflow_automationpause WHERE id = %s", [hold.pk])
    assert ledger.claim_next({manual: registry[manual]}) is not None  # the positive control: claimable without it


def test_6b7_the_application_role_cannot_lift_the_restore_hold(p2):
    from django.db import transaction

    from workflow.models import AutomationPause

    hold = AutomationPause.objects.create(subject_type=backup_module.RESTORE_HOLD[0],
                                          subject_id=backup_module.RESTORE_HOLD[1], reason="restore hold (test)",
                                          actor_ref="test")
    with pytest.raises(Exception, match="restore hold") as caught, transaction.atomic():
        AutomationPause.objects.filter(pk=hold.pk).delete()
    assert isinstance(caught.value.__cause__, psycopg.errors.InsufficientPrivilege)
    application_pause = AutomationPause.objects.create(subject_type="application", subject_id=uuid.uuid4(),
                                                       reason="staff pause (test)", actor_ref="test")
    # An ordinary pause is not the restore hold's business: its own guard (9kg.6) answers, with its own reason.
    with pytest.raises(Exception, match="automation_resumed") as caught, transaction.atomic():
        AutomationPause.objects.filter(pk=application_pause.pk).delete()
    assert isinstance(caught.value.__cause__, psycopg.errors.InsufficientPrivilege) and "restore hold" not in str(caught.value)


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


@pytest.mark.parametrize("problem", ["populated", "connected", "confirmation"])
def test_6b7_a_restore_never_touches_a_database_that_is_in_use_or_not_named(signed, tmp_path, problem):
    out = tmp_path / "sets"
    out.mkdir()
    assert run_backup(out, signed.storage).returncode == 0
    target = new_database()
    other = None
    try:
        if problem == "populated":
            with admin(target) as conn:
                conn.execute("INSERT INTO applications_application (public_ref, email, email_key, display_name, stage,"
                             " next_version_number) VALUES (gen_random_uuid(), 'live@example.test', 'live@example.test',"
                             " 'Live', 'submitted', 1)")
            expected = "not empty"
        elif problem == "connected":
            other = admin(target)  # a running worker or web process, in effect
            expected = "other sessions are connected"
        else:
            expected = "--confirm-database must name the target database"
        result = run_restore(target, out / "set", tmp_path / "restored",
                             confirm="the-wrong-database" if problem == "confirmation" else None)
        assert result.returncode == 1 and expected in result.stderr
        assert not hold_present(target)
    finally:
        if other is not None:
            other.close()
        drop(target)


def test_6b7_a_tampered_or_world_readable_set_is_refused(signed, tmp_path):
    import hashlib

    out = tmp_path / "sets"
    out.mkdir()
    assert run_backup(out, signed.storage).returncode == 0
    target_set = out / "set"
    manifest = json.loads((target_set / "manifest.json").read_text())
    manifest["documents"][0]["key"] = "../../escaped.pdf"  # with a receipt rewritten to match
    data = json.dumps(manifest).encode()
    for name in ("manifest.json", "receipt.json"):
        os.chmod(target_set / name, 0o600)
    (target_set / "manifest.json").write_bytes(data)
    receipt = json.loads((target_set / "receipt.json").read_text())
    receipt["manifest_sha256"] = hashlib.sha256(data).hexdigest()
    (target_set / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(backup_module.BackupError, match="custody key with an unexpected shape"):
        backup_module.check_set(target_set)
    os.chmod(target_set, 0o755)
    with pytest.raises(backup_module.BackupError, match="must be a private directory"):
        backup_module.check_set(target_set)


def test_6b7_a_bad_set_name_is_refused(signed, tmp_path):
    result = run_backup(tmp_path, signed.storage, name="../escape")
    assert result.returncode == 1 and "set name may hold only" in result.stderr


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


def test_6b13_a_failed_backup_keeps_the_previous_good_set_intact(signed, tmp_path):
    """TEST-P6-21 (6B.13 review): a failed run leaves the last good set exactly as it was, still verifiable."""
    from agreements.models import StoredDocument
    from config import backup

    out = tmp_path / "sets"
    out.mkdir()
    assert run_backup(out, signed.storage, name="good").returncode == 0
    before = backup.check_set(out / "good")["tables"]
    (signed.storage / StoredDocument.objects.first().storage_key).unlink()  # the next run will fail
    failed = run_backup(out, signed.storage, name="later")
    assert failed.returncode == 1 and "custody file missing" in failed.stderr
    assert sorted(p.name for p in out.iterdir()) == ["good"]  # nothing from the failed run, the good set untouched
    assert backup.check_set(out / "good")["tables"] == before  # and still verifies against its manifest


def test_6b7_a_database_error_reports_only_its_class_and_code_never_the_row(p2, monkeypatch, tmp_path):
    from io import StringIO

    from django.core.management import call_command

    from config.management.commands import catalyst_restore

    def failing(*args, **kwargs):  # what a COPY that hits a duplicate key raises: its detail quotes the row
        raise psycopg.errors.UniqueViolation("duplicate key value: Key (email)=(ada@example.test) already exists")
    monkeypatch.setattr(catalyst_restore.backup, "restore", failing)
    monkeypatch.setenv("CATALYST_DB_ADMIN_USER", ADMIN["CATALYST_DB_ADMIN_USER"])
    monkeypatch.setenv("CATALYST_DB_ADMIN_PASSWORD", ADMIN["CATALYST_DB_ADMIN_PASSWORD"])
    err = StringIO()
    with pytest.raises(SystemExit) as exit_:
        call_command("catalyst_restore", "--from", str(tmp_path), "--storage-dir", str(tmp_path / "x"),
                     "--confirm-database", "whatever", stdout=StringIO(), stderr=err)
    assert exit_.value.code == 1 and "UniqueViolation" in err.getvalue()
    assert "ada@example.test" not in err.getvalue() and "duplicate key" not in err.getvalue()

"""A local backup and restore rehearsal of the database together with the custody files (`024` proposal 1; bead
9kg.7). Synthetic only: a disposable database in this run's PostgreSQL container, synthetic custody files in temporary
storage, no worker and no provider settings during the restore. It proves the procedure, not production RPO or RTO.

Backup: one REPEATABLE READ snapshot of every public table (COPY), then the custody files those rows reference,
then a manifest (row counts and SHA-256 of every table's copy, every document's key, size and SHA-256, the
migration revision). Restore: a new database migrated to the same revision as the owner, then the data copied in
as the bootstrap administrator with triggers disabled for the load only (as `pg_restore --disable-triggers`).
Verify: the same tables and digests, the same protection triggers and role privileges, and every referenced file's
bytes; missing and corrupt files fail; orphans are reported and kept.
"""

import hashlib
import json
import os
import shutil
import sys
import uuid

import psycopg
import pytest
from django.conf import settings
from django.db import connection
from psycopg import sql

from config.backup import AT_REST_DOCUMENTS
from tests import support
from tests.conftest import EXPECTED_TRIGGERS, protection_state
from tests.test_agreement_custody import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, issued, k, nda, of, p2, run_worker, sign_and_settle, tls,
)


def login_args(role_key, dbname):
    names = {"admin": support.superuser_login(),  # the probe-only pair (6hl.10)
             "owner": (settings.CATALYST_DB_ROLES["owner"], os.environ["CATALYST_DB_OWNER_PASSWORD"]),
             "app": (settings.CATALYST_DB_ROLES["app"], os.environ["CATALYST_DB_APP_PASSWORD"])}
    user, password = names[role_key]
    return {"host": connection.settings_dict["HOST"], "port": connection.settings_dict["PORT"], "dbname": dbname,
            "user": user, "password": password}


def login(role_key, dbname):
    return psycopg.connect(**login_args(role_key, dbname), autocommit=True)


def tables(conn):
    return [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")]


def copy_out(conn, table) -> bytes:
    with conn.cursor().copy(sql.SQL("COPY {} TO STDOUT").format(sql.Identifier(table))) as cp:
        return b"".join(bytes(chunk) for chunk in cp)


def digest(data: bytes) -> str:
    """Order-independent: the SHA-256 of the sorted rows, so physical row order never matters."""
    return hashlib.sha256(b"".join(sorted(data.splitlines(keepends=True)))).hexdigest()


def backup(source_db, storage, target, during=None):
    """One consistent snapshot of the rows, then the files they reference, then the manifest. `during` runs after
    the first table is copied (a concurrent writer, in the test)."""
    target.mkdir()
    (target / "custody").mkdir(mode=0o700)
    conn = psycopg.connect(**login_args("owner", source_db))
    try:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        with conn.transaction():
            assert conn.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
            manifest = {"tables": {}, "documents": [], "revision": {}}
            for n, table in enumerate(tables(conn)):
                data = copy_out(conn, table)
                (target / f"{table}.copy").write_bytes(data)
                manifest["tables"][table] = {"rows": data.count(b"\n"), "sha256": digest(data)}
                if n == 0 and during is not None:
                    during()
            for key, sha, size in conn.execute(AT_REST_DOCUMENTS):  # 9kg.34: the sealed files as they are at rest
                shutil.copy2(storage / key, target / "custody" / key)
                manifest["documents"].append({"key": key, "sha256": sha, "size": size})
            manifest["revision"] = sorted(conn.execute("SELECT app, name FROM django_migrations").fetchall())
    finally:
        conn.close()
    (target / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=1))
    return manifest


def restore(backup_dir, restore_db):
    admin = login("admin", "postgres")
    try:
        admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(restore_db),
                                                                     sql.Identifier(settings.CATALYST_DB_ROLES["owner"])))
    finally:
        admin.close()
    result = support.run([sys.executable, "manage.py", "migrate", "--verbosity", "0"], timeout=300,
                         CATALYST_DB_NAME=restore_db, CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                         CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
    assert result.returncode == 0, result.stderr
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    load = psycopg.connect(**login_args("admin", restore_db))
    try:
        # The same migration revision as the backup, checked before any row is loaded.
        assert sorted(map(list, load.execute("SELECT app, name FROM django_migrations").fetchall())) == \
            [list(r) for r in manifest["revision"]], "the restore target is not at the backup's revision"
        load.rollback()
        with load.transaction():
            load.execute("SET LOCAL session_replication_role = replica")  # the load only: as pg_restore --disable-triggers
            names = list(manifest["tables"])
            load.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.SQL(", ").join(sql.Identifier(t) for t in names)))
            for table in names:
                with load.cursor().copy(sql.SQL("COPY {} FROM STDIN").format(sql.Identifier(table))) as cp:
                    cp.write((backup_dir / f"{table}.copy").read_bytes())
            for table, column, sequence in load.execute(
                    "SELECT c.table_name, c.column_name, pg_get_serial_sequence(quote_ident(c.table_name), c.column_name)"
                    " FROM information_schema.columns c WHERE c.table_schema = 'public'"
                    " AND pg_get_serial_sequence(quote_ident(c.table_name), c.column_name) IS NOT NULL").fetchall():
                load.execute(sql.SQL("SELECT setval({}, COALESCE((SELECT max({}) FROM {}), 0) + 1, false)").format(
                    sql.Literal(sequence), sql.Identifier(column), sql.Identifier(table)))
    finally:
        load.close()
    restored = backup_dir.parent / "restored-custody"
    shutil.copytree(backup_dir / "custody", restored)
    os.chmod(restored, 0o700)
    return manifest, restored


def verify(restore_db, storage, manifest=None):
    extra = ["--manifest", str(manifest)] if manifest else []
    return support.run([sys.executable, "manage.py", "verify_custody_restore", "--storage-dir", str(storage), *extra],
                       timeout=120,
                       CATALYST_DB_NAME=restore_db, CATALYST_DB_USER=settings.CATALYST_DB_ROLES["app"],
                       CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"])


def test_9kg_7_backup_restore_elsewhere_and_verify_rows_files_roles_and_triggers(k, monkeypatch, tmp_path):
    app = issued(k, monkeypatch)
    sign_and_settle(k, app, "nda")
    sign_and_settle(k, app, "user_agreement")
    source_db = connection.settings_dict["NAME"]
    writer = login("app", source_db)

    def concurrent_write():  # committed while the snapshot is open: it must not appear in the backup
        writer.execute("INSERT INTO agreements_documentaccess (requested_ref, actor_ref, reason, outcome)"
                       " VALUES ('synthetic-concurrent', 'test', '', 'denied')")
    try:
        manifest = backup(source_db, k.storage, tmp_path / "backup", during=concurrent_write)
    finally:
        writer.close()
    assert len(manifest["documents"]) == 2 and manifest["tables"]["agreements_storeddocument"]["rows"] == 2
    assert b"synthetic-concurrent" not in (tmp_path / "backup" / "agreements_documentaccess.copy").read_bytes()
    restore_db = f"catalyst_restore_{uuid.uuid4().hex[:12]}"
    cleanup = []
    try:
        manifest, restored = restore(tmp_path / "backup", restore_db)
        # The same rows, byte for byte, in the restored database.
        check = login("owner", restore_db)
        cleanup.append(check)
        for table, expected in manifest["tables"].items():
            assert digest(copy_out(check, table)) == expected["sha256"], table
        # The restored protection actually fires: history refuses change and truncation for the owner too.
        for statement in ("UPDATE agreements_storeddocument SET size = size + 1",
                          "DELETE FROM agreements_storeddocument", "TRUNCATE agreements_documentaccess"):
            with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)):
                check.execute(statement)
        # The same protection: every expected trigger enabled, and the same role privileges as the source.
        triggers, privileges = protection_state(check)
        assert {(t, g) for t, g, _ in triggers} == EXPECTED_TRIGGERS and {e for _, _, e in triggers} == {"O"}
        source = login("owner", source_db)
        try:
            assert privileges == protection_state(source)[1]
        finally:
            source.close()
        check.close()
        # Every referenced file verifies; then a missing, a corrupt and an orphan file.
        result = verify(restore_db, restored, tmp_path / "backup" / "manifest.json")
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert result.returncode == 0 and report["ok"] and report["verified"] == 2 and not report["orphans"]
        assert report["manifest_match"] is True
        first, second = (d["key"] for d in manifest["documents"])
        orphan = restored / f"{uuid.uuid4().hex}.pdf"
        orphan.write_bytes(b"%PDF-1.7 an unreferenced synthetic file")
        os.chmod(orphan, 0o600)
        report = json.loads(verify(restore_db, restored).stdout.strip().splitlines()[-1])
        assert report["ok"] and report["orphans"] == [orphan.name] and orphan.exists()  # reported, never deleted
        (restored / first).unlink()
        data = (restored / second).read_bytes()
        (restored / second).write_bytes(data[:-1] + bytes([data[-1] ^ 0xFF]))  # always a change (an "X" was a no-op 1 in 256)
        result = verify(restore_db, restored)
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert result.returncode == 1 and not report["ok"]
        assert report["missing"] == [first] and report["mismatch"] == [second] and report["verified"] == 0
        assert b"%PDF" not in result.stdout.encode()  # counts and keys only, never document bytes
        # A size change, a wrong mode and a link instead of a file are all refused.
        (restored / first).write_bytes(data + b"longer")
        os.chmod(restored / first, 0o600)
        (restored / second).unlink()
        (restored / second).write_bytes(data)
        os.chmod(restored / second, 0o644)
        report = json.loads(verify(restore_db, restored).stdout.strip().splitlines()[-1])
        assert report["mismatch"] == [first] and report["unsafe"] == [second]
        (restored / second).unlink()
        os.symlink(restored / first, restored / second)
        report = json.loads(verify(restore_db, restored).stdout.strip().splitlines()[-1])
        assert report["unsafe"] == [second]
        # A truncated restore cannot pass against its manifest.
        empty = login("admin", restore_db)
        try:
            with empty.transaction():
                empty.execute("SET LOCAL session_replication_role = replica")
                empty.execute("DELETE FROM agreements_storeddocument")
        finally:
            empty.close()
        result = verify(restore_db, restored, tmp_path / "backup" / "manifest.json")
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert result.returncode == 1 and report["documents"] == 0 and report["manifest_match"] is False
    finally:
        for conn in cleanup:
            conn.close()
        admin = login("admin", "postgres")
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(restore_db)))
        admin.close()


def test_9kg_7_the_checker_refuses_a_relative_or_missing_directory(privileged_reset, tmp_path):
    for bad in ("relative/dir", str(tmp_path / "absent")):
        result = verify(connection.settings_dict["NAME"], bad)
        assert result.returncode != 0 and "must be an existing absolute directory" in result.stderr

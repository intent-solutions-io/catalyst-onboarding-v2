"""Backup and restore of the database together with the custody files (026 section 6; 6B.7a; P6-D-7).

This turns the 9kg.7 rehearsal (tests/test_restore_rehearsal.py) into the operator's tools:

- **backup** reads one REPEATABLE READ, read-only snapshot as the backup role: every table except `django_session`
  (COPY), then the custody files those rows name (write-once files, so the copy is a superset of the snapshot), then
  a manifest (row counts and order-independent SHA-256 per table, each document's key, size and SHA-256, the
  migration list). It writes to `<name>.pending` (the estate archive skips in-progress sets), syncs, then renames.
  The set is mode 0700 and its files 0600: the manifest is treated as personal-data-adjacent (026 section 6). A
  receipt holds only counts, digests and versions, never personal data.
- **restore** loads a set into an already-migrated, otherwise unused database as the bootstrap administrator, with
  triggers off for the load only (as `pg_restore --disable-triggers`). It refuses before loading anything unless the
  receipt matches the manifest, the target's migrations equal the backup's, and every table and custody file matches
  its digest. It then records the **restore hold**: the worker claims nothing until the post-restore step (6B.7b)
  has invalidated links and sessions and queued the reconciliations, then lifts the hold.

Nothing here prints a row, a file's bytes or a secret: only names, counts and digests.
"""

import hashlib
import json
import os
import shutil
import stat
import time
from pathlib import Path

from psycopg import sql

EXCLUDED_TABLES = ("django_session",)
SNAPSHOT_TIMEOUT_MS = 15 * 60 * 1000  # a long snapshot holds back vacuum (6A review)
RESTORE_HOLD = ("system", "00000000-0000-0000-0000-00000000aaaa")  # the AutomationPause row the ledger honours


class BackupError(Exception):
    """A refusal, with a short reason naming what failed; never a row or a byte."""


def digest(data: bytes) -> str:
    """Order-independent: the SHA-256 of the sorted rows, so physical row order never matters."""
    return hashlib.sha256(b"".join(sorted(data.splitlines(keepends=True)))).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tables(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
            if r[0] not in EXCLUDED_TABLES]


def copy_out(conn, table: str) -> bytes:
    with conn.cursor().copy(sql.SQL("COPY {} TO STDOUT").format(sql.Identifier(table))) as cp:
        return b"".join(bytes(chunk) for chunk in cp)


def _private_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def backup(conn, out_dir: Path, storage_dir: Path, name: str, commit: str = "") -> dict:
    """Write one coherent set to out_dir/name and return its receipt. `conn` is a psycopg connection as the backup
    role, not yet in a transaction."""
    import psycopg

    if not out_dir.is_absolute() or not out_dir.is_dir():
        raise BackupError("the output directory must be an existing absolute directory")
    final, pending = out_dir / name, out_dir / f"{name}.pending"
    if final.exists() or pending.exists():
        raise BackupError("a set with this name already exists")
    pending.mkdir(mode=0o700)
    (pending / "custody").mkdir(mode=0o700)
    started = time.time()
    manifest = {"tables": {}, "documents": [], "revision": []}
    try:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(SNAPSHOT_TIMEOUT_MS)))
            for table in tables(conn):
                data = copy_out(conn, table)
                _private_file(pending / f"{table}.copy", data)
                manifest["tables"][table] = {"rows": data.count(b"\n"), "sha256": digest(data)}
            for key, sha, size in conn.execute("SELECT storage_key, sha256, size FROM agreements_storeddocument ORDER BY id"):
                source = storage_dir / key
                if not source.is_file() or source.is_symlink():
                    raise BackupError(f"custody file missing: {key}")
                target = pending / "custody" / key
                shutil.copyfile(source, target)
                os.chmod(target, 0o600)
                if file_sha256(target) != sha or target.stat().st_size != size:
                    raise BackupError(f"custody file does not match its record: {key}")
                manifest["documents"].append({"key": key, "sha256": sha, "size": size})
            manifest["revision"] = sorted(map(list, conn.execute("SELECT app, name FROM django_migrations").fetchall()))
            server = conn.execute("SHOW server_version").fetchone()[0]
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=1).encode()
        _private_file(pending / "manifest.json", manifest_bytes)
        receipt = {
            "name": name, "started_at": started, "finished_at": time.time(),
            "tables": len(manifest["tables"]), "rows": sum(t["rows"] for t in manifest["tables"].values()),
            "documents": len(manifest["documents"]), "migrations": len(manifest["revision"]),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "postgresql": server, "commit": commit,
            "excluded_tables": list(EXCLUDED_TABLES),
        }
        _private_file(pending / "receipt.json", json.dumps(receipt, sort_keys=True, indent=1).encode())
        os.rename(pending, final)
        dir_fd = os.open(out_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return receipt
    except BaseException:
        shutil.rmtree(pending, ignore_errors=True)  # a failed run never leaves a set that looks usable
        raise


def check_set(backup_dir: Path) -> dict:
    """Refuse a set whose receipt, manifest, table copies or custody files do not agree. Returns the manifest."""
    for required in ("manifest.json", "receipt.json"):
        if not (backup_dir / required).is_file():
            raise BackupError(f"the set has no {required}")
    manifest_bytes = (backup_dir / "manifest.json").read_bytes()
    receipt = json.loads((backup_dir / "receipt.json").read_text())
    if hashlib.sha256(manifest_bytes).hexdigest() != receipt.get("manifest_sha256"):
        raise BackupError("the manifest does not match the receipt")
    manifest = json.loads(manifest_bytes)
    for table, expected in manifest["tables"].items():
        path = backup_dir / f"{table}.copy"
        if not path.is_file() or digest(path.read_bytes()) != expected["sha256"]:
            raise BackupError(f"table copy does not match the manifest: {table}")
    for document in manifest["documents"]:
        path = backup_dir / "custody" / document["key"]
        if not path.is_file() or path.is_symlink() or file_sha256(path) != document["sha256"]:
            raise BackupError(f"custody file does not match the manifest: {document['key']}")
    return manifest


def restore(admin_conn, backup_dir: Path, storage_dir: Path) -> dict:
    """Load a checked set into the target database (admin_conn, the bootstrap administrator) and its custody files
    into storage_dir, then record the restore hold."""
    manifest = check_set(backup_dir)
    if storage_dir.exists() and any(storage_dir.iterdir()):
        raise BackupError("the custody directory to restore into is not empty")
    revision = sorted(map(list, admin_conn.execute("SELECT app, name FROM django_migrations").fetchall()))
    admin_conn.rollback()
    if revision != manifest["revision"]:
        raise BackupError("the target database is not at the backup's migrations")
    with admin_conn.transaction():
        admin_conn.execute("SET LOCAL session_replication_role = replica")  # the load only
        names = list(manifest["tables"])
        admin_conn.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.SQL(", ").join(sql.Identifier(t) for t in names)))
        for table in names:
            with admin_conn.cursor().copy(sql.SQL("COPY {} FROM STDIN").format(sql.Identifier(table))) as cp:
                cp.write((backup_dir / f"{table}.copy").read_bytes())
        for table, column, sequence in admin_conn.execute(
                "SELECT c.table_name, c.column_name, pg_get_serial_sequence(quote_ident(c.table_name), c.column_name)"
                " FROM information_schema.columns c WHERE c.table_schema = 'public'"
                " AND pg_get_serial_sequence(quote_ident(c.table_name), c.column_name) IS NOT NULL").fetchall():
            admin_conn.execute(sql.SQL("SELECT setval({}, COALESCE((SELECT max({}) FROM {}), 0) + 1, false)").format(
                sql.Literal(sequence), sql.Identifier(column), sql.Identifier(table)))
        admin_conn.execute(
            "INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
            " VALUES (%s, %s, %s, %s, now())",
            [*RESTORE_HOLD, "restore hold: run catalyst_post_restore before any worker", "catalyst_restore"])
        for table, expected in manifest["tables"].items():  # what was loaded is what was backed up
            if table == "workflow_automationpause":
                continue  # it now also holds the restore hold
            if digest(copy_out(admin_conn, table)) != expected["sha256"]:
                raise BackupError(f"the loaded table does not match the manifest: {table}")
    storage_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(storage_dir, 0o700)
    for document in manifest["documents"]:
        target = storage_dir / document["key"]
        shutil.copyfile(backup_dir / "custody" / document["key"], target)
        os.chmod(target, 0o600)
    return {"tables": len(manifest["tables"]), "documents": len(manifest["documents"]), "hold": "recorded"}


def private_set(backup_dir: Path) -> bool:
    """The set and every file in it are private to their owner (0700 and 0600)."""
    if stat.S_IMODE(backup_dir.stat().st_mode) != 0o700:
        return False
    return all(stat.S_IMODE(p.stat().st_mode) in (0o600, 0o700) for p in backup_dir.rglob("*"))

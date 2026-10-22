"""Backup and restore of the database together with the custody files (026 section 6; 6B.7a; P6-D-7).

This turns the 9kg.7 rehearsal (tests/test_restore_rehearsal.py) into the operator's tools:

- **backup** reads one REPEATABLE READ, read-only snapshot as the backup role: every table except `django_session`
  (COPY) and the list of custody documents. The custody files are copied after the snapshot ends: they are
  write-once, so the copy is a superset of the snapshot's rows, and the snapshot is not held open while files
  are copied. It writes to `<name>.pending` (the estate archive skips in-progress sets), fsyncs every file and
  directory, then renames. The set is 0700 and its files 0600: the manifest is personal-data-adjacent (026 section
  6). The receipt holds the set's name, its manifest digest, versions and timings, never a count of anyone's data.
- **restore** loads a set into an already-migrated, unused database as the bootstrap administrator, with triggers off
  for the load only (as `pg_restore --disable-triggers`). Before loading anything it refuses unless:
  - the operator named the target database (`--confirm-database`), no other session is connected to it, and its core
    tables are empty, so a mis-pointed restore can never overwrite a live database;
  - the set is private (0700/0600), its receipt matches its manifest (and, when given, an out-of-band digest), every
    table copy and custody file matches the manifest, every custody key has the safe shape, the set's tables are
    exactly the target's, and the target is at the backup's migrations.

  The custody files are staged and verified first; the database load is checked table by table before the restore
  hold is written in the same transaction; the files move into place only after the commit.

The **restore hold** is a database row the worker ledger honours inside its claim: nothing runs until the post-restore
step (6B.7b) has invalidated links and sessions, queued the reconciliations and lifted it. A trigger refuses the
application role any change to it (workflow migration 0004). The hold does not gate the web process: a restored
database serves no web traffic until the post-restore step has run.

Nothing here prints a row, a file's bytes or a secret: only names, digests and database error codes.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

from psycopg import sql

EXCLUDED_TABLES = ("django_session",)
SNAPSHOT_TIMEOUT_MS = 15 * 60 * 1000  # a long snapshot holds back vacuum (6A review)
RESTORE_HOLD = ("system", "00000000-0000-0000-0000-00000000aaaa")  # the AutomationPause row the ledger honours
HOLD_REASON = "restore hold: lifted only by catalyst_post_restore (6B.7b) after links, sessions and reconciliation"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
CUSTODY_KEY = re.compile(r"[0-9a-f]{32}\.pdf")  # agreements.storage.KEY: a key can never name a path
CORE_TABLES = ("applications_application", "workflow_pendingaction", "correspondence_outboundmessage",
               "agreements_storeddocument")


class BackupError(Exception):
    """A refusal, with a short reason naming what failed; never a row or a byte."""


def digest(data: bytes) -> str:
    """Order-independent: the SHA-256 of the sorted rows, so physical row order never matters."""
    return hashlib.sha256(b"".join(sorted(data.splitlines(keepends=True)))).hexdigest()


def file_sha256(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    h = hashlib.sha256()
    with os.fdopen(fd, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tables(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
            if r[0] not in EXCLUDED_TABLES]


def copy_out(conn, table: str) -> bytes:
    with conn.cursor().copy(sql.SQL("COPY {} TO STDOUT").format(sql.Identifier(table))) as cp:
        return b"".join(bytes(chunk) for chunk in cp)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _copy_private(source: Path, target: Path) -> None:
    """Copy one custody file without following links on either side, then fsync it."""
    src = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    dst = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(src, "rb") as reader, os.fdopen(dst, "wb") as writer:
        shutil.copyfileobj(reader, writer, 1 << 20)
        writer.flush()
        os.fsync(writer.fileno())


def backup(conn, out_dir: Path, storage_dir: Path, name: str, commit: str = "") -> dict:
    """Write one coherent set to out_dir/name and return its receipt. `conn` is a psycopg connection as the backup
    role, not yet in a transaction."""
    import psycopg

    if not NAME.fullmatch(name):
        raise BackupError("the set name may hold only letters, digits, dot, dash and underscore")
    if not out_dir.is_absolute() or not out_dir.is_dir():
        raise BackupError("the output directory must be an existing absolute directory")
    final, pending = out_dir / name, out_dir / f"{name}.pending"
    if final.exists() or pending.exists():
        raise BackupError("a set with this name already exists")
    started = time.time()
    manifest = {"tables": {}, "documents": [], "revision": []}
    pending.mkdir(mode=0o700)
    try:
        (pending / "custody").mkdir(mode=0o700)
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        with conn.transaction():
            conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(SNAPSHOT_TIMEOUT_MS)))
            conn.execute(sql.SQL("SET LOCAL idle_in_transaction_session_timeout = {}").format(sql.Literal(SNAPSHOT_TIMEOUT_MS)))
            deadline = time.monotonic() + SNAPSHOT_TIMEOUT_MS / 1000
            for table in tables(conn):
                if time.monotonic() > deadline:
                    raise BackupError("the snapshot ran past its time limit")
                data = copy_out(conn, table)
                _private_file(pending / f"{table}.copy", data)
                manifest["tables"][table] = {"rows": data.count(b"\n"), "sha256": digest(data)}
            documents = conn.execute("SELECT storage_key, sha256, size FROM agreements_storeddocument ORDER BY id").fetchall()
            manifest["revision"] = sorted(map(list, conn.execute("SELECT app, name FROM django_migrations").fetchall()))
            server = conn.execute("SHOW server_version").fetchone()[0]
        for key, sha, size in documents:  # after the snapshot: write-once files are a superset of its rows
            if not CUSTODY_KEY.fullmatch(key):
                raise BackupError("a custody key has an unexpected shape")
            source = storage_dir / key
            if not source.is_file() or source.is_symlink():
                raise BackupError(f"custody file missing: {key}")
            target = pending / "custody" / key
            _copy_private(source, target)
            if file_sha256(target) != sha or target.stat().st_size != size:
                raise BackupError(f"custody file does not match its record: {key}")
            manifest["documents"].append({"key": key, "sha256": sha, "size": size})
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=1).encode()
        _private_file(pending / "manifest.json", manifest_bytes)
        receipt = {"name": name, "started_at": started, "finished_at": time.time(), "postgresql": server,
                   "commit": commit, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                   "excluded_tables": list(EXCLUDED_TABLES)}  # no counts: they reveal volume (026 section 6)
        _private_file(pending / "receipt.json", json.dumps(receipt, sort_keys=True, indent=1).encode())
        _fsync_dir(pending / "custody")
        _fsync_dir(pending)
        os.rename(pending, final)
        _fsync_dir(out_dir)
        return receipt
    except BaseException:
        shutil.rmtree(pending, ignore_errors=True)  # a failed run never leaves a set that looks usable
        raise


def private_set(backup_dir: Path) -> bool:
    """The set and every file in it are private to their owner (0700 and 0600), and nothing in it is a link."""
    if backup_dir.is_symlink() or stat.S_IMODE(backup_dir.stat().st_mode) != 0o700:
        return False
    return all(not p.is_symlink() and stat.S_IMODE(p.lstat().st_mode) in (0o600, 0o700) for p in backup_dir.rglob("*"))


def check_set(backup_dir: Path, expect_manifest_sha256: str = "") -> dict:
    """Refuse a set that is not private, or whose receipt, manifest, table copies or custody files do not agree.
    Returns the manifest."""
    if not backup_dir.is_dir() or not private_set(backup_dir):
        raise BackupError("the set must be a private directory (0700, files 0600, no links)")
    for required in ("manifest.json", "receipt.json"):
        if not (backup_dir / required).is_file():
            raise BackupError(f"the set has no {required}")
    manifest_bytes = (backup_dir / "manifest.json").read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    receipt = json.loads((backup_dir / "receipt.json").read_text())
    if manifest_sha != receipt.get("manifest_sha256"):
        raise BackupError("the manifest does not match the receipt")
    if expect_manifest_sha256 and manifest_sha != expect_manifest_sha256:
        raise BackupError("the manifest does not match the digest given on the command line")
    manifest = json.loads(manifest_bytes)
    for table, expected in manifest["tables"].items():
        path = backup_dir / f"{table}.copy"
        if not re.fullmatch(r"[a-z0-9_]{1,63}", table) or not path.is_file():
            raise BackupError("the manifest names a table copy that is missing or malformed")
        if digest(path.read_bytes()) != expected["sha256"]:
            raise BackupError(f"table copy does not match the manifest: {table}")
    for document in manifest["documents"]:
        if not CUSTODY_KEY.fullmatch(str(document.get("key", ""))):
            raise BackupError("the manifest names a custody key with an unexpected shape")
        path = backup_dir / "custody" / document["key"]
        if not path.is_file() or path.is_symlink() or file_sha256(path) != document["sha256"]:
            raise BackupError(f"custody file does not match the manifest: {document['key']}")
    return manifest


def check_target(admin_conn, database: str, confirm_database: str, manifest: dict) -> None:
    """The target is the one the operator named, nobody else is connected, it is empty, at the backup's migrations,
    and has exactly the set's tables."""
    current = admin_conn.execute("SELECT current_database()").fetchone()[0]
    if not confirm_database or confirm_database != current or current != database:
        raise BackupError("--confirm-database must name the target database")
    others = admin_conn.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                                " AND pid <> pg_backend_pid() AND backend_type = 'client backend'").fetchone()[0]
    if others:
        raise BackupError("other sessions are connected to the target database; stop them first")
    for table in CORE_TABLES:
        if admin_conn.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(sql.Identifier(table))).fetchone()[0]:
            raise BackupError("the target database is not empty; restore only into a new, migrated database")
    if sorted(map(list, admin_conn.execute("SELECT app, name FROM django_migrations").fetchall())) != manifest["revision"]:
        raise BackupError("the target database is not at the backup's migrations")
    if sorted(tables(admin_conn)) != sorted(manifest["tables"]):
        raise BackupError("the set's tables are not the target database's tables")


def restore(admin_conn, backup_dir: Path, storage_dir: Path, *, database: str, confirm_database: str,
            expect_manifest_sha256: str = "") -> dict:
    """Load a checked set into the target database (admin_conn, the bootstrap administrator, not in a transaction)
    and its custody files into storage_dir, recording the restore hold in the same transaction as the load."""
    manifest = check_set(backup_dir, expect_manifest_sha256)
    if storage_dir.is_symlink() or (storage_dir.exists() and any(storage_dir.iterdir())):
        raise BackupError("the custody directory to restore into is not empty")
    check_target(admin_conn, database, confirm_database, manifest)
    admin_conn.rollback()
    staging = storage_dir.parent / f".{storage_dir.name}.staging"
    if staging.exists():
        raise BackupError("a staging directory from an earlier restore is in the way")
    staging.mkdir(mode=0o700)
    try:
        for document in manifest["documents"]:  # staged and verified before the database is touched
            target = staging / document["key"]
            _copy_private(backup_dir / "custody" / document["key"], target)
            if file_sha256(target) != document["sha256"]:
                raise BackupError(f"custody file changed while staging: {document['key']}")
        _fsync_dir(staging)
        with admin_conn.transaction():
            admin_conn.execute("SET LOCAL lock_timeout = '10s'")
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
            for table, expected in manifest["tables"].items():  # every loaded table, before the hold is written
                if digest(copy_out(admin_conn, table)) != expected["sha256"]:
                    raise BackupError(f"the loaded table does not match the manifest: {table}")
            admin_conn.execute(
                "INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
                " VALUES (%s, %s, %s, 'catalyst_restore', now()) ON CONFLICT (subject_type, subject_id) DO NOTHING",
                [*RESTORE_HOLD, HOLD_REASON])
        storage_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(storage_dir, 0o700)
        for document in manifest["documents"]:  # into place only after the commit
            os.rename(staging / document["key"], storage_dir / document["key"])
        _fsync_dir(storage_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"restored": backup_dir.name, "hold": "recorded"}

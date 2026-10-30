"""Backup and restore of the database together with the custody files (026 section 6; 6B.7a; P6-D-7).

This turns the 9kg.7 rehearsal (tests/test_restore_rehearsal.py) into the operator's tools:

- **backup** reads one REPEATABLE READ, read-only snapshot as the backup role: every table except `django_session`
  (COPY) and the list of custody documents as they are at rest (9kg.34: a sealed file is verified against its
  envelope's digest; no key is read, held or copied, and a key directory may not overlap the set or the custody
  directory). The custody files are copied after the snapshot ends: they are
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

# Staff sessions, and the two-factor tables (TOTP keys and recovery codes are credentials): a restore means staff
# sign in again and re-enrol (6B.9).
EXCLUDED_TABLES = ("django_session", "otp_static_staticdevice", "otp_static_statictoken", "otp_totp_totpdevice")
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


def refuse_real_backup_while_undecided() -> None:
    """9kg.32 (council 030 Q3, D-51): a backup in a live environment holds real personal data, which no erasure could
    reach while POL-10's registry has an undecided value (erasure.registry); refuse it. The synthetic and local
    environments are not live, so drills and tests back up as before. Since 9kg.84 the shipped values are provisional
    but decided, so a live backup is allowed; the provisional lock keeps real intake out instead."""
    from django.conf import settings

    from config.guards import LIVE_ENVIRONMENTS
    from erasure import registry

    if getattr(settings, "CATALYST_ENV", "") in LIVE_ENVIRONMENTS and registry.problems():
        raise BackupError("the erasure registry has undecided values (POL-10): a backup of real data is refused")


# 9kg.34: each custody document as it is at rest: a sealed document's file, digest and size come from its envelope
# (no key is needed to verify a sealed file); a document stored before 9kg.34 and not yet migrated is its plaintext.
AT_REST_DOCUMENTS = ("SELECT coalesce(e.storage_key, d.storage_key), coalesce(e.cipher_sha256, d.sha256),"
                     " coalesce(e.cipher_size, d.size) FROM agreements_storeddocument d"
                     " LEFT JOIN agreements_custodyenvelope e ON e.document_id = d.id ORDER BY d.id")


def refuse_custody_keys(out_dir: Path, storage_dir: Path) -> None:
    """9kg.34: a backup never carries a custody key. The backup process may not hold the wrapping key, and neither the
    output directory nor the custody directory it copies from may overlap a key directory (a set that held a key would
    be a point-in-time copy that a destruction could never reach). The set itself holds only table copies and the
    custody files its snapshot names by the custody key pattern, so a `.key` file can never be copied into it."""
    from django.conf import settings

    if getattr(settings, "CATALYST_CUSTODY_WRAPPING_KEY", ""):
        raise BackupError("the backup process may not hold the custody wrapping key (9kg.34)")
    for setting in ("CATALYST_CUSTODY_KEY_DIR", "CATALYST_CUSTODY_KEY_MIRROR_DIR"):
        value = str(getattr(settings, setting, "") or "")
        if not value:
            continue
        keys = Path(value).resolve()
        for path in (out_dir.resolve(), storage_dir.resolve()):
            if path == keys or keys in path.parents or path in keys.parents:
                raise BackupError("a backup may not read from or write to a custody key directory (9kg.34)")


def backup(conn, out_dir: Path, storage_dir: Path, name: str, commit: str = "") -> dict:
    """Write one coherent set to out_dir/name and return its receipt. `conn` is a psycopg connection as the backup
    role, not yet in a transaction."""
    import psycopg

    if not NAME.fullmatch(name):
        raise BackupError("the set name may hold only letters, digits, dot, dash and underscore")
    refuse_real_backup_while_undecided()
    refuse_custody_keys(out_dir, storage_dir)
    if not out_dir.is_absolute() or not out_dir.is_dir():
        raise BackupError("the output directory must be an existing absolute directory")
    final, pending = out_dir / name, out_dir / f"{name}.pending"
    if final.exists() or pending.exists():
        raise BackupError("a set with this name already exists")
    started = time.time()
    # 9kg.33: the effect journal's head before the snapshot opens. Entries after it may postdate the backup point;
    # the post-restore step reconciles them (reconciliation is idempotent, so a head read early errs safely).
    from workflow import journal

    # PR #89 review: a journal fault never aborts the database backup; it is recorded in the receipt and the command
    # exits non-zero so the alert path sees it.
    journal_seq, journal_head, journal_id, journal_error = None, "", "", ""
    if journal.configured():
        try:
            journal_seq, journal_head, journal_id = journal.head()
        except journal.JournalError as exc:
            journal_error = exc.code
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
            documents = conn.execute(AT_REST_DOCUMENTS).fetchall()
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
                   "excluded_tables": list(EXCLUDED_TABLES),  # no counts: they reveal volume (026 section 6)
                   "effect_journal_seq": journal_seq, "effect_journal_head": journal_head,
                   "effect_journal_id": journal_id, "effect_journal_error": journal_error}
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
            expect_manifest_sha256: str = "", shipped_from: str = "", accept_behind_shipped: bool = False) -> dict:
    """Load a checked set into the target database (admin_conn, the bootstrap administrator, not in a transaction)
    and its custody files into storage_dir, recording the restore hold in the same transaction as the load.
    `shipped_from` is the off-host copy of the journal (9kg.60): a local journal that does not hold the copy's head is
    refused unless the owner accepts the loss (`accept_behind_shipped`, recorded with the head in the restore entry)."""
    manifest = check_set(backup_dir, expect_manifest_sha256)
    if storage_dir.is_symlink() or (storage_dir.exists() and any(storage_dir.iterdir())):
        raise BackupError("the custody directory to restore into is not empty")
    receipt = json.loads((backup_dir / "receipt.json").read_text())
    check_journal(receipt)
    behind_shipped, shipped_seq = check_shipped(shipped_from, accept_behind_shipped)
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
            # 9kg.33: the hold carries the backup anchor (journal identity, seq, head), so the post-restore step can
            # verify the journal even when the journal itself was replaced or emptied (PR #89 review).
            anchor = "|".join(["catalyst_restore", f"{receipt.get('effect_journal_id') or ''}:"
                               f"{receipt.get('effect_journal_seq') or 0}:{receipt.get('effect_journal_head') or ''}"])
            admin_conn.execute(
                "INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
                " VALUES (%s, %s, %s, %s, now()) ON CONFLICT (subject_type, subject_id) DO NOTHING",
                [*RESTORE_HOLD, HOLD_REASON, anchor])
        storage_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(storage_dir, 0o700)
        for document in manifest["documents"]:  # into place only after the commit
            os.rename(staging / document["key"], storage_dir / document["key"])
        _fsync_dir(storage_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # 9kg.33: mark the restore in the effect journal, with the backup point it took the tables back to, so the
    # post-restore step knows which entries to reconcile. After the commit: the journal is outside the rollback domain.
    from workflow import journal

    marker = journal.append("restore", f"restore:{backup_dir.name}", {
        "backup_seq": receipt.get("effect_journal_seq"), "backup_head": receipt.get("effect_journal_head") or "",
        "backup_journal_id": receipt.get("effect_journal_id") or "", "backup_started_at": receipt.get("started_at"),
        **({"behind_shipped": True} if behind_shipped else {}),
        **({"shipped_seq": shipped_seq} if shipped_seq is not None else {})})
    status = "marked" if marker else "not_marked"
    if receipt.get("effect_journal_error") or not isinstance(receipt.get("effect_journal_seq"), int):
        status = "unanchored"  # the set carries no journal head: the review reconciles every entry (safe, but unverified)
    return {"restored": backup_dir.name, "hold": "recorded", "effect_journal": status}


def check_shipped(shipped_from: str, accept_behind: bool) -> tuple[bool, int | None]:
    """9kg.60: the journal on this host must hold the head of the off-host copy (`shipped_from`, its provisioned
    directory, read here, never typed), or the effects after it would be forgotten (a journal rebuilt from an older
    copy, or the old host's lost). Restore the journal from the copy first. Returns (owner accepted a journal behind
    the copy, the copy's seq). A live restore must name the copy; `none` (nothing was ever shipped) is accepted there
    only with the owner's override, which the restore entry records."""
    from django.conf import settings

    from config.guards import LIVE_ENVIRONMENTS
    from workflow import journal, shipping

    live = settings.CATALYST_ENV in LIVE_ENVIRONMENTS
    if not shipped_from:
        if live:
            raise BackupError("a live restore names the journal's off-host copy (--shipped-from)")
        return False, None
    if shipped_from == "none":
        if live and not accept_behind:
            raise BackupError("a live restore with no off-host copy needs --accept-journal-behind-shipped")
        return live, None
    try:
        head = shipping.copy_head(shipped_from)
    except shipping.ShipError as exc:
        raise BackupError(f"the journal's off-host copy cannot be read ({exc.code})") from None
    if head is None:
        return False, 0
    try:
        journal.verify_anchor(journal.read(), head["identity"], head["seq"], head["hash"])
    except journal.JournalError:
        if accept_behind:
            return True, head["seq"]
        raise BackupError("the effect journal does not hold the head of its off-host copy (journal_behind_shipped):"
                          " restore the journal from the copy, or record --accept-journal-behind-shipped") from None
    return False, head["seq"]


def check_journal(receipt: dict) -> None:
    """PR #89 review: before the load, the configured journal must be the lineage the receipt names and must hold the
    receipt's head at its seq; an empty, truncated or replaced journal is refused here, not discovered at the lift.
    An unconfigured journal is not checked (the post-restore step then refuses to lift for want of evidence)."""
    from workflow import journal

    seq, head, identity = receipt.get("effect_journal_seq"), receipt.get("effect_journal_head") or "", receipt.get("effect_journal_id") or ""
    if not journal.configured() or not isinstance(seq, int) or isinstance(seq, bool) or seq <= 0:
        return
    try:
        entries = journal.read()
    except journal.JournalError as exc:
        raise BackupError(f"the effect journal cannot be read ({exc.code})") from None
    if len(entries) < seq or entries[seq - 1].hash != head or (identity and str(entries[0].data.get("id", "")) != identity):
        raise BackupError("the effect journal does not match the backup receipt (journal_mismatch)")

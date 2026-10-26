"""Restore one checked backup set into this process's database (026 section 6; 6B.7a), as the bootstrap
administrator, then record the restore hold. The database must already be migrated (`manage.py migrate` as the
owner) and unused; the worker must be stopped. Exit 0 on success, 1 when refused (nothing is loaded)."""

import json
import os
from pathlib import Path

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand

from config import backup
from config.management.commands.catalyst_backup import connection_args


def admin_password() -> str:
    directory = settings.CATALYST_SECRETS_DIR
    if directory:
        with open(os.path.join(directory, "admin_password"), encoding="utf-8") as handle:
            return handle.read().rstrip("\r\n")
    return os.environ["CATALYST_DB_ADMIN_PASSWORD"]


class Command(BaseCommand):
    help = "Restore a backup set into this database and record the restore hold."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", required=True, help="the backup set's directory")
        parser.add_argument("--storage-dir", required=True, help="an empty or new custody directory to restore into")
        parser.add_argument("--confirm-database", required=True, help="the target database's name, typed again")
        parser.add_argument("--expect-manifest-sha256", default="", help="the manifest digest recorded with the set")
        parser.add_argument("--shipped-head", default="",
                            help="9kg.60: the journal head last shipped off the host (head.json at the copy), or none")
        parser.add_argument("--accept-journal-behind-shipped", action="store_true",
                            help="the owner accepts losing the journal entries after the local head (recorded)")

    def handle(self, *args, source, storage_dir, confirm_database, expect_manifest_sha256, shipped_head,
               accept_journal_behind_shipped, **options):
        os.umask(0o077)
        args = {**connection_args(), "user": os.environ["CATALYST_DB_ADMIN_USER"], "password": admin_password()}
        try:
            with psycopg.connect(**args) as conn:
                summary = backup.restore(conn, Path(source), Path(storage_dir), database=args["dbname"],
                                         confirm_database=confirm_database,
                                         expect_manifest_sha256=expect_manifest_sha256, shipped_head=shipped_head,
                                         accept_behind_shipped=accept_journal_behind_shipped)
        except backup.BackupError as exc:
            self.stderr.write(f"restore refused: {exc}")
            raise SystemExit(1) from None
        except psycopg.Error as exc:  # its detail can quote a row: only the class and the code (PR #67 review)
            self.stderr.write(f"restore failed: {type(exc).__name__} {exc.sqlstate or ''}".rstrip())
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(summary, sort_keys=True))

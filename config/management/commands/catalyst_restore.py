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

    def handle(self, *args, source, storage_dir, **options):
        os.umask(0o077)
        args = {**connection_args(), "user": os.environ["CATALYST_DB_ADMIN_USER"], "password": admin_password()}
        try:
            with psycopg.connect(**args) as conn:
                summary = backup.restore(conn, Path(source), Path(storage_dir))
        except backup.BackupError as exc:
            self.stderr.write(f"restore refused: {exc}")
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(summary, sort_keys=True))

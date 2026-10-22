"""Write one coherent backup set (026 section 6; 6B.7a): run it with the backup role's login. Prints the receipt
(counts, digests, versions; never personal data). Exit 0 on success, 1 when refused."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand

from config import backup


def connection_args() -> dict:
    db = settings.DATABASES["default"]
    return {"host": db["HOST"], "port": db.get("PORT") or "5432", "dbname": db["NAME"], "user": db["USER"],
            "password": db["PASSWORD"]}


def commit() -> str:
    try:
        return Path("/app/COMMIT").read_text().strip()
    except OSError:
        return ""


class Command(BaseCommand):
    help = "Write a backup set (database snapshot, custody files, manifest, receipt)."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="an existing absolute directory for the set")
        parser.add_argument("--storage-dir", required=True, help="the custody directory")
        parser.add_argument("--name", default="", help="the set's name (default: a UTC timestamp)")

    def handle(self, *args, out, storage_dir, name, **options):
        name = name or "catalyst-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        os.umask(0o077)
        try:
            with psycopg.connect(**connection_args()) as conn:
                receipt = backup.backup(conn, Path(out), Path(storage_dir), name, commit())
        except backup.BackupError as exc:
            self.stderr.write(f"backup refused: {exc}")
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(receipt, sort_keys=True))

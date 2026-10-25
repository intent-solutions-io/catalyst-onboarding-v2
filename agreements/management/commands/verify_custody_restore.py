"""Verify a restored database against a restored custody directory (`024` proposal 1; bead 9kg.7).

Read-only. For every `StoredDocument` row it checks that the file named by its key exists in `--storage-dir`, is a
regular file owned by this user with mode 0600, and has the recorded size and SHA-256. 9kg.34: a sealed document is
checked as it is at rest, against its `CustodyEnvelope` (the sealed file, its digest and size); no key is needed or
read, so this check never says whether a document can still be opened (a destroyed key is the point of an erasure). Files in the directory that
no row references are reported as orphans and never deleted (deleting them is a retention act, POL-10). Prints
counts and keys only, never document bytes. With `--manifest`, the restored rows must also equal the backup
manifest's documents, so an empty or truncated table cannot pass. Orphans are reported but do not fail the check.
Exit status 0 when every referenced file verifies (and the manifest matches), 1 otherwise.

Run it only against a restore whose effects are held: no worker and no provider settings (the rehearsal starts
neither).
"""

import hashlib
import json
import os
import stat
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from agreements.storage import KEY
from config.backup import AT_REST_DOCUMENTS


class Command(BaseCommand):
    help = "Verify restored custody files against the restored StoredDocument rows; exit 1 on any missing or bad file."

    def add_arguments(self, parser):
        parser.add_argument("--storage-dir", required=True, help="the restored custody directory")
        parser.add_argument("--manifest", help="the backup manifest: its documents must equal the restored rows")

    def handle(self, *args, storage_dir, manifest=None, **options):
        root = Path(storage_dir)
        if not root.is_absolute() or not root.is_dir():
            raise CommandError("storage directory must be an existing absolute directory")
        report = {"documents": 0, "verified": 0, "missing": [], "unsafe": [], "mismatch": [], "orphans": []}
        referenced = set()
        with connection.cursor() as cursor:
            cursor.execute(AT_REST_DOCUMENTS)
            documents = [(key, sha, size) for key, sha, size in cursor.fetchall()]
        for key, sha, size in documents:
            report["documents"] += 1
            referenced.add(key)
            problem = self._check(root, key, sha, size)
            if problem:
                report[problem].append(key)
            else:
                report["verified"] += 1
        for entry in sorted(os.listdir(root)):
            if entry not in referenced:
                report["orphans"].append(entry if KEY.fullmatch(entry) else "<non-key name>")
        ok = report["verified"] == report["documents"]
        if manifest:
            expected = {(d["key"], d["sha256"], d["size"]) for d in json.loads(Path(manifest).read_text())["documents"]}
            restored = set(documents)
            report["manifest_match"] = expected == restored  # an empty or truncated table cannot pass
            ok = ok and report["manifest_match"]
        self.stdout.write(json.dumps({"ok": ok, **report}, sort_keys=True))
        if not ok:
            raise SystemExit(1)

    @staticmethod
    def _check(root: Path, key: str, sha: str, size_expected: int) -> str:
        if not KEY.fullmatch(key or ""):
            return "unsafe"
        try:
            fd = os.open(root / key, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unsafe"
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                return "unsafe"
            digest, size = hashlib.sha256(), 0
            while chunk := os.read(fd, 65536):
                digest.update(chunk)
                size += len(chunk)
        finally:
            os.close(fd)
        if size != size_expected or digest.hexdigest() != sha:
            return "mismatch"
        return ""

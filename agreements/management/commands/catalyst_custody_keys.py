"""The custody keys, for the operator (9kg.34; agreements.keystore): their state, the migration of documents stored in
the clear before 9kg.34, and key recovery by the named holder.

    manage.py catalyst_custody_keys --provision
    manage.py catalyst_custody_keys --status
    manage.py catalyst_custody_keys --migrate --confirm
    manage.py catalyst_custody_keys --recover
    manage.py catalyst_custody_keys --reap-orphans [--confirm] [--min-age-seconds N]

- `--provision`: the one step that creates the key directory and its mirror (0700) and writes each one's
  provisioning marker. Nothing else ever creates them: every other operation refuses with `key_store_unavailable` when a
  directory or its marker is missing, so an unmounted volume is never read as an empty key store.
- `--status` (read-only): documents sealed and still in the clear, keys in the key directory and in its mirror, keys
  the journal records as destroyed and whether any of them is still present, sealed documents whose key is missing
  (recoverable from the mirror, or lost), migrated documents whose plaintext file is still on disk, and keys no
  document names. `ok` is true only when nothing is in the clear, no destroyed key is present, no key is missing and
  the mirror holds every key.
- `--migrate --confirm`: for each document stored in the clear, read it (verified against its recorded plaintext
  hash), seal it under a new name and a new key, verify that the sealed copy opens to the same bytes, record its
  envelope (committed), then remove the plaintext file; then remove any plaintext a migration interrupted after its
  commit left behind. Run it with the worker stopped; it is safe to re-run.
- `--recover`: the named holder's recovery (agreements.custody_policy `recovery_holder`, within `recovery_time_bound`)
  after a key directory or its mirror was lost or damaged: makes both hold the same keys again from the copy that
  survives, never restoring a key the journal records as destroyed, and finishes any destruction left half done. The
  wrapping key comes from the escrow, as a secret file, for this run.

- `--reap-orphans` (review of PR #102, F2): a key no envelope names (and the journal does not record as destroyed) and
  a sealed file no envelope names are what a crash between a write and its record leaves. A dry run lists the counts;
  `--confirm` journals each one (`custody_orphan_reaped`) and removes it. Only orphans older than `--min-age-seconds`
  (default 3600) are touched, so a write in progress is never reaped; run it with the worker stopped. A plaintext
  file no row names is reported, never removed here (removing it is a retention act).

Every output is one JSON line of counts and codes, never a key, a document's bytes or a person's data, and states the
claim's scope: v2's custody copy only; the provider's copy is under P4-D-15 until POL-10. Exit 0 when the action
succeeded (for `--status`: when `ok`), 1 otherwise. Not for a web or worker process.
"""

import json
import os
import time

from django.core.management.base import BaseCommand
from django.db import IntegrityError, connection, transaction

from agreements import custody_policy, keystore, storage
from agreements.models import CustodyEnvelope, StoredDocument
from config import runtime


class Command(BaseCommand):
    help = "Report on, migrate or recover the custody keys (9kg.34)."

    def add_arguments(self, parser):
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument("--provision", action="store_true", help="create the key directories and their markers")
        action.add_argument("--status", action="store_true", help="report the keys' state (read-only)")
        action.add_argument("--migrate", action="store_true", help="seal every document stored in the clear")
        action.add_argument("--recover", action="store_true", help="re-align the key directory and its mirror")
        action.add_argument("--reap-orphans", action="store_true", help="list (or with --confirm remove) orphans")
        parser.add_argument("--confirm", action="store_true", help="required with --migrate; acts with --reap-orphans")
        parser.add_argument("--min-age-seconds", type=int, default=3600, help="--reap-orphans: leave younger orphans")

    def emit(self, report: dict, ok: bool):
        self.stdout.write(json.dumps({"ok": ok, **report, "scope": custody_policy.SCOPE}, sort_keys=True))
        if not ok:
            raise SystemExit(1)

    def refuse(self, code: str):
        self.emit({"refused": code}, False)

    def handle(self, *args, provision, status, migrate, recover, reap_orphans, confirm, min_age_seconds, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            self.refuse("not_a_management_process")
        try:
            if provision:
                self.emit(keystore.provision(), True)
            elif status:
                report = state()
                self.emit(report, report["healthy"])
            elif migrate:
                if not confirm:
                    self.refuse("confirm_required")
                self.emit(migrate_plaintext(), True)
            elif reap_orphans:
                self.emit(reap(confirm, max(0, min_age_seconds)), True)
            else:
                self.emit(keystore.recover(), True)
        except keystore.KeyStoreError as exc:
            self.refuse(exc.code)
        except storage.StorageError as exc:
            self.refuse(str(exc))


def state() -> dict:
    from workflow import journal

    primary, mirror = keystore.listing()
    try:
        destroyed = keystore.destroyed_refs(journal.read()) if journal.configured() else set()
        journal_state = "ok" if journal.configured() else "not_configured"
    except journal.JournalError as exc:
        destroyed, journal_state = set(), exc.code
    envelopes = list(CustodyEnvelope.objects.select_related("document").order_by("id"))
    refs = {e.key_ref for e in envelopes}
    report = {
        "documents": StoredDocument.objects.count(),
        "sealed": len(envelopes),
        "in_the_clear": StoredDocument.objects.filter(envelope__isnull=True).count(),
        "keys_primary": len(primary),
        "keys_mirror": len(mirror),
        "mirror_missing": len(primary - mirror),
        "primary_missing_recoverable": sum(1 for r in refs - primary if r in mirror and r not in destroyed),
        "lost": sum(1 for r in refs - primary - mirror if r not in destroyed),
        "destroyed_journaled": len(destroyed),
        "destroyed_still_present": len((primary | mirror) & destroyed),
        "sealed_after_destruction": len(refs & destroyed),  # documents an erasure made unreadable (expected)
        "orphan_keys": len((primary | mirror) - refs - destroyed),  # an interrupted write's key: never used
        "orphan_sealed_files": len(orphan_files(envelopes)),
        "plaintext_lingering": sum(1 for e in envelopes if e.migrated and storage.exists(e.document.storage_key)),
        "journal": journal_state,
    }
    report["healthy"] = journal_state == "ok" and not any(
        report[k] for k in ("in_the_clear", "mirror_missing", "primary_missing_recoverable", "lost",
                            "destroyed_still_present", "plaintext_lingering", "orphan_keys", "orphan_sealed_files"))
    return report


MIGRATE_LOCK = 0x6B67_3334  # "9kg.34": one --migrate at a time (a session advisory lock)


def migrate_plaintext() -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [MIGRATE_LOCK])
        if not cursor.fetchone()[0]:
            raise storage.StorageError("migrate_in_progress")
    try:
        return _migrate()
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [MIGRATE_LOCK])


def _migrate() -> dict:
    report = {"sealed": 0, "plaintext_removed": 0, "plaintext_already_gone": 0, "already_sealed": 0}
    for document in StoredDocument.objects.filter(envelope__isnull=True).order_by("id"):
        sealed = storage.seal_existing(document.storage_key, document.sha256, document.size)
        try:
            with transaction.atomic():
                CustodyEnvelope.objects.create(document=document, migrated=True, **sealed.fields())
        except IntegrityError:
            storage.discard(sealed)  # sealed meanwhile by another run: ours is never recorded, so it goes
            report["already_sealed"] += 1
            continue
        except BaseException:
            storage.discard(sealed)  # an interrupted migration leaves no orphan it can still reach
            raise
        report["sealed"] += 1
        report["plaintext_removed" if storage.dispose_plaintext(document.storage_key) else "plaintext_already_gone"] += 1
    for envelope in CustodyEnvelope.objects.filter(migrated=True).select_related("document"):
        # A migration interrupted after its commit: the sealed copy is recorded; the plaintext goes now.
        if storage.exists(envelope.document.storage_key):
            storage.read(envelope.document.storage_key, envelope.document.sha256, envelope.document.size, envelope)
            report["plaintext_removed"] += int(storage.dispose_plaintext(envelope.document.storage_key))
    return report


def orphan_files(envelopes) -> list:
    """Sealed files in custody that no envelope names (a crash between the write and the record)."""
    named = {e.storage_key for e in envelopes}
    root = storage.root()
    out = []
    for name in sorted(os.listdir(root)) if root.is_dir() else []:
        if name in named or not storage.KEY.fullmatch(name):
            continue
        with open(root / name, "rb") as handle:
            if handle.read(len(keystore.MAGIC)) == keystore.MAGIC:
                out.append(name)
    return out


def reap(confirm: bool, min_age: int) -> dict:
    from workflow import journal

    envelopes = list(CustodyEnvelope.objects.all())
    refs = {e.key_ref for e in envelopes}
    destroyed = keystore.journaled_destroyed()
    primary_dir, mirror_dir = keystore.directories()
    primary, mirror = keystore.listing()
    cutoff = time.time() - min_age

    def old_enough(*paths) -> bool:
        return all(not p.exists() or p.stat().st_mtime <= cutoff for p in paths)

    keys = [r for r in sorted((primary | mirror) - refs - destroyed)
            if old_enough(primary_dir / f"{r}.key", mirror_dir / f"{r}.key")]
    files = [n for n in orphan_files(envelopes) if old_enough(storage.root() / n)]
    names = {n for n in os.listdir(storage.root()) if storage.KEY.fullmatch(n)} if storage.root().is_dir() else set()
    recorded = {e.storage_key for e in envelopes} | set(StoredDocument.objects.values_list("storage_key", flat=True))
    plaintext = sorted(names - recorded - set(orphan_files(envelopes)))
    report = {"orphan_keys": len(keys), "orphan_sealed_files": len(files), "unreferenced_other_files": len(plaintext),
              "confirmed": confirm, "removed_keys": 0, "removed_files": 0}
    if not confirm:
        return report
    if not journal.configured():
        raise keystore.KeyStoreError("journal_unavailable")
    for ref in keys:
        if journal.append("custody_orphan_reaped", f"custody_orphan:{ref}", {"kind": "key", "phase": "prepare"}) is None:
            raise keystore.KeyStoreError("journal_unavailable")
        keystore.discard(ref)
        report["removed_keys"] += 1
    for name in files:
        if journal.append("custody_orphan_reaped", f"custody_orphan:{name[:-4]}",
                          {"kind": "sealed_file", "phase": "prepare"}) is None:
            raise keystore.KeyStoreError("journal_unavailable")
        storage.discard_file(name)
        report["removed_files"] += 1
    return report

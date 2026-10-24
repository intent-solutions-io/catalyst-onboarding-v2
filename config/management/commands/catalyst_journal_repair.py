"""Repair a torn effect journal (9kg.33; PR #89 review): run by the owner when `catalyst_health` or the post-restore
step reports `torn_tail`. Moves the bytes after the last complete entry to `effects.jsonl.torn-<timestamp>`, so
appends can continue, and journals the repair with the discarded byte count and the last good hash. Exit 0 when
repaired or nothing was torn, 1 when refused. Nothing else ever rewrites the journal."""

import json

from django.core.management.base import BaseCommand

from workflow import journal


class Command(BaseCommand):
    help = "Move a torn tail of the effect journal aside and journal the repair (owner only)."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true", help="required: the torn bytes are moved aside, not deleted")

    def handle(self, *args, confirm, **options):
        if not confirm:
            self.stderr.write("journal repair refused: pass --confirm")
            raise SystemExit(1)
        if not journal.configured():
            self.stderr.write("journal repair refused: CATALYST_EFFECT_JOURNAL_DIR is not configured")
            raise SystemExit(1)
        try:
            result = journal.repair()
        except (journal.JournalError, OSError) as exc:
            self.stderr.write(f"journal repair refused: {getattr(exc, 'code', type(exc).__name__.lower())}")
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(result, sort_keys=True))

"""Owner-run journal rotation and retention-aware relocation, never deletion."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from workflow import journal


class Command(BaseCommand):
    help = "Rotate the effect journal, or archive segments against all retained backup receipts."

    def add_arguments(self, parser):
        action = parser.add_mutually_exclusive_group(required=True)
        action.add_argument("--rotate", action="store_true")
        action.add_argument(
            "--archive-receipts", help="JSON array of complete retained-backup receipts"
        )
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--segment-aware-recovery", action="store_true")
        parser.add_argument("--complete-backup-inventory", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm"] or not journal.configured():
            raise CommandError(
                "journal segments refused: configured journal and --confirm required"
            )
        if options["rotate"] and not options["segment_aware_recovery"]:
            raise CommandError(
                "journal rotation refused: verify recovery readers, then pass --segment-aware-recovery"
            )
        if options["archive_receipts"] and not options["complete_backup_inventory"]:
            raise CommandError(
                "journal archival refused: --complete-backup-inventory required, including off-host backups"
            )
        try:
            if options["rotate"]:
                result = journal.rotate()
            else:
                receipts = json.loads(Path(options["archive_receipts"]).read_text())
                if not isinstance(receipts, list) or any(
                    not isinstance(r, dict) for r in receipts
                ):
                    raise ValueError
                result = journal.archive_segments(receipts)
        except (journal.JournalError, OSError, ValueError, TypeError) as exc:
            raise CommandError(
                f"journal segments refused: {getattr(exc, 'code', type(exc).__name__.lower())}"
            ) from None
        self.stdout.write(json.dumps(result, sort_keys=True))

"""Run the post-restore step (026 section 6; 6B.7b; 9kg.33) as the owner, after `catalyst_restore`, before any worker
or web process starts. First without --lift: it resets links, staff passwords and sessions, recovers running actions,
queues revocations, replays the effect journal, reads each provider and prints a report. Check the outward actions
against the providers, re-issue staff passwords, resolve each `restore_effect_*` item (`--resolve <id> --note ...`),
then run it again with --lift --outward-checked --no-closures-after-backup. Exit 0 done, 1 refused. See
config.post_restore."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from config import post_restore


class Command(BaseCommand):
    help = ("Invalidate links and sessions, recover running actions, queue revocations, reconcile effects after the "
            "backup; with --lift, lift the hold.")

    def add_arguments(self, parser):
        parser.add_argument("--confirm-database", required=True, help="the restored database's name, typed again")
        parser.add_argument("--lift", action="store_true", help="lift the restore hold so work resumes (after a review run)")
        parser.add_argument("--outward-checked", action="store_true",
                            help="the reported outward actions were compared with the providers")
        parser.add_argument("--no-closures-after-backup", action="store_true",
                            help="no application was closed after the backup's time (or its access was removed again)")
        parser.add_argument("--resolve", default="", metavar="ITEM",
                            help="resolve one restore_effect_* staff item by its public id (needs --note)")
        parser.add_argument("--note", default="", help="the reason for --resolve, recorded with the resolution")

    def handle(self, *args, confirm_database, lift, outward_checked, no_closures_after_backup, resolve, note, **options):
        if confirm_database != settings.DATABASES["default"]["NAME"]:
            self.stderr.write("post-restore refused: --confirm-database must name this database")
            raise SystemExit(1)
        try:
            if resolve:
                report = post_restore.resolve_effect(resolve, note)
            else:
                report = post_restore.run(lift, outward_checked, no_closures_after_backup)
        except post_restore.PostRestoreError as exc:
            self.stderr.write(f"post-restore refused: {exc}")
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(report, sort_keys=True))

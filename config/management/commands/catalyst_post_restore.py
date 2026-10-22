"""Run the post-restore step (026 section 6; 6B.7b) as the owner, after `catalyst_restore`, before any worker or web
process starts. Without --lift it does everything but lift the restore hold and prints a report of counts; review the
queued outward actions against the providers, then run it again with --lift. Exit 0 done, 1 refused."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from config import post_restore


class Command(BaseCommand):
    help = "Invalidate links and sessions, recover running actions, queue revocations; with --lift, lift the hold."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-database", required=True, help="the restored database's name, typed again")
        parser.add_argument("--lift", action="store_true", help="also lift the restore hold so work resumes")

    def handle(self, *args, confirm_database, lift, **options):
        if confirm_database != settings.DATABASES["default"]["NAME"]:
            self.stderr.write("post-restore refused: --confirm-database must name this database")
            raise SystemExit(1)
        try:
            report = post_restore.run(lift)
        except post_restore.PostRestoreError as exc:
            self.stderr.write(f"post-restore refused: {exc}")
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(report, sort_keys=True))

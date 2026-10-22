"""Close every outstanding applicant link after the link-signing key leaked (027, the leak procedure; 6B.10a). Run as
the owner, after the new key is deployed with no fallback: links signed with the leaked key already fail, and this
closes the records behind them and opens a staff item for each applicant left waiting, so staff send fresh links.
Exit 0 done, 1 refused."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from config import post_restore


class Command(BaseCommand):
    help = "Close every outstanding applicant link and open staff items to reissue them (after a leaked link key)."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-database", required=True, help="this database's name, typed again")

    def handle(self, *args, confirm_database, **options):
        if confirm_database != settings.DATABASES["default"]["NAME"]:
            self.stderr.write("close-links refused: --confirm-database must name this database")
            raise SystemExit(1)
        if settings.CATALYST_VERIFICATION_FALLBACK_KEYS:
            self.stderr.write("close-links refused: a leaked key must not stay a fallback; deploy with no fallback first")
            raise SystemExit(1)
        report = {}
        with transaction.atomic():
            post_restore.close_outstanding_links(report, cause="rotation")
        self.stdout.write(json.dumps(report, sort_keys=True))

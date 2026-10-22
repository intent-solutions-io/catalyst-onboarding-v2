"""Close every outstanding confirmation link after the link-signing key leaked (027, the leak procedure; 6B.10a). Run
as the owner, after the new key is deployed with no fallback: links signed with the leaked key already fail, and this
closes the records behind them and opens a staff item for each applicant left waiting, so staff send fresh links. Only
confirmation links are signed with that key; password and withdrawal links are random tokens a key leak does not touch.

    manage.py catalyst_close_links --confirm-database <name> --leaked-key-sha256 <hex>

The leaked key is named by its SHA-256 (`sha256sum` of the old key file), never by its value. The command refuses
while that key is still this process's link key or one of its fallbacks: the new key must be deployed first, or the
links staff reissue would be signed with the leaked one. Exit 0 done, 1 refused."""

import hashlib
import json
import re

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from config import post_restore


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Command(BaseCommand):
    help = "After a leaked link key: close every outstanding confirmation link and open staff items to reissue them."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-database", required=True, help="this database's name, typed again")
        parser.add_argument("--leaked-key-sha256", required=True, help="sha256sum of the leaked key file's value")

    def refuse(self, why: str):
        self.stderr.write(f"close-links refused: {why}")
        raise SystemExit(1)

    def handle(self, *args, confirm_database, leaked_key_sha256, **options):
        if confirm_database != settings.DATABASES["default"]["NAME"]:
            self.refuse("--confirm-database must name this database")
        if not re.fullmatch(r"[0-9a-f]{64}", leaked_key_sha256):
            self.refuse("--leaked-key-sha256 must be 64 lowercase hex characters")
        if settings.CATALYST_VERIFICATION_FALLBACK_KEYS:
            self.refuse("a leaked key must not stay a fallback; deploy with no fallback first")
        if _digest(settings.CATALYST_VERIFICATION_KEY) == leaked_key_sha256:
            self.refuse("the leaked key is still the link key; deploy the new key first")
        report = {}
        with transaction.atomic():
            post_restore.close_outstanding_links(report, cause="rotation", signed_only=True)
        self.stdout.write(json.dumps(report, sort_keys=True))

"""Prepare local journal exports or acknowledge receipts from the trusted off-host receiver."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from config import runtime
from workflow import journal, journal_pull, shipping


class Command(BaseCommand):
    help = "Stage a journal without marking it shipped, or acknowledge a verified receiver receipt."

    def add_arguments(self, parser):
        choice = parser.add_mutually_exclusive_group(required=True)
        choice.add_argument(
            "--stage", help="Private provisioned local staging directory"
        )
        choice.add_argument(
            "--acknowledge",
            type=Path,
            help="Receipt returned by the authenticated off-host receiver",
        )

    def handle(self, stage=None, acknowledge=None, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            raise CommandError("journal transfer refused: not_a_management_process")
        try:
            if stage:
                result = journal_pull.stage(stage)
            else:
                result = journal_pull.acknowledge(
                    json.loads(journal_pull._read(acknowledge))
                )
        except (shipping.ShipError, journal.JournalError, OSError, ValueError) as exc:
            raise CommandError(
                f"journal transfer refused: {getattr(exc, 'code', type(exc).__name__)}"
            ) from None
        self.stdout.write(json.dumps(result, sort_keys=True))

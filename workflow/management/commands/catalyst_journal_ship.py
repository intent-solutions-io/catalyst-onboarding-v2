"""Copy the effect journal and its head off the host (9kg.60; workflow.shipping). Run by a host timer every few
minutes, as the owner of the journal directory, with the off-host destination mounted.

    manage.py catalyst_journal_ship --to <absolute directory>

Prints one JSON line: the shipped seq and the head (`<identity>:<seq>:<hash>`). Exit 0 when shipped, 1 when refused
(the code says why; `destination_ahead_of_journal` means the local journal lost entries already shipped)."""

import json

from django.core.management.base import BaseCommand

from config import runtime
from workflow import shipping


class Command(BaseCommand):
    help = "Ship the effect journal and its head to an off-host directory."

    def add_arguments(self, parser):
        parser.add_argument("--to", dest="destination", required=True, help="the off-host directory (absolute)")

    def handle(self, *args, destination, **options):
        if runtime.process_kind() in runtime.ENFORCED_KINDS:
            self.stderr.write("journal shipping refused: not_a_management_process")
            raise SystemExit(1)
        try:
            report = shipping.ship(destination)
        except shipping.ShipError as exc:
            self.stderr.write(f"journal shipping refused: {exc.code}")
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(report, sort_keys=True))

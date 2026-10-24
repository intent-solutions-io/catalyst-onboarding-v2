"""Check the durable erasure record (9kg.32; 029 section 6.2): the journal's chain, that it holds the head the owner
kept out of band from the last erasure (an emptied, replaced or rolled-back store is refused, never read as "no
erasures"), open intents and owed provider handoffs.

    manage.py catalyst_erasure_record --expect-head <identity>:<seq>:<hash>
    manage.py catalyst_erasure_record --expect-head none      # only before the first erasure

Prints one JSON line with counts, the current head and the public references of open intents. Exit 0 when the record
is intact, the head is present and nothing is open; 1 otherwise."""

import json

from django.core.management.base import BaseCommand

from erasure import record


class Command(BaseCommand):
    help = "Verify the durable erasure record against the head kept out of band."

    def add_arguments(self, parser):
        parser.add_argument("--expect-head", required=True, help="the head printed by the last erasure, or 'none'")

    def handle(self, *args, expect_head, **options):
        try:
            report = record.verify(expect_head)
        except record.RecordError as exc:
            self.stderr.write(f"erasure record refused: {exc.code}")
            raise SystemExit(1) from None
        self.stdout.write(json.dumps(report, sort_keys=True))
        if report["open"]:
            self.stderr.write("erasure record: an erasure is open; re-run catalyst_erase for each reference listed")
            raise SystemExit(1)

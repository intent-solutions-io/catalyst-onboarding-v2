"""Print the selection-quality counts of 019 section 9 as JSON (oc4.12; the weekly summary, `f1u.7`): decisions by
basis and outcome, human-only decisions by structured reason, decisions by policy reference. Counts only; no name,
reason text or identifier. Read-only."""

import json

from django.core.management.base import BaseCommand

from assessments import decisions


class Command(BaseCommand):
    help = "Print selection-quality counts (019 section 9): decisions by basis, outcome, human-only reason and policy."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(decisions.scorecard(), sort_keys=True))

"""Print every Catalyst health signal (026 section 7; 6B.4) as JSON. Exit 0 healthy, 1 any anomaly, 2 the check
itself failed (for example the database is unreachable), never a finding. Read-only; counts and signal names only.
A host timer runs it and submits the result to the estate alert floor (6B.12)."""

import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from config import system_health


class Command(BaseCommand):
    help = "Report Catalyst health; exit status 1 on any anomaly, 2 when the check itself fails."
    requires_system_checks = []  # a failing system check must surface as exit 2 from this command, not as exit 1

    def handle(self, *args, **options):
        try:  # everything, so any failure of the check itself is exit 2, never a finding (PR #64 review)
            report = system_health.report()
            anomalies = sorted(f"{part}.{name}" for part, values in report.items() for name in values["anomalies"])
            report["anomalies"] = anomalies
            report["generated_at"] = datetime.now(timezone.utc).isoformat()
            output = json.dumps(report, sort_keys=True, default=str)
        except Exception as exc:
            self.stderr.write(f"health check failed: {type(exc).__name__}")
            raise SystemExit(2) from None
        self.stdout.write(output)
        if anomalies:
            raise SystemExit(1)

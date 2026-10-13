"""Print the correspondence health signals (016 G) and exit 1 when any anomaly is present, so P6 can wire
the exit status to alerting. Read-only; prints counts and signal names only."""

import json

from django.core.management.base import BaseCommand

from correspondence.health import collector_health, send_health


class Command(BaseCommand):
    help = "Report correspondence health (016 G1 and G3); exit status 1 on any anomaly."

    def handle(self, *args, **options):
        report = {"sends": send_health(), "collector": collector_health()}
        self.stdout.write(json.dumps(report, sort_keys=True))
        if report["sends"]["anomalies"] or report["collector"]["anomalies"]:
            raise SystemExit(1)

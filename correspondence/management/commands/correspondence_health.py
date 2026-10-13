"""Print the correspondence health signals (016 G) and exit 1 when any anomaly is present, so P6 can wire
the exit status to alerting. Exit 2 means the check itself failed (for example, the database is unreachable),
never a health finding. Read-only; prints counts and signal names only."""

import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from correspondence.health import collector_health, mail_behaviour_health, reminder_health, reply_health, send_health


class Command(BaseCommand):
    help = "Report correspondence health (016 G1 to G7); exit status 1 on any anomaly."

    def handle(self, *args, **options):
        try:
            report = {"sends": send_health(), "collector": collector_health(), "replies": reply_health(),
                      "reminders": reminder_health(), "mail": mail_behaviour_health()}
        except Exception as exc:  # the check failed: never reported as an anomaly
            self.stderr.write(f"health check failed: {type(exc).__name__}")
            raise SystemExit(2) from None
        anomalous = any(part["anomalies"] for part in report.values())
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        self.stdout.write(json.dumps(report, sort_keys=True))
        if anomalous:
            raise SystemExit(1)

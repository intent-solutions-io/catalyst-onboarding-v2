"""Queue the recurring `clear_sessions` action if none is queued (6B.9). Idempotent; run at every deployment, after
migrate. Each run of the action queues its successor, and catalyst_health reports when none is scheduled."""

from django.core.management.base import BaseCommand

from accounts.staff_access import schedule_session_cleanup


class Command(BaseCommand):
    help = "Queue the hourly removal of expired staff sessions unless it is already queued."

    def handle(self, *args, **options):
        self.stdout.write("queued" if schedule_session_cleanup() else "already scheduled")

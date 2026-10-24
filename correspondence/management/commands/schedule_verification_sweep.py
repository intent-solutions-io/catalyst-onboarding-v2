"""Queue the recurring `verification_expiry_sweep` action if none is queued (9kg.66). Idempotent; run at every
deployment, after migrate, beside `schedule_session_cleanup`. Each pass queues its successor, and catalyst_health
reports when none is scheduled outside the local environments."""

from django.core.management.base import BaseCommand

from correspondence.verification import schedule_expiry_sweep


class Command(BaseCommand):
    help = "Queue the recurring sweep that opens a staff item when an unverified application's only link expired."

    def handle(self, *args, **options):
        self.stdout.write("queued" if schedule_expiry_sweep() else "already scheduled")

"""Queue the daily `twenty_details_fill` action if none is queued (bgl.14). Idempotent; run at every deployment, after
migrate, once the Twenty projection is switched on. Each run of the action queues its successor. While
CATALYST_TWENTY_PROJECTION is off it queues nothing."""

from django.core.management.base import BaseCommand

from crm.projection import enabled, schedule_details_fill


class Command(BaseCommand):
    help = "Queue the daily fill of blank Twenty fields from confirmed User Agreement details."

    def handle(self, *args, **options):
        if not enabled():
            self.stdout.write("projection off: nothing queued")
            return
        self.stdout.write("queued" if schedule_details_fill() else "already scheduled")

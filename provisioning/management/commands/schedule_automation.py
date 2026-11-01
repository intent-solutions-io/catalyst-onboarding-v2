"""bgl.9: start the automated countersignature and release where their modes are on (034 rows 30 and 36).

Run at deployment after migrate, beside `schedule_session_cleanup`. Under CATALYST_AGREEMENT_COUNTERSIGN "automatic" it
queues the first countersign sweep (each sweep queues its successor). Under CATALYST_RELEASE_MODE "automatic" it queues
an automatic release for every held P4 hand-off that has none yet (hand-offs held before the switch); a hand-off returned
after a superseded request (023 11.11) stays with the owner's `activate_provisioning`. With both modes off it changes
nothing. Idempotent. Prints counts and codes only.
"""

import json

from django.core.management.base import BaseCommand
from django.db import transaction

from agreements import countersign
from applications.models import Application
from provisioning import auto_release, core
from workflow.models import PendingAction


class Command(BaseCommand):
    help = "Queue the countersign sweep and automatic releases where their modes are 'automatic' (bgl.9)."

    def handle(self, *args, **options):
        report = {"countersign_sweep": "off", "auto_release_queued": 0, "release_mode": "owner"}
        if countersign.automatic():
            report["countersign_sweep"] = "queued" if countersign.schedule_sweep() else "already_scheduled"
        if auto_release.automatic():
            report["release_mode"] = "automatic"
            held = PendingAction.objects.filter(kind=core.HANDOFF, status=PendingAction.Status.HELD).exclude(
                input_ref__startswith="returned:").order_by("id")
            for handoff in held:
                with transaction.atomic():
                    application = Application.objects.select_for_update(of=("self",)).filter(
                        public_ref=handoff.subject_id).first()
                    fresh = not PendingAction.objects.filter(idempotency_key=f"{auto_release.AUTO_RELEASE}:{handoff.pk}").exists()
                    if application is not None and auto_release.enqueue(application, handoff) is not None and fresh:
                        report["auto_release_queued"] += 1
        self.stdout.write(json.dumps(report, sort_keys=True))

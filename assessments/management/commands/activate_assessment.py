"""Queue assessments for applications that completed evidence collection before 3B.2 existed (018 13, the 3B.2
backfill). Owner-run, versioned and tied to an approval reference, like `activate_evidence_collection`: an
application is queued only when it is in `assessing` with no run in flight and its snapshot never succeeded.
Prints counts only."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from applications.models import Application, ApplicationEvent, Stage
from assessments.models import AssessmentRun
from assessments.runs import enqueue_assessment

ACTIVATION_VERSIONS = (1,)


class Command(BaseCommand):
    help = "Queue assessments for applications waiting in `assessing` (018 13); --approval-ref is required."

    def add_arguments(self, parser):
        parser.add_argument("--activation-version", type=int, required=True)
        parser.add_argument("--approval-ref", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, activation_version, approval_ref, dry_run, **options):
        if activation_version not in ACTIVATION_VERSIONS:
            raise CommandError("unknown activation version")
        if not approval_ref.strip():
            raise CommandError("an approval reference is required")
        report = {"queued": 0, "skipped": 0}
        for pk in Application.objects.filter(stage=Stage.ASSESSING).values_list("pk", flat=True).order_by("pk"):
            with transaction.atomic():
                application = Application.objects.select_for_update(of=("self",)).get(pk=pk)
                if application.stage != Stage.ASSESSING or AssessmentRun.objects.filter(
                        application=application, status__in=("queued", "reserved")).exists():
                    report["skipped"] += 1
                    continue
                if dry_run:
                    report["queued"] += 1
                    continue
                run = enqueue_assessment(application, "activation")
                if run is None:
                    report["skipped"] += 1
                    continue
                report["queued"] += 1
                ApplicationEvent.objects.create(application=application, kind="assessment_activated",
                                                actor_type=ApplicationEvent.ActorType.SYSTEM, actor_ref="owner_command",
                                                data={"activation_version": activation_version, "approval_ref": approval_ref,
                                                      "run": str(run.public_id)})
        self.stdout.write(json.dumps({"dry_run": dry_run, **report}, sort_keys=True))

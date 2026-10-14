"""Release held evidence-collection work under a named activation version and approval (018 section 4.1).

Held rows are never claimed by the ledger, so registering a handler runs nothing; this owner-run command is the
release gate. It releases (to `queued`) only rows whose application is still `contact_verified`, not terminal,
not paused, with an adoption matching the action's input and claims recorded. A row whose adopted version
predates the claim fields gets one `claims_missing` staff item instead, so an empty snapshot never proceeds.
Prints counts and reason codes only.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent, Stage
from correspondence.staff_items import open_item
from workflow.models import AutomationPause, PendingAction

ACTIVATION_VERSIONS = (1,)


class Command(BaseCommand):
    help = "Release held start_evidence_collection actions (018 4.1); --approval-ref is required."

    def add_arguments(self, parser):
        parser.add_argument("--activation-version", type=int, required=True)
        parser.add_argument("--approval-ref", required=True, help="the 011 decision that authorizes the release")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, activation_version, approval_ref, dry_run, **options):
        if activation_version not in ACTIVATION_VERSIONS:
            raise CommandError("unknown activation version")
        if not approval_ref.strip():
            raise CommandError("an approval reference is required")
        report = {"released": 0, "claims_missing": 0}
        for action in PendingAction.objects.filter(kind="start_evidence_collection", status=PendingAction.Status.HELD).order_by("id"):
            with transaction.atomic():
                application = Application.objects.select_for_update(of=("self",)).filter(public_ref=action.subject_id).first()
                action = PendingAction.objects.select_for_update(of=("self",)).get(pk=action.pk)
                reason = self._ineligible(application, action)
                if reason:
                    report[reason] = report.get(reason, 0) + 1
                    if reason == "claims_missing" and not dry_run:
                        open_item("claims_missing", f"evidence:{application.public_ref}", application=application)
                    continue
                report["released"] += 1
                if dry_run:
                    continue
                PendingAction.objects.filter(pk=action.pk, status=PendingAction.Status.HELD).update(
                    status=PendingAction.Status.QUEUED, due_at=Now(), updated_at=Now())
                ApplicationEvent.objects.create(application=application, kind="evidence_collection_activated",
                                                actor_type=ApplicationEvent.ActorType.SYSTEM, actor_ref="owner_command",
                                                data={"activation_version": activation_version, "approval_ref": approval_ref})
        self.stdout.write(json.dumps({"dry_run": dry_run, **report}, sort_keys=True))

    def _ineligible(self, application, action) -> str:
        if application is None:
            return "application_not_found"
        if application.stage != Stage.CONTACT_VERIFIED:
            return "stage_not_contact_verified"
        if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
            return "paused"
        adoption = application.adoptions.select_related("submission_version").first()
        if adoption is None or str(adoption.submission_version.public_id) != action.input_ref:
            return "adoption_mismatch"
        if (adoption.submission_version.submitted_fields or {}).get("claims") is None:
            return "claims_missing"
        return ""

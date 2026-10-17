"""Release held `issue_nda` actions under a named activation version and approval (021 section 2; P4-D-13).

Held rows are never claimed by the ledger, so registering the handler runs nothing; this owner-run command is the
release gate (the 3B.1 pattern). It releases (to `queued`) only rows whose application is still `admitted`, not
paused, whose admit decision is the one the action names, and only while an approved NDA template version exists.
Prints counts and reason codes only.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.functions import Now

from agreements.handlers import ISSUE_NDA, approved_version
from applications.models import Application, ApplicationEvent, Stage
from assessments.models import QualificationDecision
from workflow.models import AutomationPause, PendingAction

ACTIVATION_VERSIONS = (1,)


class Command(BaseCommand):
    help = "Release held issue_nda actions (021 section 2); --approval-ref is required."

    def add_arguments(self, parser):
        parser.add_argument("--activation-version", type=int, required=True)
        parser.add_argument("--approval-ref", required=True, help="the 011 decision that authorizes the release")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, activation_version, approval_ref, dry_run, **options):
        if activation_version not in ACTIVATION_VERSIONS:
            raise CommandError("unknown activation version")
        if not approval_ref.strip():
            raise CommandError("an approval reference is required")
        report = {"released": 0}
        if approved_version("nda") is None:
            report["no_approved_template"] = PendingAction.objects.filter(kind=ISSUE_NDA, status=PendingAction.Status.HELD).count()
            self.stdout.write(json.dumps({"dry_run": dry_run, **report}, sort_keys=True))
            return
        for action in PendingAction.objects.filter(kind=ISSUE_NDA, status=PendingAction.Status.HELD).order_by("id"):
            with transaction.atomic():
                application = Application.objects.select_for_update(of=("self",)).filter(public_ref=action.subject_id).first()
                action = PendingAction.objects.select_for_update(of=("self",)).get(pk=action.pk)
                reason = self._ineligible(application, action)
                if reason:
                    report[reason] = report.get(reason, 0) + 1
                    continue
                report["released"] += 1
                if dry_run:
                    continue
                PendingAction.objects.filter(pk=action.pk, status=PendingAction.Status.HELD).update(
                    status=PendingAction.Status.QUEUED, due_at=Now(), updated_at=Now())
                ApplicationEvent.objects.create(application=application, kind="agreements_activated",
                                                actor_type=ApplicationEvent.ActorType.SYSTEM, actor_ref="owner_command",
                                                data={"activation_version": activation_version, "approval_ref": approval_ref})
        self.stdout.write(json.dumps({"dry_run": dry_run, **report}, sort_keys=True))

    def _ineligible(self, application, action) -> str:
        if application is None:
            return "application_not_found"
        if action.status != PendingAction.Status.HELD:
            return "not_held"
        if application.stage != Stage.ADMITTED:
            return "stage_not_admitted"
        if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
            return "paused"
        decision = QualificationDecision.objects.filter(application=application, outcome="admit").order_by("-id").first()
        if decision is None or str(decision.public_id) != action.input_ref:
            return "decision_changed"
        return ""

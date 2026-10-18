"""Release held provisioning hand-offs under a named activation version and approval (023 section 5 step 1; D-47).

Held rows are never claimed by the ledger, so this owner-run command is the release gate (the P4 pattern). Each
release first reads every required agreement afresh at the provider, outside any transaction, then re-checks the
prerequisites under the application lock, reserves the address and creates one request awaiting the approver.
Prints counts and reason codes only.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from provisioning import core, services
from workflow.models import PendingAction

ACTIVATION_VERSIONS = (1,)


class Command(BaseCommand):
    help = "Release held provisioning hand-offs (023 section 5); --approval-ref is required."

    def add_arguments(self, parser):
        parser.add_argument("--activation-version", type=int, required=True)
        parser.add_argument("--approval-ref", required=True, help="the 011 decision that authorizes the release")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, activation_version, approval_ref, dry_run, **options):
        if activation_version not in ACTIVATION_VERSIONS:
            raise CommandError("unknown activation version")
        if not approval_ref.strip():
            raise CommandError("an approval reference is required")
        report = {}
        for action_id in PendingAction.objects.filter(kind=core.HANDOFF, status=PendingAction.Status.HELD).order_by(
                "id").values_list("id", flat=True):
            reason = services.release(action_id, activation_version, approval_ref, dry_run=dry_run)
            report[reason] = report.get(reason, 0) + 1
        self.stdout.write(json.dumps({"dry_run": dry_run, "released": report.pop("released", 0), **report},
                                     sort_keys=True))

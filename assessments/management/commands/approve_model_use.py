"""Record, revoke or show the owner's approval of live model use for one purpose (oc4.9; 018 section 21).

Owner only: run connected as the migration owner role, like `grant_staff_role`. The application role may only read
the record, so the running application can never approve its own model use, and no web path writes it.

The command computes the terms from the code and settings in force (`assessments.approval.terms`): the provider and
model id given here, the exact field list, the current prompt pack, its digest, the rubric and schema versions, every
budget, the request timeout and the repair limit. It prints them and their digest before writing, and writes one
append-only `ModelUseApproval` row naming the approval the owner cites and who ran the command. The approval is
standing and terms-bound: it covers every request whose terms match, for every applicant, until revoked, and has no
expiry. Any later change to those terms makes the approval stale, so every live call refuses until the owner approves
the new terms. An assessment approval is refused while the current pack's rubric is marked synthetic: a synthetic
rubric may not be approved for live use (there is no override; allowing it is an owner decision).

- `--show` prints the terms and digest and writes nothing.
- `--revoke` records a revocation: every live call for the purpose refuses from then on.

An approval is necessary, never sufficient: no live model branch exists in this code (`agent.build_model`), and the
start-up guard refuses any live value of `CATALYST_ASSESSMENT_MODEL`. Exit 0 done, 1 refused.
"""

import json
import re

from django.core.management.base import BaseCommand, CommandError

from accounts import grants
from assessments import approval
from assessments import pack as packs
from assessments.models import APPROVAL_REF_PATTERN, ModelUseApproval


def approval_code(value) -> str:
    ref = grants.require_approval(value)
    if not re.fullmatch(APPROVAL_REF_PATTERN, ref):
        raise CommandError("--approval-ref must be a decision code: 3 to 64 of a-z, 0-9, _ . : -")
    return ref


class Command(BaseCommand):
    help = "Record, revoke or show the owner's approval of live model use (owner only; append-only)."

    def add_arguments(self, parser):
        parser.add_argument("--purpose", choices=approval.PURPOSES, required=True)
        parser.add_argument("--provider", help="the provider's lowercase name")
        parser.add_argument("--model-id", help="the exact model identifier the approval names")
        parser.add_argument("--approval-ref", help="the decision that authorizes this approval or revocation")
        parser.add_argument("--revoke", action="store_true", help="record a revocation for the purpose")
        parser.add_argument("--show", action="store_true", help="print the terms and their digest; write nothing")

    def handle(self, purpose, provider=None, model_id=None, approval_ref=None, revoke=False, show=False, **options):
        if revoke and show:
            raise CommandError("--revoke and --show cannot be combined")
        if revoke:
            ref = approval_code(approval_ref)
            record = ModelUseApproval.objects.create(
                purpose=purpose, action=ModelUseApproval.Action.REVOKE, provider="", model_id="", terms={},
                terms_sha256="", approval_ref=ref, actor_ref=grants.actor())
            self.stdout.write(f"revoked live model use for {purpose!r} (record {record.pk})")
            return
        named = approval.parse_model(f"{provider or ''}:{model_id or ''}")
        if named is None:
            raise CommandError("--provider (lowercase letters, digits, hyphens) and --model-id are required")
        try:
            use = approval.Use.current(purpose)
        except packs.PackRefused as exc:
            raise CommandError(f"the current prompt pack is refused ({exc}); nothing to approve") from None
        if purpose == "assessment" and packs.load(packs.CURRENT).rubric.get("synthetic", True):
            raise CommandError("the current assessment rubric is synthetic (POL-04 wording not approved); a synthetic "
                               "rubric may not be approved for live use")
        terms = approval.terms(use, *named)
        digest = approval.digest(terms)
        self.stdout.write(json.dumps(terms, indent=2, sort_keys=True))
        self.stdout.write(f"terms digest {digest}")
        if show:
            return
        ref = approval_code(approval_ref)
        record = ModelUseApproval.objects.create(
            purpose=purpose, action=ModelUseApproval.Action.APPROVE, provider=named[0], model_id=named[1], terms=terms,
            terms_sha256=digest, approval_ref=ref, actor_ref=grants.actor())
        self.stdout.write(f"approved live model use for {purpose!r} on these terms (record {record.pk}); no live model "
                          "branch exists in this code, so no request is made until one is built and authorized")

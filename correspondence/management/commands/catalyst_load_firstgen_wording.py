"""Load the first generation's live email wording as new v2 template versions (bead bgl.11; parity inventory 034).

    manage.py catalyst_load_firstgen_wording --source <private first-generation checkout> --dry-run
    manage.py catalyst_load_firstgen_wording --source <dir> --constant service_address=<address> \\
        --approve-as <staff username> --approval-ref <decision code>

The wording is read at run time from `--source` (a private checkout of the first generation at its live commit; a
directory inside this repository is refused) and converted by `correspondence.firstgen_wording`, whose table maps each
first-generation template to the v2 key that sends at the same moment. For each mapped key:

- a key whose template row does not exist yet (its migration has not run) is skipped with a report line;
- the conversion is refused when it uses a variable outside the key's allow-list (what the v2 sender supplies), lacks
  a required one (a link mail without its link), or when the key's current version declares a different allow-list;
- content identical to an existing version is skipped (or, with `--approve-as`, an identical draft is approved);
- otherwise a NEW version is added (never an edit): text, HTML part, the template's secret-bearing flag, not
  synthetic, as a draft. With `--approve-as <username> --approval-ref <code>` it is then approved through
  `correspondence.outbound.approve_template_version`, the service the staff template screen calls, as that staff
  account: the same permission check (approve_template_version), the same approved_by (`user:<pk>`) and approved_at,
  and the digest pin the screen uses. Like the screen, approving does not retire the previous version: the newest
  approved version is the one every sender uses, and the older one stays as history.

Nothing is written when any key is refused, and nothing at all with `--dry-run`. Each key prints one JSON line: the
key, its source files, subject, text and HTML lengths, the v2 variables used, the unmapped first-generation variables,
the lines dropped, subject differences, known differences, the action and its reason. A last line carries the totals,
the approval reference and the approver. The wording itself is printed only with `--show` (operator use). Exit 0;
1 when refused.

The approval reference is printed in the summary line for the operator's record; the template version has no column
for it (adding one is a correspondence migration, recorded as a follow-up in the bead).
"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from accounts import grants
from correspondence import firstgen_wording as fg
from correspondence.common import Refused as ServiceRefused
from correspondence.common import can
from correspondence.models import MessageTemplate, MessageTemplateVersion
from correspondence.outbound import approve_template_version
from correspondence.rendering import GREETING, TemplateRefused, check_version, version_digest

REPOSITORY = Path(__file__).resolve().parents[3]
APPROVAL_CODE = re.compile(r"[a-z0-9_.:-]{3,64}")
CONSTANT = re.compile(r"([a-z_][a-z0-9_]*)=(.*)", re.DOTALL)


def _constants(values) -> dict:
    allowed = {name for m in fg.MAPPINGS for name in (*m.constants, *m.subject_exprs.values())}
    out = {}
    for raw in values or []:
        match = CONSTANT.fullmatch(raw)
        if not match or match.group(1) not in allowed:
            raise CommandError(f"--constant must be name=value with a name in {sorted(allowed)}")
        value = match.group(2).strip()
        if not value or len(value) > 200 or any(ch in value for ch in "\r\n\x00"):
            raise CommandError(f"--constant {match.group(1)}: one line of 1 to 200 characters")
        out[match.group(1)] = value
    return out


class Command(BaseCommand):
    help = "Load the first generation's email wording as new v2 template versions (drafts unless --approve-as)."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="a private checkout of the first generation (never this repo)")
        parser.add_argument("--dry-run", action="store_true", help="report only; write nothing")
        parser.add_argument("--show", action="store_true", help="also print the converted wording (operator use)")
        parser.add_argument("--approve-as", help="the staff username that approves (needs approve_template_version)")
        parser.add_argument("--approval-ref", help="the decision code that authorizes the approval")
        parser.add_argument("--constant", action="append", help="a deployment value: name=value (repeatable)")
        parser.add_argument("--only", action="append", help="load only this v2 key (repeatable)")

    def handle(self, *args, source, dry_run=False, show=False, approve_as=None, approval_ref=None, constant=None,
               only=None, **options):
        root = Path(source).expanduser().resolve()
        if not root.is_dir():
            raise CommandError("--source must be a directory")
        if root == REPOSITORY or REPOSITORY in root.parents:
            raise CommandError("--source may not be inside this repository: point it at the private first-generation checkout")
        constants = _constants(constant)
        user, ref = None, ""
        if approve_as or approval_ref:
            if not approve_as:
                raise CommandError("--approval-ref needs --approve-as")
            ref = grants.require_approval(approval_ref)
            if not APPROVAL_CODE.fullmatch(ref):
                raise CommandError("--approval-ref must be a decision code: 3 to 64 of a-z, 0-9, _ . : -")
            user = get_user_model().objects.filter(username=approve_as).first()
            if user is None or not can(user, "approve_template_version"):
                raise CommandError("--approve-as must name an active staff account holding approve_template_version")
        keys = [m.key for m in fg.MAPPINGS]
        unknown = sorted(set(only or []) - set(keys))
        if unknown:
            raise CommandError(f"--only names no mapped key: {unknown}")
        mappings = [m for m in fg.MAPPINGS if not only or m.key in only]

        plans = [self._plan(root, mapping, constants, approving=user is not None) for mapping in mappings]
        refused = [p["report"]["key"] for p in plans if p["report"]["action"] == "refuse"]
        if not refused and not dry_run:
            with transaction.atomic():
                for plan in plans:
                    self._apply(plan, user)
        totals = {"create": 0, "approve": 0, "skip": 0, "refuse": 0}
        for plan in plans:
            report = plan["report"]
            totals[report["action"]] += 1
            if report["action"] == "create" and user is not None:
                totals["approve"] += 1
            self.stdout.write(json.dumps(report, sort_keys=True))
            if show and plan.get("version") is not None:
                version = plan["version"]
                self.stdout.write(f"--- {report['key']} subject\n{version.subject}\n--- {report['key']} text\n"
                                  f"{version.body_text}--- {report['key']} html\n{version.body_html}--- end")
        summary = {"summary": True, "dry_run": dry_run, "approval_ref": ref,
                   "approved_by": f"user:{user.pk}" if user is not None else "", **totals,
                   "v2_keys_without_first_generation_mail": sorted(fg.V2_ONLY),
                   "first_generation_mail_without_v2_moment": sorted(fg.NO_V2_MOMENT)}
        self.stdout.write(json.dumps(summary, sort_keys=True))
        if refused:
            raise CommandError(f"refused, nothing written: {', '.join(refused)}")

    def _plan(self, root, mapping, constants, *, approving) -> dict:
        report = {"key": mapping.key, "moment": mapping.moment, "source": mapping.text.path,
                  "html_source": mapping.html.path if mapping.html else "", "notes": list(mapping.notes)}
        template = MessageTemplate.objects.filter(key=mapping.key).first()
        if template is None:
            return {"report": {**report, "action": "skip", "reason": "template_missing"}}
        try:
            converted = fg.convert(root, mapping, constants, settings)
        except fg.Refused as exc:
            return {"report": {**report, "action": "refuse", "reason": str(exc)}}
        report.update({
            "subject_length": len(converted.subject), "body_length": len(converted.body_text),
            "html_length": len(converted.body_html), "variables_used": sorted(converted.used),
            "unmapped": sorted(converted.unmapped), "dropped_text_lines": converted.dropped_text_lines,
            "dropped_html_lines": converted.dropped_html_lines, "subject_differences": converted.subject_differences})
        outside = sorted(converted.used - set(mapping.variables))
        missing = sorted(set(mapping.required) - converted.used)
        latest = MessageTemplateVersion.objects.filter(template=template).order_by("-version").first()
        if outside:
            return {"report": {**report, "action": "refuse", "reason": "variable_outside_allow_list",
                               "outside": outside}}
        if missing:
            return {"report": {**report, "action": "refuse", "reason": "required_variable_missing", "missing": missing}}
        # The greeting pair may differ (a first-generation greeting uses `first_name` where v2's seed used the display
        # name): every sender offers both and fits them to the version (correspondence.rendering.fit_greeting).
        if latest is not None and set(latest.variables) - set(GREETING) != set(mapping.variables) - set(GREETING):
            return {"report": {**report, "action": "refuse", "reason": "allow_list_differs_from_the_current_version"}}
        digest = version_digest(converted.subject, converted.body_text, converted.body_html)
        version = MessageTemplateVersion(
            template=template, subject=converted.subject, body_text=converted.body_text, body_html=converted.body_html,
            variables=list(mapping.variables), secret_bearing=template.secret_bearing, content_sha256=digest,
            synthetic=False)
        try:
            check_version(version)
        except TemplateRefused as exc:
            return {"report": {**report, "action": "refuse", "reason": str(exc)}}
        report["sha256"] = digest
        existing = MessageTemplateVersion.objects.filter(template=template, content_sha256=digest).first()
        if existing is not None:
            report.update(version=existing.version, status=str(existing.status))
            if existing.status == MessageTemplateVersion.Status.DRAFT and approving:
                return {"report": {**report, "action": "approve", "reason": "identical_draft"}, "existing": existing,
                        "version": version}
            return {"report": {**report, "action": "skip", "reason": f"identical_{existing.status}"}, "version": version}
        return {"report": {**report, "action": "create", "reason": "new_content"}, "version": version, "new": True}

    def _apply(self, plan, user) -> None:
        report = plan["report"]
        target = plan.get("existing")
        if plan.get("new"):
            target = plan["version"]
            target.version = (MessageTemplateVersion.objects.filter(template=target.template)
                              .aggregate(n=Max("version"))["n"] or 0) + 1
            target.status = MessageTemplateVersion.Status.DRAFT
            target.save()
            report.update(version=target.version, status="draft")
        if user is not None and target is not None:
            try:
                approved = approve_template_version(target.pk, user, expected_digest=target.content_sha256)
            except (ServiceRefused, PermissionDenied, TemplateRefused) as exc:
                raise CommandError(f"{report['key']}: approval refused ({exc})") from None
            report.update(status=str(approved.status), approved_by=approved.approved_by)

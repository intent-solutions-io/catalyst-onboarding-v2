"""Protected legacy history and explicit pre-signing handover review (bgl.23).

Only named fields are displayed, never arbitrary imported JSON or provider payloads. Capability
links are redacted and unreviewed outgoing message bodies are withheld. History is evidence of what v1 recorded, not proof that a pending provider operation completed.
"""

import re

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from applications.models import TERMINAL_STAGES
from correspondence.mime import redact
from workflow.models import AutomationPause

from .models import ImportedCase, ImportedRecord
from . import review

PAGE_SIZE = 50
SIGNING_LINK = re.compile(
    r"(?i)/sign/(?:[^\s\"'<>)\]]|\r?\n[> \t]*(?=[A-Za-z0-9_\-:.=%/]+[ \t]*(?:\r?\n|$)))+"
)
# An unknown/new source column remains preserved in the database but is not implicitly published on
# a screen. In particular, raw review-run output and agreement payloads never become HTML or links.
FIELDS = {
    "case_event": ("event", "subject", "from_state", "to_state", "actor", "reason"),
    "review_draft": ("status", "body_text"),
    "review_question": ("criterion_id", "status", "round", "sent_at", "answered_at"),
    "applicant_message": ("direction", "subject", "body_text", "sent_at"),
    "agreement": (
        "document_type",
        "document_version",
        "status",
        "provider_ref",
        "provenance",
    ),
    "mailbox_account": (
        "username",
        "domain",
        "status",
        "created_at_provider",
        "welcome_sent_at",
    ),
    "case_release": ("status", "released_at", "released_by"),
}
GUIDANCE = {
    "requested": "Contact verification and review must be continued in v2; the old confirmation link is not accepted.",
    "reviewing": "Review the preserved assessment history before recording the next decision in v2.",
    "needs_information": "Read the legacy question drafts and applicant replies before continuing the review.",
    "held": "Review the reason for the hold before making a new decision.",
    "lapsed": "Review the previous stage and any open question or signing envelope before reopening the case.",
    "nda_pending": "Reconcile the existing NDA envelope before creating or sending another agreement.",
    "setup_pending": "Reconcile the existing User Agreement envelope and captured details before proceeding.",
    "release_pending": "Verify the completed agreements and any release already performed before provisioning.",
    "provisioning": "Reconcile the existing mailbox and any welcome delivery before creating an account or sending again.",
    "active": "Confirm mailbox ownership and existing access before transferring ongoing account operations.",
    "suspended": "Preserve the suspension and review account access before resuming any automation.",
    "offboarding": "Verify that the outstanding access revocation has completed; a closed v2 stage is not proof of revocation.",
    "offboarded": "Preserve the completed offboarding record; do not recreate access.",
    "withdrawn": "Preserve the withdrawal; do not restart onboarding.",
    "declined": "Preserve the decision; do not restart onboarding without a new authorized decision.",
}


def displayed_fields(record):
    data = record.data if isinstance(record.data, dict) else {}
    shown = []
    for key in FIELDS.get(record.v1_table, ()):
        value = data.get(key)
        if not isinstance(value, (str, int, float, bool)):
            continue
        if record.v1_table == "applicant_message" and key == "body_text":
            # The recorded clarification is ordinary correspondence. Other outbound templates may
            # carry credentials and are not implicitly exposed just because their body was imported.
            if (
                data.get("direction") != "in"
                and data.get("template") != "review_clarification"
            ):
                continue
        if isinstance(value, str):
            value = SIGNING_LINK.sub("[signing link removed]", redact(value)[0])
        shown.append((key.replace("_", " "), value))
    return shown


@admin.site.admin_view
@require_GET
def application_history(request, public_ref):
    return history_response(request, public_ref)


def history_response(request, public_ref, *, error="", note="", status=200):
    if not request.user.has_perm("applications.view_application"):
        raise PermissionDenied
    case = get_object_or_404(
        ImportedCase.objects.select_related("application"),
        application__public_ref=public_ref,
    )
    records = ImportedRecord.objects.filter(application=case.application).order_by(
        "-occurred_at", "-id"
    )
    counts = list(
        records.order_by()
        .values("v1_table")
        .annotate(total=Count("id"))
        .order_by("v1_table")
    )
    table = request.GET.get("table", "")
    # A filter can select only a table actually present on this application. It cannot query arbitrary
    # JSON fields or reveal other cases; unknown filters fail rather than silently broadening the view.
    if table:
        if table not in {row["v1_table"] for row in counts}:
            from django.http import Http404

            raise Http404
        records = records.filter(v1_table=table)
    page = Paginator(records, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "firstgen/history.html",
        {
            "case": case,
            "application": case.application,
            "page": page,
            "table": table,
            "counts": counts,
            "rows": [(record, displayed_fields(record)) for record in page],
            "guidance": GUIDANCE.get(
                case.v1_state, "This legacy state needs an explicit handover decision."
            ),
            "paused": AutomationPause.objects.filter(
                subject_type="application", subject_id=public_ref
            ).exists(),
            "open_case": case.application.stage not in TERMINAL_STAGES,
            "can_prepare_review": (
                review.can_review(request.user)
                and case.application.stage in review.STAGES
                and case.v1_state in review.SOURCE_STATES
            ),
            "review_digest": review.review_state(case.application)["digest"],
            "review_error": error,
            "review_note": note,
            "prepared_review": review.assessment_context(case.application),
        },
        status=status,
    )


@admin.site.admin_view
@require_POST
def prepare_review(request, public_ref):
    from correspondence.common import Refused

    if not review.can_review(request.user):
        raise PermissionDenied
    case = get_object_or_404(ImportedCase, application__public_ref=public_ref)
    note = request.POST.get("note", "")
    try:
        review.prepare(
            case.application_id,
            request.user,
            expected_digest=request.POST.get("digest", ""),
            source_stopped=request.POST.get("source_stopped") == "yes",
            history_reviewed=request.POST.get("history_reviewed") == "yes",
            note=note,
        )
    except Refused as exc:
        return history_response(
            request, public_ref, error=str(exc), note=note, status=409
        )
    return redirect("firstgen_staff:history", public_ref=public_ref)

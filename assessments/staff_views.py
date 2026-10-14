"""Staff screens for evidence (018 sections 3 and 7; P3-D-14; task 3B.1). The P2 screen rules apply: each page
names the permissions whose holders need it (a template owner or pause-only role never reads evidence), every
action is a one-object POST calling one service, a superuser is refused, refusals show a code, untrusted text
(claims, page text, URLs) is autoescaped through the `visible` filter, URLs are shown as text and never fetched or
linked, and pages are never cached.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from applications.models import Application
from correspondence.models import StaffItem

from . import services
from .models import EvidenceItem, EvidenceSource

REVIEW = ("review_evidence", "operate_evidence")
SOURCES = ("approve_evidence_source", "review_evidence")


def staff_page(*permissions):
    def decorate(view):
        @never_cache
        @login_required(login_url="admin:login")
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_staff or not any(services.can(request.user, p) for p in permissions):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorate


def act(request, target, service, success):
    try:
        service()
    except services.Refused as exc:
        messages.error(request, f"Refused: {exc}")
        return redirect(target)
    messages.success(request, success)
    return redirect(target)


@require_GET
@staff_page(*SOURCES)
def source_list(request):
    return render(request, "assessments/staff/sources.html",
                  {"sources": EvidenceSource.objects.order_by("key", "-version")})


@require_GET
@staff_page(*SOURCES)
def source_detail(request, pk):
    source = get_object_or_404(EvidenceSource, pk=pk)
    return render(request, "assessments/staff/source.html", {
        "source": source, "can_approve": source.status == "draft" and services.can(request.user, "approve_evidence_source")})


@require_POST
@staff_page("approve_evidence_source")
def approve_source(request, pk):
    source = get_object_or_404(EvidenceSource, pk=pk)
    return act(request, reverse("assessments_staff:source", args=[pk]),
               lambda: services.approve_evidence_source(source.pk, request.user, request.POST.get("digest", "")),
               "Source version approved.")


def _rows(application):
    """Each claim beside its latest observation (018 section 7): claims with no observation are listed as
    unsupported assertions, never as negative findings."""
    adoption = application.adoptions.select_related("submission_version").first()
    if adoption is None:
        return None, [], []
    version = adoption.submission_version
    claims = (version.submitted_fields or {}).get("claims")
    items = {}
    for item in (EvidenceItem.objects.filter(application=application, adopted_version=version)
                 .select_related("source").prefetch_related("captures").order_by("claim_ref", "round")):
        items[item.claim_ref] = item
    rows = []
    for i, work in enumerate((claims or {}).get("work") or [], start=1):
        rows.append({"label": f"Work sample {i}", "claim": work, "item": items.get(f"work:{i}")})
    for i, credential in enumerate((claims or {}).get("credentials") or [], start=1):
        rows.append({"label": f"Credential {i}", "claim": credential, "item": items.get(f"credential:{i}")})
    for row in rows:
        item = row["item"]
        row["capture"] = item.captures.order_by("-attempt_number").first() if item else None
        row["refetchable"] = bool(item) and (item.status in ("unavailable", "refused") or (
            item.status == "fetched" and row["capture"] is not None and row["capture"].outcome == "not_found"))
    return version, claims, rows


@require_GET
@staff_page(*REVIEW)
def evidence(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    version, claims, rows = _rows(application)
    return render(request, "assessments/staff/evidence.html", {
        "application": application, "version": version, "claims": claims, "rows": rows,
        "newer_versions": application.versions.filter(version_number__gt=version.version_number).count() if version else 0,
        "can_operate": services.can(request.user, "operate_evidence"),
        "blocked": StaffItem.objects.filter(application=application, status="open",
                                            reason_code="evidence_required_unavailable").exists(),
    })


@require_POST
@staff_page("operate_evidence")
def refetch(request, public_id):
    item = get_object_or_404(EvidenceItem.objects.select_related("application"), public_id=public_id)
    return act(request, reverse("assessments_staff:evidence", args=[item.application.public_ref]),
               lambda: services.refetch_item(item.pk, request.user, request.POST.get("note", "")), "Re-fetch requested.")


@require_POST
@staff_page("operate_evidence")
def proceed(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return act(request, reverse("assessments_staff:evidence", args=[public_ref]),
               lambda: services.proceed_without(application.pk, request.user, request.POST.get("note", "")),
               "Proceeding to assessment without the unavailable item.")

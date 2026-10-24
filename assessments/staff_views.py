"""Staff screens for evidence (018 sections 3 and 7; P3-D-14; task 3B.1). The P2 screen rules apply: each page
names the permissions whose holders need it (a template owner or pause-only role never reads evidence), every
action is a one-object POST calling one service, a superuser is refused, refusals show a code, untrusted text
(claims, page text, URLs) is autoescaped through the `visible` filter, URLs are shown as text and never fetched or
linked, and pages are never cached.
"""

from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from applications.models import Application
from correspondence import common as correspondence_rules
from correspondence.models import Question, StaffItem
from workflow.models import AutomationPause

from . import services
from .models import AssessmentRun, EvidenceItem, EvidenceSource

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


def refused_page(request, template, context, exc):
    """9kg.41: a refused form comes back with what the person typed (the P4 and P5 screens' rule), the
    refusal code on the page and status 409, instead of a redirect that drops the typed text."""
    messages.error(request, f"Refused: {exc}")
    return render(request, template, context, status=409)


@require_GET
@staff_page(*REVIEW)
def evidence(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return render(request, "assessments/staff/evidence.html", _evidence_context(request, application))


def _evidence_context(request, application, form=None):
    version, claims, rows = _rows(application)
    return {
        "form": form or {},
        "application": application, "version": version, "claims": claims, "rows": rows,
        "newer_versions": application.versions.filter(version_number__gt=version.version_number).count() if version else 0,
        "can_operate": services.can(request.user, "operate_evidence"),
        "blocked": StaffItem.objects.filter(application=application, status="open",
                                            reason_code="evidence_required_unavailable").exists(),
        "run": AssessmentRun.objects.filter(application=application).order_by("-id").first(),
        "can_rerun": services.can(request.user, "rerun_assessment") and application.stage == "assessing",
        "questions": Question.objects.filter(application=application).exclude(round=0).order_by("round", "id"),
        "can_approve": correspondence_rules.can(request.user, "approve_question"),
        "can_author": correspondence_rules.can(request.user, "author_question") and application.stage in services.CLARIFY_STAGES,
        "criteria": _criteria(),
    }


def _criteria():
    from . import pack as packs

    try:
        return packs.load().criteria
    except packs.PackRefused:
        return []


DECIDE = ("review_evidence", "operate_evidence", "record_qualification_decision")


@require_GET
@staff_page(*DECIDE)
def decision(request, public_ref):
    """018 section 7 (3B.4): everything the decision relies on, and only the outcomes the viewer may record."""
    application = get_object_or_404(Application, public_ref=public_ref)
    return render(request, "assessments/staff/decision.html", _decision_context(request, application))


def _decision_context(request, application, form=None):
    from . import decisions

    form = form or {}
    version, claims, rows = _rows(application)
    state = decisions.decision_state(application)
    may = decisions.can_decide(request.user)
    paused = AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists()
    criteria = state["pack"].criteria if state["pack"] else []
    return {
        "form": form,  # 9kg.41: what was typed before a refusal; the outcome is never carried over (chosen again)
        "application": application, "version": version, "claims": claims, "rows": rows, "state": state,
        "newer_versions": application.versions.filter(version_number__gt=version.version_number).count() if version else 0,
        "run": state["run"] or state["latest_run"], "authority": settings.CATALYST_QUALIFICATION_AUTHORITY is not None,
        "may_decide": may, "outcomes": [o for o in decisions.STAGE_FOR if may and not (o == "admit" and paused)
                                        and not (o == "hold" and application.stage == "on_hold")],
        # 9kg.50: a held case comes back to a decision here (admit or decline), never through a free close action.
        "decidable": application.stage in ("awaiting_decision", "on_hold")
        or (application.stage == "assessing" and state["human_only_allowed"]),
        "capability": decisions.CAPABILITY, "strength": decisions.EVIDENCE_STRENGTH,
        "criteria": [{**c, "posted": {"cap": form.get(f"cap-{c['id']}", ""), "str": form.get(f"str-{c['id']}", ""),
                                      "note": form.get(f"note-{c['id']}", "")}} for c in criteria],
        "policy_ref": decisions.policy_ref(state["pack"]) if state["pack"] else "",
        "questions": Question.objects.filter(application=application).exclude(round=0).order_by("round", "id"),
    }


@require_POST
@staff_page("record_qualification_decision")
def decide(request, public_ref):
    from . import decisions

    application = get_object_or_404(Application, public_ref=public_ref)
    post = request.POST
    pack = decisions.decision_state(application)["pack"]
    criteria = [c["id"] for c in pack.criteria] if pack else []  # no snapshot: the service refuses
    rationale = {c: {"capability": post.get(f"cap-{c}", ""), "evidence_strength": post.get(f"str-{c}", ""),
                     "note": post.get(f"note-{c}", "")} for c in criteria}
    try:
        decisions.record_decision(
            application.pk, request.user, outcome=post.get("outcome", ""), reason_code=post.get("reason_code", ""),
            reason_text=post.get("reason_text", ""), expected_digest=post.get("digest", ""), rationale=rationale,
            human_only_reason=post.get("human_only_reason", ""))
    except services.Refused as exc:  # the page shows the new state with the typed reasoning kept (9kg.41)
        changed = str(exc) == "changed_since_shown"
        # The case changed under the form: judgments made against the old state are never carried onto the new one;
        # only the free-text notes come back (operator review of PR #93).
        kept = {k: v for k, v in post.items() if k.startswith("note-")} if changed else post
        context = _decision_context(request, application, kept)
        context["changed"] = changed
        return refused_page(request, "assessments/staff/decision.html", context, exc)
    messages.success(request, "Decision recorded.")
    return redirect(reverse("assessments_staff:decision", args=[public_ref]))


@require_POST
@staff_page(*REVIEW)
def author(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    post = request.POST
    try:
        services.author_clarification(
            application.pk, request.user, text=post.get("text", ""), criterion_id=post.get("criterion", ""),
            evidence_gap=post.get("gap", ""), alternative_route=post.get("route", ""),
            requires_evidence=post.get("requires_evidence") == "on")
    except services.Refused as exc:  # the typed question comes back (9kg.41); a double submit is `duplicate_question`
        return refused_page(request, "assessments/staff/evidence.html", _evidence_context(request, application, post), exc)
    messages.success(request, "Question stored as proposed; approve it to send it.")
    return redirect(reverse("assessments_staff:evidence", args=[public_ref]))


@require_POST
@staff_page("operate_evidence")
def refetch(request, public_id):
    item = get_object_or_404(EvidenceItem.objects.select_related("application"), public_id=public_id)
    return act(request, reverse("assessments_staff:evidence", args=[item.application.public_ref]),
               lambda: services.refetch_item(item.pk, request.user, request.POST.get("note", "")), "Re-fetch requested.")


@require_POST
@staff_page("rerun_assessment")
def rerun(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return act(request, reverse("assessments_staff:evidence", args=[public_ref]),
               lambda: services.rerun_assessment(application.pk, request.user, request.POST.get("note", "")),
               "A new assessment run was queued.")


@require_POST
@staff_page("operate_evidence")
def proceed(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return act(request, reverse("assessments_staff:evidence", args=[public_ref]),
               lambda: services.proceed_without(application.pk, request.user, request.POST.get("note", "")),
               "Proceeding to assessment without the unavailable item.")

"""The staff agreement screen (021 section 9; 4B.3; D-42 to D-44).

One page per application shows each agreement type's instances with their issue, signing and custody statuses
separately, the recipients, the observations behind each status, open staff items, blockers, the next action and
who owns it. Every action is a CSRF-protected POST to one service. The P2 and P3 screen rules apply:
- the page names the permissions whose holders need it, and a superuser is refused like everyone else;
- untrusted text is autoescaped;
- pages are never cached.

Consequential choices are never preselected. A refusal re-renders the page with what the person typed, and with the
refusal code.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from applications.models import Application
from correspondence.models import StaffItem
from workflow.models import AutomationPause, PendingAction

from . import completion, handlers, services
from .models import AgreementDetailsVersion, AgreementInstance, AgreementType, EnvelopeAttempt, ProviderObservation

SCREEN = ("view_agreementinstance", "operate_agreements", "manage_agreements", "decide_uncertain_agreement",
          "resolve_agreement_integrity", "retrieve_agreement_document", "confirm_required_details")
STOP_REASONS = {"on_hold": "Hold (resumable by a decision-maker)", "withdrawn": "Withdrawn (final)",
                "closed": "Closed (final)"}
DISPOSITIONS = {"continue": "Continue: a fresh read matches fully", "replace": "Replace with a new agreement",
                "escalate": "Escalate to the owner or counsel (stays held)"}
LABELS = {
    "held": "not yet released", "create_pending": "being created", "create_uncertain": "creation outcome unknown",
    "distribute_pending": "being sent", "distribute_uncertain": "sending outcome unknown", "issued": "sent to sign",
    "failed_needs_staff": "needs staff", "cancel_pending": "being cancelled", "cancel_uncertain": "cancel outcome unknown",
    "cancelled": "cancelled", "superseded": "superseded", "not_started": "not signed", "partially_signed": "partly signed",
    "signing_complete_observed": "reported complete, not yet verified", "signing_complete_verified": "signed and verified",
    "declined": "declined", "expired": "expired", "not_due": "not due", "pending": "pending",
    "stored_verified": "stored and verified", "failed_retry_pending": "failed, retrying",
}


def screen(view):
    @never_cache
    @login_required(login_url="admin:login")
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff or not any(services.can(request.user, p) for p in SCREEN):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def _next_action(application, instances) -> tuple[str, str]:
    """(what happens next, who owns it), in plain words."""
    if completion.stopped(application):
        return "Agreements are stopped; nothing more is issued", "decision-maker"
    if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
        return "Automation is paused; the sequence waits", "staff"
    if StaffItem.objects.filter(application=application, status="open", reason_code__startswith="agreement_").exists():
        return "Resolve the open agreement items below", "staff"
    if application.stage == "agreements_complete":
        return "All agreements passed; the provisioning hand-off is held for P5", "owner (P5 release)"
    _, next_type, reason = completion.next_step(application)
    if next_type is not None and not completion.details_confirmed(application, next_type):
        return f"Record and confirm the details the {next_type.key} needs", "staff (confirm_required_details)"
    if reason == "waiting_for_gate":
        return "Waiting for the applicant to sign, and for custody", "applicant, then the system"
    return "The system continues the sequence", "system"


def _context(request, application, *, error="", form=None):
    types = list(AgreementType.objects.filter(required=True).order_by("order"))
    rows = []
    for t in types:
        for instance in (AgreementInstance.objects.filter(application=application, agreement_type=t)
                         .prefetch_related("recipients", "documents").order_by("id")):
            hold = completion.integrity_hold_open(instance)
            rows.append({
                "type": t, "instance": instance, "hold": hold,
                "issue": LABELS.get(instance.issue_status, instance.issue_status),
                "signing": LABELS.get(instance.signing_status, instance.signing_status),
                "custody": LABELS.get(instance.custody_status, instance.custody_status),
                "observations": ProviderObservation.objects.filter(instance=instance).order_by("-id")[:5],
                "integrity": services.integrity_state(instance) if hold else None,
                "watch_ended": EnvelopeAttempt.objects.filter(
                    instance=instance, outcome__in=("decided_not_sent", "abandoned"),
                    public_id__in=[i.dedupe_key.split(":", 1)[1] for i in StaffItem.objects.filter(
                        application=application, status="open", reason_code=handlers.ORPHAN_WATCH_ENDED)]),
            })
    details = []
    for t in types:
        fields = completion.required_details(t)
        if fields:
            details.append({"type": t, "fields": fields, "draft": AgreementDetailsVersion.objects.filter(
                application=application, agreement_type=t, status="draft").order_by("-version").first(),
                "confirmed": completion.details_confirmed(application, t)})
    next_action, owner = _next_action(application, rows)
    user = request.user
    return {
        "application": application, "rows": rows, "details": details, "next_action": next_action, "owner": owner,
        "items": StaffItem.objects.filter(application=application, status="open", reason_code__startswith="agreement_"),
        "handoff": PendingAction.objects.filter(kind=completion.HANDOFF, subject_id=application.public_ref).first(),
        "stop_reasons": STOP_REASONS, "dispositions": DISPOSITIONS, "error": error, "form": form or {},
        "may": {p: services.can(user, p) for p in SCREEN},
    }


@require_GET
@screen
def agreements(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return render(request, "agreements/staff/agreements.html", _context(request, application))


def _instance(application, ref):
    return get_object_or_404(AgreementInstance, public_id=ref, application=application)


ACTIONS = {
    "cancel": lambda r, a, p: services.cancel_agreement(_instance(a, p["instance"]).pk, r.user),
    "reissue": lambda r, a, p: services.reissue_agreement(_instance(a, p["instance"]).pk, r.user),
    "stop": lambda r, a, p: services.stop_agreements(a.pk, r.user, p.get("reason", "")),
    "resume": lambda r, a, p: services.resume_agreements(a.pk, r.user),
    "retry_custody": lambda r, a, p: services.retry_custody(_instance(a, p["instance"]).pk, r.user),
    "recheck": lambda r, a, p: services.recheck_integrity(_instance(a, p["instance"]).pk, r.user),
    "resolve": lambda r, a, p: services.resolve_integrity(_instance(a, p["instance"]).pk, r.user, p.get("disposition", ""),
                                                          p.get("note", ""), p.get("digest", "")),
    "rearm": lambda r, a, p: services.rearm_orphan_watch(
        get_object_or_404(EnvelopeAttempt, public_id=p["attempt"], instance__application=a).pk, r.user),
    "record_details": lambda r, a, p: services.record_required_details(
        a.pk, p.get("type", ""), {k[6:]: v for k, v in p.items() if k.startswith("field-")}, r.user),
    "confirm_details": lambda r, a, p: services.confirm_required_details(
        get_object_or_404(AgreementDetailsVersion, public_id=p["details"], application=a).pk, r.user, p.get("digest", "")),
}


@require_POST
@screen
def act(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    action = request.POST.get("action", "")
    if action not in ACTIONS:
        raise Http404
    try:
        ACTIONS[action](request, application, request.POST)
    except (services.Refused, PermissionDenied, KeyError, ValueError, ValidationError, ObjectDoesNotExist, Http404) as exc:
        code = str(exc) if isinstance(exc, services.Refused) else "not_permitted" if isinstance(
            exc, PermissionDenied) else "invalid_request"
        context = _context(request, application, error=f"{action}: refused ({code})", form=request.POST)
        return render(request, "agreements/staff/agreements.html", context, status=409)
    messages.success(request, f"{action}: done")
    return redirect(reverse("agreements_staff:agreements", args=[application.public_ref]))


@require_POST
@never_cache
def retrieve(request, public_id):
    """Audited retrieval (021 section 7). Every refusal looks the same (404): a missing document, a missing
    permission, a non-staff or anonymous caller. Staff refusals are recorded; outsiders are logged."""
    try:
        filename, data = services.retrieve_document(str(public_id), request.user, request.POST.get("note", ""))
    except services.Refused as exc:
        if str(exc) == "not_available":
            raise Http404 from None
        return HttpResponse(f"Refused: {exc}", status=409, content_type="text/plain")
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response

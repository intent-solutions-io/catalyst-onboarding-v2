"""The provisioning staff screen (023 sections 6, 7 and 9; 5B.3b; TEST-P5-19, 20).

One page per application shows each provisioning request with its approval, creation, verification, credential
setup, activation and revocation states separately; the address, limits and method; attempts and evidence; open
provisioning items with their age; the next action and who owns it; and withdrawal links. Every action is a
CSRF-protected POST to one service, which checks its own permission. The P2 to P4 screen rules apply:

- the page names the permissions whose holders need it, and a superuser is refused like everyone else;
- untrusted text is autoescaped, and no page is cached;
- a consequential choice is never preselected;
- a refusal re-renders the page with what the person typed and the refusal code.

Managing access never shows applicant mail or signed documents: this screen has neither, and its permissions grant
neither (TEST-P5-20).
"""

import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from applications.models import Application
from correspondence.models import StaffItem
from workflow.models import AutomationPause, PendingAction

from . import closure, core, credentials, services
from .models import AccessRevocation, AddressReservation, ProvisioningRequest, WithdrawalConfirmation

logger = logging.getLogger(__name__)
SCREEN = ("view_provisioningrequest", "approve_provisioning", "operate_provisioning", "close_application")
OUTCOMES = {"closed": "Close the application (a decision; final)",
            "withdrawn": "Withdraw it on the applicant's request (final)"}
LABELS = {
    "awaiting_approval": "awaiting the approver", "approved": "approved, not yet created",
    "create_pending": "being created", "create_uncertain": "creation outcome unknown",
    "found_by_evidence": "found after an unknown create: staff must confirm", "created": "created, being verified",
    "verify_uncertain": "verification not yet conclusive", "verified": "verified",
    "setup_pending": "verified; waiting for the applicant's password", "setup_complete": "password set; activating",
    "active": "active", "conflict": "conflict: someone else's mailbox or not provably ours",
    "failed_needs_staff": "needs staff", "superseded": "superseded", "stopping": "stop requested; settling",
    "stopped": "stopped", "recovered_after_stop": "a mailbox appeared after the stop",
    "invitation_pending": "invitation queued", "invitation_sending": "invitation being sent",
    "invited": "invitation sent", "invitation_uncertain": "invitation outcome unknown", "presented": "link opened",
    "set_pending": "password being set", "completed": "password set", "set_uncertain": "password outcome unknown",
    "expired": "expired", "cancelled": "cancelled", "requested": "requested", "pending": "pending: staff action",
    "applied_unverified": "applied (cannot be read back)", "not_applicable": "not applicable",
    "unsupported": "no documented mechanism: owner decision", "exception": "accepted exception",
}
PHASES = (("Approval", ("awaiting_approval",)),
          ("Creation", ("approved", "create_pending", "create_uncertain", "found_by_evidence", "conflict")),
          ("Verification", ("created", "verify_uncertain")),
          ("Credential setup", ("verified", "setup_pending")),
          ("Activation", ("setup_complete", "active")))


def screen(view):
    @never_cache
    @login_required(login_url="admin:login")
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff or not any(services.can(request.user, p) for p in SCREEN):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def _phase(status: str) -> str:
    for name, statuses in PHASES:
        if status in statuses:
            return name
    return "Stopped or closed"


def _next_action(application, requests, items) -> tuple[str, str]:
    """(what happens next, who owns it), in plain words."""
    if application.stage in ("withdrawn", "closed"):
        open_rev = AccessRevocation.objects.filter(request__application=application).exclude(state__in=closure.FINAL)
        if open_rev.exists():
            return "Finish removing access (see Revocation below)", "staff, then the owner for exceptions"
        return "Closed; nothing more happens", "nobody"
    if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
        return "Automation is paused; provisioning waits", "staff"
    if items:
        return "Resolve the open provisioning items below", "staff"
    live = next((r for r in requests if r.status not in ("superseded", "stopped", "conflict")), None)
    if live is None:
        if PendingAction.objects.filter(kind=core.HANDOFF, subject_id=application.public_ref, status="held").exists():
            return "Release provisioning (owner command activate_provisioning)", "owner"
        return "Nothing to provision yet", "the agreements stage"
    return {
        "awaiting_approval": ("Approve the exact address, limits and method", "approver"),
        "approved": ("The system creates the mailbox", "system"),
        "create_pending": ("The system creates the mailbox", "system"),
        "create_uncertain": ("The system reconciles an unknown create by reading", "system"),
        "found_by_evidence": ("Confirm whether the found mailbox is ours", "operator"),
        "created": ("The system verifies the mailbox", "system"),
        "verify_uncertain": ("The system re-checks the mailbox", "system"),
        "verified": ("Send a password link (the contact could not be used)", "operator"),
        "setup_pending": ("Waiting for the applicant to set their password", "applicant"),
        "setup_complete": ("The system activates the applicant", "system"),
        "active": ("Active; nothing more", "nobody"),
    }.get(live.status, ("Staff review", "staff"))


def _offered(r) -> set[str]:
    """Which request actions the screen offers for this status (the services still decide)."""
    s, checklist = r.status, r.method == "checklist"
    offered = set()
    if checklist and s == "approved":
        offered.add("record_checklist")
    if checklist and s == "created":
        offered.add("attest")
    if s in ("verified", "setup_pending"):
        offered.add("reissue")
    if s == "setup_complete":
        offered.add("retry_activation")
    if s in ("awaiting_approval", "approved", "verify_uncertain", "conflict", "failed_needs_staff"):
        offered.add("supersede")
    if s in ("superseded", "conflict", "stopped") and r.reservation.released_at is None:
        offered.add("release_address")
    if s in ("found_by_evidence", "recovered_after_stop", "conflict") or r.stop_requested_at is not None:
        offered.add("confirm_found")
    return offered


def _context(request, application, *, error="", form=None):
    requests = list(ProvisioningRequest.objects.filter(application=application).select_related("reservation")
                    .order_by("-id"))
    rows = []
    for r in requests:
        rows.append({
            "request": r, "phase": _phase(r.status), "status": LABELS.get(r.status, r.status), "offered": _offered(r),
            "operate": bool(_offered(r) - {"confirm_found"}),
            "attempts": list(r.attempts.order_by("id")),
            "evidence": list(r.evidence.order_by("id")),
            "setups": [{"setup": s, "state": LABELS.get(s.state, s.state)} for s in r.setups.order_by("series")],
            "revocations": [{"row": v, "state": LABELS.get(v.state, v.state),
                             "exceptionable": v.kind in closure.EXCEPTIONABLE and v.state in ("unsupported", "pending")}
                            for v in r.revocations.order_by("id")],
            "complete": closure.revocation_complete(r) if r.revocations.exists() else None,
        })
    items = list(StaffItem.objects.filter(application=application, status="open",
                                          reason_code__startswith="provisioning_").order_by("opened_at", "id"))
    next_action, owner = _next_action(application, requests, items)
    user = request.user
    return {
        "application": application, "rows": rows, "items": items, "next_action": next_action, "owner": owner,
        "reservations": AddressReservation.objects.filter(application=application).order_by("-id"),
        "withdrawals": WithdrawalConfirmation.objects.filter(application=application).order_by("-id"),
        "outcomes": OUTCOMES, "error": error, "form": form or {},
        "may": {p: services.can(user, p) for p in SCREEN},
        "closed": application.stage in ("withdrawn", "closed"),
    }


@require_GET
@screen
def provisioning(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return render(request, "provisioning/staff/provisioning.html", _context(request, application))


def _request(application, ref):
    return get_object_or_404(ProvisioningRequest, public_id=ref, application=application)


def _revocation(application, ref):
    return get_object_or_404(AccessRevocation, public_id=ref, request__application=application)


ACTIONS = {
    "approve": lambda r, a, p: services.approve(_request(a, p["request"]).pk, r.user, p.get("digest", "")),
    "reserve_exception": lambda r, a, p: services.reserve_exception(a.pk, p.get("local_part", ""), r.user,
                                                                    p.get("note", "")),
    "record_checklist": lambda r, a, p: services.record_checklist_creation(_request(a, p["request"]).pk, r.user,
                                                                           p.get("note", "")),
    "attest": lambda r, a, p: services.attest_checklist_verification(_request(a, p["request"]).pk, r.user,
                                                                     p.get("note", "")),
    "confirm_found": lambda r, a, p: services.confirm_found_mailbox(_request(a, p["request"]).pk, r.user,
                                                                    p.get("decision", ""), p.get("note", "")),
    "supersede": lambda r, a, p: services.supersede(_request(a, p["request"]).pk, r.user, p.get("note", "")),
    "release_address": lambda r, a, p: services.release_address(_request(a, p["request"]).pk, r.user, p.get("note", "")),
    "reissue": lambda r, a, p: credentials.reissue(_request(a, p["request"]).pk, r.user, p.get("note", "")),
    "retry_activation": lambda r, a, p: credentials.retry_activation(_request(a, p["request"]).pk, r.user,
                                                                     p.get("note", "")),
    "recheck_revocation": lambda r, a, p: closure.recheck_revocation(_request(a, p["request"]).pk, r.user,
                                                                     p.get("note", "")),
    "accept_exception": lambda r, a, p: closure.accept_revocation_exception(_revocation(a, p["revocation"]).pk, r.user,
                                                                            p.get("note", "")),
    "withdrawal_link": lambda r, a, p: closure.request_withdrawal_link(a.pk, r.user, p.get("note", "")),
    "close": lambda r, a, p: closure.close_application(a.pk, r.user, p.get("outcome", ""), p.get("note", "")),
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
        if code == "invalid_request":
            logger.warning("provisioning staff action %s refused as invalid (%s)", action, type(exc).__name__)
        context = _context(request, application, error=f"{action}: refused ({code})", form=request.POST)
        return render(request, "provisioning/staff/provisioning.html", context, status=409)
    messages.success(request, f"{action}: done")
    return redirect(reverse("provisioning_staff:provisioning", args=[application.public_ref]))

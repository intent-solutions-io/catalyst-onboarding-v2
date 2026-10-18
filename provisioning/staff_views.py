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
from django.core.exceptions import PermissionDenied, ValidationError
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
          ("Activation", ("setup_complete", "active")),
          ("Needs staff", ("failed_needs_staff",)))
OPERATE_ACTIONS = ("record_checklist", "attest", "reissue", "retry_activation", "supersede", "release_address")
RELEASABLE = ("superseded", "conflict", "stopped", "recovered_after_stop", "failed_needs_staff")  # release_address
CLOSED_REQUEST = ("active", "superseded", "stopped", "recovered_after_stop")
IN_FLIGHT = ("create_pending", "create_uncertain", "stopping")
# Plain words for each provisioning item, so a blocker reads as one (the code stays visible for staff searches).
ITEM_TEXT = {
    core.ITEM_NAME_REVIEW: "the naming rule cannot form an address: reserve a reviewed one",
    core.ITEM_BLOCKED: "a prerequisite no longer holds: see the blocker shown on the request",
    core.ITEM_CONFLICT: "the address is someone else's or not provably ours: supersede or decide",
    core.ITEM_CONFIRM_FOUND: "a mailbox was found after an unknown create: confirm whether it is ours",
    core.ITEM_CHECKLIST: "create the mailbox in the panel, then a different operator attests it",
    core.ITEM_FAILED: "creation failed: supersede the request or fix the cause",
    core.ITEM_LATE_MAILBOX: "a mailbox appeared late: confirm whether it is ours",
    "provisioning_revocation_needs_staff": "access removal needs staff: see Revocation",
    "provisioning_withdrawal_link_failed": "the withdrawal link could not be sent: send a new one",
    "provisioning_setup_needs_staff": "the password link needs staff: send a new one",
    "provisioning_activation_blocked": "activation is blocked: fix the cause, then retry activation",
}


def screen(view):
    @never_cache
    @login_required(login_url="admin:login")
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff or not any(services.can(request.user, p) for p in SCREEN):
            logger.warning("provisioning staff screen refused: user=%s path=%s", request.user.pk, request.path)
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def _phase(status: str) -> str:
    for name, statuses in PHASES:
        if status in statuses:
            return name
    return "Stopped or closed"


def _next_action(application, requests, items) -> tuple[str, str]:  # noqa: C901 (one table per status)
    """(what happens next, who owns it), in plain words."""
    if application.stage in ("withdrawn", "closed"):
        open_rev = AccessRevocation.objects.filter(request__application=application).exclude(state__in=closure.FINAL)
        if open_rev.exists():
            return "Finish removing access (see Revocation below)", "staff, then the owner for exceptions"
        return "Closed; nothing more happens", "nobody"
    if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
        return "Automation is paused; provisioning waits", "staff"
    live = next((r for r in requests if r.status not in ("superseded", "stopped", "conflict")), None)
    # An item that only restates the request's own next step (the checklist) does not hide that step.
    if any(i.reason_code != core.ITEM_CHECKLIST for i in items) or (items and live is None):
        return "Resolve the open provisioning items below", "staff"
    if live is None:
        if PendingAction.objects.filter(kind=core.HANDOFF, subject_id=application.public_ref, status="held").exists():
            return "Release provisioning (owner command activate_provisioning)", "owner"
        return "Nothing to provision yet", "the agreements stage"
    return {
        "awaiting_approval": ("Approve the exact address, limits and method", "approver"),
        "approved": (("Create it in the panel and record it", "operator") if live.method == "checklist"
                     else ("The system creates the mailbox", "system")),
        "create_pending": ("The system creates the mailbox", "system"),
        "create_uncertain": ("The system reconciles an unknown create by reading", "system"),
        "found_by_evidence": ("Confirm whether the found mailbox is ours", "operator"),
        "created": (("A different operator attests the panel listing", "operator") if live.method == "checklist"
                    else ("The system verifies the mailbox", "system")),
        "verify_uncertain": ("The system re-checks the mailbox", "system"),
        "verified": (("Set up the credential by the separate checklist contingency (P5-D-6)", "operator")
                     if live.method == "checklist" else ("Send a password link (the contact could not be used)",
                                                         "operator")),
        "failed_needs_staff": ("Supersede the request or fix the cause", "operator"),
        "setup_pending": ("Waiting for the applicant to set their password", "applicant"),
        "setup_complete": ("The system activates the applicant", "system"),
        "active": ("Active; nothing more", "nobody"),
    }.get(live.status, ("Staff review", "staff"))


def _decidable(r, open_codes: set[str]) -> bool:
    """The same condition `services.confirm_found_mailbox` accepts."""
    if r.status == "found_by_evidence" or open_codes & {core.ITEM_LATE_MAILBOX, core.ITEM_CONFIRM_FOUND}:
        return True
    return r.stop_requested_at is not None and r.attempts.filter(
        step="create", outcome="conflict", code__in=("present_but_not_provably_ours", "conflict_after_ours")).exists()


def _offered(r, open_codes: set[str], closed: bool) -> set[str]:
    """Which request actions the screen offers: the same conditions the services check (the services still decide;
    `work_in_flight` and `watch_open` are theirs to refuse)."""
    s, checklist = r.status, r.method == "checklist"
    offered = set()
    if s in RELEASABLE and r.reservation.released_at is None:
        offered.add("release_address")
    if _decidable(r, open_codes):
        offered.add("confirm_found")
    if closed:
        return offered  # after a close only settling actions remain
    if checklist and s == "approved":
        offered.add("record_checklist")
    if checklist and s == "created":
        offered.add("attest")
    if not checklist and s in ("verified", "setup_pending"):
        offered.add("reissue")
    if s == "setup_complete":
        offered.add("retry_activation")
    if s not in CLOSED_REQUEST and s not in IN_FLIGHT:
        offered.add("supersede")
    return offered


def _context(request, application, *, error="", form=None):
    requests = list(ProvisioningRequest.objects.filter(application=application).select_related("reservation")
                    .order_by("-id"))
    closed = application.stage in ("withdrawn", "closed")
    open_items = list(StaffItem.objects.filter(application=application, status="open",
                                               reason_code__startswith="provisioning_").order_by("opened_at", "id"))
    rows = []
    for r in requests:
        mine = [i for i in open_items if i.dedupe_key == f"provisioning:{r.public_id}"]
        offered = _offered(r, {i.reason_code for i in mine}, closed)
        live = r.status not in CLOSED_REQUEST and not closed
        rows.append({
            "request": r, "phase": _phase(r.status), "status": LABELS.get(r.status, r.status), "offered": offered,
            "operate": bool(offered - {"confirm_found"}),
            "blocker": core.database_problem(application, r) if live else "",
            "items": [{"item": i, "text": ITEM_TEXT.get(i.reason_code, "")} for i in mine],
            "attempts": list(r.attempts.order_by("id")),
            "evidence": list(r.evidence.order_by("id")),
            "setups": [{"setup": s, "state": LABELS.get(s.state, s.state)} for s in r.setups.order_by("series")],
            "revocations": [{"row": v, "state": LABELS.get(v.state, v.state),
                             "exceptionable": v.kind in closure.EXCEPTIONABLE and v.state in ("unsupported", "pending")}
                            for v in r.revocations.order_by("id")],
            "complete": closure.revocation_complete(r) if r.revocations.exists() else None,
        })
    items = [{"item": i, "text": ITEM_TEXT.get(i.reason_code, "")} for i in open_items
             if not any(i.dedupe_key == f"provisioning:{r.public_id}" for r in requests)]
    next_action, owner = _next_action(application, requests, open_items)
    user = request.user
    return {
        "application": application, "rows": rows, "items": items, "next_action": next_action, "owner": owner,
        "reservations": AddressReservation.objects.filter(application=application).order_by("-id"),
        "withdrawals": WithdrawalConfirmation.objects.filter(application=application).order_by("-id"),
        "outcomes": OUTCOMES, "error": error, "form": form or {}, "operate_actions": OPERATE_ACTIONS,
        "may": {p: services.can(user, p) for p in SCREEN},
        "closed": closed,
    }


@require_GET
@screen
def provisioning(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return render(request, "provisioning/staff/provisioning.html", _context(request, application))


class _Invalid(Exception):
    """A form value that names nothing on this application (missing, malformed or another application's)."""


def _scoped(model, ref, **scope):
    try:
        return model.objects.get(public_id=ref, **scope)
    except (model.DoesNotExist, ValueError, ValidationError):
        raise _Invalid from None


def _request(application, ref):
    return _scoped(ProvisioningRequest, ref, application=application)


def _revocation(application, ref):
    return _scoped(AccessRevocation, ref, request__application=application)


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
    except (services.Refused, PermissionDenied, _Invalid, KeyError) as exc:
        code = str(exc) if isinstance(exc, services.Refused) else "not_permitted" if isinstance(
            exc, PermissionDenied) else "invalid_request"
        # Every refusal is logged with who, what and where; never a typed value.
        logger.warning("provisioning staff action refused: user=%s action=%s application=%s code=%s",
                       request.user.pk, action, application.public_ref, code)
        context = _context(request, application, error=f"{action}: refused ({code})", form=request.POST)
        return render(request, "provisioning/staff/provisioning.html", context, status=409)
    messages.success(request, f"{action}: done")
    return redirect(reverse("provisioning_staff:provisioning", args=[application.public_ref]))

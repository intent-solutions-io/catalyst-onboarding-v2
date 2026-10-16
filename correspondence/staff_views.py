"""The permissioned staff screens for correspondence (016 F; owner decision M9; P2 task 2B.4). Synthetic only.

The spike result (recorded in 016 10.10): admin actions do not fit `ReadOnlyAdminMixin`. They cannot collect
a note, an outcome per question, a target or a message body; a changelist action receives a queryset, which
is exactly the bulk path S1 refuses; and enabling them would weaken the read-only admin and its tests. So the
admin stays read-only, and these focused views are the one place staff act:

- each page names the permissions whose holders need it, so a role reads only what its work needs (a
  template owner sees templates, never applicant mail); every action is a POST naming exactly one object in
  its URL, CSRF-protected, and calls one named service, which checks its own permission again (a superuser is
  refused like everyone else, D-23);
- a refusal shows its reason code, never exception text or data;
- untrusted text (mail derivatives, sender fields, applicant names, question and template text) is
  autoescaped and shown through the `visible` filter; it never appears in an attribute, a URL, a title or a
  flash message;
- pages are never cached, and nothing here writes the admin log.
"""

import uuid
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from applications.models import Application
from workflow.models import AutomationPause

from . import outbound, processing, staff_actions
from .common import DECIDABLE, Refused, can
from .models import (
    ApprovedMessage,
    InboundMessage,
    MailboxCursor,
    MessageTemplateVersion,
    OutboundMessage,
    Question,
    StaffItem,
    StaffMessageDraft,
)

OUTCOME_CHOICES = ("satisfied", "partial", "not_addressed")
QUEUE_LIMIT = 200

# Who may open which page (2B.4 security review): the permissions whose holders act there.
QUEUE = ("resolve_exception", "resolve_identity_exception", "decide_uncertain_send", "restart_collector",
         "confirm_question_outcome")
REPLY = ("confirm_question_outcome", "resolve_exception", "resolve_identity_exception")
APPLICATION = ("approve_question", "withdraw_question", "pause_automation", "resume_automation", "send_staff_message")
TEMPLATES = ("approve_template_version",)
# Decisions offered per send reason (016 F: a permanent rejection is abandoned or revised, never resent).
DECISIONS_BY_REASON = {"send_rejected_permanent": ("abandon", "revise")}


def staff_page(*permissions):
    def decorate(view):
        @never_cache
        @login_required(login_url="admin:login")
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_staff or not any(can(request.user, p) for p in permissions):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorate


def act(request, target: str, service, success):
    """Run one service call; a refusal becomes a fixed message with its code, never data."""
    try:
        result = service()
    except Refused as exc:
        messages.error(request, f"Refused: {exc}")
        return redirect(target)
    messages.success(request, success(result) if callable(success) else success)
    return redirect(target)


def resolutions_for(user, item) -> list[str]:
    if item.reason_code in processing.RESOLUTIONS:
        return [code for code, perm in processing.RESOLUTIONS[item.reason_code].items() if can(user, perm)]
    if item.reason_code in processing.ACKNOWLEDGE_ONLY and can(user, "resolve_exception"):
        return ["acknowledge"]
    return []


def _ref(item, prefix):
    if not item.dedupe_key.startswith(prefix):
        return None
    try:
        return uuid.UUID(item.dedupe_key.split(":")[1])
    except (IndexError, ValueError):
        return None


def inbound_of(item):
    ref = _ref(item, "inbound:")
    return InboundMessage.objects.filter(public_id=ref).first() if ref else None


def cursor_of(item):
    ref = _ref(item, "cursor:")
    return MailboxCursor.objects.filter(public_id=ref).first() if ref else None


def parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


# --- pages --------------------------------------------------------------------------------------------------

@require_GET
@staff_page(*QUEUE, *APPLICATION)
def queue(request):
    open_items = StaffItem.objects.filter(status=StaffItem.Status.OPEN)
    items = open_items.select_related("application").order_by("opened_at", "id")
    reason = request.GET.get("reason", "")
    if reason:
        items = items.filter(reason_code=reason)
    reasons = sorted(set(open_items.values_list("reason_code", flat=True)))
    total = items.count()
    return render(request, "correspondence/staff/queue.html", {
        "items": items[:QUEUE_LIMIT], "total": total, "limit": QUEUE_LIMIT, "reasons": reasons, "reason": reason,
        "paused": AutomationPause.objects.filter(subject_type="application").count(),
        "cursors": MailboxCursor.objects.order_by("id"),
    })


@require_GET
@staff_page(*QUEUE)
def item_detail(request, public_id):
    item = get_object_or_404(StaffItem.objects.select_related("application", "approved_message"), public_id=public_id)
    message, cursor = inbound_of(item), cursor_of(item)
    is_open = item.status == StaffItem.Status.OPEN
    decide = is_open and item.reason_code in DECIDABLE and item.approved_message_id and can(request.user, "decide_uncertain_send")
    sent = item.approved_message
    return render(request, "correspondence/staff/item.html", {
        "item": item, "codes": resolutions_for(request.user, item) if is_open else [], "message": message,
        "cursor": cursor, "decide": decide,
        "decisions": DECISIONS_BY_REASON.get(item.reason_code, staff_actions.DECISIONS),
        "restart": is_open and cursor is not None and cursor.state == MailboxCursor.State.BLOCKED
        and can(request.user, "restart_collector"),
        "sent": sent,
        "attempts": OutboundMessage.objects.filter(approved_message=sent).order_by("attempt_number") if sent else [],
    })


@require_GET
@staff_page(*REPLY)
def reply_detail(request, public_id):
    message = get_object_or_404(InboundMessage.objects.select_related("application"), public_id=public_id)
    links = message.question_links.select_related("question").order_by("question_id")
    # Only advice computed on the derivative shown now: after a re-derivation old spans would point at other text.
    interpretation = message.interpretations.filter(status="completed", text_sha256=message.derived_text_sha256).order_by(
        "-attempt").first()
    advice = []
    if interpretation is not None:  # P3 3B.3: advice only, shown beside the question; never pre-selected
        texts = {str(link.question.public_id): link.question.text for link in links}
        advice = [{"question": texts.get(p["question"], ""), "outcome": p["outcome"], "note": p.get("note", ""),
                   "quotes": [message.derived_text[s:e] for s, e in p["spans"]]} for p in interpretation.proposals]
    return render(request, "correspondence/staff/reply.html", {
        "message": message, "pending": [link for link in links if link.state == "pending"], "links": links,
        "interpretation": interpretation, "advice": advice,
        "outcomes": OUTCOME_CHOICES, "close_reasons": processing.CLOSE_REASONS,
        "can_decide": can(request.user, "confirm_question_outcome") and message.status == "awaiting_processing"
        and message.classification == "human",
    })


@require_GET
@staff_page(*APPLICATION)
def application_list(request):
    applications = Application.objects.annotate(
        paused=Exists(AutomationPause.objects.filter(subject_type="application", subject_id=OuterRef("public_ref"))),
        proposed=Exists(Question.objects.filter(application=OuterRef("pk"), approval_state="proposed")),
    ).order_by("-id")
    shown = request.GET.get("show", "")
    if shown == "paused":
        applications = applications.filter(paused=True)
    elif shown == "proposed":
        applications = applications.filter(proposed=True)
    ref = parse_uuid(request.GET.get("ref", ""))
    if ref is not None:
        applications = applications.filter(public_ref=ref)
    return render(request, "correspondence/staff/applications.html", {
        "applications": applications[:QUEUE_LIMIT], "show": shown, "limit": QUEUE_LIMIT})


@require_GET
@staff_page(*APPLICATION)
def application_detail(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    user = request.user
    return render(request, "correspondence/staff/application.html", {
        "application": application, "questions": Question.objects.filter(application=application).order_by("created_at", "id"),
        "paused": staff_actions._pause_row(application).first(),
        "can_pause": can(user, "pause_automation"), "can_resume": can(user, "resume_automation"),
        "can_withdraw": can(user, "withdraw_question"), "can_approve": can(user, "approve_question"),
        "can_message": can(user, "send_staff_message"), "withdraw_reasons": staff_actions.WITHDRAW_REASONS,
        "items": application.staff_items.filter(status="open").order_by("opened_at", "id"),
        "staff_messages": ApprovedMessage.objects.filter(application=application, kind="staff_message").order_by("-id")[:20],
        "draft": {"subject": "", "body": ""},
    })


@require_GET
@staff_page(*TEMPLATES)
def template_list(request):
    return render(request, "correspondence/staff/templates.html", {
        "versions": MessageTemplateVersion.objects.select_related("template").order_by("template__key", "-version")})


@require_GET
@staff_page(*TEMPLATES)
def template_detail(request, pk):
    version = get_object_or_404(MessageTemplateVersion.objects.select_related("template"), pk=pk)
    return render(request, "correspondence/staff/template.html", {
        "version": version, "can_approve": version.status == "draft" and can(request.user, "approve_template_version")})


# --- actions (POST, one object each) -------------------------------------------------------------------------

@require_POST
@staff_page(*QUEUE)
def resolve(request, public_id):
    item = get_object_or_404(StaffItem, public_id=public_id)
    target, here = None, reverse("correspondence_staff:item", args=[public_id])
    if request.POST.get("code") == "associate" and request.POST.get("target"):
        ref = parse_uuid(request.POST["target"])
        application = Application.objects.filter(public_ref=ref).first() if ref else None
        if application is None:
            messages.error(request, "Refused: unknown_application")
            return redirect(here)
        target = application.pk
    return act(request, here, lambda: processing.resolve_exception(
        item.pk, request.POST.get("code", ""), request.user, note=request.POST.get("note", ""),
        target_application_id=target), "Resolved.")


@require_POST
@staff_page(*QUEUE)
def send_decision(request, public_id):
    item = get_object_or_404(StaffItem, public_id=public_id)
    here = reverse("correspondence_staff:item", args=[public_id])
    if item.status != StaffItem.Status.OPEN or item.reason_code not in DECIDABLE or item.approved_message_id is None:
        messages.error(request, "Refused: nothing_to_decide")
        return redirect(here)
    decision = request.POST.get("decision", "")
    if decision not in DECISIONS_BY_REASON.get(item.reason_code, staff_actions.DECISIONS):
        messages.error(request, "Refused: decision_not_offered_for_this_reason")
        return redirect(here)
    return act(request, here, lambda: staff_actions.decide_uncertain_send(
        item.approved_message_id, request.user, decision, request.POST.get("note", "")), "Decision recorded.")


@require_POST
@staff_page(*QUEUE)
def restart(request, public_id):
    cursor = get_object_or_404(MailboxCursor, public_id=public_id)
    return act(request, reverse("correspondence_staff:queue"),
               lambda: staff_actions.restart_collector(cursor.pk, request.user, request.POST.get("note", "")),
               "Collector restarted.")


@require_POST
@staff_page(*REPLY)
def confirm_outcome(request, public_id):
    message = get_object_or_404(InboundMessage, public_id=public_id)
    outcomes = {}
    for link in message.question_links.filter(state="pending").select_related("question"):
        value = request.POST.get(f"q-{link.question.public_id}", "")
        if value:
            outcomes[link.question_id] = value
    return act(request, reverse("correspondence_staff:reply", args=[public_id]),
               lambda: processing.confirm_question_outcome(message.pk, outcomes, request.user,
                                                           note=request.POST.get("note", ""),
                                                           expected_digest=request.POST.get("digest", "")),
               "Outcome confirmed.")


@require_POST
@staff_page(*REPLY)
def close_reply(request, public_id):
    message = get_object_or_404(InboundMessage, public_id=public_id)
    return act(request, reverse("correspondence_staff:reply", args=[public_id]),
               lambda: processing.close_reply_without_outcome(message.pk, request.user, reason=request.POST.get("reason", ""),
                                                              note=request.POST.get("note", "")),
               "Reply closed.")


@require_POST
@staff_page(*APPLICATION)
def pause(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return act(request, reverse("correspondence_staff:application", args=[public_ref]),
               lambda: staff_actions.pause(application.pk, request.user, request.POST.get("reason", "")), "Paused.")


@require_POST
@staff_page(*APPLICATION)
def resume(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return act(request, reverse("correspondence_staff:application", args=[public_ref]),
               lambda: staff_actions.resume(application.pk, request.user, request.POST.get("note", "")),
               lambda moved: f"Resumed; {moved} reminder action(s) rescheduled.")


@require_POST
@staff_page(*APPLICATION)
def approve(request, public_id):
    question = get_object_or_404(Question.objects.select_related("application"), public_id=public_id)
    return act(request, reverse("correspondence_staff:application", args=[question.application.public_ref]),
               lambda: outbound.approve_question(question.pk, request.user), "Question approved and queued.")


@require_POST
@staff_page(*APPLICATION)
def withdraw(request, public_id):
    question = get_object_or_404(Question.objects.select_related("application"), public_id=public_id)
    return act(request, reverse("correspondence_staff:application", args=[question.application.public_ref]),
               lambda: staff_actions.withdraw_question(question.pk, request.user, request.POST.get("reason", ""),
                                                       request.POST.get("note", "")),
               "Question withdrawn.")


@require_POST
@staff_page(*TEMPLATES)
def approve_template(request, pk):
    version = get_object_or_404(MessageTemplateVersion, pk=pk)
    return act(request, reverse("correspondence_staff:template", args=[pk]),
               lambda: outbound.approve_template_version(version.pk, request.user,
                                                         expected_digest=request.POST.get("digest", "")),
               "Template version approved.")


@require_POST
@staff_page(*APPLICATION)
def preview_message(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    subject, body = request.POST.get("subject", ""), request.POST.get("body", "")
    try:
        draft = staff_actions.preview_staff_message(application.pk, request.user, subject, body)
    except Refused as exc:
        messages.error(request, f"Refused: {exc}")
        # The typed text comes back (escaped) so nothing is retyped; it is never stored.
        context = {"application": application, "draft": {"subject": subject, "body": body}}
        return render(request, "correspondence/staff/compose.html", context)
    return render(request, "correspondence/staff/preview.html", {"draft": draft, "application": application})


@require_POST
@staff_page(*APPLICATION)
def confirm_message(request, public_id):
    draft = get_object_or_404(StaffMessageDraft.objects.select_related("application"), public_id=public_id)
    return act(request, reverse("correspondence_staff:application", args=[draft.application.public_ref]),
               lambda: staff_actions.confirm_staff_message(draft.pk, request.POST.get("digest", ""), request.user),
               "Staff message confirmed and queued.")

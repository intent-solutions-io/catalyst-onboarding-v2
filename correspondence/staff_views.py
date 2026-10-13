"""The permissioned staff screens for correspondence (016 F; owner decision M9; P2 task 2B.4). Synthetic only.

The spike result (recorded in 016 10.10): admin actions do not fit `ReadOnlyAdminMixin`. They cannot collect
a note, an outcome per question, a target or a message body; a changelist action receives a queryset, which
is exactly the bulk path S1 refuses; and enabling them would weaken the read-only admin and its tests. So the
admin stays read-only, and these focused views are the one place staff act:

- every page needs an active staff account holding at least one correspondence permission; every action is a
  POST naming exactly one object in its URL, CSRF-protected, and calls one named service, which checks its own
  permission again (a superuser is refused like everyone else, D-23);
- a refusal shows its reason code, never exception text or data;
- untrusted text (mail derivatives, sender fields, applicant names) is autoescaped and shown through the
  `visible` filter; it never appears in an attribute, a URL, a title or a flash message;
- pages are never cached, and nothing here writes the admin log.
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

from . import outbound, processing, staff_actions
from .common import DECIDABLE, Refused, can
from .models import ApprovedMessage, InboundMessage, MailboxCursor, MessageTemplateVersion, Question, StaffItem, StaffMessageDraft
from .roles import GROUP_PERMISSIONS
from .staff_items import NoteRefused

STAFF_PERMISSIONS = sorted({p for perms in GROUP_PERMISSIONS.values() for p in perms})
OUTCOME_CHOICES = ("satisfied", "partial", "not_addressed")


def staff_page(view):
    @never_cache
    @login_required(login_url="admin:login")
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_staff or not any(can(user, p) for p in STAFF_PERMISSIONS):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def act(request, target: str, service, success: str):
    """Run one service call; a refusal or a missing permission becomes a fixed message, never data."""
    try:
        service()
    except PermissionDenied:
        raise
    except (Refused, NoteRefused) as exc:
        messages.error(request, f"Refused: {exc}")
        return redirect(target)
    messages.success(request, success)
    return redirect(target)


def resolutions_for(user, item) -> list[str]:
    if item.reason_code in processing.RESOLUTIONS:
        return [code for code, perm in processing.RESOLUTIONS[item.reason_code].items() if can(user, perm)]
    if item.reason_code in processing.ACKNOWLEDGE_ONLY and can(user, "resolve_exception"):
        return ["acknowledge"]
    return []


def inbound_of(item):
    if item.dedupe_key.startswith("inbound:"):
        return InboundMessage.objects.filter(public_id=item.dedupe_key.split(":")[1]).first()
    return None


def cursor_of(item):
    if item.dedupe_key.startswith("cursor:"):
        return MailboxCursor.objects.filter(public_id=item.dedupe_key.split(":")[1]).first()
    return None


# --- pages --------------------------------------------------------------------------------------------------

@require_GET
@staff_page
def queue(request):
    items = StaffItem.objects.filter(status=StaffItem.Status.OPEN).select_related("application").order_by("opened_at", "id")
    reason = request.GET.get("reason", "")
    if reason:
        items = items.filter(reason_code=reason)
    reasons = sorted(set(StaffItem.objects.filter(status=StaffItem.Status.OPEN).values_list("reason_code", flat=True)))
    return render(request, "correspondence/staff/queue.html", {"items": items[:200], "reasons": reasons, "reason": reason})


@require_GET
@staff_page
def item_detail(request, public_id):
    item = get_object_or_404(StaffItem.objects.select_related("application", "approved_message"), public_id=public_id)
    message = inbound_of(item)
    return render(request, "correspondence/staff/item.html", {
        "item": item, "codes": resolutions_for(request.user, item) if item.status == "open" else [],
        "message": message, "cursor": cursor_of(item),
        "decide": item.status == "open" and item.reason_code in DECIDABLE and can(request.user, "decide_uncertain_send"),
        "restart": item.status == "open" and cursor_of(item) is not None and can(request.user, "restart_collector"),
        "review": item.reason_code == "reply_needs_review" and message is not None,
        "decisions": staff_actions.DECISIONS,
    })


@require_GET
@staff_page
def reply_detail(request, public_id):
    message = get_object_or_404(InboundMessage.objects.select_related("application"), public_id=public_id)
    links = message.question_links.select_related("question").order_by("question_id")
    return render(request, "correspondence/staff/reply.html", {
        "message": message, "pending": [l for l in links if l.state == "pending"], "links": links,
        "outcomes": OUTCOME_CHOICES, "close_reasons": processing.CLOSE_REASONS,
        "can_decide": can(request.user, "confirm_question_outcome") and message.status == "awaiting_processing",
    })


@require_GET
@staff_page
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
    })


# --- actions (POST, one object each) -------------------------------------------------------------------------

@require_POST
@staff_page
def resolve(request, public_id):
    item = get_object_or_404(StaffItem, public_id=public_id)
    target = None
    if request.POST.get("code") == "associate" and request.POST.get("target"):
        target = get_object_or_404(Application, public_ref=request.POST["target"]).pk
    return act(request, reverse("correspondence_staff:item", args=[public_id]),
               lambda: processing.resolve_exception(item.pk, request.POST.get("code", ""), request.user,
                                                    note=request.POST.get("note", ""), target_application_id=target),
               "Resolved.")


@require_POST
@staff_page
def send_decision(request, public_id):
    item = get_object_or_404(StaffItem, public_id=public_id)
    if item.approved_message_id is None:
        raise PermissionDenied
    return act(request, reverse("correspondence_staff:item", args=[public_id]),
               lambda: staff_actions.decide_uncertain_send(item.approved_message_id, request.user,
                                                           request.POST.get("decision", ""), request.POST.get("note", "")),
               "Decision recorded.")


@require_POST
@staff_page
def restart(request, public_id):
    cursor = get_object_or_404(MailboxCursor, public_id=public_id)
    return act(request, reverse("correspondence_staff:queue"),
               lambda: staff_actions.restart_collector(cursor.pk, request.user, request.POST.get("note", "")),
               "Collector restarted.")


@require_POST
@staff_page
def confirm_outcome(request, public_id):
    message = get_object_or_404(InboundMessage, public_id=public_id)
    outcomes = {}
    for link in message.question_links.filter(state="pending"):
        value = request.POST.get(f"q-{link.question.public_id}", "")
        if value:
            outcomes[link.question_id] = value
    return act(request, reverse("correspondence_staff:reply", args=[public_id]),
               lambda: processing.confirm_question_outcome(message.pk, outcomes, request.user,
                                                           note=request.POST.get("note", ""),
                                                           expected_digest=request.POST.get("digest", "")),
               "Outcome confirmed.")


@require_POST
@staff_page
def close_reply(request, public_id):
    message = get_object_or_404(InboundMessage, public_id=public_id)
    return act(request, reverse("correspondence_staff:reply", args=[public_id]),
               lambda: processing.close_reply_without_outcome(message.pk, request.user, reason=request.POST.get("reason", ""),
                                                              note=request.POST.get("note", "")),
               "Reply closed.")


@require_POST
@staff_page
def pause(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return act(request, reverse("correspondence_staff:application", args=[public_ref]),
               lambda: staff_actions.pause(application.pk, request.user, request.POST.get("reason", "")), "Paused.")


@require_POST
@staff_page
def resume(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    return act(request, reverse("correspondence_staff:application", args=[public_ref]),
               lambda: staff_actions.resume(application.pk, request.user, request.POST.get("note", "")), "Resumed.")


@require_POST
@staff_page
def approve(request, public_id):
    question = get_object_or_404(Question, public_id=public_id)
    return act(request, reverse("correspondence_staff:application", args=[question.application.public_ref]),
               lambda: outbound.approve_question(question.pk, request.user), "Question approved and queued.")


@require_POST
@staff_page
def withdraw(request, public_id):
    question = get_object_or_404(Question, public_id=public_id)
    return act(request, reverse("correspondence_staff:application", args=[question.application.public_ref]),
               lambda: staff_actions.withdraw_question(question.pk, request.user, request.POST.get("reason", ""),
                                                       request.POST.get("note", "")),
               "Question withdrawn.")


@require_POST
@staff_page
def approve_template(request, pk):
    version = get_object_or_404(MessageTemplateVersion, pk=pk)
    return act(request, reverse("correspondence_staff:queue"),
               lambda: outbound.approve_template_version(version.pk, request.user), "Template version approved.")


@require_POST
@staff_page
def preview_message(request, public_ref):
    application = get_object_or_404(Application, public_ref=public_ref)
    try:
        draft = staff_actions.preview_staff_message(application.pk, request.user, request.POST.get("subject", ""),
                                                    request.POST.get("body", ""))
    except Refused as exc:
        messages.error(request, f"Refused: {exc}")
        return redirect(reverse("correspondence_staff:application", args=[public_ref]))
    return render(request, "correspondence/staff/preview.html", {"draft": draft, "application": application})


@require_POST
@staff_page
def confirm_message(request, public_id):
    draft = get_object_or_404(StaffMessageDraft.objects.select_related("application"), public_id=public_id)
    return act(request, reverse("correspondence_staff:application", args=[draft.application.public_ref]),
               lambda: staff_actions.confirm_staff_message(draft.pk, request.POST.get("digest", ""), request.user),
               "Staff message confirmed and queued.")

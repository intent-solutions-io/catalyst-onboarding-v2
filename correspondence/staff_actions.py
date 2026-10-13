"""Named staff services (016 section F; owner decisions D-28 A-3, D-30). 2B.1 holds the decision on a send
whose outcome is unknown, exhausted, blocked, rejected or refused (016 A6, permission
`decide_uncertain_send`, decision-maker role). Later tasks add their services here.

Every decision is one transaction (application, then the message, then its actions; 016 section 5),
writes the immutable `StaffItemResolution` and an event, and **never rewrites an attempt**: an `unknown`
attempt stays `unknown` whatever staff decide.

- `abandon`: the message becomes `operator_abandoned` ("operator abandoned further attempts"); any queued or
  held send is cancelled.
- `authorize_resend`: a new attempt series of the same frozen message, same Message-ID, so the duplicate
  risk is explicit; any held or queued send of an earlier series is cancelled in the same transaction.
  Refused after a permanent rejection, and when the verified address no longer matches.
- `revise`: a new `ApprovedMessage` re-rendered from the current approved template version, superseding
  this one, with a new identity and Message-ID; the old message becomes `superseded`.
"""

from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Now

from applications.models import ApplicationEvent
from workflow.models import PendingAction

from .models import ApprovedMessage, ApprovedMessageQuestion, OutboundMessage, Question, StaffItem
from .outbound import (
    DECIDABLE,
    SEND,
    QUESTION_TEMPLATE,
    Refused,
    _freeze,
    _lock_application,
    actor_ref,
    current_template_version,
    enqueue_send,
    require,
    verified_address,
)
from .inbound import enqueue_pass
from .models import MailboxCursor
from .rendering import TemplateRefused
from .staff_items import event, resolve_item

Disposition = ApprovedMessage.Disposition
Status = PendingAction.Status
DECISIONS = ("abandon", "authorize_resend", "revise")
CLOSED = (Disposition.ACCEPTED_BY_SERVER, Disposition.ACCEPTED_BY_EVIDENCE, Disposition.SUPERSEDED,
          Disposition.OPERATOR_ABANDONED)


def _cancel_open_sends(message, reason: str) -> list[int]:
    """Queued or held sends of this message become cancelled. Uncertain and finished actions are history
    and are never touched."""
    actions = PendingAction.objects.filter(kind=SEND, input_ref=str(message.send_ref), status__in=(Status.QUEUED, Status.HELD))
    ids = list(actions.values_list("pk", flat=True))
    actions.update(status=Status.CANCELLED, last_error=reason, completed_at=Now(), updated_at=Now())
    return ids


def decide_uncertain_send(message_id: int, user, decision: str, note: str = "") -> ApprovedMessage:
    require(user, "decide_uncertain_send")
    if decision not in DECISIONS:
        raise Refused("unknown_decision")
    actor = actor_ref(user)
    message = ApprovedMessage.objects.get(pk=message_id)
    with transaction.atomic():
        application = _lock_application(message.application_id)
        questions = list(Question.objects.select_for_update(of=("self",))
                         .filter(message_links__approved_message=message).order_by("id"))
        message = ApprovedMessage.objects.select_for_update(of=("self",)).get(pk=message_id)
        items = list(StaffItem.objects.select_for_update(of=("self",)).filter(
            approved_message=message, status=StaffItem.Status.OPEN, reason_code__in=DECIDABLE).order_by("id"))
        if not items:
            raise Refused("nothing_to_decide")
        if message.disposition in CLOSED:
            raise Refused("message_already_closed")
        unknown = OutboundMessage.objects.filter(approved_message=message, status=OutboundMessage.Status.UNKNOWN).exists()
        effects = {"send_ref": str(message.send_ref), "decision": decision, "unknown_attempts": unknown}

        if decision == "abandon":
            effects["cancelled_actions"] = _cancel_open_sends(message, "operator_abandoned")
            ApprovedMessage.objects.filter(pk=message.pk).update(
                disposition=Disposition.OPERATOR_ABANDONED, disposition_at=Now(), disposition_by=actor)
            result = message

        elif decision == "authorize_resend":
            if message.disposition == Disposition.REJECTED_PERMANENT:
                raise Refused("permanent_rejection_needs_a_revised_message")
            if verified_address(application) != message.recipient:
                raise Refused("recipient_no_longer_verified")
            if any(q.status == Question.Status.WITHDRAWN for q in questions):
                raise Refused("question_withdrawn")
            effects["cancelled_actions"] = _cancel_open_sends(message, "superseded_by_resend")
            series = (OutboundMessage.objects.filter(approved_message=message).aggregate(s=Max("attempt_series"))["s"] or 0) + 1
            existing = PendingAction.objects.filter(kind=SEND, input_ref=str(message.send_ref)).count()
            series = max(series, existing)  # a series that never reached an attempt row still owns its key
            ApprovedMessage.objects.filter(pk=message.pk).update(
                disposition=Disposition.ACTIVE, disposition_at=Now(), disposition_by=actor)
            effects["series"] = series
            effects["action"] = enqueue_send(message, series).pk
            result = message

        else:  # revise
            if verified_address(application) != message.recipient:
                raise Refused("recipient_no_longer_verified")
            if message.kind != ApprovedMessage.Kind.QUESTION or not questions:
                raise Refused("revision_not_supported_for_this_kind")
            if any(q.status == Question.Status.WITHDRAWN for q in questions):
                raise Refused("question_withdrawn")
            version = current_template_version(QUESTION_TEMPLATE)
            if version is None:
                raise Refused("no_approved_template_version")
            effects["cancelled_actions"] = _cancel_open_sends(message, "superseded_by_revision")
            ApprovedMessage.objects.filter(pk=message.pk).update(
                disposition=Disposition.SUPERSEDED, disposition_at=Now(), disposition_by=actor)
            try:
                revised = _freeze(application, message.kind, message.recipient, version,
                                  {"display_name": application.display_name, "question_text": questions[0].text},
                                  actor, ApprovedMessage.Authority.STAFF, supersedes=message)
            except TemplateRefused as exc:
                raise Refused(str(exc)) from None
            for question in questions:
                ApprovedMessageQuestion.objects.create(approved_message=revised, question=question,
                                                       purpose=ApprovedMessageQuestion.Purpose.REVISION)
            enqueue_send(revised, 0)
            effects["revised_send_ref"] = str(revised.send_ref)
            result = revised

        for item in items:
            resolve_item(item, code=decision, actor_ref=actor, note=note, effects=effects)
        event(application, f"message_{decision}", effects, actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    result.refresh_from_db()
    return result


def restart_collector(cursor_id: int, user, note: str = ""):
    """016 B1 and F: only `restart_collector` (decision-maker) resumes a blocked cursor; it is separate from
    ordinary retry. Resolves the cursor's open items with the immutable resolution record."""
    require(user, "restart_collector")
    actor = actor_ref(user)
    with transaction.atomic():
        cursor = MailboxCursor.objects.select_for_update(of=("self",)).get(pk=cursor_id)
        if cursor.state != MailboxCursor.State.BLOCKED:
            raise Refused("cursor_not_blocked")
        state = MailboxCursor.State.RECOVERY if cursor.uidvalidity is None else MailboxCursor.State.OK
        MailboxCursor.objects.filter(pk=cursor.pk).update(state=state, blocked_reason="", consecutive_failures=0,
                                                          pass_number=cursor.pass_number + 1)
        enqueue_pass(cursor, cursor.pass_number + 1)
        for item in StaffItem.objects.select_for_update(of=("self",)).filter(
                status=StaffItem.Status.OPEN, dedupe_key=f"cursor:{cursor.public_id}"):
            resolve_item(item, code="restart_collector", actor_ref=actor, note=note,
                         effects={"cursor": str(cursor.public_id), "previous_reason": cursor.blocked_reason})
    cursor.refresh_from_db()
    return cursor

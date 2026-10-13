"""Reply processing and staff resolution (016 section 4 D and C4, F; P2 task 2B.3; owner decisions D-27, D-28,
D-30, D-31). Synthetic only; no model call anywhere in P2.

- `ProcessReply` (`process_reply`, automated, so a pause holds it; internal and idempotent, D-27):
  D1, deterministic classification. A bounce for our message and the verified recipient: a hard bounce
  (5.x.x) pauses automation and opens `hard_bounce`; a soft bounce is recorded only; anything else is recorded
  with no effect. An automatic message is `automated_reply`, satisfies nothing, never suppresses or pauses on
  its own, and counts toward the loop threshold, which pauses automation and opens `loop_threshold`.
  D2, a person's trusted reply: one held `interpret_reply` per pending question (never claimed; P3 owns the
  interpreter) and `reply_needs_review` for staff.
- `confirm_question_outcome` (D3) and `close_reply_without_outcome` (D4): staff decide; a reply never
  satisfies a question by itself, and P2 changes no application stage (ADR-13).
- `resolve_exception` (C4, F): one allow-list of resolution codes per reason, under the permission the reason
  needs. Associating a message links it to an application and nothing more: it never changes the verified
  identity, the recipient, adopted evidence or the stage. Every resolution writes the immutable record, with
  or without an application.
"""

import re
from datetime import timedelta
from typing import Protocol

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from .inbound import ANSWERABLE, PROCESS_REPLY, _queue_processing, refresh_question_status
from .models import InboundMessage, Question, QuestionReplyLink, StaffItem
from .outbound import Refused, actor_ref, require, verified_address
from .staff_items import event, open_item, resolve_item

Status = PendingAction.Status
Inbound = InboundMessage.Status
INTERPRET_REPLY = "interpret_reply"
OUTCOMES = {"satisfied": "satisfied", "partial": "partial", "not_addressed": "not_addressed"}
QUOTE_STRIP_VERSION = 1

# 016 F, reason-to-permission table (as amended in 2B.2 and 2B.3).
IDENTITY_REASONS = {"unmatched", "reply_unverified", "reply_auth_failed", "sender_mismatch",
                    "repeat_after_verification", "newer_unverified_version"}
RESOLUTIONS = {
    "unmatched": {"dismiss": "resolve_exception", "associate": "resolve_identity_exception"},
    "reply_unverified": {"associate": "resolve_identity_exception", "dismiss": "resolve_identity_exception",
                         "mark_spoof": "resolve_identity_exception"},
    "reply_auth_failed": {"associate": "resolve_identity_exception", "mark_spoof": "resolve_identity_exception",
                          "dismiss": "resolve_identity_exception"},
    "sender_mismatch": {"mark_spoof": "resolve_identity_exception", "dismiss": "resolve_identity_exception"},
    "repeat_after_verification": {"acknowledge": "resolve_identity_exception"},
    "newer_unverified_version": {"acknowledge": "resolve_identity_exception"},
}
ACKNOWLEDGE_ONLY = {"processing_error", "message_id_conflict", "mailbox_uidvalidity_changed", "collector_stale",
                    "filed_copy_failed", "inbound_oversize", "application_closed", "collector_pass_failed",
                    "mailbox_history_out_of_scope", "hard_bounce", "loop_threshold"}


# --- the typed P3 interface (016 section 1); not implemented in P2 ---------------------------------------------

class ReplyInterpreter(Protocol):
    """P3 implements this; P2 only holds `interpret_reply` actions. Input: the inbound message's public id, the
    ids of the related questions still open (never a withdrawn one), the derivative text and its quote-stripped
    view (untrusted data). Output per question: `satisfied`, `partial` or `not_addressed`, with cited spans as
    offsets into the derivative text. Even then, staff confirm while the staff-confirmation default holds."""

    def interpret(self, message_id: str, question_ids: list[str], text: str, stripped: str) -> dict[str, dict]: ...


_ATTRIBUTION = re.compile(r"^\s*(on .{1,200} wrote:|-{2,}\s*original message\s*-{2,}|from: .+)\s*$", re.I)


def strip_quotes(text: str) -> str:
    """Quote-stripped view, version QUOTE_STRIP_VERSION (TEST-P2-44): lines quoted with '>' are dropped, and
    everything from a reply attribution line ("On ... wrote:", "-----Original Message-----") is dropped.
    The full derivative is always kept; this is only a view for P3."""
    kept = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if _ATTRIBUTION.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


# --- the handler ------------------------------------------------------------------------------------------------

def _pause(application, reason: str) -> None:
    if not AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
        AutomationPause.objects.create(subject_type="application", subject_id=application.public_ref, reason=reason,
                                       actor_ref="system:correspondence")
        event(application, "automation_paused", {"reason": reason})


class ProcessReply:
    kind = PROCESS_REPLY
    redeliverable = True  # internal and idempotent (D-27): it sends nothing
    automated = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        event(Application.objects.filter(public_ref=claim.subject_id).first(), kind, data,
              actor_ref=f"pending_action:{claim.id}")

    def run(self, claim) -> None:
        def write():
            application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
            message = InboundMessage.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref).first()
            if application is None or message is None or message.application_id != application.pk:
                return
            if message.status != Inbound.AWAITING_PROCESSING:
                return  # already decided (by staff or an earlier run): nothing to do
            if message.classification == "bounce":
                self._bounce(application, message)
            elif message.classification == "automatic":
                self._automatic(application, message)
            else:
                self._person(application, message)
        ledger.finish(claim, self, status=Status.DONE, write=write)

    def _bounce(self, application, message) -> None:
        markers = message.auto_markers or {}
        status = str(markers.get("dsn_status", ""))
        recipient = str(markers.get("dsn_final_recipient", "")).strip().lower()
        ours = message.approved_message_id is not None and recipient == (verified_address(application) or "").lower()
        InboundMessage.objects.filter(pk=message.pk).update(status=Inbound.PROCESSED, processed_at=Now())
        if ours and status.startswith("5"):
            _pause(application, "hard_bounce")
            open_item("hard_bounce", f"inbound:{message.public_id}", application=application)
        event(application, "bounce_recorded", {"message": str(message.public_id), "hard": ours and status.startswith("5"),
                                               "counted": ours})

    def _automatic(self, application, message) -> None:
        InboundMessage.objects.filter(pk=message.pk).update(status=Inbound.AUTOMATED_REPLY, processed_at=Now())
        for link in QuestionReplyLink.objects.filter(inbound_message=message, state="pending"):
            QuestionReplyLink.objects.filter(pk=link.pk).update(state="ignored_automated", updated_at=Now())
            refresh_question_status(link.question)
        window = Now() - timedelta(seconds=settings.CATALYST_MAIL_LOOP_WINDOW_SECONDS)
        recent = InboundMessage.objects.filter(application=application, classification="automatic",
                                               received_at__gte=window).count()
        if recent >= settings.CATALYST_MAIL_LOOP_THRESHOLD:
            _pause(application, "loop_threshold")
            open_item("loop_threshold", f"application:{application.public_ref}", application=application)

    def _person(self, application, message) -> None:
        for link in QuestionReplyLink.objects.filter(inbound_message=message, state="pending").select_related("question"):
            try:
                with transaction.atomic():
                    PendingAction.objects.create(
                        kind=INTERPRET_REPLY, subject_type="application", subject_id=application.public_ref,
                        input_ref=f"{message.public_id}:{link.question.public_id}", status=Status.HELD,
                        idempotency_key=f"{INTERPRET_REPLY}:{message.public_id}:{link.question.public_id}")
            except IntegrityError:
                pass  # already held by an earlier run of this idempotent action
        open_item("reply_needs_review", f"inbound:{message.public_id}", application=application)


# --- staff services ---------------------------------------------------------------------------------------------

def _cancel_interpretation(message) -> None:
    PendingAction.objects.filter(kind=INTERPRET_REPLY, input_ref__startswith=f"{message.public_id}:",
                                 status=Status.HELD).update(status=Status.CANCELLED, last_error="decided_by_staff",
                                                            completed_at=Now(), updated_at=Now())


def _review_items(message):
    return StaffItem.objects.select_for_update(of=("self",)).filter(
        status=StaffItem.Status.OPEN, dedupe_key=f"inbound:{message.public_id}")


def confirm_question_outcome(message_id: int, outcomes: dict, user, note: str = "") -> InboundMessage:
    """D3: `outcomes` maps each pending question's id to `satisfied`, `partial` or `not_addressed`."""
    require(user, "confirm_question_outcome")
    actor = actor_ref(user)
    message = InboundMessage.objects.get(pk=message_id)
    if message.application_id is None:
        raise Refused("message_has_no_application")
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=message.application_id)
        links = list(QuestionReplyLink.objects.select_related("question").filter(inbound_message_id=message_id, state="pending")
                     .order_by("question_id"))
        list(Question.objects.select_for_update(of=("self",)).filter(pk__in=[l.question_id for l in links]).order_by("id"))
        if not InboundMessage.objects.filter(pk=message_id, status=Inbound.AWAITING_PROCESSING).update(
                status=Inbound.PROCESSED, processed_at=Now()):
            raise Refused("reply_already_decided")  # a concurrent decision or process_reply won (TEST-P2-32)
        if {l.question_id for l in links} != set(outcomes) or not all(o in OUTCOMES for o in outcomes.values()):
            raise Refused("an_outcome_is_needed_for_every_pending_question")
        for link in links:
            QuestionReplyLink.objects.filter(pk=link.pk).update(state="applied", outcome=OUTCOMES[outcomes[link.question_id]],
                                                                actor_ref=actor, updated_at=Now())
            refresh_question_status(Question.objects.get(pk=link.question_id))
        _cancel_interpretation(message)
        for item in _review_items(message):
            resolve_item(item, code="confirmed", actor_ref=actor, note=note,
                         effects={"outcomes": {str(Question.objects.get(pk=q).public_id): o for q, o in outcomes.items()}})
        event(application, "question_outcomes_confirmed", {"message": str(message.public_id), "count": len(links)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    message.refresh_from_db()
    return message


def close_reply_without_outcome(message_id: int, user, reason: str = "no_question_outcome", note: str = "") -> InboundMessage:
    """D4: a reply with no pending link left (for example, all its questions were withdrawn) or with no
    questions at all. No question changes."""
    require(user, "confirm_question_outcome")
    actor = actor_ref(user)
    message = InboundMessage.objects.get(pk=message_id)
    with transaction.atomic():
        if message.application_id is not None:
            Application.objects.select_for_update(of=("self",)).get(pk=message.application_id)
        if QuestionReplyLink.objects.filter(inbound_message_id=message_id, state="pending").exists():
            raise Refused("pending_questions_need_outcomes")
        if not InboundMessage.objects.filter(pk=message_id, status=Inbound.AWAITING_PROCESSING).update(
                status=Inbound.PROCESSED, processed_at=Now()):
            raise Refused("reply_already_decided")
        _cancel_interpretation(message)
        for item in _review_items(message):
            resolve_item(item, code="closed_without_outcome", actor_ref=actor, note=note, effects={"reason": reason[:64]})
    message.refresh_from_db()
    return message


def resolve_exception(item_id: int, code: str, user, note: str = "", target_application_id: int | None = None) -> StaffItem:
    """C4 and F: the permission comes from the reason and the code; staff never change identity here."""
    item = StaffItem.objects.get(pk=item_id)
    if item.reason_code in RESOLUTIONS:
        permission = RESOLUTIONS[item.reason_code].get(code)
    elif item.reason_code in ACKNOWLEDGE_ONLY and code == "acknowledge":
        permission = "resolve_exception"
    else:
        permission = None
    if permission is None:
        raise Refused("resolution_not_allowed_for_this_reason")
    require(user, permission)
    actor = actor_ref(user)
    with transaction.atomic():
        lock_app = item.application_id or target_application_id
        if lock_app is not None:
            Application.objects.select_for_update(of=("self",)).get(pk=lock_app)
        item = StaffItem.objects.select_for_update(of=("self",)).get(pk=item_id)
        if item.status != StaffItem.Status.OPEN:
            raise Refused("item_already_resolved")
        message = None
        if item.dedupe_key.startswith("inbound:"):
            message = InboundMessage.objects.select_for_update(of=("self",)).filter(public_id=item.dedupe_key.split(":", 1)[1]).first()
        effects = {"reason": item.reason_code}
        if code == "associate":
            effects.update(_associate_by_staff(message, item, target_application_id, actor))
        elif code in ("dismiss", "mark_spoof") and message is not None and message.status == Inbound.EXCEPTION:
            InboundMessage.objects.filter(pk=message.pk).update(status=Inbound.PROCESSED, processed_at=Now())
            effects["message"] = str(message.public_id)
        resolve_item(item, code=code, actor_ref=actor, note=note, effects=effects)
    item.refresh_from_db()
    return item


def _associate_by_staff(message, item, target_application_id, actor) -> dict:
    """Link a message to an application and let it behave as trusted for this message only (016 C3, C4). It
    never changes the verified address, the recipient, an adoption or the stage."""
    if message is None:
        raise Refused("nothing_to_associate")
    application_id = message.application_id or target_application_id
    if application_id is None:
        raise Refused("a_target_application_is_needed")
    application = Application.objects.get(pk=application_id)
    InboundMessage.objects.filter(pk=message.pk).update(application_id=application.pk, status=Inbound.AWAITING_PROCESSING,
                                                        trust_decision="staff_associated")
    if message.approved_message_id is not None:
        for question in Question.objects.select_for_update(of=("self",)).filter(
                message_links__approved_message_id=message.approved_message_id).order_by("id"):
            if question.status in ANSWERABLE:
                QuestionReplyLink.objects.get_or_create(question=question, inbound_message=message, defaults={"state": "pending"})
                refresh_question_status(question)
    if not PendingAction.objects.filter(idempotency_key=f"{PROCESS_REPLY}:{message.public_id}").exists():
        message.refresh_from_db()
        _queue_processing(message, application)
    else:
        PendingAction.objects.filter(idempotency_key=f"{PROCESS_REPLY}:{message.public_id}").update(
            status=Status.QUEUED, due_at=Now(), attempts=0, last_error="", completed_at=None, updated_at=Now())
    return {"message": str(message.public_id), "application": str(application.public_ref), "actor": actor}

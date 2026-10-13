"""Named staff services (016 section F; owner decisions D-28 A-3, D-30). 2B.1 holds the decision on a send
whose outcome is unknown, exhausted, blocked, rejected or refused (016 A6, permission
`decide_uncertain_send`, decision-maker role); 2B.2 the collector restart; 2B.4 pause and resume (F, E4),
question withdrawal (3.3, A-8) and staff messages with preview and digest-checked confirmation (3.4, A-5).

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

import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Now

from applications.links import CONFIRM_PATH
from applications.models import TERMINAL_STAGES, ApplicationEvent
from workflow.models import AutomationPause, PendingAction

from .models import (
    ApprovedMessage,
    ApprovedMessageQuestion,
    OutboundMessage,
    Question,
    QuestionReplyLink,
    StaffItem,
    StaffMessageDraft,
)
from .outbound import (
    DECIDABLE,
    SEND_KINDS,
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
from . import mime
from .inbound import enqueue_pass, refresh_question_status
from .models import MailboxCursor
from .rendering import TemplateRefused, canonical_digest
from .scheduling import reschedule_on_resume
from .staff_items import clean_note, event, resolve_item

Disposition = ApprovedMessage.Disposition
Status = PendingAction.Status
DECISIONS = ("abandon", "authorize_resend", "revise")
CLOSED = (Disposition.ACCEPTED_BY_SERVER, Disposition.ACCEPTED_BY_EVIDENCE, Disposition.SUPERSEDED,
          Disposition.OPERATOR_ABANDONED)


def _cancel_open_sends(message, reason: str) -> list[int]:
    """Queued or held sends of this message become cancelled. Uncertain and finished actions are history
    and are never touched."""
    actions = PendingAction.objects.filter(kind__in=SEND_KINDS, input_ref=str(message.send_ref), status__in=(Status.QUEUED, Status.HELD))
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
            existing = PendingAction.objects.filter(kind__in=SEND_KINDS, input_ref=str(message.send_ref)).count()
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


# --- 2B.4: pause, resume, withdrawal and staff messages (016 F, E4, 3.3, 3.4) -------------------------------

PAUSE_REASON_MIN = 10
WITHDRAW_REASONS = ("no_longer_needed", "asked_in_error", "replaced_by_new_question", "no_response")
SUBJECT_LIMIT, BODY_LIMIT = 200, 5000
# Defence in depth, never authorization (016 3.4 step 4): refuses obvious credentials, not every secret.
_CREDENTIAL = re.compile(r"(?i)(password|passwd|api[_-]?key|secret|token)\s*[:=]|\b[A-Za-z0-9+/_-]{40,}\b")


def _has_control(text: str) -> bool:
    """Any control or format character except newline and tab (the categories the `visible` filter marks)."""
    return any(ch not in "\n\t" and unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp") for ch in text)


def _pause_row(application):
    return AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref)


def pause(application_id: int, user, reason: str) -> AutomationPause:
    """F: stop every automated kind for one application (the ledger skips them, and each handler re-checks).
    Pausing an application that is already paused changes nothing."""
    require(user, "pause_automation")
    reason = clean_note(reason)
    if len(reason) < PAUSE_REASON_MIN:
        raise Refused("pause_reason_too_short")
    actor = actor_ref(user)
    with transaction.atomic():
        application = _lock_application(application_id)
        existing = _pause_row(application).first()
        if existing is not None:
            event(application, "automation_pause_requested_while_paused", {"reason": reason},
                  actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
            return existing
        row = AutomationPause.objects.create(subject_type="application", subject_id=application.public_ref,
                                             reason=reason, actor_ref=actor)
        # The reason lives in the append-only history too: resume deletes the pause row (2B.4 review).
        event(application, "automation_paused", {"by": "staff", "reason": reason},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    return row


def resume(application_id: int, user, note: str = "") -> int:
    """E4: delete the pause and reschedule the reminders that fell due, in one transaction. Question statuses,
    counts and held reminders are unchanged; nothing is sent as catch-up. Returns how many were rescheduled."""
    require(user, "resume_automation")
    note = clean_note(note)
    actor = actor_ref(user)
    with transaction.atomic():
        application = _lock_application(application_id)
        row = _pause_row(application).first()
        if row is None:
            raise Refused("not_paused")
        prior = {"paused_by": row.actor_ref, "paused_at": row.created_at.isoformat(), "pause_reason": row.reason}
        _pause_row(application).delete()
        moved = reschedule_on_resume(application)
        event(application, "automation_resumed", {**prior, "rescheduled": moved, "note": note},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    return moved


def withdraw_question(question_id: int, user, reason_code: str, note: str = "") -> Question:
    """3.3 (A-8): an explicit staff disposition, never an answer and never reopened. One transaction: the
    application, the question, then its links and actions."""
    require(user, "withdraw_question")
    if reason_code not in WITHDRAW_REASONS:
        raise Refused("unknown_withdrawal_reason")
    note = clean_note(note)
    actor = actor_ref(user)
    question = Question.objects.get(pk=question_id)
    with transaction.atomic():
        application = _lock_application(question.application_id)
        question = Question.objects.select_for_update(of=("self",)).get(pk=question_id)
        if question.status == Question.Status.WITHDRAWN:
            return question  # withdrawing twice does nothing more
        if question.status == Question.Status.SATISFIED:
            raise Refused("question_already_satisfied")
        Question.objects.filter(pk=question.pk).update(
            status=Question.Status.WITHDRAWN, withdrawn_by=actor, withdrawn_reason=f"{reason_code}: {note}"[:200].rstrip(": "),
            withdrawn_at=Now(), updated_at=Now())
        question.refresh_from_db()
        voided = list(QuestionReplyLink.objects.filter(question=question, state="pending").values_list("inbound_message_id", flat=True))
        QuestionReplyLink.objects.filter(question=question, state="pending").update(state="void_withdrawn", actor_ref=actor,
                                                                                   updated_at=Now())
        refresh_question_status(question)  # E3: its queued and held reminders and escalation are cancelled
        held = PendingAction.objects.filter(kind="interpret_reply", status=Status.HELD,
                                            idempotency_key__endswith=f":{question.public_id}")
        cancelled_interpretations = held.update(status=Status.CANCELLED, last_error="question_withdrawn",
                                                completed_at=Now(), updated_at=Now())
        resolved = []
        for item in StaffItem.objects.select_for_update(of=("self",)).filter(status=StaffItem.Status.OPEN, question_id=question.pk):
            resolve_item(item, code="question_withdrawn", actor_ref=actor, note=note,
                         effects={"question": str(question.public_id)})
            resolved.append(str(item.public_id))
        # The reply itself is never dropped: its reply_needs_review item stays open for D3 or D4.
        event(application, "question_withdrawn", {
            "question": str(question.public_id), "reason": reason_code, "voided_links": len(voided),
            "cancelled_interpretations": cancelled_interpretations, "resolved_items": resolved},
            actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    question.refresh_from_db()
    return question


def _check_staff_content(subject: str, body: str) -> None:
    if not subject.strip() or not body.strip():
        raise Refused("subject_and_body_are_required")
    if len(subject) > SUBJECT_LIMIT or len(body) > BODY_LIMIT:
        raise Refused("message_too_long")
    if "\n" in subject or "\t" in subject or _has_control(subject) or _has_control(body):
        raise Refused("control_characters_refused")
    # The same decoding as inbound redaction (percent-encoding, HTML references, any case) finds a link.
    if mime.redact(body)[1] or mime.redact(subject)[1] or CONFIRM_PATH in body.lower():
        raise Refused("confirmation_link_refused")
    if _CREDENTIAL.search(body) or _CREDENTIAL.search(subject):
        raise Refused("credential_like_text_refused")


def preview_staff_message(application_id: int, user, subject: str, body: str) -> StaffMessageDraft:
    """3.4 steps 1 and 2: the exact content and recipient (the verified address, never typed) as a new draft."""
    require(user, "send_staff_message")
    body = body.replace("\r\n", "\n")
    _check_staff_content(subject, body)
    with transaction.atomic():
        application = _lock_application(application_id)
        if application.stage in TERMINAL_STAGES:
            raise Refused("application_closed")
        recipient = verified_address(application)
        if recipient is None:
            raise Refused("contact_not_verified")
        return StaffMessageDraft.objects.create(application=application, author=actor_ref(user), subject=subject,
                                                body=body, recipient=recipient,
                                                content_sha256=canonical_digest(subject, body))


def confirm_staff_message(draft_id: int, digest: str, user) -> ApprovedMessage:
    """3.4 step 3: the same user confirms the exact draft. Every check is repeated under the application lock;
    any mismatch refuses with nothing enqueued."""
    require(user, "send_staff_message")
    actor = actor_ref(user)
    draft = StaffMessageDraft.objects.get(pk=draft_id)
    with transaction.atomic():
        application = _lock_application(draft.application_id)
        if draft.author != actor:
            raise Refused("only_the_author_confirms")
        if StaffMessageDraft.objects.filter(pk=draft.pk, created_at__lt=Now() - timedelta(
                seconds=settings.CATALYST_STAFF_DRAFT_TTL_SECONDS)).exists():
            raise Refused("preview_expired")  # an old preview is never sent: preview again (2B.4 review)
        if digest != draft.content_sha256 or canonical_digest(draft.subject, draft.body) != draft.content_sha256:
            raise Refused("digest_mismatch")
        if application.stage in TERMINAL_STAGES:
            raise Refused("application_closed")
        if verified_address(application) != draft.recipient:
            raise Refused("recipient_no_longer_verified")
        if ApprovedMessage.objects.filter(staff_draft=draft).exists():
            raise Refused("draft_already_confirmed")
        _check_staff_content(draft.subject, draft.body)
        message = ApprovedMessage.objects.create(
            kind=ApprovedMessage.Kind.STAFF_MESSAGE, application=application, recipient=draft.recipient,
            frozen_subject=draft.subject, frozen_body=draft.body, content_sha256=draft.content_sha256,
            authorized_by=actor, authority=ApprovedMessage.Authority.STAFF, staff_draft=draft)
        enqueue_send(message, 0)  # its own non-automated kind: it runs while paused (M5, J-09)
        event(application, "staff_message_confirmed", {"send_ref": str(message.send_ref), "draft": str(draft.public_id)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    return message

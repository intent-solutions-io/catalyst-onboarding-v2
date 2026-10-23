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

from .questions import answers_settled, sent_text
from .models import (
    ApprovedMessage,
    ApprovedMessageQuestion,
    InboundMessage,
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
from .common import can
from .inbound import enqueue_pass, refresh_question_status
from .models import MailboxCursor
from .rendering import TemplateRefused, canonical_digest
from .scheduling import reschedule_on_resume
from .staff_items import clean_note, event, hard_bounce_open, resolve_item

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

        elif hard_bounce_open(application):
            raise Refused("hard_bounce_open")  # a resend or a revision is no bypass (9kg.3)

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
                                  {"display_name": application.display_name, "question_text": sent_text(questions[0])},
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


VERIFICATION_RESENT = "verification_resent"


def resend_verification(application_id: int, user, note: str = "") -> int:
    """9kg.50 (029 section 5.2): staff queue the verification message again for an applicant who has no working link
    (a failed or cancelled send, an expired link). Under the staff-send permission, one locked transaction: the
    application must be open with contact unverified, no hard bounce may be open (every send path, 9kg.3), and the
    resends are bounded (CATALYST_VERIFICATION_RESEND_LIMIT). The active challenge is superseded and a new one is
    issued through the intake path itself (applications.services.reissue_challenge), so the message, lifetime and
    handler are the ones issuance uses. Returns the number of this resend. The event names no challenge or token."""
    from applications.models import OPEN_STAGES
    from applications.services import reissue_challenge

    require(user, "send_staff_message")
    note = clean_note(note)
    actor = actor_ref(user)
    with transaction.atomic():
        application = _lock_application(application_id)
        if application.contact_verified_at is not None:
            raise Refused("contact_already_verified")
        if application.stage not in OPEN_STAGES:
            raise Refused("application_closed")
        if hard_bounce_open(application):
            raise Refused("hard_bounce_open")
        number = ApplicationEvent.objects.filter(application=application, kind=VERIFICATION_RESENT).count() + 1
        if number > settings.CATALYST_VERIFICATION_RESEND_LIMIT:
            raise Refused("resend_limit_reached")
        reissue_challenge(application)
        event(application, VERIFICATION_RESENT, {"resend_number": number, "note": note},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    return number


def usable_verification_link(application) -> bool:
    """An active, unexpired challenge whose send is queued, running or done: the applicant may still have a working
    link, so a resend duplicates it (the screen says so; security review of PR #87)."""
    from applications.services import _reusable
    from applications.staff import active_challenge

    challenge = active_challenge(application)
    return challenge is not None and _reusable(challenge)


def resends_used(application) -> int:
    return ApplicationEvent.objects.filter(application=application, kind=VERIFICATION_RESENT).count()


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


# 9kg.2: the staff items whose cause set a system safety pause (each pause's reason is its item's reason code). A
# pause is never resumed while one of them is open, whoever paused first, so a later system cause hidden behind an
# earlier staff pause is not cleared by that staff resume. Resuming never resolves these items: identity, delivery
# and agreement-integrity blocks each keep their own resolution path.
PAUSE_CAUSES = ("hard_bounce", "loop_threshold", "agreement_declined", "agreement_cancelled_at_provider",
                "agreement_expired")
SYSTEM_RESUME_REASON_MIN = 10


def is_system_pause(row) -> bool:
    return row.actor_ref == "system" or row.actor_ref.startswith("system:")


def resume(application_id: int, user, note: str = "") -> int:
    """E4: delete the pause and reschedule the reminders that fell due, in one transaction. Question statuses,
    counts and held reminders are unchanged; nothing is sent as catch-up. Returns how many were rescheduled.

    9kg.2: a staff pause is resumed by anyone with `resume_automation`. A system safety pause (actor `system...`)
    also needs decision-maker review (`decide_uncertain_send`) and a reason. Either way, the cause must be addressed
    first: no open `PAUSE_CAUSES` item for the application."""
    require(user, "resume_automation")
    note = clean_note(note)
    actor = actor_ref(user)
    refused = None
    with transaction.atomic():
        application = _lock_application(application_id)
        row = _pause_row(application).first()
        if row is None:
            raise Refused("not_paused")
        system = is_system_pause(row)
        open_causes = sorted(set(StaffItem.objects.filter(application=application, reason_code__in=PAUSE_CAUSES,
                                                          status=StaffItem.Status.OPEN)
                                 .values_list("reason_code", flat=True)))
        if system and not can(user, "decide_uncertain_send"):
            refused = "decision_maker_review_required"
        elif system and len(note) < SYSTEM_RESUME_REASON_MIN:
            refused = "reason_needed"
        elif open_causes:
            refused = "pause_cause_open"
        if refused is None:
            prior = {"paused_by": row.actor_ref, "paused_at": row.created_at.isoformat(), "pause_reason": row.reason,
                     "system_pause": system}
            _pause_row(application).delete()
            moved = reschedule_on_resume(application)
            event(application, "automation_resumed", {**prior, "rescheduled": moved, "note": note},
                  actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    if refused is not None:
        # 9kg.2: a refused resume is audited too (who, why, the causes still open), in its own transaction.
        with transaction.atomic():
            event(_lock_application(application_id), "automation_resume_refused",
                  {"code": refused, "system_pause": system, "open_causes": open_causes},
                  actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
        raise Refused(refused)
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
        # The reply itself is never dropped: its reply_needs_review item stays open for D3 or D4. Queued P3
        # message-level interpretation of those replies is cancelled; a running one re-checks its questions.
        still_asked = set(QuestionReplyLink.objects.filter(inbound_message_id__in=voided, state="pending").values_list(
            "inbound_message_id", flat=True))  # a reply still answering another question keeps its interpretation
        for message_ref in InboundMessage.objects.filter(pk__in=set(voided) - still_asked).values_list("public_id", flat=True):
            cancelled_interpretations += PendingAction.objects.filter(
                kind="interpret_message", status=Status.QUEUED, input_ref__startswith=f"{message_ref}:").update(
                status=Status.CANCELLED, last_error="question_withdrawn", completed_at=Now(), updated_at=Now())
        event(application, "question_withdrawn", {
            "question": str(question.public_id), "reason": reason_code, "voided_links": len(voided),
            "cancelled_interpretations": cancelled_interpretations, "resolved_items": resolved},
            actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
        answers_settled(application)  # P3 3B.3: the last open question withdrawn may end a clarification round
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
        if hard_bounce_open(application):
            raise Refused("hard_bounce_open")  # 9kg.3
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

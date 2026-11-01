"""9kg.33: correspondence effects after a restore (config.post_restore; 029 section 6.2).

**From the effect journal, inside the post-restore transaction (`replay`):**

- `automation_pause`: the last journaled state per application wins; a restored row older than a journaled resume
  is removed (with the reminders spread as a resume does), a journaled pause with no restored row is recreated.
  (A database-assigned version per key for replay ordering is deferred; until then the entry time orders.)
- `staff_item_resolved`: a restored item that is open again is resolved with the journaled code; the note stays
  in the database, so the replayed resolution says where it came from.
- `question_withdrawn`: a restored question that is live again is withdrawn again through the service (a `prepare`
  entry counts: a withdrawal re-applied is safe).
- `reply_link_outcome`: a restored link pending again takes the journaled outcome and the question status follows.
- `uncertain_send_decided`: `abandon` is re-applied to the restored message (its open sends are cancelled).
  `authorize_resend` and `revise` cannot be re-applied blindly, because the resend or the revised message may have
  left after the backup: each opens a blocking item (`restore_effect_resend_unverified`,
  `restore_effect_revise_unverified`) unless the Sent read finds the copy (a revised message whose `revised_send_ref`
  is in the restored tables needs nothing).
- `reminder_queued` and `send_begun` (a reminder that left): the restored series position moves past that
  reminder: a restored `remind:<question>:<n>` that is still live is cancelled and the next reminder, or the
  escalation, is scheduled as E1 would.

Every replay counts `target_missing` when the entry names a row the restored tables do not hold (an item or a
question created after the backup): information, never an error.

**From the mail host's Sent folder, outside the transaction (`read_sent`):** every admissible copy in the window
since the backup (`CATALYST_SEND_EVIDENCE_SOURCE.within(since)`; 016 A5 admissibility is unchanged, so a copy
Catalyst filed itself is never evidence) is matched by Message-ID to a restored message with the same recipient
and content digest, which becomes `accepted_by_evidence` with its queued or uncertain send finished, as the
ordinary reconciliation does; reminders the replay recreated at or below the highest journaled position are
cancelled again. A copy whose Message-ID is not Catalyst's (`<c<32 hex>@...>`) or whose date is before the window
is dropped. A copy whose Message-ID names a journaled reminder is that reminder (handled above). Any other copy is a
message the restored system does not know: one `restore_effect_unknown_send` item, keyed by a digest of the
Message-ID, with the application found by recipient and, when the journal names the question it answered, the
question (so a re-approval cannot send a second copy). Absence of a copy proves nothing: the review has already
made every live outward action uncertain, for a staff decision.
"""

import hashlib
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent
from workflow.models import AutomationPause, PendingAction

from . import outbound, scheduling, staff_actions
from .inbound import refresh_question_status
from .messages import verified_address
from .models import ApprovedMessage, Question, QuestionReplyLink, StaffItem
from .staff_items import event, resolve_item

ACTOR = "catalyst_post_restore"
ITEM_UNKNOWN_SEND = "restore_effect_unknown_send"
ITEM_RESEND = "restore_effect_resend_unverified"
ITEM_REVISE = "restore_effect_revise_unverified"
Status = PendingAction.Status
Disposition = ApprovedMessage.Disposition
_MESSAGE_ID = re.compile(r"^<c([0-9a-f]{32})@")


def _replayed(application, entry) -> None:
    event(application, "restore_effect_replayed", {"kind": entry.kind, "seq": entry.seq}, actor_ref=ACTOR)


def _pause_row(public_ref):
    return AutomationPause.objects.filter(subject_type="application", subject_id=public_ref)


def _uuid(text: str):
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def replay(entries, opener) -> dict:
    report = {"replayed": 0, "reflected": 0, "items": 0, "target_missing": 0}

    def count(outcome: str) -> None:
        report[outcome] += 1

    last_pause = {}
    for entry in entries:
        if entry.kind == "automation_pause":
            last_pause[entry.key] = entry  # the last state per application decides (below)
        elif entry.kind == "staff_item_resolved":
            ref = _uuid(entry.key.removeprefix("item:"))
            item = StaffItem.objects.filter(public_id=ref).first() if ref else None
            if item is None:
                count("target_missing")
                continue
            if item.status != StaffItem.Status.OPEN:
                count("reflected")
                continue
            resolve_item(item, code=str(entry.data.get("resolution") or "replayed"), actor_ref=ACTOR,
                         note="replayed from the effect journal after a restore", effects={"journal_seq": entry.seq},
                         actor_type=ApplicationEvent.ActorType.SYSTEM)
            _replayed(item.application, entry)
            count("replayed")
        elif entry.kind == "question_withdrawn":
            ref = _uuid(entry.key.removeprefix("question:"))
            question = Question.objects.filter(public_id=ref).first() if ref else None
            if question is None:
                count("target_missing")
                continue
            if question.status == Question.Status.WITHDRAWN:
                count("reflected")
                continue
            reason = entry.data.get("reason") if entry.data.get("reason") in staff_actions.WITHDRAW_REASONS else "no_longer_needed"
            staff_actions.withdraw_question_as(question.pk, ACTOR, reason, "replayed from the effect journal after a restore")
            _replayed(question.application, entry)
            count("replayed")
        elif entry.kind == "reply_link_outcome":
            _, question_ref, message_ref = entry.key.split(":", 2)
            link = (QuestionReplyLink.objects.select_related("question__application")
                    .filter(question__public_id=_uuid(question_ref), inbound_message__public_id=_uuid(message_ref)).first())
            if link is None:
                count("target_missing")
                continue
            if link.state != "pending":
                count("reflected")
                continue
            outcome = entry.data.get("outcome") if entry.data.get("outcome") in ("satisfied", "partial", "not_addressed") else ""
            QuestionReplyLink.objects.filter(pk=link.pk).update(state="applied", outcome=outcome, actor_ref=ACTOR, updated_at=Now())
            refresh_question_status(Question.objects.get(pk=link.question_id))
            _replayed(link.question.application, entry)
            count("replayed")
        elif entry.kind == "uncertain_send_decided":
            count(_replay_decision(entry, opener))
        elif entry.kind == "reminder_queued" or (entry.kind == "send_begun" and entry.data.get("kind") == "reminder"):
            count(_replay_reminder(entry))
    for key, entry in last_pause.items():
        public_ref = _uuid(key.removeprefix("pause:"))
        application = Application.objects.filter(public_ref=public_ref).first() if public_ref else None
        if application is None:
            count("target_missing")
            continue
        row = _pause_row(public_ref).first()
        if entry.data.get("state") == "paused":
            if row is not None:
                count("reflected")
                continue
            by = "system" if entry.data.get("by") == "system" else "staff"
            AutomationPause.objects.create(subject_type="application", subject_id=public_ref,
                                           reason="replayed from the effect journal after a restore",
                                           actor_ref=f"system:{ACTOR}" if by == "system" else ACTOR)
            event(application, "automation_paused", {"by": by, "reason": "replayed_after_restore"}, actor_ref=ACTOR)
        else:
            if row is None or row.created_at >= entry.when:
                count("reflected")
                continue
            # The pause guard (PR #88) admits a delete only with a staff `automation_resumed` event in the same
            # transaction: the actor is the journaled staff reference of the resume, or the owner who runs this step.
            actor = str(entry.data.get("actor") or f"owner:{ACTOR}")
            moved = scheduling.reschedule_on_resume(application)
            event(application, "automation_resumed",
                  {"rescheduled": moved, "note": "replayed from the effect journal after a restore", "journal_seq": entry.seq},
                  actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
            _pause_row(public_ref).delete()
        _replayed(application, entry)
        count("replayed")
    return report


def _replay_decision(entry, opener) -> str:
    ref = _uuid(entry.key.removeprefix("send:"))
    message = ApprovedMessage.objects.select_related("application").filter(send_ref=ref).first() if ref else None
    if message is None:
        return "target_missing"
    decision = entry.data.get("decision")
    if decision == "abandon":
        if message.disposition == Disposition.OPERATOR_ABANDONED:
            return "reflected"
        staff_actions._cancel_open_sends(message, "replayed_abandon_after_restore")
        ApprovedMessage.objects.filter(pk=message.pk).update(disposition=Disposition.OPERATOR_ABANDONED, disposition_at=Now(),
                                                             disposition_by=ACTOR)
        _replayed(message.application, entry)
        return "replayed"
    if decision == "authorize_resend":
        series = entry.data.get("series")
        if message.disposition in staff_actions.CLOSED or PendingAction.objects.filter(
                kind__in=outbound.SEND_KINDS, idempotency_key=outbound.send_key(message.send_ref, series or 0)).exists():
            return "reflected"  # the restored record knows the series, or the message is already settled
        opener(ITEM_RESEND, f"send:{message.send_ref}:{series}", application=message.application, approved_message=message)
        return "items"
    if decision == "revise":
        revised = _uuid(str(entry.data.get("revised_send_ref") or ""))
        if revised and ApprovedMessage.objects.filter(send_ref=revised).exists():
            return "reflected"  # the revision is in the backup
        # The original's state is restored (cancelled sends, superseded) only when the revision's send is settled; the
        # revised copy may have left after the backup, so a decision-maker settles it (PR #89 review).
        opener(ITEM_REVISE, f"send:{message.send_ref}:{entry.data.get('revised_send_ref') or ''}",
               application=message.application, approved_message=message)
        return "items"
    return "reflected"


def _replay_reminder(entry) -> str:
    question = Question.objects.select_related("application").filter(public_id=_uuid(str(entry.data.get("question", "")))).first()
    n = entry.data.get("n")
    if question is None or not isinstance(n, int) or n <= 0:
        return "target_missing" if question is None else "reflected"
    send_ref = entry.data.get("send_ref") if entry.kind == "reminder_queued" else entry.key.removeprefix("send:")
    if entry.kind == "reminder_queued" and ApprovedMessage.objects.filter(send_ref=_uuid(str(send_ref or ""))).exists():
        return "reflected"  # the reminder itself is in the backup: its own send is handled as any outward action
    live = PendingAction.objects.filter(kind=scheduling.REMIND, idempotency_key=scheduling.remind_key(question, n),
                                        status__in=scheduling.LIVE)
    cancelled = live.update(status=Status.CANCELLED, last_error="replayed_sent_after_backup", completed_at=Now(), updated_at=Now())
    before = scheduling.reminder_actions(question).count()
    if question.status in scheduling.STILL_ASKED:
        if n + 1 <= settings.CATALYST_REMINDER_MAX:
            scheduling._create(scheduling.REMIND, scheduling.remind_key(question, n + 1), question, f"{question.public_id}:{n + 1}")
        else:
            scheduling.schedule_after_last(question)  # the escalation and, since bgl.7, the lapse
        scheduling.sync_reminders(question, question.status)
    if cancelled or scheduling.reminder_actions(question).count() > before:
        _replayed(question.application, entry)
        return "replayed"
    return "reflected"


# --- the Sent-folder read ------------------------------------------------------------------------------------------

def _highest_reminders(journal_entries) -> dict:
    """question public id -> the highest reminder number the journal says left or was queued."""
    highs: dict = {}
    for e in journal_entries:
        if e.kind == "reminder_queued" or (e.kind == "send_begun" and e.data.get("kind") == "reminder"):
            q, n = str(e.data.get("question", "")), e.data.get("n")
            if q and isinstance(n, int):
                highs[q] = max(highs.get(q, 0), n)
    return highs


def _cancel_recreated_reminders(message, highs) -> None:
    """After acceptance by evidence E1 schedules the next reminder; one at or below the highest journaled position
    already left after the backup, so it is cancelled again (PR #89 review)."""
    for link in message.question_links.select_related("question"):
        top = highs.get(str(link.question.public_id), 0)
        for k in range(1, top + 1):
            PendingAction.objects.filter(kind=scheduling.REMIND, idempotency_key=scheduling.remind_key(link.question, k),
                                         status__in=scheduling.LIVE).update(
                status=Status.CANCELLED, last_error="replayed_sent_after_backup", completed_at=Now(), updated_at=Now())


def read_sent(since, journal_entries, opener) -> dict:
    """Returns {"status": "ok" | "not_configured" | "unreachable:<code>", "copies": n, "accepted": n, "items": n,
    "dropped": n}."""
    from config import guards

    needed = settings.CATALYST_ENV in guards.LIVE_ENVIRONMENTS or PendingAction.objects.filter(
        kind__in=outbound.SEND_KINDS, status__in=(Status.QUEUED, Status.RUNNING, Status.UNCERTAIN, Status.HELD)).exists()
    needed = needed or any(e.kind in ("reminder_queued", "uncertain_send_decided", "send_begun", "question_approved",
                                      "staff_message_confirmed") for e in journal_entries)
    source = outbound.evidence_source()
    if source is None:
        return {"status": "ok" if not needed else "not_configured", "copies": 0, "accepted": 0, "items": 0, "dropped": 0}
    reminders = {str(e.data.get("send_ref", "")).replace("-", "") for e in journal_entries if e.kind == "reminder_queued"}
    reminders |= {e.key.removeprefix("send:").replace("-", "") for e in journal_entries
                  if e.kind == "send_begun" and e.data.get("kind") == "reminder"}
    questions = {str(e.data.get("send_ref", "")).replace("-", ""): str(e.data.get("question", ""))
                 for e in journal_entries if e.kind == "question_approved"}
    highs = _highest_reminders(journal_entries)
    try:
        records = list(source.within(since))  # no lock is held here
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__.lower()
        return {"status": f"unreachable:{code}", "copies": 0, "accepted": 0, "items": 0, "dropped": 0}
    accepted = items = dropped = 0
    for record in records:
        if record.origin != "provider" or record.filed_by_catalyst:
            continue  # never evidence (016 A5)
        match = _MESSAGE_ID.match(record.message_id or "")
        if not match or (since is not None and record.observed_at is not None and record.observed_at < since):
            dropped += 1  # not Catalyst's, or before the window: a copy that cannot be an effect of this system
            continue
        send_ref = match.group(1)
        message = ApprovedMessage.objects.select_related("application").filter(send_ref=_uuid(send_ref)).first()
        if message is not None:
            digests = {message.content_sha256, *message.attempts.values_list("rendered_sha256", flat=True)} - {""}
            if outbound.admissible(record, message, digests):
                if message.disposition == Disposition.ACTIVE:
                    with transaction.atomic():
                        outbound.accept_by_evidence(message, record, ACTOR,
                                                    send_statuses=(Status.UNCERTAIN, Status.QUEUED, Status.HELD, Status.RUNNING))
                        _cancel_recreated_reminders(message, highs)
                        for item in StaffItem.objects.filter(approved_message=message, reason_code__in=(ITEM_RESEND, ITEM_REVISE),
                                                             status=StaffItem.Status.OPEN):
                            resolve_item(item, code="accepted_by_evidence", actor_ref=ACTOR,
                                         actor_type=ApplicationEvent.ActorType.SYSTEM)
                    accepted += 1
                continue  # accepted before the backup, or the copy matches the restored message: nothing to do
        if send_ref in reminders:
            continue  # a reminder sent after the backup: its series position was replayed from the journal
        key = hashlib.sha256((record.message_id or "").encode()).hexdigest()[:32]
        applications = [a for a in Application.objects.filter(contact_verified_at__isnull=False).order_by("id")
                        if (verified_address(a) or "").lower() == record.recipient] if record.recipient else []
        question = Question.objects.filter(public_id=_uuid(questions.get(send_ref, ""))).first() if send_ref in questions else None
        with transaction.atomic():
            fields = {"application": applications[0] if applications else None}
            if question is not None:
                fields["question_id"] = question.pk
                fields["application"] = question.application
            if opener(ITEM_UNKNOWN_SEND, f"sent:{key}", **fields):
                items += 1
                for application in applications or ([question.application] if question else []):
                    event(application, "restore_effect_unknown_send",
                          {"message_id_sha256": key, "content_sha256": record.content_sha256,
                           "question": str(question.public_id) if question else ""}, actor_ref=ACTOR)
    return {"status": "ok", "copies": len(records), "accepted": accepted, "items": items, "dropped": dropped}

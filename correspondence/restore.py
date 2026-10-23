"""9kg.33: correspondence effects after a restore (config.post_restore; 029 section 6.2).

**From the effect journal, inside the post-restore transaction (`replay`):**

- `automation_pause`: the last journaled state per application wins; a restored row older than a journaled resume
  is removed (with the reminders spread as a resume does), a journaled pause with no restored row is recreated.
- `staff_item_resolved`: a restored item that is open again is resolved with the journaled code; the note stays
  in the database, so the replayed resolution says where it came from.
- `question_withdrawn`: a restored question that is live again is withdrawn again through the service.
- `reply_link_outcome`: a restored link pending again takes the journaled outcome and the question status follows.
- `uncertain_send_decided`: `abandon` and `revise` are re-applied to the restored message (its open sends are
  cancelled; a revised message created after the backup is not restored, so its send is found by the Sent read
  below or reported there). `authorize_resend` cannot be re-applied blindly: the resend may have left after the
  backup, so it opens `restore_effect_resend_unverified` unless the Sent read finds the copy.
- `reminder_queued`: reminder n of a question left after the backup, so the restored series position moves past
  it: a restored `remind:<question>:<n>` that is still live is cancelled and the next reminder, or the
  escalation, is scheduled as E1 would.

**From the mail host's Sent folder, outside the transaction (`read_sent`):** every admissible copy in the window
since the backup (`CATALYST_SEND_EVIDENCE_SOURCE.within(since)`; 016 A5 admissibility is unchanged, so a copy
Catalyst filed itself is never evidence) is matched by Message-ID to a restored message with the same recipient
and content digest, which becomes `accepted_by_evidence` with its queued or uncertain send finished, as the
ordinary reconciliation does. A copy whose Message-ID names a journaled reminder is that reminder (handled above).
Any other copy is a message the restored system does not know: one `restore_effect_unknown_send` item, keyed by
a digest of the Message-ID, with the application found by recipient when there is one. Absence of a copy proves
nothing: a queued send without a copy stays queued and in the review's outward report for `--outward-checked`.
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
from .staff_items import event, open_item, resolve_item

ACTOR = "catalyst_post_restore"
ITEM_UNKNOWN_SEND = "restore_effect_unknown_send"
ITEM_RESEND = "restore_effect_resend_unverified"
Status = PendingAction.Status
Disposition = ApprovedMessage.Disposition
_MESSAGE_ID = re.compile(r"^<c([0-9a-f]{32})@")


def _replayed(application, entry) -> None:
    event(application, "restore_effect_replayed", {"kind": entry.kind, "seq": entry.seq}, actor_ref=ACTOR)


def _pause_row(public_ref):
    return AutomationPause.objects.filter(subject_type="application", subject_id=public_ref)


def replay(entries) -> dict:
    report = {"replayed": 0, "reflected": 0, "items": 0}
    last_pause = {}
    for entry in entries:
        if entry.kind == "automation_pause":
            last_pause[entry.key] = entry  # the last state per application decides (below)
        elif entry.kind == "staff_item_resolved":
            item = StaffItem.objects.filter(public_id=entry.key.removeprefix("item:"), status=StaffItem.Status.OPEN).first()
            if item is None:
                report["reflected"] += 1
                continue
            resolve_item(item, code=str(entry.data.get("resolution") or "replayed"), actor_ref=ACTOR,
                         note="replayed from the effect journal after a restore", effects={"journal_seq": entry.seq},
                         actor_type=ApplicationEvent.ActorType.SYSTEM)
            _replayed(item.application, entry)
            report["replayed"] += 1
        elif entry.kind == "question_withdrawn":
            question = Question.objects.filter(public_id=entry.key.removeprefix("question:")).first()
            if question is None or question.status == Question.Status.WITHDRAWN:
                report["reflected"] += 1
                continue
            reason = entry.data.get("reason") if entry.data.get("reason") in staff_actions.WITHDRAW_REASONS else "no_longer_needed"
            staff_actions.withdraw_question_as(question.pk, ACTOR, reason, "replayed from the effect journal after a restore")
            _replayed(question.application, entry)
            report["replayed"] += 1
        elif entry.kind == "reply_link_outcome":
            _, question_ref, message_ref = entry.key.split(":", 2)
            link = (QuestionReplyLink.objects.select_related("question__application")
                    .filter(question__public_id=question_ref, inbound_message__public_id=message_ref, state="pending").first())
            if link is None:
                report["reflected"] += 1
                continue
            outcome = entry.data.get("outcome") if entry.data.get("outcome") in ("satisfied", "partial", "not_addressed") else ""
            QuestionReplyLink.objects.filter(pk=link.pk).update(state="applied", outcome=outcome, actor_ref=ACTOR, updated_at=Now())
            refresh_question_status(Question.objects.get(pk=link.question_id))
            _replayed(link.question.application, entry)
            report["replayed"] += 1
        elif entry.kind == "uncertain_send_decided":
            report_part = _replay_decision(entry)
            report[report_part] += 1
        elif entry.kind == "reminder_queued":
            report[_replay_reminder(entry)] += 1
    for key, entry in last_pause.items():
        public_ref = key.removeprefix("pause:")
        try:
            application = Application.objects.filter(public_ref=uuid.UUID(public_ref)).first()
        except ValueError:
            application = None  # a key that names no application: nothing to apply, reported as reflected
        if application is None:
            report["reflected"] += 1
            continue
        row = _pause_row(public_ref).first()
        if entry.data.get("state") == "paused":
            if row is not None:
                report["reflected"] += 1
                continue
            by = "system" if entry.data.get("by") == "system" else "staff"
            AutomationPause.objects.create(subject_type="application", subject_id=public_ref,
                                           reason="replayed from the effect journal after a restore",
                                           actor_ref=f"system:{ACTOR}" if by == "system" else ACTOR)
            event(application, "automation_paused", {"by": by, "reason": "replayed_after_restore"}, actor_ref=ACTOR)
        else:
            if row is None or row.created_at >= entry.when:
                report["reflected"] += 1
                continue
            _pause_row(public_ref).delete()
            moved = scheduling.reschedule_on_resume(application)
            event(application, "automation_resumed", {"rescheduled": moved, "note": "replayed_after_restore"}, actor_ref=ACTOR)
        _replayed(application, entry)
        report["replayed"] += 1
    return report


def _replay_decision(entry) -> str:
    message = ApprovedMessage.objects.select_related("application").filter(send_ref=entry.key.removeprefix("send:")).first()
    if message is None:
        return "reflected"
    decision = entry.data.get("decision")
    if decision in ("abandon", "revise"):
        disposition = Disposition.OPERATOR_ABANDONED if decision == "abandon" else Disposition.SUPERSEDED
        if message.disposition == disposition:
            return "reflected"
        staff_actions._cancel_open_sends(message, f"replayed_{decision}_after_restore")
        ApprovedMessage.objects.filter(pk=message.pk).update(disposition=disposition, disposition_at=Now(), disposition_by=ACTOR)
        _replayed(message.application, entry)
        return "replayed"
    if decision == "authorize_resend":
        series = entry.data.get("series")
        if message.disposition in staff_actions.CLOSED or PendingAction.objects.filter(
                kind__in=outbound.SEND_KINDS, idempotency_key=outbound.send_key(message.send_ref, series or 0)).exists():
            return "reflected"  # the restored record knows the series, or the message is already settled
        open_item(ITEM_RESEND, f"send:{message.send_ref}:{series}", application=message.application,
                  approved_message=message, audit=False)
        return "items"
    return "reflected"


def _replay_reminder(entry) -> str:
    question = Question.objects.select_related("application").filter(public_id=entry.data.get("question", "")).first()
    n = entry.data.get("n")
    if question is None or not isinstance(n, int):
        return "reflected"
    if ApprovedMessage.objects.filter(send_ref=entry.data.get("send_ref") or None).exists():
        return "reflected"  # the reminder itself is in the backup
    live = PendingAction.objects.filter(kind=scheduling.REMIND, idempotency_key=scheduling.remind_key(question, n),
                                        status__in=scheduling.LIVE)
    cancelled = live.update(status=Status.CANCELLED, last_error="replayed_sent_after_backup", completed_at=Now(), updated_at=Now())
    before = scheduling.reminder_actions(question).count()
    if question.status in scheduling.STILL_ASKED:
        if n + 1 <= settings.CATALYST_REMINDER_MAX:
            scheduling._create(scheduling.REMIND, scheduling.remind_key(question, n + 1), question, f"{question.public_id}:{n + 1}")
        else:
            scheduling._create(scheduling.ESCALATE, scheduling.escalate_key(question), question, str(question.public_id))
        scheduling.sync_reminders(question, question.status)
    if cancelled or scheduling.reminder_actions(question).count() > before:
        _replayed(question.application, entry)
        return "replayed"
    return "reflected"


# --- the Sent-folder read ------------------------------------------------------------------------------------------

def _accept(message, record) -> None:
    """The ordinary acceptance by evidence (outbound.ReconcileSend), for a restored message of any send status."""
    outbound.accept_by_evidence(message, record, ACTOR, send_statuses=(Status.UNCERTAIN, Status.QUEUED, Status.HELD, Status.RUNNING))


def read_sent(since, journal_entries) -> dict:
    """Returns {"status": "ok" | "not_configured" | "unreachable:<code>", "copies": n, "accepted": n, "items": n}."""
    needed = PendingAction.objects.filter(kind__in=outbound.SEND_KINDS,
                                          status__in=(Status.QUEUED, Status.RUNNING, Status.UNCERTAIN, Status.HELD)).exists()
    needed = needed or any(e.kind in ("reminder_queued", "uncertain_send_decided") for e in journal_entries)
    source = outbound.evidence_source()
    if source is None:
        return {"status": "ok" if not needed else "not_configured", "copies": 0, "accepted": 0, "items": 0}
    reminders = {e.data.get("send_ref", ""): e for e in journal_entries if e.kind == "reminder_queued"}
    try:
        records = list(source.within(since))  # no lock is held here
    except Exception as exc:
        code = getattr(exc, "code", None) or type(exc).__name__.lower()
        return {"status": f"unreachable:{code}", "copies": 0, "accepted": 0, "items": 0}
    accepted = items = 0
    for record in records:
        if record.origin != "provider" or record.filed_by_catalyst:
            continue  # never evidence (016 A5)
        match = _MESSAGE_ID.match(record.message_id or "")
        send_ref = match.group(1) if match else ""
        message = (ApprovedMessage.objects.select_related("application").filter(send_ref=send_ref).first()
                   if send_ref else None)
        if message is not None:
            digests = {message.content_sha256, *message.attempts.values_list("rendered_sha256", flat=True)} - {""}
            if outbound.admissible(record, message, digests):
                if message.disposition == Disposition.ACTIVE:
                    with transaction.atomic():
                        _accept(message, record)
                        for item in StaffItem.objects.filter(approved_message=message, reason_code=ITEM_RESEND,
                                                             status=StaffItem.Status.OPEN):
                            resolve_item(item, code="accepted_by_evidence", actor_ref=ACTOR,
                                         actor_type=ApplicationEvent.ActorType.SYSTEM)
                    accepted += 1
                continue  # accepted before the backup, or the copy matches the restored message: nothing to do
        if send_ref and send_ref in {ref.replace("-", "") for ref in reminders}:
            continue  # a reminder sent after the backup: its series position was replayed from the journal
        key = hashlib.sha256((record.message_id or "").encode()).hexdigest()[:32]
        applications = [a for a in Application.objects.filter(contact_verified_at__isnull=False).order_by("id")
                        if verified_address(a) == record.recipient] if record.recipient else []
        with transaction.atomic():
            item = open_item(ITEM_UNKNOWN_SEND, f"sent:{key}", application=applications[0] if applications else None, audit=False)
            for application in applications:
                event(application, "restore_effect_unknown_send",
                      {"item": str(item.public_id), "message_id_sha256": key, "content_sha256": record.content_sha256},
                      actor_ref=ACTOR)
        items += 1
    return {"status": "ok", "copies": len(records), "accepted": accepted, "items": items}

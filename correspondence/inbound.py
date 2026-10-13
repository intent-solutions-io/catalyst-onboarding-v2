"""Inbound collection and correlation (016 section 4 B and C, 4.1; P2 task 2B.2; owner decisions D-27, D-28, D-31).
Synthetic only.

- `Collect` (`collect`, internal and idempotent, D-27): one pass over the collected folder. Read-only EXAMINE and
  BODY.PEEK. Each message is one transaction: lock the cursor, then the application and its questions; record
  identity and location; associate and decide trust; set `reply_pending` where the trust table allows; queue
  `process_reply`; advance `last_uid`; last, `ledger.fence`. A pass that reaches the mailbox's last UID as
  observed at its start sets the completed-collection watermark; a partial batch never does. A blocked cursor
  schedules no successor.
- `FileCopy` (`file_copy`, 016 A4): files a copy of an accepted send into the Sent folder with
  X-Catalyst-Filed-Copy. It searches before APPEND (not exactly-once), retries the APPEND only, and never
  sends SMTP. A filed copy is never evidence of acceptance.
- `bootstrap_mailbox` and `recover_mailbox` (B0): explicit start modes; recovery never skips.

Collection never marks a question answered and never cancels a reminder (J-07).
"""

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.db import DataError, IntegrityError, InterfaceError, OperationalError, connection, transaction
from django.db.models.functions import Now

from applications.models import TERMINAL_STAGES, Application
from workflow import ledger
from workflow.models import PendingAction

from . import association, mime
from .imap import NETWORK_ERRORS, MailboxClient, MailboxError, classify
from .models import (
    ApprovedMessage,
    InboundMessage,
    InboundMessageLocation,
    MailboxCursor,
    OutboundMessage,
    Question,
    QuestionReplyLink,
)
from .common import Refused
from .messages import FILE_COPY, build_email, enqueue_file_copy, message_id, only_duplicate_key, verified_address  # noqa: F401
from .scheduling import sync_reminders
from .staff_items import open_item

logger = logging.getLogger(__name__)
Status = PendingAction.Status
State = MailboxCursor.State
Inbound = InboundMessage.Status

COLLECT = "collect"
PROCESS_REPLY = "process_reply"
CURSOR_SUBJECT = "mailbox_cursor"
BLOCKING = ("auth_failed", "tls_refused", "peer_refused", "not_configured")
ANSWERABLE = (Question.Status.OPEN, Question.Status.PARTIALLY_ANSWERED, Question.Status.REPLY_PENDING)


def collect_key(cursor, n: int) -> str:
    return f"collect:{cursor.public_id}:{n}"


def enqueue_pass(cursor, n: int, delay: float = 0.0) -> None:
    """Idempotent: the pass key is unique, so a retried finish never creates a second successor."""
    try:
        with transaction.atomic():
            PendingAction.objects.create(
                kind=COLLECT, subject_type=CURSOR_SUBJECT, subject_id=cursor.public_id, input_ref="",
                idempotency_key=collect_key(cursor, n), due_at=Now() + timedelta(seconds=delay),
                max_attempts=settings.CATALYST_MAIL_SEND_ATTEMPTS,
            )
    except IntegrityError as exc:
        only_duplicate_key(exc)


def _pass_number(claim) -> int:
    key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""
    try:
        return int(key.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def refresh_question_status(question: Question) -> str:
    """016 3.3: one function derives the status from the links (withdrawn is terminal)."""
    if question.status == Question.Status.WITHDRAWN:
        sync_reminders(question, question.status)
        return question.status
    links = question.reply_links.all()
    if links.filter(state="pending").exists():
        status = Question.Status.REPLY_PENDING
    elif links.filter(state="applied", outcome="satisfied").exists():
        status = Question.Status.SATISFIED
    elif links.filter(state="applied", outcome="partial").exists():
        status = Question.Status.PARTIALLY_ANSWERED
    else:
        status = Question.Status.OPEN
    if status != question.status:
        Question.objects.filter(pk=question.pk).update(status=status, updated_at=Now())
    sync_reminders(question, status)  # E3, in the same transaction as every status change
    return status


def _item(reason, message, application=None):
    open_item(reason, f"inbound:{message.public_id}", application=application)


def _exception(message, reason, application=None, item=True):
    InboundMessage.objects.filter(pk=message.pk).update(status=Inbound.EXCEPTION, exception_reason=reason,
                                                        application_id=application.pk if application else None)
    if item:
        _item(reason, message, application)


def queue_processing(message, application) -> None:
    PendingAction.objects.create(
        kind=PROCESS_REPLY, subject_type="application", subject_id=application.public_ref, input_ref=str(message.public_id),
        idempotency_key=f"{PROCESS_REPLY}:{message.public_id}", max_attempts=settings.CATALYST_MAIL_SEND_ATTEMPTS)


def _associate(message: InboundMessage, derived) -> None:
    """C0 to C3 for a newly stored message (inside the per-message transaction)."""
    refs = association.candidate_refs(derived)
    found = {m.send_ref: m for m in ApprovedMessage.objects.select_related("application").filter(send_ref__in=refs)}
    approved = next((found[r] for r in refs if r in found), None)  # In-Reply-To first, then References newest first
    classification = "bounce" if derived.is_bounce else ("automatic" if association.is_automatic(derived.auto_markers) else "human")
    InboundMessage.objects.filter(pk=message.pk).update(classification=classification)
    if approved is None:
        _exception(message, "unmatched")
        return
    application = Application.objects.select_for_update(of=("self",)).get(pk=approved.application_id)
    questions = list(Question.objects.select_for_update(of=("self",))
                     .filter(message_links__approved_message=approved).order_by("id"))
    InboundMessage.objects.filter(pk=message.pk).update(application_id=application.pk, approved_message_id=approved.pk)
    if application.stage in TERMINAL_STAGES:
        _exception(message, "application_closed", application)
        return
    if classification != "human":
        # Automatic messages and bounces never make a question reply_pending (016 D1); 2B.3 classifies them.
        InboundMessage.objects.filter(pk=message.pk).update(status=Inbound.AWAITING_PROCESSING)
        queue_processing(message, application)
        return
    sender_ok = association.from_matches(derived.from_addresses, verified_address(application))
    evidence = association.auth_evidence(derived.authentication_results)
    decision = association.trust_decision(evidence, sender_ok)
    InboundMessage.objects.filter(pk=message.pk).update(
        from_matches_verified_address=sender_ok, auth_evidence=evidence[:24], trust_decision=decision)
    if decision != association.TRUSTED:
        reason = {association.AUTH_FAILED: "reply_auth_failed", association.UNVERIFIED: "reply_unverified",
                  association.SENDER_MISMATCH: "sender_mismatch"}[decision]
        _exception(message, reason, application)
        return
    for question in questions:
        if question.status in ANSWERABLE:
            QuestionReplyLink.objects.create(question=question, inbound_message=message, state="pending")
            refresh_question_status(question)
    InboundMessage.objects.filter(pk=message.pk).update(status=Inbound.AWAITING_PROCESSING)
    queue_processing(message, application)


def ingest(cursor_id: int, validity: int, uid: int, size: int, internal_date: str, raw: bytes | None, headers_only: bool):
    """One message, one transaction (016 B4). Returns a short outcome code."""
    cursor = MailboxCursor.objects.select_for_update(of=("self",)).get(pk=cursor_id)
    if cursor.uidvalidity != validity or cursor.last_uid >= uid:
        return "stale_position"
    location = dict(mailbox_ref=cursor.mailbox_ref, folder=cursor.folder, uidvalidity=validity, uid=uid)

    def advance(outcome):
        MailboxCursor.objects.filter(pk=cursor.pk, uidvalidity=validity, last_uid__lt=uid).update(last_uid=uid, last_batch_at=Now())
        return outcome

    if InboundMessageLocation.objects.filter(**location).exists():
        return advance("location_known")
    try:
        derived = mime.derive(raw, max_text_chars=settings.CATALYST_MAIL_MAX_TEXT_CHARS, headers_only=headers_only)
        failed = False
    except Exception:  # a parser defect must not block the cursor (016 B4): recorded as processing_error
        derived, failed = mime.Derived(), True
    digest = "" if headers_only or raw is None else mime.digest(raw)
    if digest:
        known = InboundMessage.objects.filter(mailbox_ref=cursor.mailbox_ref, original_sha256=digest).first()
        if known is not None:
            InboundMessageLocation.objects.create(message=known, matched_by="digest", **location)
            MailboxCursor.objects.filter(pk=cursor.pk).update(duplicates_seen=cursor.duplicates_seen + 1)
            return advance("duplicate")
    elif derived.message_id:
        known = InboundMessage.objects.filter(mailbox_ref=cursor.mailbox_ref, identity_state="unestablished",
                                              message_id_header=derived.message_id, size=size, internal_date=internal_date).first()
        if known is not None:
            InboundMessageLocation.objects.create(message=known, matched_by="metadata", **location)
            return advance("duplicate_by_metadata")
    try:
        with transaction.atomic():  # savepoint: a value the database refuses must not poison the cursor
            message = _store(cursor, derived, size, internal_date, digest)
    except DataError:
        failed = True
        message = _store(cursor, mime.Derived(), size, internal_date, digest)
    InboundMessageLocation.objects.create(message=message, matched_by="new", **location)
    return _after_store(cursor, message, derived, digest, failed, headers_only, advance)


def _store(cursor, derived, size, internal_date, digest):
    return InboundMessage.objects.create(
        mailbox_ref=cursor.mailbox_ref, message_id_header=derived.message_id[:998],
        in_reply_to=" ".join(derived.in_reply_to)[:4000], references=" ".join(derived.references)[:8000],
        from_address=(derived.from_addresses[0] if len(derived.from_addresses) == 1 else "")[:320],
        from_normalized=(derived.from_addresses[0].casefold() if len(derived.from_addresses) == 1 else "")[:320],
        auto_markers={**derived.auto_markers, **({"dsn_status": derived.dsn_status,
                                                    "dsn_final_recipient": derived.dsn_final_recipient}
                                                   if derived.dsn_status else {})},
        date_header=derived.date_header, internal_date=internal_date[:64], size=size,
        original_sha256=digest, derived_text=derived.text, derived_text_sha256=mime.digest(derived.text.encode()), derivation_version=mime.DERIVATION_VERSION,
        redaction_version=mime.REDACTION_VERSION, truncated=derived.truncated, truncated_at_chars=derived.truncated_at_chars,
        omitted_parts=derived.omitted_parts, redactions=derived.redactions, attachments=derived.attachments,
        identity_state="established" if digest else "unestablished",
    )


def _after_store(cursor, message, derived, digest, failed, headers_only, advance):
    if failed:
        _exception(message, "processing_error")
    elif headers_only:
        _exception(message, "inbound_oversize")
    elif derived.filed_copy and association.send_ref_of(derived.message_id) is not None:
        InboundMessage.objects.filter(pk=message.pk).update(classification="own_copy", status=Inbound.PROCESSED,
                                                            processed_at=Now())  # our own filed copy: no effect
    elif digest and derived.message_id and InboundMessage.objects.filter(
            mailbox_ref=cursor.mailbox_ref, message_id_header=derived.message_id).exclude(pk=message.pk).exists():
        _exception(message, "message_id_conflict")  # same Message-ID, different bytes: kept, staff decide
    else:
        try:
            with transaction.atomic():
                _associate(message, derived)
        except (OperationalError, InterfaceError):
            raise  # a database failure aborts the pass (016 B4); it is never demoted to processing_error
        except Exception:
            _exception(message, "processing_error")
    return advance("stored")


class Collect:
    kind = COLLECT
    redeliverable = True  # internal and idempotent (D-27): reads the mailbox, sends nothing
    automated = True

    def lock_subject(self, claim) -> None:
        MailboxCursor.objects.select_for_update(of=("self",)).filter(public_id=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        """The chain survives a final failure or the poison rule (016 B1), unless the cursor is blocked."""
        if kind in ("action_attempts_exhausted",) or (kind == "action_failed" and data.get("final")):
            cursor = MailboxCursor.objects.filter(public_id=claim.subject_id).first()
            if cursor is not None and cursor.state != State.BLOCKED:
                n = _pass_number(claim)
                MailboxCursor.objects.filter(pk=cursor.pk).update(pass_number=n + 1, last_error_code="pass_failed")
                enqueue_pass(cursor, n + 1, settings.CATALYST_MAIL_POLL_SECONDS)
                open_item("collector_pass_failed", f"cursor:{cursor.public_id}")

    def _blocked_or_backoff(self, claim, cursor, code: str) -> None:
        n = _pass_number(claim)

        def write():
            failures = cursor.consecutive_failures + 1
            if code in BLOCKING or failures >= settings.CATALYST_MAIL_COLLECT_FAILURE_LIMIT:
                MailboxCursor.objects.filter(pk=cursor.pk).update(
                    state=State.BLOCKED, blocked_reason=code, last_error_code=code, consecutive_failures=failures, pass_number=n)
                open_item("mailbox_auth_failed" if code == "auth_failed" else "collector_blocked", f"cursor:{cursor.public_id}")
            else:
                MailboxCursor.objects.filter(pk=cursor.pk).update(last_error_code=code, consecutive_failures=failures,
                                                                  pass_number=n + 1)
                enqueue_pass(cursor, n + 1, settings.CATALYST_MAIL_POLL_SECONDS)
        ledger.finish(claim, self, status=Status.DONE, error=f"mailbox:{code}", write=write)

    def run(self, claim) -> None:
        cursor = MailboxCursor.objects.filter(public_id=claim.subject_id).first()
        if cursor is None:
            ledger.finish(claim, self, status=Status.FAILED, error="cursor_not_found")
            return
        if cursor.state == State.BLOCKED:
            ledger.finish(claim, self, status=Status.DONE, error="cursor_blocked")  # no successor (016 B1)
            return
        with connection.cursor() as db:
            db.execute("SELECT now()")
            pass_started_at = db.fetchone()[0]
        lease_half = settings.CATALYST_WORKER_LEASE_SECONDS / 2
        budget = time.monotonic() + lease_half
        try:
            client = MailboxClient(timeout=min(settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS, lease_half))
        except MailboxError as exc:
            self._blocked_or_backoff(claim, cursor, exc.code)
            return
        complete, fetch_failed, n = True, None, _pass_number(claim)
        with client:
            try:
                validity, uidnext = client.examine(cursor.folder)
            except (MailboxError, *NETWORK_ERRORS) as exc:
                self._blocked_or_backoff(claim, cursor, classify(exc).code)
                return
            target = uidnext - 1
            if cursor.uidvalidity is None or cursor.uidvalidity != validity:
                self._new_validity(claim, cursor, validity)
                cursor.refresh_from_db()
            elif cursor.state == State.OK and InboundMessageLocation.objects.filter(
                    mailbox_ref=cursor.mailbox_ref, folder=cursor.folder, uidvalidity=validity, uid__gt=cursor.last_uid).exists():
                # A regressed cursor (for example a restore): walk forward as a recovery; known locations are skipped.
                MailboxCursor.objects.filter(pk=cursor.pk).update(state=State.RECOVERY)
                cursor.refresh_from_db()
            try:
                uids = client.uids_after(cursor.last_uid)
            except (MailboxError, *NETWORK_ERRORS) as exc:
                self._blocked_or_backoff(claim, cursor, classify(exc).code)
                return
            if len(uids) > settings.CATALYST_MAIL_BATCH_SIZE:
                uids, complete = uids[:settings.CATALYST_MAIL_BATCH_SIZE], False
            for uid in uids:
                if time.monotonic() > budget:
                    complete = False
                    break
                try:
                    size, internal_date = client.meta(uid)
                    headers_only = size > settings.CATALYST_MAIL_MAX_MESSAGE_BYTES
                    raw = client.fetch_headers(uid) if headers_only else client.fetch(uid)
                except (MailboxError, *NETWORK_ERRORS) as exc:  # the connection failed mid-message
                    fetch_failed = classify(exc).code
                    complete = False
                    break
                try:
                    with transaction.atomic():
                        ingest(cursor.pk, validity, uid, size, internal_date, raw, headers_only)
                        ledger.fence(claim)  # last: a lost lease rolls this message back and stops the pass
                except ledger.LeaseLost:
                    logger.warning("collect %s: lease lost; pass stopped", claim.id)
                    return
        if fetch_failed:
            cursor.refresh_from_db()
            self._blocked_or_backoff(claim, cursor, fetch_failed)
            return

        def write():
            fields = {"pass_number": n + 1, "consecutive_failures": 0, "last_error_code": ""}
            if complete:
                fields.update(complete_through_uid=target, complete_through_at=pass_started_at, state=State.OK)
            MailboxCursor.objects.filter(pk=cursor.pk).update(**fields)
            enqueue_pass(cursor, n + 1, settings.CATALYST_MAIL_POLL_SECONDS)
        ledger.finish(claim, self, status=Status.DONE, write=write)

    def _new_validity(self, claim, cursor, validity: int) -> None:
        """First sight in recovery, or a UIDVALIDITY change (016 4.1): one fenced transaction."""
        with transaction.atomic():
            locked = MailboxCursor.objects.select_for_update(of=("self",)).get(pk=cursor.pk)
            if locked.uidvalidity is None:
                MailboxCursor.objects.filter(pk=locked.pk).update(uidvalidity=validity, last_uid=0)
            else:
                MailboxCursor.objects.filter(pk=locked.pk).update(
                    state=State.RESYNC, epoch=locked.epoch + 1, uidvalidity=validity, last_uid=0,
                    complete_through_uid=None, complete_through_at=None)
                open_item("mailbox_uidvalidity_changed", f"cursor:{locked.public_id}:{validity}")
            ledger.fence(claim)


# --- bootstrap and recovery (016 B0; host-level commands) ------------------------------------------------

def _locations_exist(mailbox_ref, folder) -> bool:
    return InboundMessageLocation.objects.filter(mailbox_ref=mailbox_ref, folder=folder).exists()


def bootstrap_mailbox(start_mode: str, start_uid: int | None = None) -> MailboxCursor:
    mailbox_ref, folder = settings.CATALYST_MAIL_MAILBOX_REF, settings.CATALYST_MAIL_COLLECT_FOLDER
    if start_mode not in ("from_now", "from_uid") or (start_mode == "from_uid" and not start_uid):
        raise Refused("start_mode_must_be_from_now_or_from_uid")
    if MailboxCursor.objects.filter(mailbox_ref=mailbox_ref, folder=folder).exists() or _locations_exist(mailbox_ref, folder):
        raise Refused("mailbox_already_collected_use_recovery")
    with MailboxClient(timeout=settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS) as client:
        validity, uidnext = client.examine(folder)
    last = uidnext - 1 if start_mode == "from_now" else start_uid - 1
    with transaction.atomic():
        cursor = MailboxCursor.objects.create(
            mailbox_ref=mailbox_ref, folder=folder, uidvalidity=validity, last_uid=max(last, 0), start_mode=start_mode,
            complete_through_uid=last if start_mode == "from_now" else None)
        if start_mode == "from_now":
            MailboxCursor.objects.filter(pk=cursor.pk).update(complete_through_at=Now())
            # Messages already in the mailbox are explicitly out of scope, and that is recorded (016 B0).
            open_item("mailbox_history_out_of_scope", f"cursor:{cursor.public_id}:bootstrap")
        enqueue_pass(cursor, 1)
    return cursor


def recover_mailbox() -> MailboxCursor:
    mailbox_ref, folder = settings.CATALYST_MAIL_MAILBOX_REF, settings.CATALYST_MAIL_COLLECT_FOLDER
    with transaction.atomic():
        cursor = MailboxCursor.objects.select_for_update(of=("self",)).filter(mailbox_ref=mailbox_ref, folder=folder).first()
        if cursor is not None and cursor.state == State.BLOCKED:
            raise Refused("cursor_blocked_use_restart_collector")  # only restart_collector resumes a blocked cursor
        if cursor is None:
            if not _locations_exist(mailbox_ref, folder):
                raise Refused("nothing_to_recover_use_bootstrap")
            cursor = MailboxCursor.objects.create(mailbox_ref=mailbox_ref, folder=folder, uidvalidity=None, last_uid=0,
                                                  state=State.RECOVERY, start_mode="recovery")
        else:
            MailboxCursor.objects.filter(pk=cursor.pk).update(state=State.RECOVERY, last_uid=0, complete_through_uid=None,
                                                              complete_through_at=None, blocked_reason="")
        n = (PendingAction.objects.filter(kind=COLLECT, subject_id=cursor.public_id).count()) + 1
        enqueue_pass(cursor, n)
    cursor.refresh_from_db()
    return cursor


# --- filed copies (016 A4) -------------------------------------------------------------------------------

class FileCopy:
    kind = FILE_COPY
    redeliverable = True  # a mailbox record for humans; a repeat is at worst a duplicate copy, never a send
    automated = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            message = ApprovedMessage.objects.select_related("application").filter(send_ref=claim.input_ref).first()
            if message is not None:
                OutboundMessage.objects.filter(approved_message=message, filed_copy_state="pending").update(filed_copy_state="failed")
                open_item("filed_copy_failed", str(message.send_ref), application=message.application, approved_message=message)

    def run(self, claim) -> None:
        message = ApprovedMessage.objects.select_related("application", "template_version").filter(send_ref=claim.input_ref).first()
        if message is None:
            ledger.finish(claim, self, status=Status.FAILED, error="approved_message_not_found")
            return
        if message.template_version is not None and message.template_version.secret_bearing:
            ledger.finish(claim, self, status=Status.CANCELLED, error="secret_bearing_never_filed")
            return
        mid = message_id(message.send_ref)
        try:
            with MailboxClient(timeout=settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS) as client:
                if not client.search_message_id(settings.CATALYST_MAIL_SENT_FOLDER, mid):
                    data = build_email(message, message.frozen_subject, message.frozen_body,
                                       extra_headers={mime.FILED_COPY_HEADER: str(message.send_ref)})
                    client.append(settings.CATALYST_MAIL_SENT_FOLDER, data)
        except (MailboxError, *NETWORK_ERRORS) as exc:
            ledger.fail_or_retry(claim, self, f"mailbox:{classify(exc).code}",
                                 write=lambda: self.record(claim, "action_failed", {"final": claim.final}) if claim.final else None)
            return
        ledger.finish(claim, self, status=Status.DONE, write=lambda: OutboundMessage.objects.filter(
            approved_message=message, filed_copy_state="pending").update(filed_copy_state="filed"))

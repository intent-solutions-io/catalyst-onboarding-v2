"""P2 task 2B.4, reminders and controlled staff intervention (016 section 4 E and F, 3.3, 3.4; owner decisions
D-28 A-5, A-8, D-30): TEST-P2-04, 05, 11, 28 to 31, 35, 45, 50, the 2B.4 services of 52, and G4 to G7.

Synthetic only, against the scripted SMTP and IMAP servers of tests/test_inbound.py. Reminders are made due by
setting `due_at` to the completed-collection watermark, so the watermark rule (4.1) is always exercised.
"""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent
from correspondence import outbound, processing, reminders, scheduling, staff_actions  # noqa: F401
from correspondence.health import mail_behaviour_health, reminder_health
from correspondence.models import (
    ApprovedMessage,
    MailboxCursor,
    MessageTemplate,
    MessageTemplateVersion,
    Question,
    QuestionReplyLink,
    StaffItem,
    StaffItemResolution,
    StaffMessageDraft,
)
from correspondence.outbound import Refused
from correspondence.rendering import canonical_digest
from tests.test_inbound import collect, mailbox, reply, sent_question, tls  # noqa: F401  (fixtures and helpers)
from tests.test_outbound import ask, p2, ready, run_worker, staff, verified_application  # noqa: F401
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

REMINDER_SUBJECT = "A reminder about your application"
REMINDER_BODY = ("Hello $display_name,\n\nWe are still waiting for your answer to this question:\n\n$question_text\n\n"
                 "Please reply to this message.\n")


@pytest.fixture
def remind(mailbox, settings):
    """`mailbox` plus an approved reminder template and synthetic cadence settings: reminders are scheduled far
    ahead, so each test decides when one falls due; no quiet hours and no gap unless a test sets them."""
    settings.CATALYST_REMINDER_MAX = 2
    settings.CATALYST_REMINDER_INTERVAL_SECONDS = 3600
    settings.CATALYST_REMINDER_MIN_GAP_SECONDS = 0
    settings.CATALYST_REMINDER_QUIET_START_HOUR = settings.CATALYST_REMINDER_QUIET_END_HOUR = 0
    settings.CATALYST_REMINDER_RESUME_GRACE_SECONDS = 60
    settings.CATALYST_REMINDER_STALE_DEFERRALS = 3
    settings.CATALYST_REMINDER_STALE_RETRY_SECONDS = 3600
    version = MessageTemplateVersion.objects.filter(template__key="question_reminder", version=1).first()
    if version is None:  # the test reset truncated the migration's seed: recreate the same synthetic draft
        template = MessageTemplate.objects.create(key="question_reminder", purpose="Remind an applicant")
        version = MessageTemplateVersion.objects.create(
            template=template, version=1, subject=REMINDER_SUBJECT, body_text=REMINDER_BODY,
            variables=["display_name", "question_text"], content_sha256=canonical_digest(REMINDER_SUBJECT, REMINDER_BODY))
    outbound.approve_template_version(version.pk, mailbox.owner)
    return mailbox


def actions(question, kind="remind"):
    return list(PendingAction.objects.filter(kind=kind, input_ref__startswith=str(question.public_id)).order_by("id"))


def states(question):
    return [(a.idempotency_key.rsplit(":", 1)[-1] if a.kind == "remind" else "escalate", a.status)
            for a in PendingAction.objects.filter(kind__in=scheduling.REMINDER_KINDS,
                                                  input_ref__startswith=str(question.public_id)).order_by("id")]


def fire(kind=None):
    """Complete a collection pass, make every queued reminder due exactly at the new watermark, run the worker."""
    collect()
    watermark = MailboxCursor.objects.get().complete_through_at
    PendingAction.objects.filter(kind__in=[kind] if kind else scheduling.REMINDER_KINDS, status="queued").update(due_at=watermark)
    run_worker()


def reminder_mails(env):
    return [env.server.parsed(i) for i in range(len(env.server.messages))
            if env.server.parsed(i)["Subject"] == "A reminder about your application"]


def paused(env, app=None):
    return AutomationPause.objects.filter(subject_type="application", subject_id=(app or env.app).public_ref).exists()


# --- E1, E2: cadence, maximum, escalation -------------------------------------------------------------------

def test_p2_29_cadence_maximum_and_escalation_after_the_last_reminder(remind):
    question, _ = sent_question(remind)
    assert states(question) == [("1", "queued")]  # scheduled in the acceptance transaction (E1)
    fire()
    assert states(question) == [("1", "done"), ("2", "queued")]
    [mail] = reminder_mails(remind)
    assert mail["Auto-Submitted"] == "auto-generated" and question.text in mail.get_content()
    assert ApprovedMessage.objects.filter(kind="reminder").count() == 1
    fire()
    assert states(question) == [("1", "done"), ("2", "done"), ("escalate", "queued")]
    fire()
    assert states(question) == [("1", "done"), ("2", "done"), ("escalate", "done")]
    assert len(reminder_mails(remind)) == 2  # never more than the maximum
    assert StaffItem.objects.filter(reason_code="escalate_unanswered", question_id=question.pk, status="open").count() == 1
    assert ApplicationEvent.objects.filter(kind="question_unanswered").count() == 1
    fire()
    assert len(reminder_mails(remind)) == 2 and StaffItem.objects.filter(reason_code="escalate_unanswered").count() == 1


def test_p2_29_quiet_hours_defer_to_their_end_and_the_minimum_gap_is_kept(remind, settings):
    question, _ = sent_question(remind)
    now = reminders.db_now()
    settings.CATALYST_REMINDER_QUIET_START_HOUR, settings.CATALYST_REMINDER_QUIET_END_HOUR = now.hour, (now.hour + 1) % 24
    fire()
    [action] = actions(question)
    end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    assert (action.status, action.last_error, action.attempts) == ("queued", "quiet_hours", 0)
    assert abs((action.due_at - end).total_seconds()) < 2 and reminder_mails(remind) == []
    settings.CATALYST_REMINDER_QUIET_START_HOUR = settings.CATALYST_REMINDER_QUIET_END_HOUR = 0
    settings.CATALYST_REMINDER_MIN_GAP_SECONDS = 7200
    fire()
    action.refresh_from_db()
    assert (action.status, action.last_error) == ("queued", "minimum_gap") and reminder_mails(remind) == []
    assert action.due_at > reminders.db_now() + timedelta(seconds=7000)


@pytest.mark.parametrize(("start", "end", "hour", "inside"), [(21, 7, 22, True), (21, 7, 3, True), (21, 7, 12, False),
                                                              (8, 17, 8, True), (8, 17, 17, False), (5, 5, 5, False)])
def test_p2_29_quiet_hours_wrap_midnight(settings, start, end, hour, inside):
    from datetime import datetime, timezone

    settings.CATALYST_REMINDER_QUIET_START_HOUR, settings.CATALYST_REMINDER_QUIET_END_HOUR = start, end
    assert (reminders.quiet_until(datetime(2026, 10, 13, hour, 30, tzinfo=timezone.utc)) is not None) is inside


# --- the watermark rule (4.1) ---------------------------------------------------------------------------------

def test_p2_28_a_reminder_waits_for_a_complete_collection_after_its_due_time(remind):
    question, _ = sent_question(remind)
    cursor = MailboxCursor.objects.get()
    for attempt in (1, 2, 3):
        PendingAction.objects.filter(kind="remind").update(due_at=Now())  # due after the last completed pass
        # A recent partial batch moves last_batch_at past the due time, but not the completed watermark.
        MailboxCursor.objects.filter(pk=cursor.pk).update(last_batch_at=Now() + timedelta(hours=1))
        cursor.refresh_from_db()
        assert cursor.complete_through_at < PendingAction.objects.get(kind="remind").due_at < cursor.last_batch_at
        run_worker()
        [action] = actions(question)
        assert (action.status, action.last_error) == ("queued", "watermark_stale")
        assert StaffItem.objects.filter(reason_code="collector_stale").exists() is (attempt == 3)
    assert reminder_mails(remind) == []
    fire()  # a completed pass after the due time releases it
    assert states(question)[0] == ("1", "done") and len(reminder_mails(remind)) == 1


# --- E3: the projection, and the reminder race ----------------------------------------------------------------

def test_p2_04_a_pending_reply_holds_the_reminder_and_staff_outcomes_release_or_cancel_it(remind):
    question, message = sent_question(remind)
    remind.imap.deliver(reply(message))
    collect()
    assert states(question) == [("1", "held")]  # held, never cancelled, by the reply alone
    fire()
    assert states(question) == [("1", "held")] and reminder_mails(remind) == []
    run_worker()  # process_reply: the reply goes to staff
    received = processing.InboundMessage.objects.get()
    processing.confirm_question_outcome(received.pk, {question.pk: "partial"}, remind.operator)
    assert states(question) == [("1", "queued")]  # a partial answer keeps reminders
    fire()
    assert states(question)[:1] == [("1", "done")] and len(reminder_mails(remind)) == 1
    remind.imap.deliver(reply(ApprovedMessage.objects.get(kind="reminder"), body="The rest of my answer."))
    collect()
    run_worker()
    assert states(question) == [("1", "done"), ("2", "held")]
    received = processing.InboundMessage.objects.order_by("-id").first()
    processing.confirm_question_outcome(received.pk, {question.pk: "satisfied"}, remind.operator)
    assert states(question) == [("1", "done"), ("2", "cancelled")]
    assert actions(question)[1].last_error == "question_satisfied"


def test_p2_04_a_reminder_claimed_while_a_reply_is_pending_is_held_by_the_handler(remind):
    question, message = sent_question(remind)
    remind.imap.deliver(reply(message))
    collect()
    PendingAction.objects.filter(kind="remind").update(status="queued")  # the race: projection not yet seen
    fire()
    [action] = actions(question)
    assert (action.status, action.last_error, action.attempts) == ("held", "reply_pending", 0)
    assert reminder_mails(remind) == []


def test_p2_30_the_projection_never_revives_finished_actions_or_creates_reminders(remind):
    question, _ = sent_question(remind)
    [action] = actions(question)
    PendingAction.objects.filter(pk=action.pk).update(attempts=2)  # an exhaustion count the projection must keep
    for status in ("done", "failed", "uncertain", "cancelled"):
        PendingAction.objects.filter(pk=action.pk).update(status=status)
        for to in ("open", "reply_pending", "partially_answered", "satisfied", "withdrawn"):
            assert scheduling.sync_reminders(question, to) == 0
        action.refresh_from_db()
        assert (action.status, action.attempts) == (status, 2)
    PendingAction.objects.filter(pk=action.pk).update(status="queued")
    for to in ("reply_pending", "open"):  # held, then queued again: counts are never reset
        scheduling.sync_reminders(question, to)
        action.refresh_from_db()
        assert action.attempts == 2
    assert len(actions(question)) == 1  # only E1 creates reminders


def test_p2_35_a_late_reply_to_a_satisfied_question_changes_nothing(remind):
    question, message = sent_question(remind)
    remind.imap.deliver(reply(message))
    collect()
    run_worker()
    processing.confirm_question_outcome(processing.InboundMessage.objects.get().pk, {question.pk: "satisfied"}, remind.operator)
    remind.imap.deliver(reply(message, body="One more thing."))
    collect()
    run_worker()
    question.refresh_from_db()
    assert question.status == "satisfied" and QuestionReplyLink.objects.filter(question=question).count() == 1
    assert states(question) == [("1", "cancelled")]


# --- 3.3: withdrawal ------------------------------------------------------------------------------------------

def test_p2_50_withdrawal_effects(remind):
    question, message = sent_question(remind)
    other, _ = sent_question(remind, text="A second synthetic question?")
    remind.imap.deliver(reply(message))
    collect()
    run_worker()
    received = processing.InboundMessage.objects.get()
    StaffItem.objects.create(reason_code="escalate_unanswered", dedupe_key=f"question:{question.public_id}",
                             application=remind.app, question_id=question.pk)
    withdrawn = staff_actions.withdraw_question(question.pk, remind.operator, "asked_in_error", "synthetic note")
    assert withdrawn.status == "withdrawn" and withdrawn.withdrawn_by == f"user:{remind.operator.pk}"
    assert withdrawn.withdrawn_reason == "asked_in_error: synthetic note"
    assert states(question) == [("1", "cancelled")] and actions(question)[0].last_error == "question_withdrawn"
    assert states(other) == [("1", "queued")]  # only that question's actions
    assert QuestionReplyLink.objects.get(question=question).state == "void_withdrawn"
    received.refresh_from_db()
    assert received.status == "awaiting_processing"  # the reply itself is never dropped
    assert PendingAction.objects.get(kind="interpret_reply").status == "cancelled"
    assert StaffItem.objects.get(reason_code="escalate_unanswered").status == "resolved"
    assert StaffItem.objects.get(reason_code="reply_needs_review").status == "open"
    assert ApplicationEvent.objects.filter(kind="question_withdrawn").count() == 1
    # A reply left with no pending link is closed through D4; withdrawal never counts as an answer.
    processing.close_reply_without_outcome(received.pk, remind.operator, reason="questions_withdrawn")
    assert StaffItem.objects.get(reason_code="reply_needs_review").status == "resolved"
    assert staff_actions.withdraw_question(question.pk, remind.operator, "asked_in_error").status == "withdrawn"
    from correspondence.inbound import refresh_question_status

    assert refresh_question_status(Question.objects.get(pk=question.pk)) == "withdrawn"  # never reopened
    remind.imap.deliver(reply(message, body="A late answer."))
    collect()
    run_worker()
    assert QuestionReplyLink.objects.filter(question=question).count() == 1  # a late reply changes nothing (P2-35)
    with pytest.raises(Refused, match="unknown_withdrawal_reason"):
        staff_actions.withdraw_question(other.pk, remind.operator, "because")


def test_p2_50_a_satisfied_question_is_not_withdrawn(remind):
    question, message = sent_question(remind)
    remind.imap.deliver(reply(message))
    collect()
    run_worker()
    processing.confirm_question_outcome(processing.InboundMessage.objects.get().pk, {question.pk: "satisfied"}, remind.operator)
    with pytest.raises(Refused, match="question_already_satisfied"):
        staff_actions.withdraw_question(question.pk, remind.operator, "no_longer_needed")


# --- F, E4: pause and resume ----------------------------------------------------------------------------------

def test_p2_05_a_pause_stops_every_automated_kind_and_resume_spreads_reminders_without_a_burst(remind, settings):
    settings.CATALYST_REMINDER_MIN_GAP_SECONDS = 600
    first, _ = sent_question(remind)
    PendingAction.objects.filter(kind="remind").update(due_at=Now() - timedelta(days=1))  # no gap pressure on q2
    second, _ = sent_question(remind, text="A second synthetic question?")
    staff_actions.pause(remind.app.pk, remind.operator, "synthetic pause for the test")
    assert staff_actions.pause(remind.app.pk, remind.operator, "a second pause changes nothing").reason.startswith("synthetic")
    third, queued = ask(remind, text="A third synthetic question?")
    fire()
    assert reminder_mails(remind) == [] and len(remind.server.messages) == 2  # nothing automated ran
    assert set(PendingAction.objects.filter(kind="remind").values_list("status", flat=True)) == {"queued"}
    assert PendingAction.objects.get(kind="send_message", input_ref=str(queued.send_ref)).status == "queued"
    statuses = {q.pk: q.status for q in Question.objects.all()}
    moved = staff_actions.resume(remind.app.pk, remind.operator, "back to normal")
    assert moved == 2 and not paused(remind)
    due = sorted(PendingAction.objects.filter(kind="remind").values_list("due_at", flat=True))
    now = reminders.db_now()
    assert [round((d - now).total_seconds() / 60) for d in due] == [1, 11]  # grace, then grace + 1 x gap
    assert {q.pk: q.status for q in Question.objects.all()} == statuses  # resume changes no question
    paused_event = ApplicationEvent.objects.get(kind="automation_paused")
    resumed_event = ApplicationEvent.objects.get(kind="automation_resumed")
    assert paused_event.data["reason"] == "synthetic pause for the test"  # kept after resume deletes the pause row
    assert resumed_event.data["pause_reason"] == "synthetic pause for the test" and resumed_event.data["note"] == "back to normal"
    assert ApplicationEvent.objects.filter(kind="automation_pause_requested_while_paused").count() == 1
    with pytest.raises(Refused, match="not_paused"):
        staff_actions.resume(remind.app.pk, remind.operator)
    run_worker()
    assert len(remind.server.messages) == 3  # the held-back question send goes out once


def test_p2_31_a_pause_during_a_running_reminder_and_resume_across_applications(remind, settings):
    question, _ = sent_question(remind)
    collect()
    PendingAction.objects.filter(kind="remind").update(due_at=MailboxCursor.objects.get().complete_through_at)
    claim = ledger.claim_next(ledger.handlers())
    assert claim.kind == "remind"
    staff_actions.pause(remind.app.pk, remind.operator, "paused while the reminder runs")
    reminders.SendReminder().run(claim)
    [action] = actions(question)
    assert (action.status, action.last_error, action.attempts) == ("queued", "automation_paused", 0)
    assert ApprovedMessage.objects.filter(kind="reminder").count() == 0
    # A second application, paused too: resuming one never touches the other's reminders.
    other_app = verified_application(email="bob@example.test")
    remind.app, first_app = other_app, remind.app
    other_q, _ = sent_question(remind)
    staff_actions.pause(other_app.pk, remind.operator, "second application paused")
    PendingAction.objects.filter(kind="remind").update(due_at=Now() - timedelta(minutes=5))
    staff_actions.resume(first_app.pk, remind.operator)
    mine, theirs = actions(question)[0], actions(other_q)[0]
    assert mine.due_at > reminders.db_now() and theirs.due_at < reminders.db_now()


# --- 3.4: staff messages --------------------------------------------------------------------------------------

def test_p2_11_a_confirmed_staff_message_is_sent_while_paused_and_nothing_automated_runs(remind):
    question, _ = sent_question(remind)
    staff_actions.pause(remind.app.pk, remind.operator, "staff take over this conversation")
    draft = staff_actions.preview_staff_message(remind.app.pk, remind.operator, "About your application",
                                                "Hello, a synthetic note from staff.")
    assert draft.recipient == "ada@example.test" and ApprovedMessage.objects.filter(kind="staff_message").count() == 0
    message = staff_actions.confirm_staff_message(draft.pk, draft.content_sha256, remind.operator)
    fire()
    message.refresh_from_db()
    assert message.disposition == "accepted_by_server"
    sent = remind.server.parsed(len(remind.server.messages) - 1)
    assert sent["Subject"] == "About your application" and sent["Auto-Submitted"] is None
    assert reminder_mails(remind) == [] and states(question) == [("1", "queued")]  # no reminder ran or was created
    assert paused(remind)  # a staff message never resumes automation
    assert PendingAction.objects.get(input_ref=str(message.send_ref)).kind == "send_staff_message"


@pytest.mark.parametrize(("tamper", "code"), [("digest", "digest_mismatch"), ("address", "recipient_no_longer_verified"),
                                              ("permission", None), ("twice", "draft_already_confirmed"),
                                              ("author", "only_the_author_confirms"), ("expired", "preview_expired")])
def test_p2_45_confirmation_refuses_any_change_since_the_preview(remind, tamper, code):
    draft = staff_actions.preview_staff_message(remind.app.pk, remind.operator, "Subject", "A synthetic body.")
    digest, user = draft.content_sha256, remind.operator
    if tamper == "digest":
        digest = "0" * 64
    elif tamper == "address":
        Application.objects.filter(pk=remind.app.pk).update(contact_verified_at=None)
    elif tamper == "permission":
        owner = remind.committed.connect("owner", autocommit=True)
        owner.execute("DELETE FROM accounts_user_groups WHERE user_id = %s", [user.pk])
        user = type(user).objects.get(pk=user.pk)
    elif tamper == "twice":
        staff_actions.confirm_staff_message(draft.pk, digest, user)
    elif tamper == "author":
        user = remind.decider
    elif tamper == "expired":
        owner = remind.committed.connect("owner", autocommit=True)
        owner.execute("UPDATE correspondence_staffmessagedraft SET created_at = now() - interval '2 hours' WHERE id = %s",
                      [draft.pk])
    before = PendingAction.objects.filter(kind="send_staff_message").count()
    with pytest.raises(PermissionDenied if code is None else Refused, match=code):
        staff_actions.confirm_staff_message(draft.pk, digest, user)
    assert PendingAction.objects.filter(kind="send_staff_message").count() == before


@pytest.mark.parametrize(("subject", "body", "code"), [
    ("Subject", "Use this link: http://catalyst.example.test/confirm/abc/", "confirmation_link"),
    ("Subject", "Use http://catalyst.example.test/%63onfirm/abc/ instead", "confirmation_link"),
    ("Subject", "nbsp\u0085 next line", "control_characters"),
    ("Subject", "password: hunter2-synthetic", "credential_like"),
    ("Subject", "key " + "A" * 48, "credential_like"),
    ("Line\nbreak", "Body", "control_characters"),
    ("Subject", "bidi ‮ text", "control_characters"),
    ("", "Body", "subject_and_body"),
])
def test_p2_45_content_checks_refuse_links_credentials_and_controls(remind, subject, body, code):
    with pytest.raises(Refused, match=code):
        staff_actions.preview_staff_message(remind.app.pk, remind.operator, subject, body)
    assert StaffMessageDraft.objects.count() == 0


def test_p2_45_a_staff_message_cannot_reach_a_non_test_host(remind, settings):
    from config import guards

    settings.CATALYST_MAIL_HOST = "smtp.example.com"
    assert any("CATALYST_MAIL_HOST" in p for p in guards.mail_problems(settings))


# --- TEST-P2-52: the 2B.4 services need their roles ----------------------------------------------------------

def test_p2_52_each_2b4_service_needs_its_permission_and_a_superuser_is_refused(remind):
    question, _ = sent_question(remind)
    nobody = staff(remind, "nobody")
    root = staff(remind, "root", superuser=True)
    for user in (nobody, root):
        with pytest.raises(PermissionDenied):
            staff_actions.pause(remind.app.pk, user, "a long enough reason")
        with pytest.raises(PermissionDenied):
            staff_actions.resume(remind.app.pk, user)
        with pytest.raises(PermissionDenied):
            staff_actions.withdraw_question(question.pk, user, "asked_in_error")
        with pytest.raises(PermissionDenied):
            staff_actions.preview_staff_message(remind.app.pk, user, "Subject", "Body")
    with pytest.raises(Refused, match="pause_reason_too_short"):
        staff_actions.pause(remind.app.pk, remind.operator, "short")


# --- G4 to G7 -------------------------------------------------------------------------------------------------

def test_g4_g5_g6_reminder_health_reports_each_seeded_anomaly(remind, settings):
    question, _ = sent_question(remind)
    assert reminder_health()["anomalies"] == []
    PendingAction.objects.filter(kind="remind").update(due_at=Now() - timedelta(days=1))
    assert "overdue_reminders" in reminder_health()["anomalies"]
    PendingAction.objects.filter(kind="remind").update(status="held")
    assert "held_reminder_not_reply_pending" in reminder_health()["anomalies"]
    PendingAction.objects.filter(kind="remind").update(status="cancelled")
    assert "question_without_live_reminder" in reminder_health()["anomalies"]
    PendingAction.objects.filter(kind="remind").update(status="queued")
    Question.objects.filter(pk=question.pk).update(status="withdrawn")
    assert "live_reminder_on_withdrawn_question" in reminder_health()["anomalies"]
    staff_actions.pause(remind.app.pk, remind.operator, "seeded pause for G5")
    report = reminder_health()
    assert report["paused_applications"] == 1 and report["oldest_pause"] is not None


def test_g7_mail_behaviour_health(remind):
    _, message = sent_question(remind)
    for n in range(3):
        remind.imap.deliver(reply(message, headers=["Auto-Submitted: auto-replied"], body=f"away {n}"))
    collect()
    report = mail_behaviour_health()
    assert report["max_automatic_per_application"] == 3 and report["anomalies"] == ["automatic_mail_at_loop_threshold"]
    assert report["inbound_received_in_window"] == 3 and report["automatic_unassociated"] == 0


def test_resolving_an_escalation_needs_resolve_exception(remind):
    question, _ = sent_question(remind)
    fire()
    fire()
    fire()
    [item] = StaffItem.objects.filter(reason_code="escalate_unanswered")
    processing.resolve_exception(item.pk, "acknowledge", remind.operator)
    assert StaffItemResolution.objects.filter(item=item).exists()



# --- review fixes (QA, correspondence, security and monitoring reviews of PR #24) --------------------------

def test_e2_reminders_due_together_never_leave_in_a_burst(remind, settings):
    settings.CATALYST_REMINDER_MIN_GAP_SECONDS = 3600
    first, _ = sent_question(remind)
    second, _ = sent_question(remind, text="A second synthetic question?")
    owner = remind.committed.connect("owner", autocommit=True)  # age the earlier mail past the gap
    owner.execute("UPDATE correspondence_outboundmessage SET server_accepted_at = now() - interval '2 hours'")
    owner.execute("UPDATE correspondence_approvedmessage SET authorized_at = now() - interval '2 hours'")
    fire()
    assert len(reminder_mails(remind)) == 1  # the second waits for the gap after the first is frozen
    deferred = [a for a in PendingAction.objects.filter(kind="remind") if a.last_error == "minimum_gap"]
    assert len(deferred) == 1 and deferred[0].due_at > reminders.db_now() + timedelta(minutes=55)


def test_e2_a_frozen_reminder_send_follows_its_question(remind, settings):
    question, message = sent_question(remind)
    staff_actions.pause(remind.app.pk, remind.operator, "hold the reminder mail")
    collect()
    PendingAction.objects.filter(kind="remind").update(due_at=MailboxCursor.objects.get().complete_through_at)
    AutomationPause.objects.all().delete()
    reminders.SendReminder().run(ledger.claim_next(ledger.handlers()))  # frozen and queued, not yet sent
    send = PendingAction.objects.get(kind="send_message", input_ref=str(ApprovedMessage.objects.get(kind="reminder").send_ref))
    PendingAction.objects.filter(pk=send.pk).update(due_at=Now() + timedelta(hours=1))  # it waits (backoff, say)
    remind.imap.deliver(reply(message))
    collect()  # the reply arrives while the reminder mail waits
    PendingAction.objects.filter(pk=send.pk).update(due_at=Now())
    run_worker()
    send.refresh_from_db()
    assert (send.status, send.last_error) == ("queued", "reply_pending") and reminder_mails(remind) == []
    received = processing.InboundMessage.objects.get()
    processing.confirm_question_outcome(received.pk, {question.pk: "satisfied"}, remind.operator)
    PendingAction.objects.filter(pk=send.pk).update(due_at=Now())
    run_worker()
    send.refresh_from_db()
    assert (send.status, send.last_error) == ("cancelled", "question_satisfied") and reminder_mails(remind) == []


def test_e2_an_unapproved_reminder_template_waits_for_staff_and_the_chain_survives(remind):
    question, _ = sent_question(remind)
    MessageTemplateVersion.objects.filter(template__key="question_reminder").update(status="retired")
    fire()
    [action] = actions(question)
    assert (action.status, action.last_error, action.attempts) == ("queued", "no_approved_reminder_template", 0)
    assert StaffItem.objects.filter(reason_code="reminder_refused", status="open").count() == 1
    MessageTemplateVersion.objects.filter(template__key="question_reminder").update(status="approved")
    fire()
    assert states(question)[0] == ("1", "done") and len(reminder_mails(remind)) == 1


def test_e1_a_released_reminder_waits_at_least_the_grace(remind):
    question, message = sent_question(remind)
    remind.imap.deliver(reply(message))
    collect()
    PendingAction.objects.filter(kind="remind").update(due_at=Now() - timedelta(days=1))  # long overdue while held
    processing.confirm_question_outcome(processing.InboundMessage.objects.get().pk, {question.pk: "partial"}, remind.operator)
    [action] = actions(question)
    assert action.status == "queued" and action.due_at > reminders.db_now() + timedelta(seconds=50)


def test_e2_an_incomplete_cursor_makes_the_watermark_stale(remind):
    question, _ = sent_question(remind)
    collect()
    MailboxCursor.objects.create(mailbox_ref="applicants", folder="Other", state="ok")  # never completed a pass
    PendingAction.objects.filter(kind="remind").update(due_at=MailboxCursor.objects.get(folder="INBOX").complete_through_at)
    run_worker()
    assert actions(question)[0].last_error == "watermark_stale"


def test_reconciliation_is_not_held_by_a_pause():
    from correspondence.outbound import ReconcileSend

    assert ReconcileSend.automated is False  # it sends nothing; an unknown staff send stays reconcilable


def test_g4_ignores_closed_applications_and_a_reminder_still_in_flight(remind):
    question, _ = sent_question(remind)
    PendingAction.objects.filter(kind="remind").update(status="done")
    ApprovedMessage.objects.create(kind="reminder", application=remind.app, recipient="ada@example.test",
                                   template_version=MessageTemplateVersion.objects.get(template__key="question_reminder"),
                                   frozen_subject="s", frozen_body="b", content_sha256="0" * 64, authorized_by="test",
                                   authority="system_policy")
    from correspondence.models import ApprovedMessageQuestion

    ApprovedMessageQuestion.objects.create(approved_message=ApprovedMessage.objects.get(kind="reminder"), question=question,
                                           purpose="reminder")
    assert "question_without_live_reminder" not in reminder_health()["anomalies"]  # its mail is still in flight
    ApprovedMessage.objects.filter(kind="reminder").update(disposition="accepted_by_server")
    assert "question_without_live_reminder" in reminder_health()["anomalies"]
    Application.objects.filter(pk=remind.app.pk).update(stage="closed")
    assert "question_without_live_reminder" not in reminder_health()["anomalies"]


def test_health_command_exit_codes(remind, monkeypatch):
    from django.core.management import call_command

    from correspondence import health
    from correspondence.management.commands import correspondence_health as command

    def broken():
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(command, "send_health", broken)
    with pytest.raises(SystemExit) as exit_info:
        call_command("correspondence_health")
    assert exit_info.value.code == 2  # a failed check is never reported as a health anomaly
    assert health.send_health  # untouched



def test_p2_54_36_a_staff_message_and_a_reply_to_address_change_no_identity_and_no_recipient(remind):
    question, message = sent_question(remind)
    adoption = remind.app.adoptions.get().pk
    remind.imap.deliver(reply(message, headers=["Reply-To: elsewhere@example.test"]))
    collect()
    processing.confirm_question_outcome(processing.InboundMessage.objects.get().pk, {question.pk: "partial"}, remind.operator)
    draft = staff_actions.preview_staff_message(remind.app.pk, remind.operator, "Subject", "Body")
    staff_actions.confirm_staff_message(draft.pk, draft.content_sha256, remind.operator)
    PendingAction.objects.filter(kind="remind").update(due_at=Now())
    fire()
    app = Application.objects.get(pk=remind.app.pk)
    assert (app.stage, app.contact_verified_at is not None, app.adoptions.get().pk) == (remind.app.stage, True, adoption)
    assert {m["rcpts"][0] for m in remind.server.messages} == {"ada@example.test"}  # never Reply-To or From


def test_p2_50_withdrawal_cancels_held_reminders_and_the_escalation(remind):
    question, message = sent_question(remind)
    remind.imap.deliver(reply(message))
    collect()
    PendingAction.objects.create(kind="escalate_unanswered", subject_type="application", subject_id=remind.app.public_ref,
                                 input_ref=str(question.public_id), idempotency_key=scheduling.escalate_key(question),
                                 status="held")
    assert {a.status for a in PendingAction.objects.filter(kind__in=scheduling.REMINDER_KINDS)} == {"held"}
    staff_actions.withdraw_question(question.pk, remind.operator, "no_longer_needed")
    assert set(PendingAction.objects.filter(kind__in=scheduling.REMINDER_KINDS).values_list("status", "last_error")) == {
        ("cancelled", "question_withdrawn")}


# --- GATE-P2 closeout (owner directive 2026-10-13) --------------------------------------------------------------

def test_p2_08_two_questions_in_separate_messages_a_partial_then_full_answer_touches_only_the_first(remind):
    first, first_message = sent_question(remind)
    second, _ = sent_question(remind, text="A second synthetic question?")
    second_reminder = actions(second)[0]
    remind.imap.deliver(reply(first_message, body="Part of the first answer."))
    collect()
    received = processing.InboundMessage.objects.get()
    processing.confirm_question_outcome(received.pk, {first.pk: "partial"}, remind.operator)
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, second.status) == ("partially_answered", "open")
    assert states(first) == [("1", "queued")] and states(second) == [("1", "queued")]
    assert actions(second)[0].due_at == second_reminder.due_at  # the second's reminder is untouched
    remind.imap.deliver(reply(first_message, body="The rest of the first answer."))
    collect()
    received = processing.InboundMessage.objects.order_by("-id").first()
    processing.confirm_question_outcome(received.pk, {first.pk: "satisfied"}, remind.operator)
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, second.status) == ("satisfied", "open")  # only the first is satisfied
    assert states(first) == [("1", "cancelled")] and states(second) == [("1", "queued")]
    app = Application.objects.get(pk=remind.app.pk)
    assert app.stage == remind.app.stage  # no application-wide completion
    assert not StaffItem.objects.filter(question_id=second.pk).exists()
    assert QuestionReplyLink.objects.filter(question=second).count() == 0


# Reminder races (016 E2, E3, section 5) on separate connections. A controlled lock holder (an application-role
# session holding the application row) lets the reply ingestion and the reminder or send check queue in a
# chosen order; releasing it decides which commits first. No two coordinated sessions ever hold the same lock.

def _lock_holder(env):
    holder = env.committed.connect("app")
    holder.execute("SELECT id FROM applications_application WHERE id = %s FOR UPDATE", [env.app.pk])
    return holder


def _in_thread(env, errors, fn, *args):
    def run():
        try:
            fn(*args)
        except Exception as exc:  # a deadlock or any other error fails the test below
            errors.append(repr(exc))
    return env.committed.thread(run)


def _race(env, first, second):
    """Queue `first` then `second` behind the held application lock, release, and join both."""
    from tests.test_intake import wait_for_waiters

    monitor = env.committed.connect("app", autocommit=True)
    holder, errors = _lock_holder(env), []
    threads = [_in_thread(env, errors, first)]
    wait_for_waiters(monitor, 1)
    threads.append(_in_thread(env, errors, second))
    wait_for_waiters(monitor, 2)
    holder.rollback()  # releases the lock: the first waiter proceeds first
    for t in threads:
        t.join(timeout=60)
        assert not t.is_alive(), "a racing transaction did not finish"
    assert errors == []  # no deadlock, no error in either transaction


def _due_reminder(env):
    """Reminder 1 due exactly at a completed watermark, claimed now (so the collector cannot take it)."""
    collect()
    PendingAction.objects.filter(kind="remind").update(due_at=MailboxCursor.objects.get().complete_through_at)
    claim = ledger.claim_next({"remind": reminders.SendReminder()})
    assert claim is not None and claim.kind == "remind"
    return claim


def _collect_reply():
    collect()


def test_reminder_race_the_reply_commits_before_the_reminder_check_so_no_reminder(remind):
    question, message = sent_question(remind)
    claim = _due_reminder(remind)
    remind.imap.deliver(reply(message))
    _race(remind, _collect_reply, lambda: reminders.SendReminder().run(claim))
    question.refresh_from_db()
    [action] = actions(question)
    assert question.status == "reply_pending" and (action.status, action.last_error) == ("held", "reply_pending")
    assert ApprovedMessage.objects.filter(kind="reminder").count() == 0 and reminder_mails(remind) == []


def test_reminder_race_the_reminder_check_commits_first_and_its_frozen_send_then_respects_the_reply(remind):
    question, message = sent_question(remind)
    claim = _due_reminder(remind)
    remind.imap.deliver(reply(message))
    _race(remind, lambda: reminders.SendReminder().run(claim), _collect_reply)
    question.refresh_from_db()
    assert question.status == "reply_pending"
    assert states(question) == [("1", "done")]  # authorized once; no second reminder was scheduled
    [frozen] = ApprovedMessage.objects.filter(kind="reminder")
    run_worker()
    send = PendingAction.objects.get(kind="send_message", input_ref=str(frozen.send_ref))
    assert (send.status, send.last_error) == ("queued", "reply_pending") and reminder_mails(remind) == []
    processing.confirm_question_outcome(processing.InboundMessage.objects.get().pk, {question.pk: "satisfied"}, remind.operator)
    PendingAction.objects.filter(pk=send.pk).update(due_at=Now())
    run_worker()
    send.refresh_from_db()
    question.refresh_from_db()
    assert question.status == "satisfied" and send.status == "cancelled" and reminder_mails(remind) == []
    assert states(question) == [("1", "done")] and ApprovedMessage.objects.filter(kind="reminder").count() == 1


def _frozen_reminder_send(env):
    """A reminder already frozen with its send queued, then claimed now."""
    claim = _due_reminder(env)
    reminders.SendReminder().run(claim)
    frozen = ApprovedMessage.objects.get(kind="reminder")
    send_claim = ledger.claim_next({"send_message": outbound.SendMessage()})
    assert send_claim is not None and send_claim.input_ref == str(frozen.send_ref)
    return frozen, send_claim


def test_reminder_race_a_reply_committed_before_the_frozen_send_check_holds_the_mail(remind):
    question, message = sent_question(remind)
    frozen, send_claim = _frozen_reminder_send(remind)
    remind.imap.deliver(reply(message))
    _race(remind, _collect_reply, lambda: outbound.SendMessage().run(send_claim))
    send = PendingAction.objects.get(pk=send_claim.id)
    assert (send.status, send.last_error) == ("queued", "reply_pending") and reminder_mails(remind) == []
    assert states(question) == [("1", "done")]  # nothing new scheduled


def test_reminder_race_a_frozen_send_past_its_check_completes_once_and_later_reminders_respect_the_reply(remind):
    question, message = sent_question(remind)
    frozen, send_claim = _frozen_reminder_send(remind)
    remind.imap.deliver(reply(message))
    _race(remind, lambda: outbound.SendMessage().run(send_claim), _collect_reply)
    frozen.refresh_from_db()
    question.refresh_from_db()
    assert frozen.disposition == "accepted_by_server" and len(reminder_mails(remind)) == 1  # the authorized send, once
    assert question.status == "reply_pending"
    assert states(question) == [("1", "done"), ("2", "held")]  # the next reminder exists and waits for the reply
    fire()
    assert len(reminder_mails(remind)) == 1 and states(question) == [("1", "done"), ("2", "held")]


def test_p2_45_a_confirmed_staff_message_to_a_non_test_host_is_refused_before_any_connection(remind, settings, monkeypatch):
    """The protection's boundary: transport.send refuses a host that is not a loopback literal or the named test
    host before opening a socket, so no credential, envelope or content can be transmitted. (The start-up
    guards refuse the same configuration earlier; here it is changed after start-up.)"""
    import socket

    draft = staff_actions.preview_staff_message(remind.app.pk, remind.operator, "Subject", "A synthetic body.")
    message = staff_actions.confirm_staff_message(draft.pk, draft.content_sha256, remind.operator)
    before = list(remind.server.commands)
    settings.CATALYST_MAIL_HOST = "smtp.example.com"
    opened = []
    real = socket.create_connection
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: opened.append(a) or real(*a, **k))
    run_worker()
    message.refresh_from_db()
    assert opened == [] and remind.server.commands == before  # no connection, so no AUTH, MAIL or DATA
    assert message.disposition == "transport_blocked"
    assert StaffItem.objects.filter(approved_message=message, reason_code="smtp_transport_blocked").count() == 1

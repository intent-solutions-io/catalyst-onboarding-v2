"""P2 task 2B.3, reply processing and staff resolution (016 section 4 D and C4, F, 3.8; owner decisions D-27, D-28,
D-30, D-31): TEST-P2-02, 06, 08 to 10, 32 to 34, 43, 44, 53, 54, the 2B.3 services of 52, G2 and G6 for
questions, and staff attention reading open staff items (M9, 2B.3 part).

Synthetic only, against the scripted SMTP and IMAP servers of tests/test_inbound.py.
"""

import threading
import uuid
from pathlib import Path

import pytest
from django.apps import apps
from django.core.exceptions import PermissionDenied

from applications import staff as staff_view
from applications.models import Application, VersionAdoption
from correspondence import processing
from correspondence.health import reply_health
from correspondence.models import InboundMessage, Question, QuestionReplyLink, StaffItem, StaffItemResolution
from correspondence.outbound import Refused
from tests import support
from tests.test_inbound import collect, mailbox, reply, sent_question, tls  # noqa: F401  (fixtures and helpers)
from tests.test_outbound import p2, ready, run_worker, staff  # noqa: F401
from workflow.models import AutomationPause, PendingAction


def processed():
    run_worker()  # process_reply actions run in the worker; held interpret_reply actions never do


def delivered(env, **kwargs):
    question, message = sent_question(env)
    env.imap.deliver(reply(message, **kwargs))
    collect()
    processed()
    return question, message, InboundMessage.objects.order_by("-id").first()


def bounce(message, status="5.1.1", recipient="ada@example.test"):
    from correspondence.outbound import message_id

    return (b"From: MAILER-DAEMON@synthetic.example.test\r\nMessage-ID: <" + uuid.uuid4().hex.encode()
            + b"@synthetic.example.test>\r\nMIME-Version: 1.0\r\n"
            b"Content-Type: multipart/report; report-type=delivery-status; boundary=r\r\n\r\n"
            b"--r\r\nContent-Type: text/plain\r\n\r\nDelivery report.\r\n"
            b"--r\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; synthetic.example.test\r\n\r\n"
            b"Final-Recipient: rfc822; " + recipient.encode() + b"\r\nAction: failed\r\nStatus: " + status.encode() + b"\r\n\r\n"
            b"--r\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: " + message_id(message.send_ref).encode()
            + b"\r\n\r\n--r--\r\n")


def paused(env):
    return AutomationPause.objects.filter(subject_type="application", subject_id=env.app.public_ref).exists()


# --- D1: automatic messages, loops, bounces -------------------------------------------------------------------

def test_p2_10_02_a_single_autoresponder_is_classified_never_answered_and_neither_suppresses_nor_pauses(mailbox):
    question, _, received = delivered(mailbox, headers=["Auto-Submitted: auto-replied"], body="I am away.")
    question.refresh_from_db()
    assert (received.classification, received.status) == ("automatic", "automated_reply")
    assert question.status == "open" and QuestionReplyLink.objects.count() == 0
    assert not paused(mailbox) and not StaffItem.objects.filter(reason_code="loop_threshold").exists()
    assert len(mailbox.server.messages) == 1  # never answered


def test_p2_34_02_the_loop_threshold_pauses_automation_and_opens_a_staff_item(mailbox):
    _, message = sent_question(mailbox)
    for _ in range(3):
        mailbox.imap.deliver(reply(message, headers=["Auto-Submitted: auto-replied"], body=f"away {uuid.uuid4().hex}"))
    collect()
    processed()
    assert paused(mailbox)
    assert StaffItem.objects.filter(reason_code="loop_threshold", status="open").count() == 1


@pytest.mark.parametrize(("status", "recipient", "pauses"), [("5.1.1", "ada@example.test", True),
                                                             ("4.2.2", "ada@example.test", False),
                                                             ("5.1.1", "someone-else@example.test", False)],
                         ids=["hard", "soft", "forged-recipient"])
def test_p2_33_only_a_hard_bounce_for_our_message_and_the_verified_recipient_pauses(mailbox, status, recipient, pauses):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(bounce(message, status, recipient))
    collect()
    processed()
    received = InboundMessage.objects.get()
    assert (received.classification, received.status) == ("bounce", "processed")
    assert paused(mailbox) is pauses
    assert StaffItem.objects.filter(reason_code="hard_bounce").exists() is pauses


# --- D2, D3, D4: a person's reply and staff decisions ----------------------------------------------------------

def test_p2_43_a_persons_reply_holds_interpretation_for_p3_and_asks_staff(mailbox):
    question, _, received = delivered(mailbox)
    [held] = PendingAction.objects.filter(kind="interpret_reply")
    assert held.status == "held" and held.input_ref == f"{received.public_id}:{question.public_id}"
    processed()
    held.refresh_from_db()
    assert held.status == "held"  # never claimed: no handler, and held is never claimable
    assert received.status == "awaiting_processing"
    assert StaffItem.objects.filter(reason_code="reply_needs_review", status="open").count() == 1


def test_p2_43_correspondence_imports_no_model_client():
    for path in Path(support.ROOT, "correspondence").rglob("*.py"):
        text = path.read_text().lower()
        for banned in ("pydantic_ai", "import openai", "import anthropic", "minimax", "from openai", "from anthropic"):
            assert banned not in text, (path.name, banned)


@pytest.mark.parametrize(("outcome", "status"), [("satisfied", "satisfied"), ("partial", "partially_answered"),
                                                  ("not_addressed", "open")])
def test_p2_08_09_staff_confirm_each_outcome_and_a_reply_never_satisfies_by_itself(mailbox, outcome, status):
    question, _, received = delivered(mailbox)
    question.refresh_from_db()
    assert question.status == "reply_pending"  # not satisfied by the reply alone
    processing.confirm_question_outcome(received.pk, {question.pk: outcome}, mailbox.operator, note="synthetic")
    question.refresh_from_db()
    received.refresh_from_db()
    assert question.status == status and received.status == "processed"
    assert PendingAction.objects.get(kind="interpret_reply").status == "cancelled"
    [item] = StaffItem.objects.filter(reason_code="reply_needs_review")
    assert item.status == "resolved" and StaffItemResolution.objects.get(item=item).resolution_code == "confirmed"
    assert Application.objects.get(pk=mailbox.app.pk).stage == mailbox.app.stage  # P2 changes no stage (ADR-13)


def test_p2_32_staff_confirmation_and_process_reply_race_and_exactly_one_decides(mailbox):
    question, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message))
    collect()  # the worker also runs process_reply: interpretation is held and staff are asked
    received = InboundMessage.objects.get()
    results, barrier = [], threading.Barrier(2)

    def confirm():
        barrier.wait(10)
        try:
            processing.confirm_question_outcome(received.pk, {question.pk: "satisfied"}, mailbox.operator)
            results.append("confirmed")
        except Refused as exc:
            results.append(str(exc))
    threads = [mailbox.committed.thread(confirm) for _ in range(2)]
    for t in threads:
        t.join(30)
    assert sorted(results) == ["confirmed", "reply_already_decided"]
    # A process_reply that runs after the decision (re-queued here) finds the reply decided and does nothing.
    from django.db.models.functions import Now

    PendingAction.objects.filter(kind="process_reply").update(status="queued", due_at=Now(), attempts=0)
    processed()
    question.refresh_from_db()
    assert question.status == "satisfied"
    assert not PendingAction.objects.filter(kind="interpret_reply", status="held").exists()
    assert StaffItem.objects.filter(reason_code="reply_needs_review", status="open").count() == 0


def test_d4_a_reply_with_pending_questions_cannot_be_closed_without_outcomes(mailbox):
    _, _, received = delivered(mailbox)
    with pytest.raises(Refused, match="pending_questions_need_outcomes"):
        processing.close_reply_without_outcome(received.pk, mailbox.operator)


# --- C4 and F: exception resolution ----------------------------------------------------------------------------

def test_p2_06_53_an_unmatched_message_is_resolved_without_ssh_and_leaves_a_record_without_an_application(mailbox):
    _, message = sent_question(mailbox)
    applications_before = Application.objects.count()
    mailbox.imap.deliver(reply(message, in_reply_to=False))
    collect()
    [item] = StaffItem.objects.filter(reason_code="unmatched")
    assert item.application_id is None
    processing.resolve_exception(item.pk, "dismiss", mailbox.operator, note="synthetic spam")
    item.refresh_from_db()
    resolution = StaffItemResolution.objects.get(item=item)
    assert item.status == "resolved" and resolution.resolution_code == "dismiss" and resolution.note == "synthetic spam"
    assert InboundMessage.objects.get().status == "processed"
    assert Application.objects.count() == applications_before  # no dummy application
    conn = mailbox.committed.connect("app")
    from psycopg import errors

    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute("UPDATE correspondence_staffitemresolution SET resolution_code = 'x'")
    conn.rollback()


def test_p2_54_associating_an_unverified_reply_needs_the_decision_maker_and_changes_no_identity(mailbox):
    question, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, auth=None))  # unverified: no effect until staff associate it
    collect()
    [item] = StaffItem.objects.filter(reason_code="reply_unverified")
    adoption_before = list(VersionAdoption.objects.values_list("id", "via_challenge_id", "submission_version_id"))
    app_before = Application.objects.filter(pk=mailbox.app.pk).values("email", "email_key", "stage", "contact_verified_at").get()
    with pytest.raises(PermissionDenied):
        processing.resolve_exception(item.pk, "associate", mailbox.operator)
    processing.resolve_exception(item.pk, "associate", mailbox.decider)
    question.refresh_from_db()
    assert question.status == "reply_pending"  # now it behaves as trusted, for this message only
    assert InboundMessage.objects.get().trust_decision == "staff_associated"
    assert list(VersionAdoption.objects.values_list("id", "via_challenge_id", "submission_version_id")) == adoption_before
    assert Application.objects.filter(pk=mailbox.app.pk).values("email", "email_key", "stage", "contact_verified_at").get() == app_before
    processed()
    assert StaffItem.objects.filter(reason_code="reply_needs_review", status="open").count() == 1


def test_c4_resolution_codes_are_an_allow_list_per_reason(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, sender="someone-else@example.test"))
    collect()
    [item] = StaffItem.objects.filter(reason_code="sender_mismatch")
    with pytest.raises(Refused, match="not_allowed"):
        processing.resolve_exception(item.pk, "associate", mailbox.decider)  # a mismatched sender is never associated
    processing.resolve_exception(item.pk, "mark_spoof", mailbox.decider)
    assert StaffItemResolution.objects.get(item=item).resolution_code == "mark_spoof"


def test_d4_an_associated_unmatched_reply_without_questions_is_closed_by_staff(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, in_reply_to=False))
    collect()
    [item] = StaffItem.objects.filter(reason_code="unmatched")
    processing.resolve_exception(item.pk, "associate", mailbox.decider, target_application_id=mailbox.app.pk)
    processed()
    received = InboundMessage.objects.get()
    assert received.status == "awaiting_processing" and QuestionReplyLink.objects.count() == 0
    processing.close_reply_without_outcome(received.pk, mailbox.operator)
    received.refresh_from_db()
    assert received.status == "processed"
    assert StaffItem.objects.filter(reason_code="reply_needs_review", status="open").count() == 0


def test_p2_52_each_2b3_service_needs_its_role(mailbox):
    question, _, received = delivered(mailbox)
    reader = staff(mailbox, "reader", "Read-only staff")
    superuser = staff(mailbox, "root", superuser=True)
    for user in (reader, superuser, mailbox.owner):
        with pytest.raises(PermissionDenied):
            processing.confirm_question_outcome(received.pk, {question.pk: "satisfied"}, user)
    processing.confirm_question_outcome(received.pk, {question.pk: "satisfied"}, mailbox.decider)


# --- 3.8, M9 (2B.3 part): staff attention reads open staff items ----------------------------------------------

def test_m9_staff_attention_reads_open_items_and_resolving_clears_it(mailbox):
    from django.test import Client
    from urllib.parse import urlencode

    from django.urls import reverse

    Client().post(reverse("applications:request_access"), urlencode({"name": "Ada Example", "email": "ada@example.test",
                                                                     "reason": "A repeat after verification."}),
                  content_type="application/x-www-form-urlencoded")
    [item] = StaffItem.objects.filter(reason_code="repeat_after_verification")
    assert item.application_id == mailbox.app.pk and item.dedupe_key.startswith("event:")
    flagged = lambda: Application.objects.filter(staff_view.attention_q(), pk=mailbox.app.pk).exists()  # noqa: E731
    assert flagged()
    assert "(version 2)" in staff_view.describe_attention(item)
    processing.resolve_exception(item.pk, "acknowledge", mailbox.decider)
    assert not flagged()


def test_m9_the_migration_opens_one_item_for_each_earlier_attention_event(mailbox):
    import importlib

    from applications.models import ApplicationEvent

    event = ApplicationEvent.objects.create(application=mailbox.app, kind="needs_staff_attention", actor_type="system",
                                            data={"reason": "repeat_after_verification", "version_number": 9})
    migration = importlib.import_module("correspondence.migrations.0008_reply_processing_groups_and_s1_items")
    migration.open_items_for_s1_events(apps, None)
    migration.open_items_for_s1_events(apps, None)  # idempotent
    assert StaffItem.objects.filter(dedupe_key=f"event:{event.pk}", status="open").count() == 1


# --- quote stripping (TEST-P2-44) and health (G2, G6) ----------------------------------------------------------

@pytest.mark.parametrize(("text", "stripped"), [
    ("My answer.\n\nOn Tue, 13 Oct 2026, Catalyst wrote:\n> the question\n", "My answer."),
    ("Line one\n> quoted\nLine two", "Line one\nLine two"),
    ("Answer\n-----Original Message-----\nold text", "Answer"),
    ("> only quoted", ""),
])
def test_p2_44_quote_stripping_golden_cases(text, stripped):
    assert processing.QUOTE_STRIP_VERSION == 1
    assert processing.strip_quotes(text) == stripped


def test_g2_g6_reply_health(mailbox):
    question, _, received = delivered(mailbox)
    report = reply_health()
    assert report["awaiting_processing"] == 1 and report["anomalies"] == []
    owner = mailbox.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE correspondence_questionreplylink SET state = 'applied'")  # an inconsistency, seeded
    assert reply_health()["anomalies"] == ["reply_pending_without_link"]

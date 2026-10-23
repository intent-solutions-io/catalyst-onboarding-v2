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
    received.refresh_from_db()
    pin = f"{received.derived_text_sha256[:16]}:{received.derivation_version}.{received.redaction_version}"
    assert held.status == "held" and held.input_ref == f"{received.public_id}:{question.public_id}:{pin}"
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



# --- review fixes (QA, architecture, data and P3-interface reviews of PR #23) ----------------------------------

def test_a_reply_whose_processing_fails_finally_goes_to_staff_not_silence(mailbox, monkeypatch):
    def defect(self, application, message):
        raise RuntimeError("simulated handler defect")
    monkeypatch.setattr(processing.ProcessReply, "_person", defect)
    question, _, received = delivered(mailbox)
    received.refresh_from_db()
    assert (received.status, received.exception_reason) == ("exception", "processing_error")
    [item] = StaffItem.objects.filter(reason_code="processing_error", status="open")
    processing.resolve_exception(item.pk, "acknowledge", mailbox.operator)  # resolvable, not stuck
    item.refresh_from_db()
    assert item.status == "resolved"


def test_p2_32_staff_confirm_while_process_reply_holds_the_lock(mailbox, monkeypatch):
    import time

    question, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message))
    outcome = []

    def confirm_concurrently(locked_message):
        def confirm():
            try:
                processing.confirm_question_outcome(locked_message.pk, {question.pk: "satisfied"}, mailbox.operator)
                outcome.append("confirmed")
            except Refused as exc:
                outcome.append(str(exc))
        mailbox.committed.thread(confirm)
        time.sleep(0.5)  # the thread now waits on the application lock process_reply holds
    monkeypatch.setattr(processing, "_before_decide", confirm_concurrently)
    collect()  # collection, then process_reply, whose seam starts the concurrent confirmation
    mailbox.committed.release()  # join the thread
    question.refresh_from_db()
    assert outcome == ["confirmed"] and question.status == "satisfied"
    assert not PendingAction.objects.filter(kind="interpret_reply", status="held").exists()
    assert StaffItem.objects.filter(reason_code="reply_needs_review", status="open").count() == 0


def test_d3_d4_staff_decide_only_a_persons_trusted_reply_and_need_every_outcome(mailbox):
    q1, m1 = sent_question(mailbox)
    mailbox.imap.deliver(reply(m1, headers=["Auto-Submitted: auto-replied"], body="away"))
    mailbox.imap.deliver(reply(m1, body="a real answer"))
    collect()
    processed()
    automatic, person = InboundMessage.objects.order_by("id")
    with pytest.raises(Refused, match="only_a_trusted"):
        processing.close_reply_without_outcome(automatic.pk, mailbox.operator)
    with pytest.raises(Refused, match="no_outcomes"):
        processing.confirm_question_outcome(person.pk, {}, mailbox.operator)
    with pytest.raises(Refused, match="an_outcome_is_needed"):
        processing.confirm_question_outcome(person.pk, {q1.pk: "maybe"}, mailbox.operator)
    person.refresh_from_db()
    assert person.status == "awaiting_processing"  # the refused attempts were rolled back whole
    with pytest.raises(Refused, match="unknown_close_reason"):
        processing.close_reply_without_outcome(person.pk, mailbox.operator, reason="free text")


def test_p2_34_loop_threshold_boundary_and_recount_after_staff_resolve(mailbox, settings):
    _, message = sent_question(mailbox)
    for _ in range(2):
        mailbox.imap.deliver(reply(message, headers=["Auto-Submitted: auto-replied"], body=f"away {uuid.uuid4().hex}"))
    collect()
    processed()
    assert not paused(mailbox)  # two is below the threshold of three
    mailbox.imap.deliver(reply(message, headers=["Auto-Submitted: auto-replied"], body=f"away {uuid.uuid4().hex}"))
    collect()
    processed()
    assert paused(mailbox)
    [item] = StaffItem.objects.filter(reason_code="loop_threshold")
    processing.resolve_exception(item.pk, "acknowledge", mailbox.operator)
    support.resume_pauses(mailbox.app)  # staff resume (2B.4 service), in the guard's shape
    mailbox.imap.deliver(reply(message, headers=["Auto-Submitted: auto-replied"], body=f"away {uuid.uuid4().hex}"))
    collect()
    processed()
    assert not paused(mailbox)  # the earlier three no longer count after the resolution


def test_p2_33_a_bounce_for_a_message_that_is_not_ours_is_unmatched_and_a_soft_bounce_is_recorded(mailbox):
    from applications.models import ApplicationEvent

    _, message = sent_question(mailbox)
    foreign = bounce(message).replace(str(message.send_ref.hex).encode(), b"f" * 32)
    mailbox.imap.deliver(foreign)
    mailbox.imap.deliver(bounce(message, "4.2.2"))
    collect()
    processed()
    unmatched, soft = InboundMessage.objects.order_by("id")
    assert (unmatched.status, unmatched.exception_reason) == ("exception", "unmatched")
    assert soft.status == "processed" and not paused(mailbox)
    assert ApplicationEvent.objects.filter(kind="bounce_recorded", data__hard=False, data__counted=True).count() == 1


@pytest.mark.parametrize(("reason_kwargs", "code", "role"), [
    ({"sender": "someone-else@example.test"}, "mark_spoof", "operator"),
    ({"auth": None}, "dismiss", "operator"),
    ({"auth": None}, "associate", "operator"),
])
def test_f_identity_resolutions_are_refused_to_operators(mailbox, reason_kwargs, code, role):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, **reason_kwargs))
    collect()
    item = StaffItem.objects.filter(dedupe_key__startswith="inbound:").exclude(reason_code="reply_needs_review").get()
    with pytest.raises(PermissionDenied):
        processing.resolve_exception(item.pk, code, getattr(mailbox, role))


def test_f_reply_and_send_items_are_not_resolvable_through_resolve_exception(mailbox):
    _, _, received = delivered(mailbox)
    [item] = StaffItem.objects.filter(reason_code="reply_needs_review")
    for code in ("acknowledge", "dismiss"):
        with pytest.raises(Refused, match="not_allowed"):
            processing.resolve_exception(item.pk, code, mailbox.decider)


def test_c4_staff_association_records_prior_values_and_an_event(mailbox):
    from applications.models import ApplicationEvent

    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, in_reply_to=False))
    collect()
    [item] = StaffItem.objects.filter(reason_code="unmatched")
    processing.resolve_exception(item.pk, "associate", mailbox.decider, target_application_id=mailbox.app.pk)
    effects = StaffItemResolution.objects.get(item=item).effects
    assert effects["prior_status"] == "exception" and effects["prior_exception_reason"] == "unmatched"
    assert ApplicationEvent.objects.filter(application=mailbox.app, kind="inbound_associated_by_staff").count() == 1


def test_g2_g6_every_reply_signal_reports_its_seeded_anomaly(mailbox, settings):
    question, _, received = delivered(mailbox)
    owner = mailbox.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE correspondence_inboundmessage SET status = 'processed'")  # the pending link now points nowhere
    report = reply_health()
    assert "pending_link_not_awaiting" in report["anomalies"]
    settings.CATALYST_MAIL_MAX_MESSAGE_BYTES = 200
    _, message = sent_question(mailbox, text="Second?")
    mailbox.imap.deliver(reply(message, body="x" * 5000))
    collect()
    assert reply_health()["unestablished_identity"] == 1


def test_p2_43_no_network_outside_the_transports_and_no_interpret_handler():
    from django.conf import settings

    assert "interpret_reply" not in settings.CATALYST_ACTION_HANDLERS
    allowed = {"transport.py", "imap.py"}
    for path in Path(support.ROOT, "correspondence").rglob("*.py"):
        if path.name in allowed or "migrations" in path.parts:
            continue
        text = path.read_text()
        for banned in ("import socket", "import urllib.request", "import http.client", "import requests", "smtplib", "imaplib"):
            assert banned not in text, (path.name, banned)


def test_adr01_applications_never_imports_correspondence():
    for path in Path(support.ROOT, "applications").rglob("*.py"):
        if "migrations" in path.parts or path.name == "admin.py":  # the admin inline is a presentation seam (deferred)
            continue
        text = path.read_text()
        for banned in ("from correspondence", "import correspondence", 'get_model("correspondence"'):
            assert banned not in text, (path.name, banned)


# --- the typed P3 interface ------------------------------------------------------------------------------------

def _request(text, questions=("q1",), truncated=False, sent_body=""):
    return processing.InterpretRequest(
        message_id="m", text=text, text_sha256=processing.text_sha256(text), derivation_version=1, redaction_version=1,
        truncated=truncated, omitted_parts=(), attachments=(), questions=tuple(processing.QuestionRef(q, "Question?") for q in questions),
        quoted=tuple(processing.quoted_ranges(text)), sent_body=sent_body)


def test_p3_interface_validation_rules():
    text = "My answer is yes.\n> Which project?\n"
    request = _request(text, sent_body="Which project?")
    good = processing.QuestionProposal("q1", "satisfied", (processing.Span(0, 17),))
    assert processing.validate_proposals(request, [good], request.text_sha256) == []
    assert "span_inside_quoted_text" in processing.validate_proposals(
        request, [processing.QuestionProposal("q1", "satisfied", (processing.Span(18, 34),))], request.text_sha256)
    assert "outcome_without_evidence" in processing.validate_proposals(request, [processing.QuestionProposal("q1", "partial")], request.text_sha256)
    assert "questions_do_not_match" in processing.validate_proposals(request, [], request.text_sha256)
    assert "span_out_of_bounds" in processing.validate_proposals(
        request, [processing.QuestionProposal("q1", "satisfied", (processing.Span(0, 999),))], request.text_sha256)
    truncated = _request(text, truncated=True)
    assert "not_addressed_on_truncated_text" in processing.validate_proposals(
        truncated, [processing.QuestionProposal("q1", "not_addressed")], truncated.text_sha256)
    changed = processing.InterpretRequest(**{**request.__dict__, "text_sha256": "0" * 64})
    assert "text_changed" in processing.validate_proposals(changed, [good], request.text_sha256)


def test_p3_eligibility_refuses_degraded_or_untrusted_text(mailbox):
    _, _, received = delivered(mailbox)
    received.refresh_from_db()
    assert processing.eligible(received)
    received.truncated = True
    assert not processing.eligible(received)


@pytest.mark.parametrize(("text", "stripped"), [
    ("From: my side the answer is yes.\nThanks", "From: my side the answer is yes.\nThanks"),
    ("Answer here.\nOn Tue, 13 Oct 2026 at 10:00, Catalyst Onboarding\n<onboarding@example.invalid> wrote:\n> q", "Answer here."),
])
def test_p2_44_quote_stripping_keeps_from_lines_and_catches_wrapped_attributions(text, stripped):
    assert processing.strip_quotes(text) == stripped



def test_p3_validation_is_total_and_refuses_straddling_long_or_stale_spans():
    text = "Yes, project Alpha.\n> Which project?\n"
    request = _request(text)
    straddle = processing.QuestionProposal("q1", "satisfied", (processing.Span(10, 25),))
    assert "span_inside_quoted_text" in processing.validate_proposals(request, [straddle], request.text_sha256)
    assert processing.validate_proposals(request, [processing.QuestionProposal("q1", "satisfied", (processing.Span("0", 3),))],
                                         request.text_sha256) == ["malformed_result"]
    assert processing.validate_proposals(request, "nonsense", request.text_sha256) == ["malformed_result"]
    assert "text_changed" in processing.validate_proposals(
        request, [processing.QuestionProposal("q1", "satisfied", (processing.Span(0, 4),))], "0" * 64)
    noisy = processing.QuestionProposal("q1", "satisfied", (processing.Span(0, 4),), note="ok\u202eevil")
    assert "note_not_clean" in processing.validate_proposals(request, [noisy], request.text_sha256)
    long_text = "a" * 3000
    long_request = _request(long_text)
    assert "span_too_long" in processing.validate_proposals(
        long_request, [processing.QuestionProposal("q1", "satisfied", (processing.Span(0, 2500),))], long_request.text_sha256)


def test_c4_association_refuses_a_closed_target_or_an_automatic_message(mailbox):
    from applications.models import Application

    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, in_reply_to=False))
    collect()
    [item] = StaffItem.objects.filter(reason_code="unmatched")
    Application.objects.filter(pk=mailbox.app.pk).update(stage="closed")
    with pytest.raises(Refused, match="application_closed"):
        processing.resolve_exception(item.pk, "associate", mailbox.decider, target_application_id=mailbox.app.pk)
    InboundMessage.objects.filter(pk=InboundMessage.objects.get().pk).update(classification="automatic")
    with pytest.raises(Refused, match="only_a_persons_message"):
        processing.resolve_exception(item.pk, "associate", mailbox.decider, target_application_id=mailbox.app.pk)


# --- 9kg.3: an unresolved hard bounce blocks every send; only a decision-maker reopens the address -------------

def test_9kg_3_an_open_hard_bounce_holds_every_send_and_refuses_staff_bypasses(mailbox):
    from correspondence import outbound, staff_actions

    mailbox.imap.deliver(bounce(sent_question(mailbox)[1]))
    collect()
    processed()
    [item] = StaffItem.objects.filter(reason_code="hard_bounce", status="open")
    sent = len(mailbox.server.messages)
    # A staff message (not automated, so the pause alone would not stop it) is refused before it is queued.
    draft = staff_actions.preview_staff_message(mailbox.app.pk, mailbox.operator, "Synthetic subject", "Synthetic body.")
    with pytest.raises(Refused, match="hard_bounce_open"):
        staff_actions.confirm_staff_message(draft.pk, draft.content_sha256, mailbox.operator)
    # A question approved meanwhile is frozen, but its send is held, refunded, and looks again later.
    question = Question.objects.create(application=mailbox.app, text="A second synthetic question?")
    message = outbound.approve_question(question.pk, mailbox.operator)
    support.resume_pauses(mailbox.app)  # isolate the bounce rule from the pause (the service would refuse: cause open)
    run_worker()
    [held] = PendingAction.objects.filter(kind="send_message", input_ref=str(message.send_ref))
    assert (held.status, held.last_error, held.attempts) == ("queued", "hard_bounce_open", 0)
    assert len(mailbox.server.messages) == sent
    # Recovery is an explicit, audited decision: never an acknowledgement, never an operator, always a reason.
    with pytest.raises(Refused, match="resolution_not_allowed"):
        processing.resolve_exception(item.pk, "acknowledge", mailbox.operator)
    with pytest.raises(PermissionDenied):
        processing.resolve_exception(item.pk, "address_usable_again", mailbox.operator, note="Applicant confirmed by phone")
    with pytest.raises(Refused, match="reason_needed"):
        processing.resolve_exception(item.pk, "address_usable_again", mailbox.decider, note="ok")
    processing.resolve_exception(item.pk, "address_usable_again", mailbox.decider, note="Applicant confirmed by phone")
    resolution = StaffItemResolution.objects.get(item=item)
    assert resolution.resolved_by == f"user:{mailbox.decider.pk}" and resolution.effects["released_sends"] == 1
    run_worker()
    assert len(mailbox.server.messages) == sent + 1  # released at once, after every check ran again



def test_9kg_3_an_exchange_in_flight_still_reconciles_and_the_verification_send_is_held(mailbox, monkeypatch):
    from datetime import timedelta
    from urllib.parse import urlencode

    from django.core import mail
    from django.db.models.functions import Now
    from django.test import Client

    from correspondence import outbound
    from tests.test_outbound import FORM, VALID, ask, attempts, no_blind_retry, sends

    no_blind_retry(monkeypatch)
    crashed = []

    def crash_once(claim, result):
        if not crashed:
            crashed.append(result.outcome)
            raise RuntimeError("synthetic: the worker stopped before recording")
    monkeypatch.setattr(outbound, "_after_send", crash_once)
    _, message = ask(mailbox)
    run_worker()
    [action] = sends(message)
    assert action.status == "running" and attempts(message) == [(1, 0, "sending")]
    # The bounce arrives while the exchange's outcome is unrecorded: reconciliation still runs first (it sends nothing).
    StaffItem.objects.create(application=mailbox.app, reason_code="hard_bounce", dedupe_key=f"inbound:{uuid.uuid4()}")
    PendingAction.objects.filter(pk=action.pk).update(lease_expires_at=Now() - timedelta(seconds=1))
    run_worker()
    action.refresh_from_db()
    assert action.status == "uncertain" and attempts(message) == [(1, 0, "unknown")]
    assert len(mailbox.server.messages) == 1
    # The S1 verification send is held as well, refunded, for an application with an open hard bounce.
    outbox = len(mail.outbox)
    assert Client().post(FORM, urlencode({**VALID, "email": "grace@example.test"}),
                         content_type="application/x-www-form-urlencoded").status_code == 302
    other = Application.objects.get(email_key="grace@example.test")
    StaffItem.objects.create(application=other, reason_code="hard_bounce", dedupe_key=f"inbound:{uuid.uuid4()}")
    run_worker()
    [held] = PendingAction.objects.filter(kind="send_verification", subject_id=other.public_ref)
    assert (held.status, held.last_error, held.attempts) == ("queued", "hard bounce open", 0)
    assert len(mail.outbox) == outbox
    item = StaffItem.objects.get(application=other, reason_code="hard_bounce")
    processing.resolve_exception(item.pk, "address_usable_again", mailbox.decider, note="Address confirmed by phone")
    assert StaffItemResolution.objects.get(item=item).effects["released_sends"] == 1
    run_worker()
    assert len(mail.outbox) == outbox + 1 and mail.outbox[-1].to == ["grace@example.test"]


# --- 9kg.2: a system safety pause needs decision-maker review, a reason and its cause addressed ----------------

def test_9kg_2_a_system_pause_resumes_only_by_a_decision_maker_with_a_reason_after_its_cause(mailbox):
    from applications.models import ApplicationEvent
    from correspondence import staff_actions

    mailbox.imap.deliver(bounce(sent_question(mailbox)[1]))
    collect()
    processed()
    assert AutomationPause.objects.get(subject_id=mailbox.app.public_ref).actor_ref.startswith("system")
    with pytest.raises(Refused, match="decision_maker_review_required"):  # an operator may not clear it
        staff_actions.resume(mailbox.app.pk, mailbox.operator, "Looks fine to me now")
    with pytest.raises(Refused, match="reason_needed"):
        staff_actions.resume(mailbox.app.pk, mailbox.decider, "ok")
    with pytest.raises(Refused, match="pause_cause_open"):  # resuming never clears the delivery block itself
        staff_actions.resume(mailbox.app.pk, mailbox.decider, "Applicant confirmed the address")
    assert paused(mailbox)
    item = StaffItem.objects.get(reason_code="hard_bounce", status="open")
    processing.resolve_exception(item.pk, "address_usable_again", mailbox.decider, note="Applicant confirmed by phone")
    staff_actions.resume(mailbox.app.pk, mailbox.decider, "Applicant confirmed the address")
    assert not paused(mailbox)
    resumed = ApplicationEvent.objects.get(kind="automation_resumed")
    assert resumed.data["system_pause"] is True and resumed.actor_ref == f"user:{mailbox.decider.pk}"
    assert resumed.data["note"] == "Applicant confirmed the address"
    refusals = [e.data["code"] for e in ApplicationEvent.objects.filter(kind="automation_resume_refused").order_by("id")]
    assert refusals == ["decision_maker_review_required", "reason_needed", "pause_cause_open"]  # each refusal audited


def test_9kg_2_a_staff_pause_cannot_be_resumed_past_a_system_cause_that_arrived_later(mailbox):
    from correspondence import staff_actions
    from correspondence.staff_items import open_item

    staff_actions.pause(mailbox.app.pk, mailbox.operator, "Checking the applicant's details")
    # Agreement reads run while paused (D-44): a decline found meanwhile opens its item, and its own pause is a no-op
    # because the staff pause row already exists.
    item = open_item("agreement_declined", f"read:{uuid.uuid4()}", application=mailbox.app)
    with pytest.raises(Refused, match="pause_cause_open"):
        staff_actions.resume(mailbox.app.pk, mailbox.operator)
    assert paused(mailbox)
    with pytest.raises(PermissionDenied):  # the agreement cause is settled by a decision-maker, with a reason
        processing.resolve_exception(item.pk, "agreement_decided", mailbox.operator, note="Reissued on the screen")
    with pytest.raises(Refused, match="reason_needed"):
        processing.resolve_exception(item.pk, "agreement_decided", mailbox.decider, note="done")
    processing.resolve_exception(item.pk, "agreement_decided", mailbox.decider, note="Reissued on the agreements screen")
    staff_actions.resume(mailbox.app.pk, mailbox.operator)  # a staff pause stays an operator's to resume
    assert not paused(mailbox)


def test_9kg_2_every_system_pause_reason_is_a_resumable_cause_with_a_resolution():
    """A new system pause creator must add its reason to PAUSE_CAUSES and give its item a resolution, or an
    application would either skip the cause check or stay paused for good."""
    import re

    from correspondence import staff_actions

    root = Path(__file__).resolve().parent.parent
    reasons = set()
    for source in ("correspondence/processing.py", "agreements/completion.py"):
        reasons |= set(re.findall(r'_pause\(application, "([a-z_]+)"\)', (root / source).read_text()))
    assert reasons and reasons == set(staff_actions.PAUSE_CAUSES)
    for reason in reasons:
        # Every cause has a resolution path (the resume itself still needs the decision-maker and a reason).
        assert reason in processing.RESOLUTIONS or reason in processing.ACKNOWLEDGE_ONLY, reason


def test_9kg_2_the_screen_offers_a_system_resume_only_to_a_decision_maker_with_a_required_reason(mailbox):
    from django.test import Client
    from django.urls import reverse

    mailbox.imap.deliver(bounce(sent_question(mailbox)[1]))
    collect()
    processed()
    url = reverse("correspondence_staff:application", args=[mailbox.app.public_ref])
    pages = {}
    for who in ("operator", "decider"):
        client = Client()
        client.force_login(getattr(mailbox, who))
        pages[who] = client.get(url).content.decode()
    assert "needs decision-maker review" in pages["operator"] and "Resume automation" not in pages["operator"]
    assert "Resume automation" in pages["decider"] and 'minlength="10"' in pages["decider"]

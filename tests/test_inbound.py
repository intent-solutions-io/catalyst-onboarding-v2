"""P2 task 2B.2, inbound collection and correlation (016 section 4 B and C, 4.1, A4; owner decisions D-27, D-28,
D-31, M6): TEST-P2-01, 07, 12 (fetch and own-copy side), 13 to 24, 25 and 26 (filed-copy side), 46, 47, 51,
the IMAP half of 40, G1, and the M6 TLS certificate tests on the real SMTP and IMAP transport paths.

Everything is synthetic: scripted SMTP and IMAP servers on loopback, TLS material generated at run time by the
pinned image's openssl (no committed key), `example.test` addresses. Injected faults are labelled as
simulations; the collector-crash case kills a real worker process with SIGKILL.
"""

import json
import logging
import signal
import socket
import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.db.models.functions import Now
from psycopg import errors

from correspondence import inbound, mime, outbound, staff_actions, transport
from correspondence.health import collector_health
from correspondence.imap import MailboxClient, MailboxError
from correspondence.models import (
    InboundMessage,
    InboundMessageLocation,
    MailboxCursor,
    OutboundMessage,
    Question,
    QuestionReplyLink,
    StaffItem,
    StaffItemResolution,
)
from tests import support
from tests.imap_server import ScriptedIMAP
from tests.smtp_server import ScriptedSMTP
from tests.test_outbound import (  # helpers only, never test functions
    ask,
    attempts,
    items,
    p2,  # noqa: F401  (fixture)
    ready,  # noqa: F401  (fixture)
    run_worker,
    sends,
    staff,
    wait_until,
)
from tests.tls_certs import generate
from workflow import ledger
from workflow.models import PendingAction

TRUSTED = "mx.synthetic.example.test"


@pytest.fixture(scope="session")
def tls(tmp_path_factory):
    return generate(tmp_path_factory.mktemp("tls"))


@pytest.fixture
def mailbox(ready, tls, settings):
    """`ready` (a verified applicant, an approved template, staff) plus a TLS IMAP server, a bootstrapped
    cursor (from now) and trusted Authentication-Results from the synthetic MTA."""
    imap = ScriptedIMAP(tls=tls.good).start()
    settings.CATALYST_MAIL_CA_FILE = tls.ca
    settings.CATALYST_MAIL_IMAP_PORT = imap.port
    settings.CATALYST_MAIL_TRUSTED_AUTHSERV_ID = TRUSTED
    settings.CATALYST_MAIL_MAILBOX_REF = "applicants"
    settings.CATALYST_MAIL_COLLECT_FOLDER = "INBOX"
    settings.CATALYST_MAIL_SENT_FOLDER = ""
    settings.CATALYST_MAIL_POLL_SECONDS = 3600  # a successor is never due by itself: tests run passes explicitly
    settings.CATALYST_MAIL_COLLECT_FAILURE_LIMIT = 3
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    ready.imap = imap
    ready.cursor = inbound.bootstrap_mailbox("from_now")
    yield ready
    imap.stop()


def collect():
    PendingAction.objects.filter(kind="collect", status="queued").update(due_at=Now())
    run_worker()


def reply(message, *, sender="ada@example.test", body="My synthetic answer.", auth="dmarc=pass", authserv=TRUSTED,
          headers=(), message_id=None, in_reply_to=True, subject="Re: synthetic question"):
    lines = []
    if auth is not None:
        lines.append(f"Authentication-Results: {authserv}; {auth}")
    lines += [f"From: {sender}", "To: onboarding@example.invalid", f"Subject: {subject}",
              f"Message-ID: <{message_id or uuid.uuid4().hex}@synthetic.example.test>",
              "Date: Tue, 13 Oct 2026 10:00:00 +0000", "MIME-Version: 1.0", "Content-Type: text/plain; charset=utf-8"]
    if in_reply_to is True:
        lines.append(f"In-Reply-To: {outbound.message_id(message.send_ref)}")
    elif in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    lines += list(headers)
    return ("\r\n".join(lines) + "\r\n\r\n" + body + "\r\n").encode()


def sent_question(env, text="Which synthetic project best shows your work?"):
    question, message = ask(env, text=text)
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "accepted_by_server"
    return question, message


def cursor(env):
    return MailboxCursor.objects.get(pk=env.cursor.pk)


# --- M6: TLS certificate tests on the real transport paths --------------------------------------------------

@pytest.mark.parametrize("which", ["good", "untrusted", "wrong_host"])
def test_m6_smtp_starttls_verifies_the_chain_and_the_hostname(ready, tls, settings, monkeypatch, which):
    settings.CATALYST_MAIL_TLS, settings.CATALYST_MAIL_CA_FILE = "starttls", tls.ca
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "sentinel-user-m6", "sentinel-password-m6"
    server = ready.use(ScriptedSMTP(tls=getattr(tls, which)))
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    if which == "good":
        assert message.disposition == "accepted_by_server" and server.messages[0]["tls"] is True
        assert server.tls_sessions == 1 and "AUTH" in server.commands  # the credential went only over verified TLS
    else:
        assert attempts(message) == [(1, 0, "transport_blocked")] and message.disposition == "transport_blocked"
        assert "MAIL" not in server.commands and server.messages == []  # held at once; no plaintext fallback
        assert "AUTH" not in server.commands and server.tls_sessions == 0  # no credential reached the server


def test_m6_smtp_never_falls_back_to_plaintext_when_starttls_is_refused(ready, tls, settings):
    settings.CATALYST_MAIL_TLS, settings.CATALYST_MAIL_CA_FILE = "starttls", tls.ca
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "sentinel-user-m6", "sentinel-password-m6"
    server = ready.use(ScriptedSMTP({"starttls": 454}, tls=tls.good))
    _, message = ask(ready)
    run_worker()
    assert "MAIL" not in server.commands and "AUTH" not in server.commands
    assert server.messages == [] and server.tls_sessions == 0


@pytest.mark.parametrize(("which", "plaintext"), [("good", False), ("untrusted", False), ("wrong_host", False), ("good", True)],
                         ids=["verified", "untrusted", "wrong-hostname", "plaintext-server"])
def test_m6_imap_verifies_the_chain_and_hostname_and_has_no_plaintext_path(p2, tls, settings, which, plaintext):
    settings.CATALYST_MAIL_CA_FILE = tls.ca
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    server = ScriptedIMAP(tls=None if plaintext else getattr(tls, which)).start()
    settings.CATALYST_MAIL_IMAP_PORT = server.port
    try:
        if which == "good" and not plaintext:
            with MailboxClient(timeout=2) as client:
                assert client.examine("INBOX")[0] == 1000
            assert server.logins == 1
        else:
            with pytest.raises(MailboxError) as refused:
                MailboxClient(timeout=2)
            expected = ("tls_refused", "unreachable") if plaintext else ("tls_refused",)
            assert refused.value.code in expected and server.logins == 0  # no credential sent
    finally:
        server.stop()


def test_m6_a_collector_facing_an_untrusted_certificate_blocks_without_logging_in(mailbox, tls, settings):
    mailbox.imap.stop()
    bad = ScriptedIMAP(tls=tls.untrusted).start()
    settings.CATALYST_MAIL_IMAP_PORT = bad.port
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    mailbox.imap = bad
    collect()
    state = cursor(mailbox)
    assert (state.state, state.blocked_reason) == ("blocked", "tls_refused") and bad.logins == 0
    assert StaffItem.objects.filter(reason_code="collector_blocked", status="open").count() == 1
    assert not PendingAction.objects.filter(kind="collect", status="queued").exists()  # a blocked cursor schedules nothing


# --- TEST-P2-01, 12, 13: correlation, duplicates, identity -----------------------------------------------------

def test_p2_01_a_trusted_reply_is_correlated_and_makes_its_question_reply_pending(mailbox):
    question, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message))
    collect()
    [received] = InboundMessage.objects.all()
    question.refresh_from_db()
    assert (received.status, received.classification, received.trust_decision) == ("awaiting_processing", "human", "trusted")
    assert received.application_id == mailbox.app.pk and received.approved_message_id == message.pk
    assert question.status == "reply_pending"
    assert list(QuestionReplyLink.objects.values_list("state", flat=True)) == ["pending"]
    assert PendingAction.objects.filter(kind="process_reply", input_ref=str(received.public_id), status="queued").exists()
    assert received.is_derivative and received.original_sha256 and "My synthetic answer." in received.derived_text
    state = cursor(mailbox)
    assert state.last_uid == 1 and state.complete_through_uid == 1 and state.complete_through_at is not None
    assert list(received.locations.values_list("uid", "matched_by")) == [(1, "new")]


def test_p2_12_the_same_bytes_seen_again_and_our_own_filed_copy_have_no_new_effect(mailbox):
    question, message = sent_question(mailbox)
    data = reply(message)
    mailbox.imap.deliver(data)
    mailbox.imap.deliver(data)  # identical bytes at a second UID
    filed = outbound.build_email(message, message.frozen_subject, message.frozen_body,
                                 extra_headers={mime.FILED_COPY_HEADER: str(message.send_ref)})
    mailbox.imap.deliver(filed)
    collect()
    replies = InboundMessage.objects.exclude(classification="own_copy")
    assert replies.count() == 1 and QuestionReplyLink.objects.count() == 1
    assert sorted(InboundMessageLocation.objects.values_list("uid", "matched_by")) == [(1, "new"), (2, "digest"), (3, "new")]
    own = InboundMessage.objects.get(classification="own_copy")
    assert own.status == "processed" and PendingAction.objects.filter(kind="process_reply").count() == 1
    assert cursor(mailbox).duplicates_seen == 1


def test_p2_13_the_same_message_id_with_different_bytes_is_kept_with_a_staff_item(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, message_id="fixed-id", body="First body AAAA."))
    mailbox.imap.deliver(reply(message, message_id="fixed-id", body="First body BBBB."))  # same Message-ID, size and date
    assert len(mailbox.imap.folders["INBOX"].messages[0][1]) == len(mailbox.imap.folders["INBOX"].messages[1][1])
    collect()
    first, second = InboundMessage.objects.order_by("id")
    assert first.original_sha256 != second.original_sha256
    assert (second.status, second.exception_reason) == ("exception", "message_id_conflict")
    assert StaffItem.objects.filter(reason_code="message_id_conflict", status="open").count() == 1


# --- TEST-P2-14, 15, 47: derivation ---------------------------------------------------------------------------

def test_p2_14_malformed_mime_is_recorded_and_the_cursor_passes_it(mailbox):
    _, message = sent_question(mailbox)
    nested = b"Content-Type: multipart/mixed; boundary=a\r\n\r\n--a\r\n" * 12
    mailbox.imap.deliver(b"From: ada@example.test\r\nContent-Type: text/plain; charset=no-such-charset\r\n\r\nbad \x00 bytes\xff\r\n")
    mailbox.imap.deliver(b"MIME-Version: 1.0\r\n" + nested + b"\r\n")
    mailbox.imap.deliver(reply(message))
    collect()
    assert cursor(mailbox).last_uid == 3
    assert InboundMessage.objects.count() == 3
    assert InboundMessage.objects.filter(trust_decision="trusted").count() == 1  # the good one still worked
    assert all("\x00" not in t for t in InboundMessage.objects.values_list("derived_text", flat=True))
    assert any(p.get("reason") == "mime_defects" for parts in InboundMessage.objects.values_list("omitted_parts", flat=True)
               for p in parts)


def test_p2_15_an_oversize_message_is_recorded_from_its_headers_only(mailbox, settings):
    _, message = sent_question(mailbox)
    settings.CATALYST_MAIL_MAX_MESSAGE_BYTES = 200
    mailbox.imap.deliver(reply(message, body="x" * 5000))
    collect()
    [big] = InboundMessage.objects.all()
    assert (big.status, big.exception_reason, big.identity_state) == ("exception", "inbound_oversize", "unestablished")
    assert big.derived_text == "" and big.original_sha256 == "" and {"part": "body", "reason": "oversize"} in big.omitted_parts


def test_p2_47_confirmation_links_are_redacted_in_every_encoding_and_the_text_is_a_labelled_derivative():
    token = "http://catalyst.example.test/confirm/Zm9vYmFy:SIGNATURE123/"
    import base64
    import quopri

    html = f'<p>Click <a href="{token}">here</a></p>'.encode()
    forwarded = f"Content-Type: text/plain\r\n\r\nForwarded: {token}\r\n".encode()
    raw = (b"From: ada@example.test\r\nMessage-ID: <x@example.test>\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: multipart/mixed; boundary=b\r\n\r\n"
           b"--b\r\nContent-Type: text/plain\r\nContent-Transfer-Encoding: base64\r\n\r\n"
           + base64.b64encode(f"> quoted {token}\n".encode()) + b"\r\n"
           b"--b\r\nContent-Type: text/plain\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n"
           + quopri.encodestring(("soft broken " + token + " " * 80 + "end").encode()) + b"\r\n"
           b"--b\r\nContent-Type: text/plain\r\n\r\npercent http://catalyst.example.test%2Fconfirm%2FZm9vYmFy:SIG/\r\n"
           b"--b\r\nContent-Type: text/html\r\n\r\n" + html + b"\r\n"
           b"--b\r\nContent-Type: message/rfc822\r\n\r\n" + forwarded + b"\r\n--b--\r\n")
    derived = mime.derive(raw, max_text_chars=10_000)
    assert "/confirm/" not in derived.text.lower() and "SIGNATURE123" not in derived.text
    assert derived.redactions["confirmation_link"] >= 5
    short = mime.derive(raw, max_text_chars=40)
    assert short.truncated and short.truncated_at_chars == 40 and len(short.text) == 40


def test_p2_47_a_redaction_version_bump_rederives_from_the_mailbox_and_keeps_no_old_text(mailbox, monkeypatch):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="secret-like LEAKME123 text"))
    collect()
    monkeypatch.setattr(mime, "REDACTION_VERSION", 2)
    monkeypatch.setattr(mime, "_CONFIRM", __import__("re").compile(r"LEAKME\d+"))
    from django.core.management import call_command
    from io import StringIO
    call_command("correspondence_rederive", stdout=StringIO())
    received = InboundMessage.objects.get()
    assert received.redaction_version == 2 and "LEAKME123" not in received.derived_text


# --- TEST-P2-16, 17, 18: trust and association ----------------------------------------------------------------

@pytest.mark.parametrize(("kwargs", "decision", "status"), [
    ({"auth": "dmarc=pass"}, "trusted", "awaiting_processing"),
    ({"auth": "dmarc=fail"}, "auth_failed", "exception"),
    ({"auth": "spf=fail smtp.mailfrom=example.test; dkim=pass header.d=example.test; dmarc=pass"}, "trusted", "awaiting_processing"),
    ({"auth": "spf=pass"}, "unverified", "exception"),
    ({"auth": "dmarc=temperror"}, "unverified", "exception"),
    ({"auth": None}, "unverified", "exception"),
    ({"authserv": "forged.example.test"}, "unverified", "exception"),
    ({"sender": "someone-else@example.test"}, "sender_mismatch", "exception"),
    ({"sender": "ａda@example.test"}, "sender_mismatch", "exception"),  # a full-width look-alike never matches
], ids=["pass", "fail", "spf-fail-dkim-pass", "no-dmarc", "temperror", "missing", "untrusted-authserv", "mismatch", "lookalike"])
def test_p2_16_17_the_trust_table_decides_every_effect(mailbox, kwargs, decision, status):
    question, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, **kwargs))
    collect()
    received = InboundMessage.objects.get()
    question.refresh_from_db()
    assert (received.trust_decision, received.status) == (decision, status)
    assert question.status == ("reply_pending" if decision == "trusted" else "open")
    assert QuestionReplyLink.objects.count() == (1 if decision == "trusted" else 0)
    if decision != "trusted":
        assert StaffItem.objects.filter(dedupe_key=f"inbound:{received.public_id}", status="open").count() == 1
    assert question.approval_state == "approved"  # nothing changed identity or the question's approval


def test_p2_18_unmatched_mail_and_a_reply_to_a_closed_application_go_to_staff(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, in_reply_to=False))
    owner = mailbox.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE applications_application SET stage = 'closed' WHERE id = %s", [mailbox.app.pk])
    mailbox.imap.deliver(reply(message))
    collect()
    unmatched, closed = InboundMessage.objects.order_by("id")
    assert (unmatched.status, unmatched.exception_reason, unmatched.application_id) == ("exception", "unmatched", None)
    assert (closed.exception_reason, closed.application_id) == ("application_closed", mailbox.app.pk)
    assert QuestionReplyLink.objects.count() == 0


def test_p2_18_a_bounce_is_matched_only_through_its_embedded_message_id(mailbox):
    _, message = sent_question(mailbox)
    bounce = (b"From: MAILER-DAEMON@synthetic.example.test\r\nMessage-ID: <b1@synthetic.example.test>\r\nMIME-Version: 1.0\r\n"
              b"Content-Type: multipart/report; report-type=delivery-status; boundary=r\r\n\r\n"
              b"--r\r\nContent-Type: text/plain\r\n\r\nDelivery failed.\r\n"
              b"--r\r\nContent-Type: message/delivery-status\r\n\r\nStatus: 5.1.1\r\n\r\n"
              b"--r\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: " + outbound.message_id(message.send_ref).encode()
              + b"\r\n\r\n--r--\r\n")
    mailbox.imap.deliver(bounce)
    collect()
    received = InboundMessage.objects.get()
    assert (received.classification, received.status, received.approved_message_id) == ("bounce", "awaiting_processing", message.pk)
    assert QuestionReplyLink.objects.count() == 0  # a bounce never makes a question reply_pending


# --- TEST-P2-07, 46, 20, 51: positions, resync, recovery, bootstrap -------------------------------------------

def test_p2_07_46_a_uidvalidity_change_resyncs_with_no_new_effect_even_mid_batch(mailbox, settings):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="one"))
    mailbox.imap.deliver(reply(message, body="two"))
    collect()
    settings.CATALYST_MAIL_BATCH_SIZE = 1
    mailbox.imap.renumber()
    collect()  # the resync pass handles one message: partial, so no watermark
    partial = cursor(mailbox)
    assert (partial.state, partial.complete_through_at, partial.last_uid) == ("resync", None, 1)
    assert partial.last_batch_at is not None
    collect()
    state = cursor(mailbox)
    assert InboundMessage.objects.count() == 2 and QuestionReplyLink.objects.count() == 2
    assert state.state == "ok" and state.epoch == 1 and state.uidvalidity == 1100
    assert sorted(InboundMessageLocation.objects.values_list("uidvalidity", "matched_by")) == [
        (1000, "new"), (1000, "new"), (1100, "digest"), (1100, "digest")]
    assert StaffItem.objects.filter(reason_code="mailbox_uidvalidity_changed").count() == 1


def test_p2_20_a_lost_or_regressed_cursor_recovers_without_skipping_or_duplicating(mailbox, settings):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="one"))
    collect()
    settings.CATALYST_MAIL_MAX_MESSAGE_BYTES = 200
    mailbox.imap.deliver(reply(message, body="x" * 5000))  # unestablished identity
    collect()
    owner = mailbox.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE workflow_pendingaction SET status = 'cancelled' WHERE kind = 'collect' AND status = 'queued'")
    owner.execute("DELETE FROM correspondence_mailboxcursor")  # the row is lost (a restore without it)
    with pytest.raises(inbound.Refused, match="use_recovery"):
        inbound.bootstrap_mailbox("from_now")  # recovery, never a fresh start
    mailbox.imap.deliver(reply(message, body="arrived while the cursor was lost"))
    recovered = inbound.recover_mailbox()
    assert recovered.state == "recovery"
    collect()
    assert InboundMessage.objects.count() == 3  # the new one stored; the two known ones not duplicated
    state = MailboxCursor.objects.get()
    assert state.state == "ok" and state.last_uid == 3


def test_p2_51_bootstrap_records_its_start_mode_and_refuses_a_collected_mailbox(mailbox):
    first = cursor(mailbox)
    assert first.start_mode == "from_now" and StaffItem.objects.filter(reason_code="mailbox_history_out_of_scope").count() == 1
    with pytest.raises(inbound.Refused, match="use_recovery"):
        inbound.bootstrap_mailbox("from_uid", 1)
    with pytest.raises(inbound.Refused, match="start_mode"):
        inbound.bootstrap_mailbox("everything")


# --- TEST-P2-19, 21, 22, 23: crashes, leases, chains, blocking -------------------------------------------------

def test_p2_21_a_lease_lost_between_messages_rolls_that_message_back_and_stops_the_pass(mailbox, monkeypatch):
    _, message = sent_question(mailbox)
    for body in ("one", "two"):
        mailbox.imap.deliver(reply(message, body=body))
    real = inbound.ingest
    calls = []

    def takeover(*args, **kwargs):
        result = real(*args, **kwargs)
        calls.append(result)
        if len(calls) == 2:  # SIMULATION: another collector took the lease during the second message
            PendingAction.objects.filter(kind="collect", status="running").update(lease_token=uuid.uuid4())
        return result
    monkeypatch.setattr(inbound, "ingest", takeover)
    collect()
    assert InboundMessage.objects.count() == 1 and cursor(mailbox).last_uid == 1  # the second was rolled back


def test_p2_22_one_claim_per_pass_one_successor_and_the_chain_survives_a_final_failure(mailbox):
    handlers = ledger.handlers()
    first = ledger.claim_next(handlers)
    assert first.kind == "collect" and ledger.claim_next(handlers) is None
    PendingAction.objects.filter(pk=first.id).update(status="queued", lease_token=None, lease_expires_at=None, due_at=Now())
    inbound.enqueue_pass(cursor(mailbox), 2)
    inbound.enqueue_pass(cursor(mailbox), 2)  # idempotent
    assert PendingAction.objects.filter(kind="collect").count() == 2
    PendingAction.objects.filter(kind="collect").update(status="cancelled")
    poisoned = PendingAction.objects.create(kind="collect", subject_type="mailbox_cursor", subject_id=mailbox.cursor.public_id,
                                            input_ref="", idempotency_key=inbound.collect_key(mailbox.cursor, 7), attempts=3)
    run_worker()  # the poison rule finishes it; the record enqueues the successor
    poisoned.refresh_from_db()
    assert poisoned.status == "failed"
    assert PendingAction.objects.filter(idempotency_key=inbound.collect_key(mailbox.cursor, 8), status="queued").exists()


def test_p2_23_an_authentication_failure_blocks_without_a_retry_chain_and_only_restart_resumes(mailbox, settings, caplog):
    caplog.set_level(logging.DEBUG)
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "sentinel-user-7a", "sentinel-password-3c"
    mailbox.imap.login_reply = "NO"
    collect()
    state = cursor(mailbox)
    assert (state.state, state.blocked_reason) == ("blocked", "auth_failed")
    assert not PendingAction.objects.filter(kind="collect", status="queued").exists()
    [item] = StaffItem.objects.filter(reason_code="mailbox_auth_failed", status="open")
    for user in (mailbox.operator, staff(mailbox, "root", superuser=True)):
        with pytest.raises(PermissionDenied):
            staff_actions.restart_collector(state.pk, user)
    mailbox.imap.login_reply = "OK"
    resumed = staff_actions.restart_collector(state.pk, mailbox.decider)
    assert resumed.state == "ok"
    item.refresh_from_db()
    assert item.status == "resolved" and StaffItemResolution.objects.get(item=item).resolution_code == "restart_collector"
    collect()
    assert cursor(mailbox).consecutive_failures == 0
    stored = json.dumps([list(StaffItem.objects.values()), list(PendingAction.objects.values("last_error"))], default=str)
    for sentinel in ("sentinel-user-7a", "sentinel-password-3c"):
        assert sentinel not in stored and sentinel not in caplog.text


def test_p2_23_an_unreachable_server_backs_off_then_blocks_at_the_bound(mailbox):
    mailbox.imap.stop()
    for _ in range(3):
        collect()
    state = cursor(mailbox)
    assert (state.state, state.blocked_reason, state.consecutive_failures) == ("blocked", "unreachable", 3)
    assert collector_health()["anomalies"] == ["blocked", "failing"]


def test_p2_19_a_collector_killed_mid_message_loses_nothing_and_duplicates_nothing(mailbox, tmp_path, tls):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="one"))
    mailbox.imap.deliver(reply(message, body="two"))
    marker = tmp_path / "fetching"
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    env = dict(CATALYST_MAIL_HOST="127.0.0.1", CATALYST_MAIL_IMAP_PORT=str(mailbox.imap.port), CATALYST_MAIL_CA_FILE=tls.ca,
               CATALYST_MAIL_USER="synthetic-user", CATALYST_MAIL_PASSWORD="synthetic-password-only",
               CATALYST_MAIL_TLS="none", CATALYST_MAIL_TRUSTED_AUTHSERV_ID=TRUSTED, CATALYST_MAIL_POLL_SECONDS="3600")
    PendingAction.objects.filter(kind="collect", status="queued").update(due_at=Now())
    killed = support.worker_process(sink, str(marker), module="tests.worker_child_collect", **env)
    survivor = None
    try:
        wait_until(marker.exists, 30, "the first collector to be inside the second message's transaction")
        killed.send_signal(signal.SIGKILL)
        assert killed.wait(10) == -signal.SIGKILL
        survivor = support.worker_process(sink, **env)
        wait_until(lambda: InboundMessage.objects.count() == 2 and MailboxCursor.objects.get().complete_through_uid == 2,
                   40, "recovery of the pass by a fresh worker")
        survivor.send_signal(signal.SIGTERM)
        survivor.communicate(timeout=20)
    finally:
        for proc in (killed, survivor):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(10)
    assert sorted(InboundMessageLocation.objects.values_list("uid", flat=True)) == [1, 2]
    assert QuestionReplyLink.objects.count() == 2


# --- TEST-P2-25, 26 (filed-copy side), 40 (IMAP), 39, 41 (G1) ---------------------------------------------------

def test_p2_26_an_accepted_send_files_one_copy_and_an_append_failure_never_sends_again(mailbox, settings):
    settings.CATALYST_MAIL_SENT_FOLDER = "Sent"
    _, message = sent_question(mailbox)
    [copy] = mailbox.imap.folders["Sent"].messages
    assert mime.FILED_COPY_HEADER.encode() in copy[1] and outbound.message_id(message.send_ref).encode() in copy[1]
    assert OutboundMessage.objects.get(approved_message=message).filed_copy_state == "filed"
    PendingAction.objects.filter(kind="file_copy").update(status="queued", due_at=Now(), attempts=0)
    run_worker()
    assert len(mailbox.imap.folders["Sent"].messages) == 1  # searched before APPEND
    settings.CATALYST_MAIL_SENT_FOLDER = "Missing"
    _, second = sent_question(mailbox, text="A second synthetic question?")
    assert OutboundMessage.objects.get(approved_message=second).filed_copy_state == "failed"
    assert StaffItem.objects.filter(reason_code="filed_copy_failed", approved_message=second).count() == 1
    assert len(mailbox.server.messages) == 2  # one SMTP send per message: an APPEND failure never re-sends


def test_p2_25_a_catalyst_filed_copy_in_sent_is_never_evidence_even_if_mislabelled(mailbox, settings):
    from correspondence.outbound import Evidence, admissible

    settings.CATALYST_MAIL_SENT_FOLDER = "Sent"
    _, message = sent_question(mailbox)
    data = mailbox.imap.folders["Sent"].messages[0][1]
    derived = mime.derive(data, max_text_chars=10_000)
    record = Evidence(origin="provider", message_id=derived.message_id, recipient=message.recipient,
                      content_sha256=message.content_sha256, filed_by_catalyst=bool(derived.filed_copy))
    assert record.filed_by_catalyst and not admissible(record, message, {message.content_sha256})


def test_p2_40_the_imap_peer_is_checked_before_login(mailbox, settings, monkeypatch):
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    import ssl

    before = mailbox.imap.logins  # the fixture's bootstrap logged in once
    for cls in (socket.socket, ssl.SSLSocket):  # SIMULATION: the name resolved to a non-allowed address
        monkeypatch.setattr(cls, "getpeername", lambda self: ("203.0.113.9", 993))
    with pytest.raises(MailboxError, match="peer_refused"):
        MailboxClient(timeout=2)
    assert mailbox.imap.logins == before  # no LOGIN reached the refused peer


@pytest.mark.parametrize("sql", [
    "UPDATE correspondence_inboundmessage SET original_sha256 = 'x' WHERE false",
    "UPDATE correspondence_inboundmessage SET from_address = 'x' WHERE false",
    "UPDATE correspondence_inboundmessage SET message_id_header = 'x' WHERE false",
    "DELETE FROM correspondence_inboundmessage WHERE false",
    "UPDATE correspondence_inboundmessagelocation SET uid = 1 WHERE false",
    "DELETE FROM correspondence_inboundmessagelocation WHERE false",
    "UPDATE correspondence_mailboxcursor SET mailbox_ref = 'x' WHERE false",
    "DELETE FROM correspondence_mailboxcursor WHERE false",
    "UPDATE correspondence_questionreplylink SET question_id = 1 WHERE false",
    "DELETE FROM correspondence_questionreplylink WHERE false",
    "TRUNCATE correspondence_inboundmessage",
])
def test_p2_39_inbound_records_cannot_be_rewritten_or_removed_by_the_application_role(p2, sql):
    conn = p2.committed.connect("app")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(sql)
    conn.rollback()


def test_p2_41_g1_reports_a_healthy_collector_and_a_broken_chain(mailbox):
    collect()
    assert collector_health()["anomalies"] == []
    PendingAction.objects.filter(kind="collect", status="queued").update(status="cancelled")
    assert collector_health()["anomalies"] == ["broken_chain"]


# --- review fixes (2B.2 independent review) -------------------------------------------------------------------

@pytest.mark.parametrize(("auth", "decision"), [
    ('spf=fail smtp.mailfrom="x dmarc=pass"@evil.example.test; dmarc=fail header.from=example.test', "auth_failed"),
    ("dkim=pass (comment dmarc=pass) header.d=example.test; dmarc=fail", "auth_failed"),
    ("dmarc=pass; dmarc=fail", "unverified"),  # conflicting results
], ids=["quoted-injection", "comment-injection", "conflict"])
def test_c3_text_inside_property_values_or_comments_is_never_read_as_a_result(mailbox, auth, decision):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, auth=auth))
    collect()
    assert InboundMessage.objects.get().trust_decision == decision


def test_c3_a_forged_trusted_header_below_the_real_one_and_a_malformed_header_are_harmless(mailbox):
    _, message = sent_question(mailbox)
    forged = reply(message, auth="dmarc=fail", headers=[f"Authentication-Results: {TRUSTED}; dmarc=pass"])
    mailbox.imap.deliver(forged)
    mailbox.imap.deliver(reply(message, auth="dmarc=pass", authserv=";"))  # empty authserv-id
    collect()
    first, second = InboundMessage.objects.order_by("id")
    assert first.trust_decision == "auth_failed"  # only the topmost trusted header counts
    assert (second.trust_decision, second.exception_reason) == ("unverified", "reply_unverified")


def test_c1_in_reply_to_wins_over_older_references(mailbox):
    q1, m1 = sent_question(mailbox, text="First synthetic question?")
    q2, m2 = sent_question(mailbox, text="Second synthetic question?")
    mailbox.imap.deliver(reply(m2, in_reply_to=outbound.message_id(m2.send_ref),
                               headers=[f"References: {outbound.message_id(m1.send_ref)} {outbound.message_id(m2.send_ref)}"]))
    collect()
    q1.refresh_from_db()
    q2.refresh_from_db()
    assert InboundMessage.objects.get().approved_message_id == m2.pk
    assert (q1.status, q2.status) == ("open", "reply_pending")


def test_b4_a_database_failure_aborts_the_pass_and_is_never_demoted(mailbox, monkeypatch):
    from django.db import OperationalError

    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message))

    real = inbound._associate

    def database_down(*args, **kwargs):
        raise OperationalError("simulated: the database connection failed")
    monkeypatch.setattr(inbound, "_associate", database_down)
    collect()
    assert InboundMessage.objects.count() == 0 and cursor(mailbox).last_uid == 0  # rolled back, not processing_error
    monkeypatch.setattr(inbound, "_associate", real)  # only this patch; the fixture's own patches stay in force
    PendingAction.objects.filter(kind="collect", status="running").update(lease_expires_at=Now() - timedelta(seconds=1))
    collect()
    assert InboundMessage.objects.get().trust_decision == "trusted"


def test_b5_an_unestablished_message_is_matched_by_metadata_after_a_resync(mailbox, settings):
    _, message = sent_question(mailbox)
    settings.CATALYST_MAIL_MAX_MESSAGE_BYTES = 200
    mailbox.imap.deliver(reply(message, body="x" * 5000))
    collect()
    mailbox.imap.renumber()
    collect()
    assert InboundMessage.objects.count() == 1
    assert sorted(InboundMessageLocation.objects.values_list("matched_by", flat=True)) == ["metadata", "new"]


def test_4_1_a_regressed_cursor_becomes_a_recovery_and_skips_nothing(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="one"))
    collect()
    owner = mailbox.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE correspondence_mailboxcursor SET last_uid = 0")  # a restore to an older position
    mailbox.imap.deliver(reply(message, body="two"))
    seen = []
    real = inbound.ingest

    def watch(*args, **kwargs):
        seen.append(MailboxCursor.objects.get().state)
        return real(*args, **kwargs)
    inbound.ingest = watch
    try:
        collect()
    finally:
        inbound.ingest = real
    assert seen and set(seen) == {"recovery"} and InboundMessage.objects.count() == 2
    assert cursor(mailbox).state == "ok"


def test_b0_recovery_refuses_a_blocked_cursor(mailbox):
    mailbox.imap.login_reply = "NO"
    collect()
    assert cursor(mailbox).state == "blocked"
    with pytest.raises(inbound.Refused, match="restart_collector"):
        inbound.recover_mailbox()


def test_a4_a_secret_bearing_message_is_never_filed(mailbox, settings):
    settings.CATALYST_MAIL_SENT_FOLDER = "Sent"
    _, message = sent_question(mailbox)
    message.template_version.secret_bearing = True  # in memory only: the guard reads the frozen template's flag
    before = PendingAction.objects.filter(kind="file_copy").count()
    inbound.enqueue_file_copy(message, OutboundMessage.objects.get(approved_message=message).pk)
    assert PendingAction.objects.filter(kind="file_copy").count() == before


def test_p2_47_rederivation_without_the_source_rederives_the_stored_derivative(mailbox, monkeypatch):
    from io import StringIO

    from django.core.management import call_command

    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="secret-like LEAKME456 text"))
    collect()
    mailbox.imap.folders["INBOX"].messages.clear()  # the source is gone
    monkeypatch.setattr(mime, "REDACTION_VERSION", 2)
    monkeypatch.setattr(mime, "_CONFIRM", __import__("re").compile(r"LEAKME\d+"))
    call_command("correspondence_rederive", stdout=StringIO())
    received = InboundMessage.objects.get()
    assert "LEAKME456" not in received.derived_text
    assert {"part": "derivative", "reason": "rederived_from_derivative"} in received.omitted_parts


def test_p2_23_collected_content_never_reaches_logs_items_events_or_actions(mailbox, caplog):
    caplog.set_level(logging.DEBUG)
    _, message = sent_question(mailbox)
    sentinel_body, sentinel_subject = "SENTINEL-BODY-5e1", "SENTINEL-SUBJECT-9c2"
    mailbox.imap.deliver(reply(message, body=sentinel_body, subject=sentinel_subject))
    mailbox.imap.deliver(reply(message, sender="sentinel-sender-4d@example.test", body=sentinel_body, subject=sentinel_subject))
    collect()
    from applications.models import ApplicationEvent

    stored = json.dumps([list(ApplicationEvent.objects.values()), list(StaffItem.objects.values()),
                         list(PendingAction.objects.values("idempotency_key", "input_ref", "last_error")),
                         list(StaffItemResolution.objects.values())], default=str)
    for sentinel in (sentinel_body, sentinel_subject, "sentinel-sender-4d", "ada@example.test"):
        assert sentinel not in stored and sentinel not in caplog.text, sentinel


def test_6_mail_code_never_logs_tracebacks_or_enables_protocol_debugging():
    from pathlib import Path

    for path in Path(support.ROOT, "correspondence").rglob("*.py"):
        text = path.read_text()
        for banned in ("logger.exception", "set_debuglevel", "imaplib.Debug", ".debug = "):
            assert banned not in text, (path.name, banned)


def test_p2_41_g1_reports_a_stale_watermark(mailbox):
    collect()
    owner = mailbox.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE correspondence_mailboxcursor SET complete_through_at = now() - interval '30 days'")
    assert "stale_watermark" in collector_health()["anomalies"]


def test_b4_percent_encoded_and_raw_nul_never_poison_the_cursor(mailbox):
    _, message = sent_question(mailbox)
    mailbox.imap.deliver(reply(message, body="before %00 after"))
    mailbox.imap.deliver(reply(message, headers=["X-Autoreply: yes %00 here"], body="automatic"))
    mailbox.imap.deliver(b"From: ada@example.test\r\nMessage-ID: <nul\x00id@example.test>\r\n\r\nraw nul\r\n")
    mailbox.imap.deliver(reply(message, body="still collected afterwards"))
    collect()
    assert cursor(mailbox).last_uid == 4 and InboundMessage.objects.count() == 4
    for text in InboundMessage.objects.values_list("derived_text", flat=True):
        assert "\x00" not in text
    assert InboundMessage.objects.filter(derived_text__contains="still collected afterwards").exists()


def test_p2_47_a_wrapped_link_is_redacted_without_swallowing_the_following_words():
    raw = (b"From: ada@example.test\r\nContent-Type: text/plain\r\n\r\n"
           b"> see http://catalyst.example.test/confirm/Zm9vYmFyYmF6\r\n> cXV4:SIGNATURE987/\r\nThanks for asking.\r\n")
    derived = mime.derive(raw, max_text_chars=10_000)
    assert "SIGNATURE987" not in derived.text and "cXV4" not in derived.text
    assert "Thanks for asking." in derived.text

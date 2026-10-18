"""P2 task 2B.1, outbound foundations (016 section 4 A, owner decisions D-27 to D-30): the tests 016
section 9 assigns to 2B.1 (TEST-P2-03, 12, 25 to 27, 36 to 39, 48, 49, the SMTP half of 40, G3 of 41,
and 52 for 2B.1's services), plus the ledger additions of A-7.

Every test commits real data (`privileged_reset`). An applicant is verified through the real S1 flow
(intake, worker, confirmation). Sends go to a scripted SMTP server on loopback (tests/smtp_server.py):
synthetic only, no provider, no real mail. Staff accounts and group memberships are created as the owner
(the authorized path), never through the application.
"""

import json
import logging
import re
import socket
import sys
from datetime import timedelta
from io import StringIO
from urllib.parse import urlencode

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.functions import Now
from django.test import Client
from django.urls import reverse
from psycopg import errors

from applications.models import Application, ApplicationEvent
from config import guards, runtime
from correspondence import outbound, staff_actions, transport
from correspondence.health import send_health
from correspondence.models import (
    ApprovedMessage,
    ApprovedMessageQuestion,
    MessageTemplate,
    MessageTemplateVersion,
    OutboundMessage,
    Question,
    StaffItem,
    StaffItemResolution,
)
from correspondence.rendering import TemplateRefused, canonical_digest, render
from correspondence.roles import DECISION_MAKER, OPERATOR, TEMPLATE_OWNER
from tests import support
from tests.smtp_server import ScriptedSMTP, ServerEvidence
from workflow import ledger
from workflow.models import PendingAction

FORM = reverse("applications:request_access")
VALID = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}
QUESTION_SUBJECT = "A question about your application"
QUESTION_BODY = "Hello $display_name,\n\nWe have a question about your application:\n\n$question_text\n\nPlease reply to this message.\n"
Attempt = OutboundMessage.Status
Disposition = ApprovedMessage.Disposition
_hash = {}


class Env:
    def __init__(self, committed, server, settings):
        self.committed, self.server, self.settings = committed, server, settings

    def use(self, server):
        self.server.stop()
        self.server = server.start()
        self.settings.CATALYST_MAIL_PORT = server.port
        ServerEvidence.server = server
        return server


@pytest.fixture
def p2(privileged_reset, monkeypatch, settings):
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    settings.CATALYST_WORKER_RETRY_SECONDS = 0
    server = ScriptedSMTP().start()
    settings.CATALYST_MAIL_HOST = "127.0.0.1"
    settings.CATALYST_MAIL_PORT = server.port
    settings.CATALYST_MAIL_TEST_HOST = ""
    settings.CATALYST_MAIL_TLS = "none"
    settings.CATALYST_MAIL_USER = settings.CATALYST_MAIL_PASSWORD = ""
    settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS = 1.5
    settings.CATALYST_MAIL_SEND_ATTEMPTS = 3
    settings.CATALYST_MAIL_TRANSPORT_BLOCK_LIMIT = 3
    settings.CATALYST_MAIL_TRANSPORT_BACKOFF_SECONDS = 0
    settings.CATALYST_MAIL_RECONCILE_CHECKS = 2
    settings.CATALYST_MAIL_RECONCILE_GRACE_SECONDS = 0
    settings.CATALYST_SEND_EVIDENCE_SOURCE = ""
    ServerEvidence.server, ServerEvidence.origin, ServerEvidence.recipient, ServerEvidence.digest = server, "provider", None, None
    env = Env(privileged_reset, server, settings)
    yield env
    env.server.stop()


def run_worker():
    call_command("run_worker", exit_when_idle=True, stdout=StringIO())


def staff(env, username, *groups, superuser=False):
    """As the owner (the authorized setup path, D-23)."""
    if "hash" not in _hash:
        _hash["hash"] = make_password("synthetic-password-only")
    owner = env.committed.connect("owner", autocommit=True)
    uid = owner.execute(
        "INSERT INTO accounts_user (password, is_superuser, username, first_name, last_name, email, is_staff, is_active,"
        " date_joined) VALUES (%s, %s, %s, '', '', '', true, true, now()) RETURNING id",
        [_hash["hash"], superuser, username]).fetchone()[0]
    for group in groups:
        owner.execute("INSERT INTO accounts_user_groups (user_id, group_id) SELECT %s, id FROM auth_group WHERE name = %s",
                      [uid, group])
    return get_user_model().objects.get(pk=uid)


def verified_application(email="ada@example.test"):
    """The S1 flow: intake, the verification send to the locmem sink, the applicant's confirmation."""
    assert Client().post(FORM, urlencode({**VALID, "email": email}), content_type="application/x-www-form-urlencoded").status_code == 302
    run_worker()
    path = re.search(r"http://catalyst\.example\.test(/confirm/\S+/)", mail.outbox[-1].body).group(1)
    page = Client().get(path)
    version = re.search(r'name="version" value="([^"]+)"', page.content.decode()).group(1)
    assert Client().post(path, {"version": version}).status_code == 200
    app = Application.objects.filter(email_key=email).order_by("-id").first()  # the newest, after a closed one
    assert app.contact_verified_at is not None
    return app


def question_template(version=1, body=QUESTION_BODY, variables=("display_name", "question_text"), secret=False):
    template, _ = MessageTemplate.objects.get_or_create(key="question_request", defaults={
        "purpose": "Ask an applicant an approved question", "secret_bearing": secret})
    return MessageTemplateVersion.objects.create(
        template=template, version=version, subject=QUESTION_SUBJECT, body_text=body, variables=list(variables),
        secret_bearing=secret, content_sha256=canonical_digest(QUESTION_SUBJECT, body))


@pytest.fixture
def ready(p2):
    """A verified applicant, an approved question template, an operator, a decision-maker and the owner."""
    app = verified_application()
    owner = staff(p2, "owner", TEMPLATE_OWNER)
    MessageTemplateVersion.objects.filter(template__key="question_request").exists() or question_template()
    version = MessageTemplateVersion.objects.get(template__key="question_request", version=1)
    outbound.approve_template_version(version.pk, owner)
    p2.app, p2.owner = app, owner
    p2.operator = staff(p2, "operator", OPERATOR)
    p2.decider = staff(p2, "decider", DECISION_MAKER)
    return p2


def ask(env, text="Which synthetic project best shows your work?"):
    question = Question.objects.create(application=env.app, text=text)
    return question, outbound.approve_question(question.pk, env.operator)


def sends(message):
    return list(PendingAction.objects.filter(kind="send_message", input_ref=str(message.send_ref)).order_by("id"))


def attempts(message):
    return list(OutboundMessage.objects.filter(approved_message=message).order_by("attempt_number")
                .values_list("attempt_number", "attempt_series", "status"))


def items(message, reason=None):
    found = StaffItem.objects.filter(approved_message=message)
    return list(found.filter(reason_code=reason) if reason else found)


def no_blind_retry(monkeypatch):
    """Every classified outcome is recorded with `finish` directly (016 A3)."""
    def refuse(*args, **kwargs):
        raise AssertionError("fail_or_retry used for a classified outcome")
    monkeypatch.setattr(ledger, "fail_or_retry", refuse)


# --- A-7: the ledger additions ------------------------------------------------------------------------------

def test_a7_due_in_held_and_fence(p2):
    app = verified_application()
    action = PendingAction.objects.create(kind="probe", subject_type="application", subject_id=app.public_ref,
                                          input_ref="", idempotency_key="probe:due")

    class Probe:
        kind, redeliverable, automated = "probe", True, True

        def lock_subject(self, claim):
            pass

    claim = ledger.claim_next({"probe": Probe()})
    assert claim.id == action.pk
    with transaction.atomic():
        ledger.fence(claim)  # still ours: extends the lease
    with pytest.raises(RuntimeError):
        ledger.fence(claim)  # outside a transaction it refuses
    assert ledger.finish(claim, Probe(), status=PendingAction.Status.QUEUED, due_in=timedelta(hours=1), refund_attempt=True)
    action.refresh_from_db()
    assert action.status == "queued" and action.attempts == 0 and action.completed_at is None
    assert PendingAction.objects.filter(pk=action.pk, due_at__gt=Now() + timedelta(minutes=59)).exists()
    assert ledger.claim_next({"probe": Probe()}) is None  # not due: no hot loop
    PendingAction.objects.filter(pk=action.pk).update(due_at=Now())
    claim = ledger.claim_next({"probe": Probe()})
    PendingAction.objects.filter(pk=action.pk).update(lease_token=None, status="queued")  # another claim took over
    with pytest.raises(ledger.LeaseLost), transaction.atomic():
        ledger.fence(claim)
    claim = ledger.claim_next({"probe": Probe()})
    assert ledger.finish(claim, Probe(), status=PendingAction.Status.HELD)
    action.refresh_from_db()
    assert action.status == "held" and action.completed_at is None  # held is not terminal


# --- TEST-P2-37: templates -----------------------------------------------------------------------------------

def test_p2_37_only_owner_approved_versions_render_and_approved_text_is_fixed(p2):
    app = verified_application()
    owner, operator = staff(p2, "owner", TEMPLATE_OWNER), staff(p2, "operator", OPERATOR)
    MessageTemplateVersion.objects.filter(template__key="question_request").exists() or question_template()
    draft = MessageTemplateVersion.objects.get(template__key="question_request", version=1)
    with pytest.raises(TemplateRefused, match="not_approved"):
        render(draft, {"display_name": "x", "question_text": "y"})
    question = Question.objects.create(application=app, text="Synthetic question?")
    with pytest.raises(outbound.Refused, match="no_approved_template_version"):
        outbound.approve_question(question.pk, operator)
    with pytest.raises(PermissionDenied):
        outbound.approve_template_version(draft.pk, operator)  # template approval stays with the owner (D-29)
    approved = outbound.approve_template_version(draft.pk, owner)
    assert approved.status == "approved" and approved.approved_by == f"user:{owner.pk}" and approved.approved_at
    for values in ({"display_name": "x"}, {"display_name": "x", "question_text": "y", "extra": "z"}):
        with pytest.raises(TemplateRefused, match="allow_list"):
            render(approved, values)
    app_role = p2.committed.connect("app")
    for sql in ("UPDATE correspondence_messagetemplateversion SET body_text = 'x' WHERE false",
                "UPDATE correspondence_messagetemplateversion SET subject = 'x' WHERE false",
                "UPDATE correspondence_messagetemplateversion SET variables = '[]' WHERE false",
                "DELETE FROM correspondence_messagetemplateversion WHERE false"):
        with pytest.raises(errors.InsufficientPrivilege):
            app_role.execute(sql)
        app_role.rollback()
    outside = question_template(version=2, body="Hello $display_name, $secret_value\n")
    with pytest.raises(TemplateRefused, match="placeholder_outside_allow_list"):
        outbound.approve_template_version(outside.pk, owner)
    with pytest.raises(IntegrityError, match="template_version_link_is_secret_bearing"), transaction.atomic():
        question_template(version=3, body="Open $link\n", variables=("link",))


# --- TEST-P2-12, 36, 49: the approved message ----------------------------------------------------------------

def test_p2_12_approving_a_question_twice_freezes_and_queues_one_message(ready):
    question, first = ask(ready)
    again = outbound.approve_question(question.pk, ready.operator)
    assert again.pk == first.pk
    assert ApprovedMessage.objects.count() == 1 and ApprovedMessageQuestion.objects.count() == 1
    assert [a.idempotency_key for a in sends(first)] == [f"send:{first.send_ref}:0"]
    second = ApprovedMessage.objects.create(
        kind="question", application=ready.app, recipient=first.recipient, template_version=first.template_version,
        frozen_subject=first.frozen_subject, frozen_body=first.frozen_body, content_sha256=first.content_sha256,
        authorized_by="user:0", authority="staff")
    with pytest.raises(IntegrityError, match="question_one_initial_message"), transaction.atomic():
        ApprovedMessageQuestion.objects.create(approved_message=second, question=question, purpose="initial")
    question.refresh_from_db()
    assert (question.approval_state, question.approved_by) == ("approved", f"user:{ready.operator.pk}")
    assert first.authorized_by == f"user:{ready.operator.pk}" and first.authority == "staff"
    assert first.content_sha256 == canonical_digest(first.frozen_subject, first.frozen_body)
    assert "Which synthetic project" in first.frozen_body and "$" not in first.frozen_body


def test_p2_36_the_recipient_is_always_the_frozen_verified_address(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    _, message = ask(ready)
    adoption = ready.app.adoptions.select_related("via_challenge").get()
    assert message.recipient == adoption.via_challenge.email_at_issue == "ada@example.test"
    run_worker()
    [delivered] = ready.server.messages
    assert delivered["rcpts"] == ["ada@example.test"]
    assert ready.server.parsed()["To"] == "ada@example.test"
    # A message whose frozen recipient is not the verified address is refused before any SMTP exchange.
    rogue = ApprovedMessage.objects.create(
        kind="question", application=ready.app, recipient="someone-else@example.test", template_version=message.template_version,
        frozen_subject=message.frozen_subject, frozen_body=message.frozen_body, content_sha256=message.content_sha256,
        authorized_by="user:0", authority="staff")
    outbound.enqueue_send(rogue, 0)
    before = list(ready.server.commands)
    run_worker()
    assert ready.server.commands == before and len(ready.server.messages) == 1
    [action] = sends(rogue)
    assert (action.status, action.last_error) == ("failed", "recipient_changed")
    assert attempts(rogue) == [] and [i.reason_code for i in items(rogue)] == ["send_refused"]


def test_p2_49_a_restarted_worker_sends_exactly_the_frozen_message(ready):
    _, message = ask(ready)
    # After freezing: a newer template version is approved and the question text changes in the database.
    newer = question_template(version=2, body="Changed wording for $display_name: $question_text\n")
    outbound.approve_template_version(newer.pk, ready.owner)
    owner = ready.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE correspondence_question SET text = 'Edited after approval' WHERE id = %s",
                  [message.question_links.get().question_id])
    # A first worker claims the send and dies before sending; the lease expires; a fresh worker runs it.
    claim = ledger.claim_next(ledger.handlers())
    assert claim.input_ref == str(message.send_ref)
    PendingAction.objects.filter(pk=claim.id).update(lease_expires_at=Now() - timedelta(seconds=1))
    run_worker()
    parsed = ready.server.parsed()
    assert canonical_digest(str(parsed["Subject"]), parsed.get_content()) == message.content_sha256
    assert "Changed wording" not in parsed.get_content() and "Edited after approval" not in parsed.get_content()
    assert parsed["Message-ID"] == outbound.message_id(message.send_ref)
    assert attempts(message) == [(1, 0, "accepted_by_server")]


# --- TEST-P2-48: outcome classes by protocol phase -----------------------------------------------------------

MATRIX = [
    # script, attempt statuses, disposition, send action status, staff item, messages received
    ({}, ["accepted_by_server"], "accepted_by_server", "done", None, 1),
    ({"greeting": 421}, ["transport_blocked"] * 3, "transport_blocked", "held", "smtp_transport_blocked", 0),
    ({"ehlo": "drop"}, ["transport_blocked"] * 3, "transport_blocked", "held", "smtp_transport_blocked", 0),
    ({"mail": 550}, ["transport_blocked"], "transport_blocked", "held", "smtp_transport_blocked", 0),
    ({"rcpt": 450}, ["rejected_temporary"] * 3, "retries_exhausted", "failed", "retries_exhausted", 0),
    ({"rcpt": 550}, ["rejected_permanent"], "rejected_permanent", "failed", "send_rejected_permanent", 0),
    ({"data": 554}, ["rejected_permanent"], "rejected_permanent", "failed", "send_rejected_permanent", 0),
    ({"end": 451}, ["rejected_temporary"] * 3, "retries_exhausted", "failed", "retries_exhausted", 3),
    ({"end": 554}, ["rejected_permanent"], "rejected_permanent", "failed", "send_rejected_permanent", 1),
    ({"end": "silent"}, ["unknown"], "active", "uncertain", "send_outcome_unknown", 1),
    ({"end": "drop"}, ["unknown"], "active", "uncertain", "send_outcome_unknown", 1),
    ({"end": "garbage"}, ["unknown"], "active", "uncertain", "send_outcome_unknown", 1),  # unparseable: code not recorded
    ({"ehlo": "garbage"}, ["transport_blocked"] * 3, "transport_blocked", "held", "smtp_transport_blocked", 0),
]


@pytest.mark.parametrize(("script", "statuses", "disposition", "action_status", "item", "received"), MATRIX,
                         ids=["accepted", "greeting-421", "ehlo-drop", "mail-550", "rcpt-450", "rcpt-550", "data-554",
                              "end-451", "end-554", "end-silent", "end-drop", "end-garbage", "ehlo-garbage"])
def test_p2_48_each_protocol_phase_maps_to_its_outcome_class(ready, monkeypatch, script, statuses, disposition,
                                                             action_status, item, received):
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP(script))
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert [s for _, _, s in attempts(message)] == statuses
    assert [n for n, _, _ in attempts(message)] == list(range(1, len(statuses) + 1))  # numbers never reused
    assert message.disposition == disposition
    [action] = sends(message)
    assert action.status == action_status
    if statuses[0] == "transport_blocked":
        assert action.attempts == 0 and action.completed_at is None  # channel faults consume no attempt; held is not final
    assert [i.reason_code for i in items(message)] == ([item] if item else [])
    assert len(ready.server.messages) == received
    if statuses == ["unknown"]:
        # Never an ordinary retry: one exchange, then reconciliation, which found no admissible evidence.
        assert PendingAction.objects.filter(kind="reconcile_send", status="done").count() == 2
    codes = list(OutboundMessage.objects.filter(approved_message=message).values_list("smtp_reply_code", flat=True))
    assert all(c is None or 100 <= c <= 599 for c in codes)
    if disposition == "accepted_by_server":
        parsed = ready.server.parsed()
        assert parsed["Auto-Submitted"] == "auto-generated" and parsed["Message-ID"] == outbound.message_id(message.send_ref)
        assert not any("deliver" in k for k in ApplicationEvent.objects.values_list("kind", flat=True))


def test_p2_48_a_write_failure_once_the_marker_write_started_is_unknown_and_never_resent(ready, monkeypatch):
    """SIMULATION (not a reproduced OS-level fault): the body and end-of-data marker are really handed to the
    socket and the synthetic server receives the complete message, then the sending call reports failure.
    sendall's progress is unknowable after an error, so the outcome is unknown: reconciled, then staff;
    never an automatic second send."""
    no_blind_retry(monkeypatch)
    real_send = transport._send_body

    def delivered_then_reported_failure(smtp, payload):
        real_send(smtp, payload)
        raise OSError("simulated: the sending call reports failure after handing over the whole payload")
    monkeypatch.setattr(transport, "_send_body", delivered_then_reported_failure)
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert len(ready.server.messages) == 1  # the server has the complete message
    assert attempts(message) == [(1, 0, "unknown")] and message.disposition == "active"
    assert sends(message)[0].status == "uncertain"
    assert PendingAction.objects.filter(kind="reconcile_send", status="done").count() == 2
    assert [i.reason_code for i in items(message)] == ["send_outcome_unknown"]
    run_worker()
    assert len(ready.server.messages) == 1 and ready.server.commands.count("DATA") == 1  # no second send
    assert "QUIT" not in ready.server.commands  # nothing was sent after the body write started


def test_p2_48_a_failure_known_before_the_marker_write_is_retried_within_its_bound(ready, monkeypatch):
    """The connection is closed at the DATA command, before any body byte is written: provably not accepted,
    so the bounded retry policy applies (and nothing reaches the server)."""
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"data": "drop"}))
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert [s for _, _, s in attempts(message)] == ["rejected_temporary"] * 3
    assert message.disposition == "retries_exhausted" and ready.server.messages == []


def test_p2_48_starttls_is_required_unless_the_host_is_loopback_with_tls_off(ready, settings, monkeypatch):
    no_blind_retry(monkeypatch)
    settings.CATALYST_MAIL_TLS = "starttls"  # the scripted server offers no STARTTLS: refused before MAIL
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert attempts(message) == [(1, 0, "transport_blocked")] and message.disposition == "transport_blocked"
    assert "MAIL" not in ready.server.commands and ready.server.messages == []


@pytest.mark.parametrize("script", [{}, {"end": "silent"}, {"rcpt": 550}], ids=["accepted", "unknown", "rejected"])
def test_p2_48_events_logs_errors_and_items_carry_no_address_subject_body_or_credential(ready, caplog, settings, script):
    caplog.set_level(logging.DEBUG)
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "sentinel-user-91d2", "sentinel-password-4be8"
    ready.use(ScriptedSMTP(script))
    _, message = ask(ready, text="Sentinel question text 7c1f?")
    run_worker()
    if StaffItem.objects.filter(status="open").exists():
        staff_actions.decide_uncertain_send(message.pk, ready.decider, "abandon", note="synthetic note")
    stored = json.dumps([
        list(ApplicationEvent.objects.values("kind", "data", "actor_ref")),
        list(PendingAction.objects.values("idempotency_key", "last_error")),
        list(StaffItem.objects.values("reason_code", "dedupe_key")),
        list(StaffItemResolution.objects.values("resolution_code", "note", "effects")),
    ], default=str)
    for sentinel in ("ada@example.test", "Sentinel question text 7c1f", QUESTION_SUBJECT, "sentinel-user-91d2",
                     "sentinel-password-4be8", "synthetic auth", "synthetic rcpt reply"):
        assert sentinel not in stored and sentinel not in caplog.text, sentinel
    assert "AUTH" in ready.server.commands  # the credential was really used


# --- TEST-P2-03, 25, 26, 27: unknown outcomes, evidence and staff decisions ----------------------------------

def test_p2_03_25_admissible_evidence_resolves_the_message_and_the_attempt_stays_unknown(ready, settings, monkeypatch):
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"end": "silent"}))
    settings.CATALYST_SEND_EVIDENCE_SOURCE = "tests.smtp_server.ServerEvidence"
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "accepted_by_evidence"
    assert attempts(message) == [(1, 0, "unknown")]  # evidence shows the message was accepted, not which attempt
    [action] = sends(message)
    assert (action.status, action.last_error) == ("done", "accepted_by_evidence")
    assert len(ready.server.messages) == 1 and items(message) == []
    assert ApplicationEvent.objects.filter(kind="message_accepted_by_evidence").count() == 1


@pytest.mark.parametrize("bad", ["catalyst_filed", "wrong_recipient", "wrong_digest"])
def test_p2_25_inadmissible_evidence_is_ignored_and_the_outcome_stays_unknown(ready, settings, monkeypatch, bad):
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"end": "silent"}))
    settings.CATALYST_SEND_EVIDENCE_SOURCE = "tests.smtp_server.ServerEvidence"
    if bad == "catalyst_filed":
        monkeypatch.setattr(ServerEvidence, "origin", "catalyst_filed")
    elif bad == "wrong_recipient":
        monkeypatch.setattr(ServerEvidence, "recipient", "other@example.test")
    else:
        monkeypatch.setattr(ServerEvidence, "digest", "0" * 64)
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "active" and attempts(message) == [(1, 0, "unknown")]
    assert [i.reason_code for i in items(message)] == ["send_outcome_unknown"] and len(ready.server.messages) == 1


def test_p2_26_staff_decide_an_unknown_send_and_no_decision_rewrites_the_attempt(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"end": ["silent", 250]}))  # the first exchange gets no reply; later ones are accepted
    _, message = ask(ready)
    run_worker()
    [item] = items(message, "send_outcome_unknown")
    superuser = staff(ready, "root", superuser=True)
    for user in (ready.operator, superuser):  # the decision-maker role only (D-30); superusers are refused too
        with pytest.raises(PermissionDenied):
            staff_actions.decide_uncertain_send(message.pk, user, "authorize_resend")
    resent = staff_actions.decide_uncertain_send(message.pk, ready.decider, "authorize_resend", note="synthetic\x00 note")
    run_worker()
    resent.refresh_from_db()
    assert resent.pk == message.pk and resent.disposition == "accepted_by_server"
    assert attempts(message) == [(1, 0, "unknown"), (2, 1, "accepted_by_server")]  # the unknown attempt is never rewritten
    assert [a.idempotency_key for a in sends(message)] == [f"send:{message.send_ref}:0", f"send:{message.send_ref}:1"]
    assert [a.status for a in sends(message)] == ["uncertain", "done"]
    first, second = (ready.server.parsed(i) for i in (0, 1))
    assert first["Message-ID"] == second["Message-ID"]  # the same logical message: the duplicate risk is explicit
    item.refresh_from_db()
    resolution = StaffItemResolution.objects.get(item=item)
    assert (item.status, resolution.resolution_code, resolution.resolved_by) == ("resolved", "authorize_resend", f"user:{ready.decider.pk}")
    assert resolution.note == "synthetic note" and resolution.effects["unknown_attempts"] is True
    with pytest.raises(outbound.Refused, match="nothing_to_decide|message_already_closed"):
        staff_actions.decide_uncertain_send(message.pk, ready.decider, "abandon")


def test_p2_26_abandon_records_the_operator_decision_not_a_provider_verdict(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"end": "silent"}))
    _, message = ask(ready)
    run_worker()
    staff_actions.decide_uncertain_send(message.pk, ready.decider, "abandon")
    message.refresh_from_db()
    assert message.disposition == "operator_abandoned" and message.disposition_by == f"user:{ready.decider.pk}"
    assert attempts(message) == [(1, 0, "unknown")] and sends(message)[0].status == "uncertain"
    run_worker()
    assert len(ready.server.messages) == 1  # nothing is sent after abandonment


def test_p2_26_a_permanent_rejection_is_never_resent_unchanged_only_revised(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"rcpt": [550, 250]}))
    _, message = ask(ready)
    run_worker()
    with pytest.raises(outbound.Refused, match="permanent_rejection_needs_a_revised_message"):
        staff_actions.decide_uncertain_send(message.pk, ready.decider, "authorize_resend")
    revised = staff_actions.decide_uncertain_send(message.pk, ready.decider, "revise")
    run_worker()
    message.refresh_from_db()
    revised.refresh_from_db()
    assert message.disposition == "superseded" and revised.supersedes_id == message.pk
    assert revised.send_ref != message.send_ref and revised.disposition == "accepted_by_server"
    assert ready.server.parsed()["Message-ID"] == outbound.message_id(revised.send_ref) != outbound.message_id(message.send_ref)
    assert list(revised.question_links.values_list("purpose", flat=True)) == ["revision"]


def test_p2_26_a_resend_after_a_held_channel_cancels_the_held_action_and_counts_blocks_per_series(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"greeting": [421, 421, 421, 421, 220]}))
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "transport_blocked" and [a.status for a in sends(message)] == ["held"]
    staff_actions.decide_uncertain_send(message.pk, ready.decider, "authorize_resend")
    assert [a.status for a in sends(message)] == ["cancelled", "queued"]  # no held action is left behind
    run_worker()
    message.refresh_from_db()
    # The new series is counted from zero: one more block, then acceptance, without re-holding at once.
    assert [(s, st) for _, s, st in attempts(message)] == [(0, "transport_blocked")] * 3 + [(1, "transport_blocked"), (1, "accepted_by_server")]
    assert message.disposition == "accepted_by_server"


def test_p2_27_a_crash_after_acceptance_and_before_recording_is_reconciled_never_resent(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    crashed = []

    def crash_once(claim, result):
        if not crashed:
            crashed.append(result.outcome)
            raise RuntimeError("synthetic: the worker stopped before recording")
    monkeypatch.setattr(outbound, "_after_send", crash_once)
    _, message = ask(ready)
    run_worker()
    assert crashed == ["accepted_by_server"]
    [action] = sends(message)
    assert action.status == "running" and attempts(message) == [(1, 0, "sending")]  # left for lease recovery
    PendingAction.objects.filter(pk=action.pk).update(lease_expires_at=Now() - timedelta(seconds=1))
    run_worker()
    action.refresh_from_db()
    assert action.status == "uncertain" and attempts(message) == [(1, 0, "unknown")]
    assert len(ready.server.messages) == 1  # reconciled, never sent again
    assert [i.reason_code for i in items(message)] == ["send_outcome_unknown"]


# --- TEST-P2-38: header injection ----------------------------------------------------------------------------

def test_p2_38_no_input_can_add_a_header(ready):
    _, message = ask(ready, text="Line one\r\nBcc: attacker@example.test\r\n\r\nInjected body?")
    with pytest.raises(ValueError):
        outbound.build_email(message, "Subject\r\nBcc: attacker@example.test", message.frozen_body)
    run_worker()
    [delivered] = ready.server.messages
    parsed = ready.server.parsed()
    assert delivered["rcpts"] == ["ada@example.test"] and parsed["Bcc"] is None and parsed["Cc"] is None
    assert ready.server.commands.count("RCPT") == 1


# --- TEST-P2-39: grants on the 2B.1 tables --------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "UPDATE correspondence_approvedmessage SET frozen_body = 'x' WHERE false",
    "UPDATE correspondence_approvedmessage SET recipient = 'x@example.test' WHERE false",
    "UPDATE correspondence_approvedmessage SET authorized_by = 'x' WHERE false",
    "UPDATE correspondence_approvedmessage SET content_sha256 = 'x' WHERE false",
    "UPDATE correspondence_approvedmessage SET template_version_id = NULL WHERE false",
    "DELETE FROM correspondence_approvedmessage WHERE false",
    "UPDATE correspondence_approvedmessagequestion SET purpose = 'initial' WHERE false",
    "DELETE FROM correspondence_approvedmessagequestion WHERE false",
    "UPDATE correspondence_question SET text = 'x' WHERE false",
    "UPDATE correspondence_question SET application_id = 1 WHERE false",
    "DELETE FROM correspondence_question WHERE false",
    "UPDATE correspondence_staffitem SET reason_code = 'x' WHERE false",
    "DELETE FROM correspondence_staffitem WHERE false",
    "UPDATE correspondence_staffitemresolution SET resolution_code = 'x' WHERE false",
    "DELETE FROM correspondence_staffitemresolution WHERE false",
    "UPDATE correspondence_outboundmessage SET rendered_sha256 = 'x' WHERE false",
    "UPDATE correspondence_outboundmessage SET approved_message_id = NULL WHERE false",
    "DELETE FROM correspondence_outboundmessage WHERE false",
    "UPDATE correspondence_messagetemplate SET secret_bearing = false WHERE false",
    "TRUNCATE correspondence_approvedmessage",
])
def test_p2_39_the_application_role_cannot_rewrite_or_remove_outbound_records(p2, sql):
    conn = p2.committed.connect("app")
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(sql)
    conn.rollback()


def test_p2_39_the_application_role_updates_only_the_status_columns(p2):
    conn = p2.committed.connect("app")
    for sql in ("UPDATE correspondence_approvedmessage SET disposition = disposition, disposition_at = now(), disposition_by = '' WHERE false",
                "UPDATE correspondence_staffitem SET status = status WHERE false",
                "UPDATE correspondence_outboundmessage SET status = status, protocol_phase_reached = '', smtp_reply_code = NULL,"
                " server_accepted_at = NULL WHERE false",
                "UPDATE correspondence_question SET status = status, approval_state = approval_state WHERE false"):
        conn.execute(sql)
    conn.rollback()


def test_p2_39_the_p2_groups_hold_exactly_the_matrix_permissions(p2):
    from django.contrib.auth.models import Group

    held = {g.name: set(g.permissions.values_list("codename", flat=True))
            for g in Group.objects.filter(name__in=[OPERATOR, DECISION_MAKER, TEMPLATE_OWNER])}
    controls = {"withdraw_question", "send_staff_message", "pause_automation", "resume_automation"}  # +2B.4
    assert held == {OPERATOR: {"approve_question", "confirm_question_outcome", "resolve_exception", *controls},  # +2B.3
                    DECISION_MAKER: {"approve_question", "decide_uncertain_send", "restart_collector",  # +2B.2
                                     "confirm_question_outcome", "resolve_exception", "resolve_identity_exception",
                                     *controls},
                    TEMPLATE_OWNER: {"approve_template_version"}}


# --- TEST-P2-40 (SMTP half): guards ----------------------------------------------------------------------------

class FakeSettings:
    def __init__(self, env="test", host="", test_host="", tls="none", user="", password=""):
        self.CATALYST_ENV, self.CATALYST_MAIL_HOST, self.CATALYST_MAIL_TEST_HOST = env, host, test_host
        self.CATALYST_MAIL_TLS, self.CATALYST_MAIL_USER, self.CATALYST_MAIL_PASSWORD = tls, user, password


@pytest.mark.parametrize(("kwargs", "ok"), [
    ({}, True),
    ({"host": "127.0.0.1"}, True),
    ({"host": "::1"}, True),
    ({"env": "development", "host": "127.0.0.1"}, True),
    ({"host": "smtp.example.test", "tls": "starttls"}, False),
    ({"host": "localhost"}, False),  # a name, not a literal: it could resolve anywhere
    ({"host": "203.0.113.9", "tls": "starttls"}, False),
    ({"host": "mailtest", "test_host": "mailtest", "tls": "starttls"}, True),
    ({"host": "mailtest", "test_host": "mailtest", "tls": "none"}, False),  # TLS off only for loopback
    ({"env": "development", "host": "mailtest", "test_host": "mailtest", "tls": "starttls"}, False),
    ({"user": "synthetic"}, False),  # credentials with no allowed host
    ({"host": "127.0.0.1", "user": "synthetic", "password": "synthetic"}, True),
    ({"host": "127.0.0.1", "tls": "opportunistic"}, False),
])
def test_p2_40_only_loopback_or_the_named_test_host_may_be_configured(kwargs, ok):
    assert (guards.mail_problems(FakeSettings(**kwargs)) == []) is ok


def test_p2_40_a_non_loopback_mail_host_refuses_to_start():
    result = support.run([sys.executable, "manage.py", "check"], CATALYST_MAIL_HOST="smtp.example.test")
    assert result.returncode != 0 and "CATALYST_MAIL_HOST must be a literal loopback address" in result.stderr


def test_p2_40_the_connected_peer_is_checked_before_any_credential(p2, settings, monkeypatch):
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    monkeypatch.setattr(socket.socket, "getpeername", lambda self: ("203.0.113.9", 25))  # a name that resolved elsewhere
    result = transport.send(b"Subject: x\r\n\r\nbody\r\n", "from@example.test", "ada@example.test")
    assert (result.outcome, result.hard) == ("transport_blocked", True)
    assert p2.server.commands == []  # not even EHLO, so no AUTH could carry the credential


# --- TEST-P2-41 (G3) and TEST-P2-52 ---------------------------------------------------------------------------

def test_p2_41_g3_reports_the_send_anomalies(ready):
    assert send_health()["anomalies"] == []
    out = StringIO()
    call_command("correspondence_health", stdout=out)
    ready.use(ScriptedSMTP({"rcpt": 550}))
    _, rejected = ask(ready)
    run_worker()
    ready.use(ScriptedSMTP({"end": "silent"}))
    _, unknown = ask(ready, text="A second synthetic question?")
    run_worker()
    stale = ApprovedMessage.objects.create(
        kind="question", application=ready.app, recipient=rejected.recipient, template_version=rejected.template_version,
        frozen_subject="s", frozen_body="b", content_sha256=canonical_digest("s", "b"), authorized_by="user:0", authority="staff")
    action = outbound.enqueue_send(stale, 0)
    OutboundMessage.objects.create(application=ready.app, pending_action=action, attempt_number=1, template_key="question_request",
                                   template_version="1", recipient=stale.recipient, status="sending", approved_message=stale)
    owner = ready.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE correspondence_outboundmessage SET created_at = now() - interval '1 day' WHERE approved_message_id = %s", [stale.pk])
    report = send_health()
    assert report["messages_by_disposition"]["rejected_permanent"] == 1 and report["needs_decision"] == 1
    assert report["unknown_attempts"] == 1 and report["uncertain_sends"] == 1 and report["stale_sending_attempts"] == 1
    assert report["open_send_items"] == 2
    assert report["anomalies"] == ["needs_decision", "open_send_items", "stale_sending_attempts", "uncertain_sends",
                                   "unknown_attempts"]
    with pytest.raises(SystemExit) as exit_:
        call_command("correspondence_health", stdout=StringIO())
    assert exit_.value.code == 1


def test_p2_52_each_2b1_service_needs_its_role(ready):
    question = Question.objects.create(application=ready.app, text="Synthetic question?")
    reader = staff(ready, "reader", "Read-only staff")
    superuser = staff(ready, "root", superuser=True)
    for user in (reader, superuser, ready.owner):
        with pytest.raises(PermissionDenied):
            outbound.approve_question(question.pk, user)
    version = question_template(version=2)
    for user in (reader, superuser, ready.operator, ready.decider):
        with pytest.raises(PermissionDenied):
            outbound.approve_template_version(version.pk, user)
    outbound.approve_question(question.pk, ready.decider)  # the decision-maker may also approve questions
    message = ApprovedMessage.objects.get()
    for user in (reader, superuser, ready.owner, ready.operator):
        with pytest.raises(PermissionDenied):
            staff_actions.decide_uncertain_send(message.pk, user, "abandon")


def test_p2_41_g3_clears_once_staff_have_decided(ready):
    ready.use(ScriptedSMTP({"end": "silent", "rcpt": [250, 550]}))
    _, unknown = ask(ready)
    run_worker()
    _, rejected = ask(ready, text="A second synthetic question?")
    run_worker()
    assert send_health()["anomalies"]
    staff_actions.decide_uncertain_send(unknown.pk, ready.decider, "abandon")
    staff_actions.decide_uncertain_send(rejected.pk, ready.decider, "abandon")
    assert send_health()["anomalies"] == []  # the unknown attempt stays in history but no longer alarms
    call_command("correspondence_health", stdout=StringIO())


# --- review fixes: races, bounds, poison, evidence, refusals ---------------------------------------------------

def test_p2_27_a_reclaim_during_the_exchange_discards_the_stale_result_and_sends_once(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    seen = []

    def reclaim_mid_exchange(claim, result):
        if seen:
            return
        seen.append(result.outcome)
        PendingAction.objects.filter(pk=claim.id).update(lease_expires_at=Now() - timedelta(seconds=1))
        assert ledger.run_one(ledger.handlers())  # a second worker reclaims while the first is between SMTP and recording
    monkeypatch.setattr(outbound, "_after_send", reclaim_mid_exchange)
    _, message = ask(ready)
    run_worker()
    assert seen == ["accepted_by_server"]
    [action] = sends(message)
    assert action.status == "uncertain"  # the stale worker's "accepted" was discarded by the fence
    assert attempts(message) == [(1, 0, "unknown")] and len(ready.server.messages) == 1
    message.refresh_from_db()
    assert message.disposition == "active" and [i.reason_code for i in items(message)] == ["send_outcome_unknown"]


def test_p2_12_two_concurrent_approvals_freeze_one_message(ready):
    import threading

    question = Question.objects.create(application=ready.app, text="Synthetic concurrent question?")
    barrier, results = threading.Barrier(2), []

    def approve():
        barrier.wait(10)
        results.append(outbound.approve_question(question.pk, ready.operator).pk)
    threads = [ready.committed.thread(approve) for _ in range(2)]
    for t in threads:
        t.join(30)
    assert len(results) == 2 and len(set(results)) == 1
    assert ApprovedMessage.objects.count() == 1 and PendingAction.objects.filter(kind="send_message").count() == 1


def test_p2_26_a_resend_that_ends_unknown_again_gets_its_own_reconciliation_checks(ready):
    ready.use(ScriptedSMTP({"end": "silent"}))
    _, message = ask(ready)
    run_worker()
    staff_actions.decide_uncertain_send(message.pk, ready.decider, "authorize_resend")
    run_worker()
    keys = sorted(PendingAction.objects.filter(kind="reconcile_send").values_list("idempotency_key", flat=True))
    assert keys == sorted(f"reconcile:{message.send_ref}:{series}:{n}" for series in (0, 1) for n in (1, 2))
    assert attempts(message) == [(1, 0, "unknown"), (2, 1, "unknown")]
    assert [i.status for i in items(message, "send_outcome_unknown")] == ["resolved", "open"]


def test_p2_a7_the_poison_rule_ends_a_send_unknown_with_a_staff_item(ready, monkeypatch):
    no_blind_retry(monkeypatch)
    _, message = ask(ready)
    [action] = sends(message)
    PendingAction.objects.filter(pk=action.pk).update(attempts=action.max_attempts)  # every attempt died
    run_worker()
    action.refresh_from_db()
    assert action.status == "uncertain" and ready.server.messages == []
    assert [i.reason_code for i in items(message)] == ["send_outcome_unknown"]


def test_p2_25_a_catalyst_filed_copy_is_never_evidence_whatever_its_label(ready):
    _, message = ask(ready)
    record = outbound.Evidence(origin="provider", message_id=outbound.message_id(message.send_ref),
                               recipient=message.recipient, content_sha256=message.content_sha256)
    assert outbound.admissible(record, message, {message.content_sha256})
    filed = outbound.Evidence(**{**record.__dict__, "filed_by_catalyst": True})
    assert not outbound.admissible(filed, message, {message.content_sha256})


def test_p2_40_an_evidence_source_is_refused_outside_test():
    fake = FakeSettings(env="development")
    fake.CATALYST_SEND_EVIDENCE_SOURCE = "tests.smtp_server.ServerEvidence"
    assert any("CATALYST_SEND_EVIDENCE_SOURCE" in p for p in guards.mail_problems(fake))


def test_p2_05_a_paused_application_sends_nothing_until_resumed(ready):
    from workflow.models import AutomationPause

    pause = AutomationPause.objects.create(subject_type="application", subject_id=ready.app.public_ref,
                                           reason="synthetic", actor_ref="user:0")
    _, message = ask(ready)
    run_worker()
    assert sends(message)[0].status == "queued" and ready.server.messages == [] and attempts(message) == []
    pause.delete()
    run_worker()
    message.refresh_from_db()
    assert message.disposition == "accepted_by_server" and len(ready.server.messages) == 1


def test_approve_question_refusals(p2):
    operator, owner = staff(p2, "operator", OPERATOR), staff(p2, "owner", TEMPLATE_OWNER)
    MessageTemplateVersion.objects.filter(template__key="question_request").exists() or question_template()
    outbound.approve_template_version(MessageTemplateVersion.objects.get(template__key="question_request", version=1).pk, owner)
    assert Client().post(FORM, urlencode({**VALID, "email": "unverified@example.test"}),
                         content_type="application/x-www-form-urlencoded").status_code == 302
    unverified = Application.objects.get(email_key="unverified@example.test")
    with pytest.raises(outbound.Refused, match="contact_not_verified"):
        outbound.approve_question(Question.objects.create(application=unverified, text="q?").pk, operator)
    app = verified_application()
    withdrawn = Question.objects.create(application=app, text="q?", status="withdrawn")
    with pytest.raises(outbound.Refused, match="question_withdrawn"):
        outbound.approve_question(withdrawn.pk, operator)
    owner_conn = p2.committed.connect("owner", autocommit=True)
    owner_conn.execute("UPDATE applications_application SET stage = 'closed' WHERE id = %s", [app.pk])
    with pytest.raises(outbound.Refused, match="application_closed"):
        outbound.approve_question(Question.objects.create(application=app, text="q?").pk, operator)
    assert ApprovedMessage.objects.count() == 0


def test_p2_26_a_resend_is_refused_for_a_withdrawn_question_and_a_note_with_a_link_changes_nothing(ready):
    from correspondence.staff_items import NoteRefused

    ready.use(ScriptedSMTP({"end": "silent"}))
    question, message = ask(ready)
    run_worker()
    with pytest.raises(NoteRefused):
        staff_actions.decide_uncertain_send(message.pk, ready.decider, "abandon",
                                            note="see http://catalyst.example.test/confirm/abc/")
    message.refresh_from_db()
    assert message.disposition == "active" and StaffItemResolution.objects.count() == 0  # rolled back whole
    Question.objects.filter(pk=question.pk).update(status="withdrawn")
    with pytest.raises(outbound.Refused, match="question_withdrawn"):
        staff_actions.decide_uncertain_send(message.pk, ready.decider, "authorize_resend")


@pytest.mark.parametrize(("auth", "statuses"), [(535, ["transport_blocked"]), (454, ["transport_blocked"] * 3)],
                         ids=["auth-535-held-now", "auth-454-retried"])
def test_p2_48_an_authentication_refusal_is_a_channel_fault(ready, settings, monkeypatch, auth, statuses):
    no_blind_retry(monkeypatch)
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD = "synthetic-user", "synthetic-password-only"
    ready.use(ScriptedSMTP({"auth": auth}))
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert [s for _, _, s in attempts(message)] == statuses and message.disposition == "transport_blocked"
    assert "MAIL" not in ready.server.commands and sends(message)[0].attempts == 0


def test_p2_48_a_refused_connection_is_a_channel_fault(ready, settings, monkeypatch):
    no_blind_retry(monkeypatch)
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    settings.CATALYST_MAIL_PORT = probe.getsockname()[1]
    probe.close()  # nothing listens there now
    _, message = ask(ready)
    run_worker()
    message.refresh_from_db()
    assert [s for _, _, s in attempts(message)] == ["transport_blocked"] * 3 and message.disposition == "transport_blocked"


def test_p2_48_a_real_disconnect_after_354_is_never_accepted_or_retried_blindly(ready, monkeypatch):
    """The server replies 354 and closes. Once the marker-carrying write has started, whether the marker
    reached the server cannot be known, so the outcome is `unknown` whether or not the write itself raised.
    Never accepted, and an unknown is never retried as ordinary."""
    no_blind_retry(monkeypatch)
    ready.use(ScriptedSMTP({"data": "354-then-drop"}))
    _, message = ask(ready)
    run_worker()
    statuses = [s for _, _, s in attempts(message)]
    assert ready.server.messages == [] and statuses == ["unknown"]  # the marker write started: unknown


def test_p2_38_a_recipient_with_a_line_break_cannot_be_framed(ready):
    _, message = ask(ready)
    message.recipient = "ada@example.test\r\nBcc: attacker@example.test"
    with pytest.raises(ValueError):
        outbound.build_email(message, message.frozen_subject, message.frozen_body)


def test_a7_fence_extends_the_lease(p2):
    app = verified_application()
    PendingAction.objects.create(kind="probe", subject_type="application", subject_id=app.public_ref,
                                 input_ref="", idempotency_key="probe:fence")

    class Probe:
        kind, redeliverable, automated = "probe", True, True
    claim = ledger.claim_next({"probe": Probe()})
    PendingAction.objects.filter(pk=claim.id).update(lease_expires_at=Now() + timedelta(seconds=5))
    with transaction.atomic():
        ledger.fence(claim)
    assert PendingAction.objects.filter(pk=claim.id, lease_expires_at__gt=Now() + timedelta(seconds=60)).exists()


@pytest.mark.django_db
def test_the_seeded_question_template_is_a_valid_synthetic_draft():
    from correspondence.rendering import check_version

    version = MessageTemplateVersion.objects.select_related("template").get(template__key="question_request", version=1)
    assert (version.status, version.synthetic, version.secret_bearing) == ("draft", True, False)
    check_version(version)


def test_p2_a7_evidence_after_the_poison_rule_resolves_its_item(ready, settings):
    settings.CATALYST_SEND_EVIDENCE_SOURCE = "tests.smtp_server.ServerEvidence"
    ready.use(ScriptedSMTP({"end": "silent"}))
    _, message = ask(ready)
    claim = ledger.claim_next(ledger.handlers())
    decision = ledger.handlers()["send_message"].check(claim)
    transport.send(decision.payload, settings.DEFAULT_FROM_EMAIL, decision.recipient)  # reaches the server, no reply
    PendingAction.objects.filter(pk=claim.id).update(attempts=claim.max_attempts, lease_expires_at=Now() - timedelta(seconds=1))
    run_worker()  # the poison rule: uncertain, an item at once, then reconciliation finds admissible evidence
    message.refresh_from_db()
    assert message.disposition == "accepted_by_evidence"
    [item] = items(message)
    assert item.status == "resolved" and item.resolution.resolution_code == "accepted_by_evidence"
    assert send_health()["anomalies"] == []


def test_p2_a7_an_uncertain_send_without_an_unknown_attempt_reaches_staff(ready):
    _, message = ask(ready)
    [action] = sends(message)
    PendingAction.objects.filter(pk=action.pk).update(status="uncertain")  # a defect ended it before any exchange
    outbound.enqueue_reconcile(message, 0, 1)
    run_worker()
    assert [i.reason_code for i in items(message)] == ["send_outcome_unknown"] and ready.server.messages == []


def wait_until(predicate, seconds, what):
    import time

    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {seconds}s waiting for {what}")
        time.sleep(0.1)


def test_p2_27_a_real_worker_killed_after_acceptance_is_recovered_without_a_second_send(ready, tmp_path):
    """M7 (owner closeout of PR #21): a real `run_worker` process sends to the synthetic server, is killed
    with SIGKILL after the server accepted the complete message and before the result is recorded, and a
    fresh real worker recovers the action through the normal lease path. The synthetic server lives in this
    test process, so it survives the kill and keeps its count."""
    import signal

    question, message = ask(ready)  # through the real services
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    marker = tmp_path / "exchange-finished"
    mail_env = dict(CATALYST_MAIL_HOST="127.0.0.1", CATALYST_MAIL_PORT=str(ready.server.port), CATALYST_MAIL_TLS="none",
                    CATALYST_MAIL_RECONCILE_GRACE_SECONDS="0", CATALYST_MAIL_RECONCILE_CHECKS="2")
    killed = support.worker_process(sink, str(marker), module="tests.worker_child_outbound", **mail_env)
    survivor = None
    try:
        wait_until(marker.exists, 30, "the first worker to finish its SMTP exchange")
        assert marker.read_text() == "accepted_by_server" and len(ready.server.messages) == 1
        assert attempts(message) == [(1, 0, "sending")] and sends(message)[0].status == "running"
        killed.send_signal(signal.SIGKILL)
        assert killed.wait(10) == -signal.SIGKILL
        survivor = support.worker_process(sink, **mail_env)  # the real command, no seam
        wait_until(lambda: StaffItem.objects.filter(approved_message=message, reason_code="send_outcome_unknown").exists(),
                   40, "recovery through reconciliation to a staff item")
        survivor.send_signal(signal.SIGTERM)
        out, err = survivor.communicate(timeout=20)
        assert survivor.returncode == 0, err
    finally:
        for proc in (killed, survivor):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(10)
    message.refresh_from_db()
    assert len(ready.server.messages) == 1 and ready.server.commands.count("DATA") == 1  # no second SMTP send
    assert attempts(message) == [(1, 0, "unknown")]  # uncertainty preserved; no invented acceptance
    assert message.disposition == "active" and sends(message)[0].status == "uncertain"
    assert not ApplicationEvent.objects.filter(kind__in=["message_accepted_by_server", "message_accepted_by_evidence"]).exists()
    assert ApprovedMessage.objects.count() == 1 and Question.objects.count() == 1
    assert ApprovedMessageQuestion.objects.count() == 1 and StaffItemResolution.objects.count() == 0
    assert [i.status for i in items(message)] == ["open"]
    for text in (out, err):
        assert "ada@example.test" not in text and "Which synthetic project" not in text


# --- 9kg.1: correspondence evidence is protected for every role, not only by the application role's grants -------

REFUSED = (errors.InsufficientPrivilege, errors.RaiseException)


def test_9kg_1_an_approved_message_keeps_its_authorization_and_only_its_disposition_changes(ready):
    question, message = ask(ready)
    owner = ready.committed.connect("owner", autocommit=True)
    for column, value in (("recipient", "mallory@example.test"), ("frozen_body", "changed"),
                          ("authorized_by", "user:0"), ("content_sha256", "0" * 64), ("authorized_at", None)):
        with pytest.raises(REFUSED, match="approved message"):
            owner.execute(f"UPDATE correspondence_approvedmessage SET {column} = %s WHERE id = %s", [value, message.pk])
    with pytest.raises(REFUSED, match="approved message"):
        owner.execute("DELETE FROM correspondence_approvedmessage WHERE id = %s", [message.pk])
    with pytest.raises(REFUSED):
        owner.execute("TRUNCATE correspondence_approvedmessage CASCADE")
    # Delivery state is not evidence: the disposition stays updatable.
    owner.execute("UPDATE correspondence_approvedmessage SET disposition = 'operator_abandoned', disposition_at = now(),"
                  " disposition_by = 'user:1' WHERE id = %s", [message.pk])


def test_9kg_1_an_approved_template_version_is_final_and_may_only_retire_while_drafts_stay_free(ready):
    owner = ready.committed.connect("owner", autocommit=True)
    approved = MessageTemplateVersion.objects.get(template__key="question_request", version=1)
    for sql in ("UPDATE correspondence_messagetemplateversion SET body_text = 'changed' WHERE id = %s",
                "UPDATE correspondence_messagetemplateversion SET approved_by = 'user:0' WHERE id = %s",
                "UPDATE correspondence_messagetemplateversion SET status = 'draft' WHERE id = %s",
                "DELETE FROM correspondence_messagetemplateversion WHERE id = %s"):
        with pytest.raises(REFUSED, match="message template version"):
            owner.execute(sql, [approved.pk])
    draft = question_template(version=2)
    owner.execute("UPDATE correspondence_messagetemplateversion SET body_text = body_text || ' ' WHERE id = %s", [draft.pk])
    owner.execute("UPDATE correspondence_messagetemplateversion SET status = 'retired' WHERE id = %s", [approved.pk])
    with pytest.raises(REFUSED, match="message template version"):  # retired is final too
        owner.execute("UPDATE correspondence_messagetemplateversion SET status = 'approved' WHERE id = %s", [approved.pk])


def test_9kg_1_a_staff_item_resolution_is_append_only_for_every_role(ready):
    from correspondence.staff_items import open_item, resolve_item

    item = open_item("synthetic_protection_check", "protection:1", application=ready.app)
    resolve_item(item, code="checked", actor_ref=f"user:{ready.decider.pk}")
    resolution = StaffItemResolution.objects.get(item=item)
    for role in ("app", "owner"):
        conn = ready.committed.connect(role, autocommit=True)
        for sql in ("UPDATE correspondence_staffitemresolution SET note = 'rewritten' WHERE id = %s",
                    "DELETE FROM correspondence_staffitemresolution WHERE id = %s"):
            with pytest.raises(REFUSED):
                conn.execute(sql, [resolution.pk])
        with pytest.raises(REFUSED):
            conn.execute("TRUNCATE correspondence_staffitemresolution")

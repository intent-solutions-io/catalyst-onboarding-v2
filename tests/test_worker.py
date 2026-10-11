"""The worker and the verification send (S1-T5; 005 S1.2 Send, S1.4; D-20, D-24): TEST-S1-06, TEST-S1-07,
TEST-S1-17 to TEST-S1-19, and the worker parts of TEST-S1-13, 14 and 16.

Every test commits real data (`privileged_reset`), because claims, leases and fences only mean something
across committed transactions. Work is always created by an actual intake POST. In-process tests run the
real `run_worker` command (locmem sink) or, where a fault must land at an exact point, the ledger's own
claim and result functions with a named seam. Subprocess tests run `manage.py run_worker` with a
run-owned file sink and an explicit minimal environment (tests/support.py). Lease expiry is either written
as a past time or, for the killed-worker test, a real two-second lease; no clock is mocked.
"""

import json
import logging
import re
import select
import signal
import threading
import time
import uuid
from datetime import timedelta
from io import StringIO
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.db.models.functions import Now
from django.test import Client
from django.urls import reverse

from applications.links import CONFIRM_PATH, signer, verification_link
from applications.models import Application, ApplicationEvent, ContactChallenge, VersionAdoption
from config import runtime
from correspondence import verification
from correspondence.models import OutboundMessage
from tests import support
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

FORM = reverse("applications:request_access")
VALID = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}
APP_ROLE = settings.CATALYST_DB_ROLES["app"]


def intake(**fields):
    response = Client().post(FORM, urlencode({**VALID, **fields}), content_type="application/x-www-form-urlencoded")
    assert response.status_code == 302
    return Application.objects.get(email_key=fields.get("email", VALID["email"]).lower())


@pytest.fixture
def worker(privileged_reset, monkeypatch, settings):
    """Runs the real command in-process. It declares this process a worker, so its connections are role
    checked like the real one; the declaration is undone afterwards."""
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    settings.CATALYST_WORKER_RETRY_SECONDS = 0

    def run():
        out = StringIO()
        call_command("run_worker", exit_when_idle=True, stdout=out)
        return out.getvalue()
    return run


def expire_lease(action_id):
    PendingAction.objects.filter(pk=action_id).update(lease_expires_at=Now() - timedelta(seconds=1))


def link_in(body):
    match = re.search(re.escape(settings.CATALYST_PUBLIC_BASE_URL + CONFIRM_PATH) + r"(\S+)/", body)
    assert match, "no verification link in the message"
    return match.group(0), match.group(1)


def handler():
    return ledger.handlers()["send_verification"]


def events(app):
    return list(app.events.order_by("id").values_list("kind", flat=True))


# --- TEST-S1-06: normal processing --------------------------------------------------------------------------

def test_s1_06_the_worker_sends_the_queued_verification_and_records_the_outcome(worker, caplog, monkeypatch):
    app = intake()
    challenge = ContactChallenge.objects.get()
    caplog.set_level(logging.DEBUG)
    seen = []

    def spy(claim):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            seen.append(cursor.fetchone()[0])
    monkeypatch.setattr(verification, "_after_send", spy)

    assert "worker stopped after 1 actions" in worker()
    assert seen == [APP_ROLE] and runtime.process_kind() == "worker"
    [message] = mail.outbox
    assert message.to == ["ada@example.test"] and message.subject == verification.SUBJECT
    link, token = link_in(message.body)
    assert link == verification_link(challenge.public_id)
    assert link.startswith("http://catalyst.example.test/confirm/")  # PUBLIC_BASE_URL, not the request's host
    assert "testserver" not in message.body
    assert signer().unsign(token) == str(challenge.public_id)
    action = PendingAction.objects.get()
    assert (action.status, action.attempts, action.lease_token, action.last_error) == ("done", 1, None, "")
    assert action.completed_at is not None
    outbound = OutboundMessage.objects.get()
    assert (outbound.attempt_number, outbound.status, outbound.recipient) == (1, "accepted", "ada@example.test")
    assert (outbound.template_key, outbound.template_version) == ("verification_invitation", "s1-synthetic-1")
    assert outbound.message_id == message.extra_headers["Message-ID"] and outbound.sent_at is not None
    assert events(app) == ["submission_received", "verification_sent"]
    sent = ApplicationEvent.objects.get(kind="verification_sent")
    assert sent.data == {"attempt": 1, "template_version": "s1-synthetic-1"} and sent.actor_type == "system"
    # D-24 and logging: neither the token nor the link nor the address is stored in history or logged.
    history = json.dumps(list(ApplicationEvent.objects.values("data", "actor_ref")))
    for secret in (token, link, "ada@example.test"):
        assert secret not in history and secret not in caplog.text
    assert VersionAdoption.objects.count() == 0  # adoption is S1-T6's


def test_s1_06_an_action_is_invisible_to_the_worker_until_its_intake_commits(worker, privileged_reset):
    inserted, release, results = threading.Event(), threading.Event(), []

    def hold_before_commit(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.startswith('INSERT INTO "applications_applicationevent"'):  # the last write, after the action
            inserted.set()
            release.wait(20)
        return result

    def submit():
        with connection.execute_wrapper(hold_before_commit):
            results.append(Client().post(FORM, urlencode(VALID), content_type="application/x-www-form-urlencoded").status_code)

    thread = privileged_reset.thread(submit)
    try:
        assert inserted.wait(20), "intake did not reach its last write"
        assert ledger.claim_next() is None  # the queued action exists only inside the open transaction
        assert worker().endswith("worker stopped after 0 actions\n") and mail.outbox == []
    finally:
        release.set()
        thread.join(20)
    assert results == [302]
    assert "worker stopped after 1 actions" in worker()
    assert len(mail.outbox) == 1


# --- TEST-S1-07: interruption ---------------------------------------------------------------------------

def test_s1_07a_claimed_then_stopped_before_sending_sends_exactly_once(worker):
    app = intake()
    claim = ledger.claim_next()  # the worker stops here: claimed, nothing sent
    assert claim.attempt == 1 and mail.outbox == []
    expire_lease(claim.id)
    assert "worker stopped after 1 actions" in worker()
    assert len(mail.outbox) == 1
    action = PendingAction.objects.get()
    assert (action.status, action.attempts) == ("done", 2)
    assert list(OutboundMessage.objects.values_list("attempt_number", "status")) == [(2, "accepted")]
    assert events(app) == ["submission_received", "verification_sent"]


class Crash(BaseException):
    """The process dies: not an Exception, so nothing in the worker catches it."""


def test_s1_07b_sink_accepted_then_stopped_before_recording_redelivers_the_identical_link(worker, monkeypatch):
    app = intake()

    def crash(claim):
        raise Crash
    monkeypatch.setattr(verification, "_after_send", crash)
    with pytest.raises(Crash):
        ledger.run_one()
    assert len(mail.outbox) == 1  # the sink has it
    action = PendingAction.objects.get()
    assert (action.status, action.attempts) == ("running", 1)
    assert OutboundMessage.objects.count() == 0 and events(app) == ["submission_received"]  # nothing recorded

    monkeypatch.setattr(verification, "_after_send", lambda claim: None)
    expire_lease(action.pk)
    assert "worker stopped after 1 actions" in worker()
    first, second = mail.outbox
    assert link_in(first.body) == link_in(second.body)  # D-20: the identical invitation, same link
    assert first.to == second.to == ["ada@example.test"]
    assert first.extra_headers["Message-ID"] != second.extra_headers["Message-ID"]
    action.refresh_from_db()
    assert (action.status, action.attempts) == ("done", 2)
    assert list(OutboundMessage.objects.values_list("attempt_number", "status")) == [(2, "accepted")]
    # The only repeated effect is the message: one challenge, one action, no adoption, no next-stage work.
    assert ContactChallenge.objects.count() == 1 and PendingAction.objects.count() == 1
    assert VersionAdoption.objects.count() == 0
    assert events(app) == ["submission_received", "verification_sent"]


def sink_messages(sink):
    """Every message the file sink holds (one file per backend connection, messages separated by dashes)."""
    bodies = []
    for path in sorted(sink.iterdir()):
        bodies += [m for m in path.read_text().split("-" * 79) if m.strip()]
    return bodies


def wait_until(predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(0.05)


def test_s1_07c_a_killed_worker_is_recovered_automatically_by_the_running_worker_loop(privileged_reset, tmp_path):
    app = intake()
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    marker = tmp_path / "accepted"
    # The first worker's claim carries a 6-second lease, long enough for the second loop to be running
    # before it expires, so the recovery below is the running loop's own, not a fresh start's.
    killed = support.worker_process(sink, str(marker), module="tests.worker_child", CATALYST_WORKER_LEASE_SECONDS="6")
    survivor = None
    try:
        wait_until(marker.exists, 30, "the first worker to hand a message to the sink")
        assert len(sink_messages(sink)) == 1
        survivor = support.worker_process(sink)
        ready, _, _ = select.select([survivor.stdout], [], [], 30)
        assert ready and survivor.stdout.readline().strip() == "worker started"
        # The survivor is polling and the first worker's lease is still current (database clock); then it dies.
        assert PendingAction.objects.filter(status="running", lease_expires_at__gt=Now()).exists(), "lease expired too early"
        killed.send_signal(signal.SIGKILL)
        assert killed.wait(10) == -signal.SIGKILL
        wait_until(lambda: PendingAction.objects.filter(status="done").exists(), 30, "automatic recovery")
        survivor.send_signal(signal.SIGTERM)  # clean shutdown
        out, err = survivor.communicate(timeout=20)
        assert survivor.returncode == 0, err
        assert out.strip() == "worker stopped after 1 actions"
    finally:
        for proc in (killed, survivor):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(10)
    messages = sink_messages(sink)
    assert len(messages) == 2
    assert link_in(messages[0])[0] == link_in(messages[1])[0] == verification_link(ContactChallenge.objects.get().public_id)
    action = PendingAction.objects.get()
    assert (action.status, action.attempts) == ("done", 2)
    assert list(OutboundMessage.objects.values_list("attempt_number", "status")) == [(2, "accepted")]
    assert events(app) == ["submission_received", "verification_sent"]
    assert ContactChallenge.objects.count() == 1 and VersionAdoption.objects.count() == 0
    for text in (out, err):
        assert "ada@example.test" not in text and CONFIRM_PATH not in text


# --- TEST-S1-17: lease fencing ----------------------------------------------------------------------------

def test_s1_17_a_stale_worker_cannot_record_an_authoritative_result(worker, caplog):
    caplog.set_level(logging.DEBUG)
    app = intake()
    stale = ledger.claim_next()
    expire_lease(stale.id)
    current = ledger.claim_next()
    assert (current.id, current.attempt) == (stale.id, 2) and current.lease_token != stale.lease_token
    handler().run(current)
    assert len(mail.outbox) == 1

    # The stale worker's late success: outbound record and history inside the fenced transaction.
    def late_write():
        OutboundMessage.objects.create(
            application=app, pending_action_id=stale.id, attempt_number=stale.attempt, template_key="x",
            template_version="x", recipient="ada@example.test", status="accepted")
        handler().record(stale, "verification_sent", {"attempt": stale.attempt})
    assert ledger.finish(stale, handler(), status="done", write=late_write) is False
    assert "lease lost; result discarded" in caplog.text
    # And the stale worker running its whole handler late sends nothing: the check sees the lease is gone.
    handler().run(stale)
    assert len(mail.outbox) == 1
    action = PendingAction.objects.get()
    assert (action.status, action.attempts) == ("done", 2)
    assert list(OutboundMessage.objects.values_list("attempt_number", flat=True)) == [2]
    assert events(app).count("verification_sent") == 1


def test_s1_17_a_stale_result_cannot_overwrite_a_reclaimed_running_action(worker):
    intake()
    stale = ledger.claim_next()
    expire_lease(stale.id)
    current = ledger.claim_next()
    def late_write():
        OutboundMessage.objects.create(
            application=Application.objects.get(), pending_action_id=stale.id, attempt_number=stale.attempt,
            template_key="x", template_version="x", recipient="ada@example.test", status="accepted")
    # Same status (running), different token: the fence alone refuses it, and the write is rolled back.
    assert ledger.finish(stale, handler(), status="done", write=late_write) is False
    action = PendingAction.objects.get()
    assert (action.status, action.lease_token, action.last_error) == ("running", current.lease_token, "")
    assert OutboundMessage.objects.count() == 0


# --- TEST-S1-18: bounded attempts and the poison rule ---------------------------------------------------------

@pytest.mark.parametrize(("fault", "error"), [("raise", "ConnectionRefusedError"), ("zero", "SendCountMismatch")])
def test_s1_18_a_send_that_always_fails_reaches_failed_at_the_maximum(worker, monkeypatch, fault, error):
    from django.core.mail.backends.locmem import EmailBackend

    def broken(self, messages):
        if fault == "raise":
            raise ConnectionRefusedError("synthetic")
        return 0
    monkeypatch.setattr(EmailBackend, "send_messages", broken)
    app = intake()
    assert "worker stopped after 3 actions" in worker()  # retried with zero backoff, then nothing claimable
    action = PendingAction.objects.get()
    assert (action.status, action.attempts, action.last_error) == ("failed", 3, f"send failed: {error}")
    assert list(OutboundMessage.objects.order_by("attempt_number").values_list("attempt_number", "status")) == [
        (1, "failed"), (2, "failed"), (3, "failed")]
    failures = list(app.events.filter(kind="verification_send_failed").order_by("id").values_list("data", flat=True))
    assert failures == [{"attempt": n, "error": error, "final": n == 3} for n in (1, 2, 3)]
    assert worker().endswith("worker stopped after 0 actions\n")  # not run again


def test_s1_18_a_failed_attempt_is_retried_only_after_the_backoff(worker, monkeypatch, settings):
    from django.core.mail.backends.locmem import EmailBackend

    monkeypatch.setattr(EmailBackend, "send_messages", lambda self, messages: 0)
    intake()
    settings.CATALYST_WORKER_RETRY_SECONDS = 600
    assert "worker stopped after 1 actions" in worker()
    action = PendingAction.objects.get()
    assert (action.status, action.attempts) == ("queued", 1)
    assert PendingAction.objects.filter(pk=action.pk, due_at__gt=Now() + timedelta(seconds=590)).exists()  # database clock


def test_s1_18_a_worker_that_dies_on_every_attempt_is_stopped_by_the_poison_rule(worker):
    app = intake()
    for attempt in (1, 2, 3):  # each claim, then the process dies before doing anything
        claim = ledger.claim_next()
        assert claim.attempt == attempt
        expire_lease(claim.id)
    assert "worker stopped after 1 actions" in worker()
    assert mail.outbox == []  # the handler never ran again
    action = PendingAction.objects.get()
    assert (action.status, action.attempts, action.last_error) == ("failed", 3, "attempts exhausted")
    assert app.events.get(kind="action_attempts_exhausted").data == {"attempts": 3}
    assert worker().endswith("worker stopped after 0 actions\n")


def test_s1_18_a_handler_defect_is_bounded_and_recorded(worker, monkeypatch):
    def defect(self, claim):
        raise KeyError("synthetic defect")
    monkeypatch.setattr(verification.SendVerification, "check", defect)
    app = intake()
    assert "worker stopped after 3 actions" in worker()
    action = PendingAction.objects.get()
    assert (action.status, action.attempts, action.last_error) == ("failed", 3, "handler raised KeyError")
    assert [e["final"] for e in app.events.filter(kind="action_failed").order_by("id").values_list("data", flat=True)] == [
        False, False, True]


# --- TEST-S1-19: held, paused, done, unknown, and two workers -------------------------------------------------

def test_s1_19_held_paused_completed_and_unknown_work_is_never_claimed(worker):
    held = intake(email="held@example.test")
    paused = intake(email="paused@example.test")
    PendingAction.objects.filter(subject_id=held.public_ref).update(status="held")
    AutomationPause.objects.create(subject_type="application", subject_id=paused.public_ref,
                                   reason="synthetic pause", actor_ref="test")
    PendingAction.objects.create(kind="drop_everything", subject_type="application", subject_id=held.public_ref,
                                 idempotency_key="unknown:1")
    done = intake(email="done@example.test")
    assert "worker stopped after 1 actions" in worker()  # only the ordinary one
    assert [m.to for m in mail.outbox] == [["done@example.test"]]
    assert worker().endswith("worker stopped after 0 actions\n")  # re-running completed work is a no-op
    statuses = {a.subject_id: (a.kind, a.status, a.attempts) for a in PendingAction.objects.all()}
    assert statuses[paused.public_ref] == ("send_verification", "queued", 0)
    assert PendingAction.objects.get(kind="drop_everything").status == "queued"  # not executed, not looped on
    assert PendingAction.objects.get(subject_id=held.public_ref, kind="send_verification").status == "held"
    assert statuses[done.public_ref] == ("send_verification", "done", 1)


def test_s1_19_a_pause_found_at_the_check_returns_the_action_without_sending(worker):
    app = intake()
    claim = ledger.claim_next()
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    handler().run(claim)
    assert mail.outbox == []
    action = PendingAction.objects.get()
    assert (action.status, action.attempts, action.lease_token) == ("queued", 0, None)  # the attempt is refunded
    assert ledger.claim_next() is None  # still paused
    AutomationPause.objects.all().delete()  # staff resume (P2); the application role may delete pauses
    assert "worker stopped after 1 actions" in worker() and len(mail.outbox) == 1


def test_s1_19_two_workers_competing_for_one_action_claim_it_once(worker, privileged_reset, monkeypatch):
    intake()
    locked, release, claims = threading.Event(), threading.Event(), []

    def hold(action_id):  # reached only by a worker that locked a row
        locked.set()
        release.wait(20)
    monkeypatch.setattr(ledger, "_after_claim_select", hold)

    def first():
        claims.append(ledger.claim_next())
    thread = privileged_reset.thread(first)
    # The coordination is on the first worker only, while it holds the row lock; the second never waits.
    assert locked.wait(20), "the first worker did not lock the action"
    second = ledger.claim_next()  # SKIP LOCKED: the only row is locked by the first worker
    assert claims == [], "the second claim waited for the first worker's lock instead of skipping it"
    release.set()
    thread.join(20)
    assert second is None
    assert len(claims) == 1 and claims[0] is not None and claims[0].attempt == 1
    assert PendingAction.objects.get().attempts == 1


def test_s1_19_two_worker_loops_process_each_action_exactly_once(worker, privileged_reset):
    for i in range(6):
        intake(email=f"w{i}@example.test")
    counts = []

    def loop():
        n = 0
        while ledger.run_one():
            n += 1
        counts.append(n)
    threads = [privileged_reset.thread(loop) for _ in range(2)]
    for t in threads:
        t.join(30)
    assert sum(counts) == 6
    assert sorted(m.to[0] for m in mail.outbox) == [f"w{i}@example.test" for i in range(6)]
    assert set(PendingAction.objects.values_list("status", "attempts")) == {("done", 1)}
    assert OutboundMessage.objects.count() == 6


# --- Send eligibility: stale and mismatched work sends nothing ---------------------------------------------

def test_old_queued_work_left_behind_when_intake_replaced_the_challenge_sends_nothing(worker, privileged_reset):
    app = intake()
    owner = privileged_reset.connect("owner", autocommit=True)
    # Test setup only, as the owner: age the challenge, so the repeat below supersedes it.
    owner.execute("UPDATE applications_contactchallenge SET created_at = now() - interval '2 hours',"
                  " expires_at = now() - interval '1 hour'")
    intake()  # the repeat supersedes challenge 1 and queues a send for challenge 2; send 1 stays queued
    old, new = ContactChallenge.objects.order_by("id")
    assert old.superseded_at is not None and PendingAction.objects.filter(status="queued").count() == 2
    assert "worker stopped after 2 actions" in worker()
    [message] = mail.outbox
    assert link_in(message.body)[0] == verification_link(new.public_id)
    by_input = {a.input_ref: (a.status, a.last_error) for a in PendingAction.objects.all()}
    assert by_input == {str(old.public_id): ("cancelled", "challenge superseded"), str(new.public_id): ("done", "")}
    skipped = app.events.get(kind="verification_send_skipped")
    assert skipped.data == {"attempt": 1, "reason": "challenge superseded"}
    assert worker().endswith("worker stopped after 0 actions\n")  # terminal: not retried


@pytest.mark.parametrize(("change", "reason"), [
    ("used", "challenge already used"),
    ("expired", "challenge expired"),
    ("verified", "contact already verified or application closed"),
])
def test_ineligible_challenges_end_cancelled_without_sending(worker, privileged_reset, change, reason):
    app = intake()
    challenge = ContactChallenge.objects.get()
    if change == "used":
        ContactChallenge.objects.filter(pk=challenge.pk).update(used_at=Now())
    elif change == "expired":
        privileged_reset.connect("owner", autocommit=True).execute(  # test setup only, as the owner
            "UPDATE applications_contactchallenge SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 hour'")
    else:
        Application.objects.filter(pk=app.pk).update(contact_verified_at=Now())  # stand-in for S1-T6
    assert "worker stopped after 1 actions" in worker()
    assert mail.outbox == []
    action = PendingAction.objects.get()
    assert (action.status, action.last_error, action.attempts) == ("cancelled", reason, 1)
    assert OutboundMessage.objects.count() == 0


def mismatched(kind):
    """A queued action whose references do not fit, inserted as the application role could."""
    app = intake()
    other = intake(email="other@example.test")
    challenge = ContactChallenge.objects.get(application=app)
    foreign = ContactChallenge.objects.get(application=other)
    PendingAction.objects.update(status="done")  # the two ordinary sends are out of the way
    fields = dict(kind="send_verification", subject_type="application", subject_id=app.public_ref,
                  input_ref=str(challenge.public_id), idempotency_key=f"test:{uuid.uuid4()}")
    fields.update({
        "subject-type": {"subject_type": "person"},
        "missing-subject": {"subject_id": uuid.uuid4()},
        "not-a-reference": {"input_ref": "not-a-uuid"},
        "foreign-challenge": {"input_ref": str(foreign.public_id)},
        "key-mismatch": {},
    }[kind])
    return PendingAction.objects.create(**fields)


@pytest.mark.parametrize(("kind", "reason"), [
    ("subject-type", "subject is not an application"),
    ("missing-subject", "subject application not found"),
    ("not-a-reference", "input is not a challenge reference"),
    ("foreign-challenge", "challenge does not belong to the subject application"),
    ("key-mismatch", "idempotency key does not match the challenge"),
])
def test_mismatched_references_fail_closed_visibly_and_send_nothing(worker, caplog, kind, reason):
    caplog.set_level(logging.DEBUG)
    action = mismatched(kind)
    assert "worker stopped after 1 actions" in worker()
    assert mail.outbox == []
    action.refresh_from_db()
    assert (action.status, action.last_error, action.attempts) == ("failed", reason, 1)  # kept, not deleted
    assert f"action {action.pk} refused: {reason}" in caplog.text
    assert "@example.test" not in caplog.text
    assert worker().endswith("worker stopped after 0 actions\n")  # not retried


# --- Connections ----------------------------------------------------------------------------------------------

def test_the_worker_reconnects_after_its_database_connection_is_lost(worker, caplog):
    intake()
    lost = []

    def drop_once(execute, sql, params, many, context):
        if "SKIP LOCKED" in sql and not lost:
            lost.append(True)
            context["connection"].connection.close()  # the server connection goes away under the worker
        return execute(sql, params, many, context)

    with connection.execute_wrapper(drop_once):
        assert "worker stopped after 1 actions" in worker()
    assert lost == [True]
    assert "worker: database unavailable (OperationalError); reconnecting" in caplog.text
    assert len(mail.outbox) == 1 and PendingAction.objects.get().status == "done"


# --- Fresh worker processes: roles, start-up guards and an intake-to-file-sink run (TEST-S1-13, 14) ---------

def test_intake_to_file_sink_through_a_real_worker_process(privileged_reset, tmp_path):
    app = intake()
    sink = tmp_path / "sink"
    sink.mkdir(mode=0o700)
    env = support.worker_env(sink)
    assert not [k for k in env if k.startswith(("CATALYST_DB_ADMIN", "CATALYST_DB_OWNER", "CATALYST_DB_RETENTION"))]
    assert env["CATALYST_DB_USER"] == APP_ROLE
    proc = support.worker_process(sink, "--exit-when-idle")
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert out.splitlines() == ["worker started", "worker stopped after 1 actions"]
    [message] = sink_messages(sink)
    assert "To: ada@example.test" in message and "Subject: Confirm your email address" in message
    assert link_in(message)[0] == verification_link(ContactChallenge.objects.get().public_id)
    assert PendingAction.objects.get().status == "done" and events(app)[-1] == "verification_sent"
    assert "ada@example.test" not in out + err and CONFIRM_PATH not in out + err


def worker_check(tmp_path, **overrides):
    proc = support.worker_process(tmp_path, "--exit-when-idle", **overrides)
    out, err = proc.communicate(timeout=60)
    for secret in [v for k, v in support.os.environ.items() if k.endswith("_PASSWORD")]:
        assert secret not in out + err
    return proc.returncode, out, err


@pytest.mark.parametrize(("role_key", "reason"), [
    ("owner", "worker process connects as"),
    ("retention", "worker process connects as"),
    ("admin", "connects as superuser"),
])
def test_a_worker_process_refuses_a_privileged_login(privileged_reset, tmp_path, role_key, reason):
    user = support.os.environ["CATALYST_DB_ADMIN_USER"] if role_key == "admin" else settings.CATALYST_DB_ROLES[role_key]
    password = support.os.environ[f"CATALYST_DB_{role_key.upper()}_PASSWORD"]
    code, out, err = worker_check(tmp_path, CATALYST_DB_USER=user, CATALYST_DB_PASSWORD=password,
                                  CATALYST_PROCESS="management")  # a stale value does not exempt the worker
    assert code != 0
    assert "Catalyst refuses the database connection 'default'" in err and reason in err
    assert "worker stopped" not in out


@pytest.mark.parametrize(("overrides", "message"), [
    ({"DJANGO_SETTINGS_MODULE": "tests.settings_sqlite"}, "sqlite3"),
    ({"CATALYST_EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend"}, "not a local sink backend"),
    ({"MINIMAX_API_KEY": "synthetic-not-a-key"}, "MINIMAX_API_KEY"),
], ids=["non-postgresql", "smtp-backend", "provider-credential"])
def test_the_worker_command_refuses_to_start_on_a_guard(privileged_reset, tmp_path, overrides, message):
    code, out, err = worker_check(tmp_path, **overrides)
    assert code != 0 and "Catalyst refuses to start" in err and message in err
    assert "synthetic-not-a-key" not in out + err


def test_the_link_comes_from_the_setting_and_differs_per_key(settings):
    challenge, original = uuid.uuid4(), settings.CATALYST_VERIFICATION_KEY
    first = verification_link(challenge)
    assert first.startswith(settings.CATALYST_PUBLIC_BASE_URL + CONFIRM_PATH) and first.endswith("/")
    assert verification_link(challenge) == first  # deterministic: a redelivery carries the same link
    settings.CATALYST_VERIFICATION_KEY = "synthetic-other-key"
    assert verification_link(challenge) != first
    settings.CATALYST_VERIFICATION_FALLBACK_KEYS = [original]
    assert signer().unsign(first.rsplit("/", 2)[1]) == str(challenge)  # the retired key still verifies (S1-T6 uses it)


def test_a_recording_failure_after_the_sink_accepted_is_left_for_lease_recovery(worker, monkeypatch, caplog):
    app = intake()
    real_finish = ledger.finish

    def finish_fails_on_done(claim, handler, *, status, **kwargs):
        if status == "done":
            raise RuntimeError("synthetic recording failure")
        return real_finish(claim, handler, status=status, **kwargs)
    monkeypatch.setattr(ledger, "finish", finish_fails_on_done)
    assert ledger.run_one() is True
    assert len(mail.outbox) == 1
    action = PendingAction.objects.get()
    assert (action.status, action.attempts) == ("running", 1)  # not failed: the message is in the sink
    assert "result not recorded (RuntimeError); left for lease recovery" in caplog.text
    assert events(app) == ["submission_received"] and OutboundMessage.objects.count() == 0
    monkeypatch.setattr(ledger, "finish", real_finish)
    expire_lease(action.pk)
    assert "worker stopped after 1 actions" in worker()
    action.refresh_from_db()
    assert (action.status, action.attempts) == ("done", 2) and len(mail.outbox) == 2


def test_retry_backoff_doubles_per_attempt_and_is_capped(settings):
    settings.CATALYST_WORKER_RETRY_SECONDS = 60
    assert [ledger.retry_delay(n).total_seconds() for n in (1, 2, 3, 4, 5, 9)] == [60, 120, 240, 480, 480, 480]

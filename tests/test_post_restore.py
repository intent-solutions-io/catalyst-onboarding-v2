"""6B.7b (026 section 6 steps 4, 5 and 7; TEST-P6-29): the post-restore step, run as the owner in a real process.
9kg.33 (029 section 6.2): the effect journal and the reconciliation of effects after the backup point before the
hold lifts, against the fakes."""

import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.core import mail
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

from applications.models import Application, ApplicationEvent
from config import post_restore as step
from config.backup import RESTORE_HOLD
from correspondence import outbound
from correspondence.models import InboundMessage, Question, QuestionReplyLink, StaffItem, StaffItemResolution
from correspondence.staff_items import open_item
from provisioning import closure, credentials
from provisioning.models import AccessRevocation, CredentialSetup, WithdrawalConfirmation
from tests import support
from tests.support import ROOT
from tests.test_backup_commands import admin, drop, new_database, run_backup, run_restore
from tests.test_closure import active_member, cl  # noqa: F401  (fixture chain and helpers)
from tests.test_credentials import invited, post
from tests.test_outbound import FORM, VALID, ask, ready, staff  # noqa: F401  (fixture chain and helpers)
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, approve, approved, c, d, ev, g, h, issued, k, nda, p2, pv, run_worker, sign_and_settle, tls,
)
from workflow import journal
from workflow.models import AutomationPause, PendingAction

LIFT = ("--lift", "--outward-checked", "--no-closures-after-backup")
# The owner-run process reads its Sent evidence from files the test writes (tests.smtp_server.DirectoryEvidence).
SENT = {"CATALYST_SEND_EVIDENCE_SOURCE": "tests.smtp_server.DirectoryEvidence"}


def post_restore(*extra, confirm=None, db=None, **env):
    result = support.run([sys.executable, "manage.py", "catalyst_post_restore", "--confirm-database",
                          confirm or db or connection.settings_dict["NAME"], *extra], timeout=120,
                         CATALYST_DB_NAME=db or connection.settings_dict["NAME"],
                         CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                         CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"], **env)
    return result, (json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else None)


def hold():
    return AutomationPause.objects.filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1])


def place_hold():
    AutomationPause.objects.create(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1],
                                   reason="restore hold (test)", actor_ref="catalyst_restore")


def test_6b7b_links_from_before_the_restore_stop_working_the_negative_control(cl, monkeypatch):
    """026 section 6 step 7: a link that worked at T (and may have been used after T) is refused after the step."""
    response = Client().post(FORM, urlencode({**VALID, "email": "second@example.test"}),
                             content_type="application/x-www-form-urlencoded")
    assert response.status_code == 302
    run_worker()
    confirm_path = re.search(r"http://catalyst\.example\.test(/confirm/\S+/)", mail.outbox[-1].body).group(1)
    assert b'name="version"' in Client().get(confirm_path).content  # before: the confirmation form is offered
    app, request, setup_path = invited(cl, monkeypatch)
    assert Client().get(setup_path).status_code == 200  # before: the password form is offered
    place_hold()
    result, report = post_restore()
    assert result.returncode == 0, result.stderr
    assert report["confirmation_links_closed"] >= 1 and report["password_links_closed"] == 1
    assert b'name="version"' not in Client().get(confirm_path).content  # after: the link is closed
    assert post(setup_path).status_code == 404 and CredentialSetup.objects.get(request=request).state == "superseded"
    assert StaffItem.objects.filter(application=request.application, reason_code=credentials.ITEM_SETUP,
                                    status="open").exists()  # staff send a fresh link
    assert StaffItem.objects.filter(reason_code=step.ITEM_CONFIRMATION, status="open").exists()  # nobody stranded


def test_6b7b_staff_passwords_and_sessions_from_before_the_restore_never_return(p2):
    from accounts.models import User
    from django.contrib.sessions.models import Session

    user = staff(p2, "restore-staff")
    client = Client()
    assert client.login(username="restore-staff", password="synthetic-password-only")  # gitleaks:allow
    assert client.get("/staff/").status_code == 200  # before: signed in
    place_hold()
    result, report = post_restore()
    assert result.returncode == 0, result.stderr
    assert report["staff_passwords_disabled"] >= 1 and report["staff_sessions_ended"] >= 1
    assert Session.objects.count() == 0 and client.get("/staff/").status_code == 302
    assert not User.objects.get(pk=user.pk).has_usable_password()  # re-issued by the owner after a roster check
    assert not Client().login(username="restore-staff", password="synthetic-password-only")  # gitleaks:allow


def test_6b7b_withdrawal_links_close_and_in_flight_password_sets_become_unknown(cl, monkeypatch):
    app, request, path = invited(cl, monkeypatch)
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked to withdraw by email")
    owner = cl.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE provisioning_credentialsetup SET state = 'set_pending', set_started_at = now() WHERE request_id = %s",
                  [request.pk])
    place_hold()
    result, report = post_restore()
    assert result.returncode == 0, result.stderr
    assert report["password_sets_now_unknown"] == 1 and report["withdrawal_links_closed"] == 1
    assert CredentialSetup.objects.get(request=request).state == "set_uncertain"  # never replayed
    assert WithdrawalConfirmation.objects.get(application=app).state == "superseded"
    assert StaffItem.objects.filter(application=app, reason_code=step.ITEM_WITHDRAWAL, status="open").exists()


def test_6b7b_unfinished_access_removal_gets_one_new_round(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    assert AccessRevocation.objects.filter(request=request).exclude(state__in=closure.FINAL).exists()
    PendingAction.objects.filter(kind=closure.REVOKE).update(status="done")  # as if the backup predates the rounds
    place_hold()
    _, report = post_restore()
    assert report["revocation_rounds_queued"] == 1
    _, again = post_restore()  # a second review run queues nothing new, and says so
    assert again["revocation_rounds_queued"] == 0
    assert PendingAction.objects.filter(kind=closure.REVOKE, status="queued").count() == 1


def test_6b7b_the_report_lists_outward_actions_and_running_ones_are_recovered(p2):
    queued = PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                          idempotency_key="post-restore-queued-send")
    running = PendingAction.objects.create(kind="send_verification", subject_type="application", subject_id=uuid.uuid4(),
                                           idempotency_key="post-restore-running-verification")
    PendingAction.objects.filter(pk=running.pk).update(status="running", lease_token=uuid.uuid4(),
                                                       lease_expires_at=timezone.now() + timedelta(hours=1))
    place_hold()
    result, report = post_restore()
    assert report["running_actions_recovered"] == 1
    listed = {(r["kind"], r["status"]): r["ids"] for r in report["outward_actions"]}
    assert listed[("send_message", "queued")] == [queued.pk]
    assert listed[("send_verification", "running")] == [running.pk]  # a redeliverable kind that still sends mail
    running.refresh_from_db()
    assert running.lease_expires_at <= timezone.now()
    assert "@" not in result.stdout  # kinds, counts and ids only


def test_6b7b_lifting_needs_a_review_run_and_both_confirmations(p2, tmp_path):
    from workflow import ledger

    action = PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                          idempotency_key="post-restore-lift-probe")
    place_hold()
    early, _ = post_restore(*LIFT)
    assert early.returncode == 1 and "run the review first" in early.stderr
    # 9kg.33: a queued send needs the Sent-folder evidence source; an empty folder is evidence of nothing, so the
    # send stays queued, listed for --outward-checked.
    sent = tmp_path / "sent"
    sent.mkdir()
    post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    for partial in (("--lift",), ("--lift", "--outward-checked"), ("--lift", "--no-closures-after-backup")):
        result, _ = post_restore(*partial)
        assert result.returncode == 1 and "needs --outward-checked and --no-closures-after-backup" in result.stderr
    assert hold().exists() and ledger.claim_next() is None  # still held
    result, lifted = post_restore(*LIFT)
    assert result.returncode == 0 and lifted["hold"] == "lifted" and not hold().exists()
    claim = ledger.claim_next({"send_message": ledger.handlers()["send_message"]})
    assert claim is not None and claim.id == action.pk  # work resumes only now


def test_6b7b_refuses_without_a_hold_or_a_named_database(p2):
    assert hold().count() == 0
    no_hold, _ = post_restore()
    assert no_hold.returncode == 1 and "there is no restore hold" in no_hold.stderr
    place_hold()
    wrong, _ = post_restore(confirm="the-wrong-database")
    assert wrong.returncode == 1 and "--confirm-database must name this database" in wrong.stderr
    assert hold().exists()


# --- 9kg.33: the effect journal and reconciliation after the backup point (029 section 6.2) ------------------------

def entries():
    return journal.read()


def kinds(report, app):
    return report["effects"][app]


def test_9kg_33_the_effect_journal_is_append_only_chained_and_refuses_a_broken_chain(effect_journal):
    assert journal.read() == [] and journal.head() == (0, journal.GENESIS)
    first = journal.append("application_closed", "application:synthetic-1", {"outcome": "closed"})
    second = journal.append("automation_pause", "pause:synthetic-1", {"state": "paused", "by": "staff"})
    assert (first.seq, first.prev, second.seq, second.prev) == (1, journal.GENESIS, 2, first.hash)
    assert journal.head() == (2, second.hash) and [e.kind for e in journal.read()] == ["application_closed", "automation_pause"]
    with journal.replaying():
        assert journal.append("application_closed", "application:synthetic-2") is None  # a replay journals nothing
    assert journal.head() == (2, second.hash)
    path = effect_journal / journal.FILE
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    lines = path.read_bytes().split(b"\n")
    lines[0] = lines[0].replace(b'"closed"', b'"withdrawn"')  # a changed entry
    path.write_bytes(b"\n".join(lines))
    with pytest.raises(journal.JournalError, match="chain_broken"):
        journal.read()
    with pytest.raises(journal.JournalError, match="chain_broken"):
        journal.usage_high_water("2026-10-23")  # the budget floor is unknown: refused, never zero
    journal.append("x", "y")  # appending after the tamper keeps the file chained from its (tampered) tail
    with pytest.raises(journal.JournalError):
        journal.read()


def test_9kg_33_a_backup_records_the_journal_head_and_a_restore_marks_the_backup_point(p2, tmp_path):
    journal.append("automation_pause", f"pause:{uuid.uuid4()}", {"state": "paused", "by": "staff"})
    out, storage = tmp_path / "sets", tmp_path / "custody"
    out.mkdir()
    storage.mkdir()
    result = run_backup(out, storage)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((out / "set" / "receipt.json").read_text())
    assert receipt["effect_journal_seq"] == 1 and receipt["effect_journal_head"] == journal.read()[0].hash
    after = journal.append("automation_pause", f"pause:{uuid.uuid4()}", {"state": "paused", "by": "staff"})
    target = new_database()
    try:
        restored = run_restore(target, out / "set", tmp_path / "restored-custody")
        assert restored.returncode == 0, restored.stderr
        marker = journal.read()[-1]
        assert marker.kind == "restore" and marker.data["backup_seq"] == 1 and marker.data["backup_head"] == receipt["effect_journal_head"]
        assert marker.data["backup_started_at"] == receipt["started_at"]
        to_reconcile, since, marker_seq = journal.after_restore()
        assert [e.seq for e in to_reconcile] == [after.seq] and marker_seq == marker.seq  # only what postdates the backup
        assert since == datetime.fromtimestamp(receipt["started_at"], UTC)
        result, report = post_restore(db=target, **SENT, CATALYST_TEST_SENT_DIR=str(tmp_path))
        assert result.returncode == 0, result.stderr
        assert report["effects"]["journal"] == "ok" and report["effects"]["entries"] == 1
        assert report["effects"]["since"] == since.isoformat() and report["effects"]["blocked"] == []
    finally:
        drop(target)


def test_9kg_33_pauses_resolutions_withdrawals_outcomes_and_decisions_after_the_backup_are_replayed_once(ready, tmp_path):
    """The restored tables are the state at T; the journal says what happened after T; the review re-applies it,
    and a second review finds everything reflected and changes nothing."""
    app = ready.app
    question, abandoned = ask(ready, text="A question whose send was abandoned after the backup?")
    withdrawn_q, withdrawn_msg = ask(ready, text="A question withdrawn after the backup?")
    answered_q, _ = ask(ready, text="A question answered after the backup?")
    item = open_item("synthetic_probe", "probe:restore", application=app)
    reply = InboundMessage.objects.create(mailbox_ref="applicants", application=app, classification="human",
                                          trust_decision="trusted", status="awaiting_processing")
    link = QuestionReplyLink.objects.create(question=answered_q, inbound_message=reply, state="pending")
    Question.objects.filter(pk=answered_q.pk).update(status="reply_pending")
    assert not AutomationPause.objects.filter(subject_id=app.public_ref).exists()
    journal.append("automation_pause", f"pause:{app.public_ref}", {"state": "paused", "by": "staff"})
    journal.append("automation_pause", f"pause:{app.public_ref}", {"state": "resumed", "by": "staff"})
    journal.append("automation_pause", f"pause:{app.public_ref}", {"state": "paused", "by": "system"})  # the last wins
    journal.append("staff_item_resolved", f"item:{item.public_id}", {"reason": "synthetic_probe", "resolution": "acknowledged"})
    journal.append("question_withdrawn", f"question:{withdrawn_q.public_id}", {"reason": "asked_in_error"})
    journal.append("reply_link_outcome", f"reply_link:{answered_q.public_id}:{reply.public_id}",
                   {"state": "applied", "outcome": "satisfied"})
    journal.append("uncertain_send_decided", f"send:{abandoned.send_ref}", {"decision": "abandon", "series": None})
    place_hold()
    sent = tmp_path / "sent"
    sent.mkdir()
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert result.returncode == 0, result.stderr
    assert kinds(report, "correspondence") == {"replayed": 5, "reflected": 0, "items": 0}
    row = AutomationPause.objects.get(subject_type="application", subject_id=app.public_ref)
    assert row.actor_ref.startswith("system:")  # the last journaled state: a system pause
    item.refresh_from_db()
    assert item.status == "resolved" and StaffItemResolution.objects.get(item=item).resolution_code == "acknowledged"
    assert "effect journal" in StaffItemResolution.objects.get(item=item).note
    withdrawn_q.refresh_from_db()
    assert withdrawn_q.status == "withdrawn" and withdrawn_q.withdrawn_reason.startswith("asked_in_error")
    assert PendingAction.objects.get(kind="send_message", input_ref=str(withdrawn_msg.send_ref)).status == "queued"  # E3: the send itself re-checks
    link.refresh_from_db()
    answered_q.refresh_from_db()
    assert (link.state, link.outcome, answered_q.status) == ("applied", "satisfied", "satisfied")
    abandoned.refresh_from_db()
    assert abandoned.disposition == "operator_abandoned"
    assert PendingAction.objects.get(kind="send_message", input_ref=str(abandoned.send_ref)).status == "cancelled"
    replayed = ApplicationEvent.objects.filter(application=app, kind="restore_effect_replayed").count()
    assert replayed == 5 and "@" not in result.stdout
    result, again = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))  # a second run reconciles nothing twice
    assert kinds(again, "correspondence") == {"replayed": 0, "reflected": 5, "items": 0}
    assert ApplicationEvent.objects.filter(application=app, kind="restore_effect_replayed").count() == replayed
    assert StaffItemResolution.objects.filter(item=item).count() == 1
    assert AutomationPause.objects.filter(subject_type="application", subject_id=app.public_ref).count() == 1
    # The journal entries the replays would have made are not made: a replay re-applies facts, it is not one.
    assert [e.kind for e in entries() if e.kind == "staff_item_resolved"] == ["staff_item_resolved"]


def test_9kg_33_closures_and_revocations_after_the_backup_are_replayed_and_access_is_removed_again(cl, monkeypatch, tmp_path):
    app, request = active_member(cl, monkeypatch)
    before = entries()
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    run_worker()
    closed_entry = next(e for e in entries() if e.kind == "application_closed")
    assert closed_entry.key == f"application:{app.public_ref}" and closed_entry.data == {"outcome": "closed"}
    revoked = [e for e in entries() if e.kind == "access_revocation"]
    assert {e.data["state"] for e in revoked} >= {"applied_unverified", "verified"}
    assert all("@" not in json.dumps(e.data) and "ada" not in e.key for e in entries()[len(before):])
    # "Restore": the application is active again and the revocation obligations are back to requested, as at T. As
    # the restore's load does, the rows are put back with the triggers off (the bootstrap administrator, replica mode).
    with admin(connection.settings_dict["NAME"]) as load:
        load.execute("SET session_replication_role = replica")
        load.execute("UPDATE applications_application SET stage = 'active' WHERE id = %s", [app.pk])
        load.execute("UPDATE provisioning_provisioningrequest SET status = 'active', stop_requested_at = NULL WHERE id = %s", [request.pk])
        load.execute("UPDATE provisioning_accessrevocation SET state = 'requested' WHERE request_id = %s AND kind <> 'setup_links'", [request.pk])
    place_hold()
    sent = tmp_path / "sent"
    sent.mkdir()
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert result.returncode == 0, result.stderr
    assert kinds(report, "provisioning")["replayed"] >= 1 + 3 and kinds(report, "provisioning")["items"] == 0
    assert Application.objects.get(pk=app.pk).stage == "closed"
    request.refresh_from_db()
    assert request.stop_requested_at is not None and request.status == "stopped"
    states = dict(AccessRevocation.objects.filter(request=request).values_list("kind", "state"))
    assert states["password_rotation"] == "applied_unverified" and states["owned_forwarders"] == "verified"
    # The replayed closure queued the round itself, so the review's own step found one waiting; either way one round
    # runs and reads the host after the lift.
    assert PendingAction.objects.filter(kind=closure.REVOKE, input_ref=str(request.public_id), status="queued").count() == 1
    result, again = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert kinds(again, "provisioning")["replayed"] == 0


def test_9kg_33_a_reminder_that_left_after_the_backup_moves_the_series_position(ready, tmp_path):
    question, message = ask(ready)
    run_worker()  # accepted: reminder 1 is scheduled (E1)
    first = PendingAction.objects.get(kind="remind", idempotency_key=f"remind:{question.public_id}:1")
    assert first.status == "queued"
    journal.append("reminder_queued", f"reminder:{question.public_id}:1",
                   {"n": 1, "question": str(question.public_id), "send_ref": str(uuid.uuid4())})  # left after T
    place_hold()
    sent = tmp_path / "sent"
    sent.mkdir()
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert result.returncode == 0, result.stderr
    first.refresh_from_db()
    assert (first.status, first.last_error) == ("cancelled", "replayed_sent_after_backup")  # never sent twice
    assert PendingAction.objects.filter(kind="remind", idempotency_key=f"remind:{question.public_id}:2", status="queued").exists()
    result, again = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert kinds(again, "correspondence") == {"replayed": 0, "reflected": 1, "items": 0}
    assert PendingAction.objects.filter(kind="remind", idempotency_key__startswith=f"remind:{question.public_id}:").count() == 2


def write_copy(directory, message, subject=None, body=None, message_id=None):
    data = outbound.build_email(message, subject or message.frozen_subject, body or message.frozen_body)
    if message_id:
        data = data.replace(outbound.message_id(message.send_ref).encode(), message_id.encode())
    path = directory / f"{uuid.uuid4().hex}.eml"
    path.write_bytes(data)
    return path


def test_9kg_33_sent_copies_after_the_backup_settle_restored_sends_and_unknown_copies_block_the_lift(ready, tmp_path):
    """The restored ledger has two sends queued and one decided for resend; the Sent folder shows one of them left
    after the backup, a resend, and a message the restored system does not know. Absence proves nothing."""
    _, left = ask(ready, text="A question whose message left after the backup?")
    _, waiting = ask(ready, text="A question whose message is still queued?")
    _, resent = ask(ready, text="A question whose resend was authorized after the backup?")
    journal.append("uncertain_send_decided", f"send:{resent.send_ref}", {"decision": "authorize_resend", "series": 1})
    sent = tmp_path / "sent"
    sent.mkdir()
    write_copy(sent, left)
    write_copy(sent, left, body="a changed body with the same Message-ID", message_id=None)  # inadmissible: digest
    write_copy(sent, resent)
    write_copy(sent, waiting, message_id=f"<c{uuid.uuid4().hex}@catalyst.example.test>")  # unknown to the ledger
    place_hold()
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert result.returncode == 0, result.stderr
    sends = report["effects"]["sends"]
    assert sends["status"] == "ok" and sends["copies"] == 4 and sends["accepted"] == 2
    for message in (left, resent):
        message.refresh_from_db()
        assert message.disposition == "accepted_by_evidence"
        [action] = PendingAction.objects.filter(kind="send_message", input_ref=str(message.send_ref))
        assert (action.status, action.last_error) == ("done", "accepted_by_evidence")
    waiting.refresh_from_db()
    assert waiting.disposition == "active"  # no copy: not proof of non-send, and never marked failed
    assert PendingAction.objects.get(kind="send_message", input_ref=str(waiting.send_ref)).status == "queued"
    assert [r["kind"] for r in report["outward_actions"]] == ["send_message"]  # listed for --outward-checked
    unknown = list(StaffItem.objects.filter(reason_code=step.EFFECT_ITEM_PREFIX + "unknown_send", status="open"))
    assert len(unknown) == 2 and all(i.application == ready.app for i in unknown)  # the changed body, the unknown id
    assert not StaffItem.objects.filter(reason_code="restore_effect_resend_unverified", status="open").exists()
    assert "@" not in result.stdout and "ada" not in result.stdout
    refused, _ = post_restore(*LIFT)
    assert refused.returncode == 1 and "effects are unresolved" in refused.stderr and "restore_effect_unknown_send" in refused.stderr
    for item in unknown:
        short, _ = post_restore("--resolve", str(item.public_id), "--note", "short")
        assert short.returncode == 1 and "at least 10 characters" in short.stderr
        done, resolved = post_restore("--resolve", str(item.public_id), "--note", "Compared with the mailbox: a staff test send.")
        assert done.returncode == 0 and resolved == {"resolved": str(item.public_id), "already": False}
    assert StaffItemResolution.objects.filter(item__in=unknown, resolution_code=step.RESOLVED_BY_OWNER).count() == 2
    lifted, _ = post_restore(*LIFT)
    assert lifted.returncode == 0 and not hold().exists()
    # The system's resolution of the resend item by evidence and the owner's two resolutions are effects too.
    assert [e.data["resolution"] for e in entries() if e.kind == "staff_item_resolved"] == [
        "accepted_by_evidence", step.RESOLVED_BY_OWNER, step.RESOLVED_BY_OWNER]


def test_9kg_33_a_resend_without_a_copy_waits_for_a_decision_maker(ready, tmp_path):
    _, resent = ask(ready)
    journal.append("uncertain_send_decided", f"send:{resent.send_ref}", {"decision": "authorize_resend", "series": 1})
    place_hold()
    sent = tmp_path / "sent"
    sent.mkdir()
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert kinds(report, "correspondence") == {"replayed": 0, "reflected": 0, "items": 1}
    [item] = StaffItem.objects.filter(reason_code="restore_effect_resend_unverified", status="open")
    assert item.approved_message == resent and report["effect_items_open"] == [f"restore_effect_resend_unverified:{item.public_id}"]
    refused, _ = post_restore(*LIFT)
    assert refused.returncode == 1 and str(item.public_id) in refused.stderr


def test_9kg_33_missing_or_unreachable_evidence_blocks_the_lift(p2, tmp_path, effect_journal):
    PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                 idempotency_key="post-restore-evidence-probe")
    place_hold()
    result, report = post_restore()  # a queued send and no Sent-folder source
    assert result.returncode == 0 and report["effects"]["sends"]["status"] == "not_configured"
    assert report["effects"]["blocked"] == ["sends"] and "evidence missing or unreachable" in report["hold"]
    refused, _ = post_restore(*LIFT)
    assert refused.returncode == 1 and "run the review again" in refused.stderr
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(tmp_path / "absent"))
    assert report["effects"]["sends"]["status"].startswith("unreachable:") and report["effects"]["blocked"] == ["sends"]
    assert post_restore(*LIFT)[0].returncode == 1
    sent = tmp_path / "sent"
    sent.mkdir()
    (effect_journal / journal.FILE).write_bytes(b'{"seq": 1, "at": "x", "kind": "x", "key": "x", "data": {}, "prev": "0", "hash": "0"}\n')
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert report["effects"]["journal"] == "chain_broken" and report["effects"]["blocked"] == ["journal"]
    assert post_restore(*LIFT)[0].returncode == 1
    (effect_journal / journal.FILE).unlink()
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert report["effects"]["blocked"] == [] and post_restore(*LIFT)[0].returncode == 0


def test_9kg_33_staff_access_removed_after_the_backup_is_removed_again_and_grants_wait_for_the_owner(p2, monkeypatch, tmp_path):
    from django.contrib.auth import get_user_model

    monkeypatch.setenv("CATALYST_TEST_STAFF_PASSWORD", "synthetic-Restore-Pass-9kg33")  # gitleaks:allow
    support.manage_as_owner("add_readonly_staff", "staff-after-backup", "--password-env", "CATALYST_TEST_STAFF_PASSWORD")
    support.manage_as_owner("add_correspondence_staff", "staff-after-backup", "--role", "operator", "--existing")
    changes = [(e.key, e.data["change"], e.data["groups"]) for e in entries() if e.kind == "staff_role_changed"]
    assert changes == [("staff:staff-after-backup", "created", []), ("staff:staff-after-backup", "group_added", ["Read-only staff"]),
                       ("staff:staff-after-backup", "group_added", ["Correspondence operator"])]
    assert all("Pass" not in json.dumps(e.data) for e in entries())
    # "Restore" to a state before the account existed, with another account that was active and in a group at T.
    User = get_user_model()
    owner = p2.committed.connect("owner", autocommit=True)  # the restored state: that account never existed
    owner.execute("DELETE FROM accounts_user_groups WHERE user_id IN (SELECT id FROM accounts_user WHERE username = %s)",
                  ["staff-after-backup"])
    owner.execute("DELETE FROM accounts_user WHERE username = %s", ["staff-after-backup"])
    kept = staff(p2, "staff-kept", "Read-only staff")
    journal.append("staff_role_changed", "staff:staff-kept", {"change": "group_removed", "active": True, "groups": ["Read-only staff"]})
    journal.append("staff_role_changed", "staff:staff-kept", {"change": "deactivated", "active": False, "groups": []})
    place_hold()
    sent = tmp_path / "sent"
    sent.mkdir()
    result, report = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert result.returncode == 0, result.stderr
    assert kinds(report, "accounts") == {"replayed": 2, "reflected": 0, "items": 3}
    kept.refresh_from_db()
    assert not kept.is_active and not kept.groups.exists()
    assert not User.objects.filter(username="staff-after-backup").exists()  # never created from a file
    [item] = StaffItem.objects.filter(reason_code="restore_effect_staff_account", status="open")
    assert item.dedupe_key == "staff:staff-after-backup"
    result, again = post_restore(**SENT, CATALYST_TEST_SENT_DIR=str(sent))
    assert kinds(again, "accounts") == {"replayed": 0, "reflected": 2, "items": 3}
    assert StaffItem.objects.filter(reason_code="restore_effect_staff_account").count() == 1


def test_9kg_33_model_usage_never_drops_below_the_journal_high_water_mark(ready, settings):
    from assessments.interpret import Interpreter, daily_requests_used, record_usage

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert daily_requests_used() == 0
    journal.append("model_usage", f"usage:{today}", {"requests": 7})
    journal.append("model_usage", f"usage:{today}", {"requests": 5})  # an older, lower total never lowers the mark
    journal.append("model_usage", "usage:2000-01-01", {"requests": 99})
    assert daily_requests_used() == 7  # the restored tables say 0; the journal says 7 were possibly spent
    settings.CATALYST_ASSESSMENT_MODEL = "test"
    settings.CATALYST_ASSESSMENT_DAILY_REQUESTS = 8
    with transaction.atomic():
        assert Interpreter().admit(ready.app) == "daily_request_budget"  # 7 + 2 > 8
    settings.CATALYST_ASSESSMENT_DAILY_REQUESTS = 9
    with transaction.atomic():
        assert Interpreter().admit(ready.app) == ""
        record_usage()  # the reservation's running total, journaled once the transaction commits
    assert [e.data for e in entries() if e.kind == "model_usage"][-1] == {"requests": 7}


def test_9kg_33_provider_reads_report_moved_envelopes_and_unexpected_mailboxes_or_unreachable_evidence(pv, monkeypatch):
    from agreements import restore as agreements_restore
    from provisioning import restore as provisioning_restore
    from provisioning.adapter import Mailbox
    from tests.mxroute_fake import FakeMailHost

    app, request = approved(pv, monkeypatch)
    assert agreements_restore.read_envelopes(None) == {"status": "ok", "checked": 2, "items": 0}
    assert provisioning_restore.read_mailboxes() == {"status": "ok", "checked": 1, "items": 0}
    instance = nda(app)
    pv.fake.envelopes[instance.envelope_id]["status"] = "CANCELLED"  # cancelled at the provider after the backup
    assert agreements_restore.read_envelopes(None) == {"status": "ok", "checked": 2, "items": 1}
    [item] = StaffItem.objects.filter(reason_code="restore_effect_envelope", status="open")
    assert item.application == app and item.dedupe_key == f"agreement:{instance.public_id}"
    assert agreements_restore.read_envelopes(None)["items"] == 1 and StaffItem.objects.filter(reason_code="restore_effect_envelope").count() == 1
    pv.fake.fault("GET /envelope", ("drop_before",))
    assert agreements_restore.read_envelopes(None)["status"].startswith("unreachable:")
    FakeMailHost.mailboxes[("team.example.test", "ada.example")] = Mailbox("ada.example", "team.example.test", 1024, 100, False)
    assert provisioning_restore.read_mailboxes() == {"status": "ok", "checked": 1, "items": 1}  # present, not expected
    assert StaffItem.objects.filter(reason_code="restore_effect_mailbox", application=app, status="open").count() == 1
    FakeMailHost.faults.append("read_500")
    assert provisioning_restore.read_mailboxes()["status"] == "unreachable:server_error"
    assert all("@" not in e.data.get("request", "") for e in ApplicationEvent.objects.filter(kind__startswith="restore_effect"))


def test_9kg_33_the_restore_drill_exercises_the_effect_reconciliation():
    """The drill carries the behaviour (TEST-P6-22, 29); the gate pins its shape: an effect after the backup, the
    refused lift, the owner's resolution, the lift."""
    script = (ROOT / "scripts/restore_drill.sh").read_text()
    for line in ("add_readonly_staff", "restore_effect_", "--resolve", "effects reconciled", "catalyst-effects"):
        assert line in script, line

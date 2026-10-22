"""6B.7b (026 section 6 steps 4, 5 and 7; TEST-P6-29): the post-restore step, run as the owner in a real process."""

import json
import os
import re
import sys
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core import mail
from django.db import connection
from django.test import Client
from django.utils import timezone

from config import post_restore as step
from config.backup import RESTORE_HOLD
from correspondence.models import StaffItem
from provisioning import closure, credentials
from provisioning.models import AccessRevocation, CredentialSetup, WithdrawalConfirmation
from tests import support
from tests.test_closure import active_member, cl  # noqa: F401  (fixture chain and helpers)
from tests.test_credentials import invited, post
from tests.test_outbound import FORM, VALID, staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, approve, c, d, ev, g, h, issued, k, nda, p2, pv, run_worker, sign_and_settle, tls,
)
from workflow.models import AutomationPause, PendingAction

LIFT = ("--lift", "--outward-checked", "--no-closures-after-backup")


def post_restore(*extra, confirm=None):
    result = support.run([sys.executable, "manage.py", "catalyst_post_restore", "--confirm-database",
                          confirm or connection.settings_dict["NAME"], *extra], timeout=120,
                         CATALYST_DB_NAME=connection.settings_dict["NAME"],
                         CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                         CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
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


def test_6b7b_lifting_needs_a_review_run_and_both_confirmations(p2):
    from workflow import ledger

    action = PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                          idempotency_key="post-restore-lift-probe")
    place_hold()
    early, _ = post_restore(*LIFT)
    assert early.returncode == 1 and "run the review first" in early.stderr
    post_restore()
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

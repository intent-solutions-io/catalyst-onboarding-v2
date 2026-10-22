"""6B.7b (026 section 6 steps 4 and 5; TEST-P6-29): the post-restore step, run as the owner in a real process."""

import json
import os
import sys
import uuid

from django.conf import settings
from django.db import connection
from django.test import Client
from django.utils import timezone

from config.backup import RESTORE_HOLD
from provisioning import closure
from provisioning.models import AccessRevocation, CredentialSetup, WithdrawalConfirmation
from tests import support
from tests.test_closure import active_member, cl  # noqa: F401  (fixture chain and helpers)
from tests.test_credentials import invited, post
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, approve, c, d, ev, g, h, issued, k, nda, p2, pv, run_worker, sign_and_settle, tls,
)
from workflow.models import AutomationPause, PendingAction


def post_restore(*extra, confirm=None):
    return support.run([sys.executable, "manage.py", "catalyst_post_restore", "--confirm-database",
                        confirm or connection.settings_dict["NAME"], *extra], timeout=120,
                       CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
                       CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])


def hold():
    return AutomationPause.objects.filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1])


def place_hold():
    AutomationPause.objects.create(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1],
                                   reason="restore hold (test)", actor_ref="catalyst_restore")


def test_6b7b_links_sessions_and_running_actions_are_reset_before_anything_runs(cl, monkeypatch):
    app, request, path = invited(cl, monkeypatch)  # a live password link
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked to withdraw by email")
    running = PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                           idempotency_key="post-restore-running")
    PendingAction.objects.filter(pk=running.pk).update(status="running", lease_token=uuid.uuid4(),
                                                       lease_expires_at=timezone.now() + timezone.timedelta(hours=1))
    place_hold()
    result = post_restore()
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["password_links_closed"] == 1 and report["withdrawal_links_closed"] == 1
    assert report["running_actions_recovered"] == 1 and report["hold"] == "kept"
    assert "@" not in result.stdout  # counts and kinds only
    assert CredentialSetup.objects.get(request=request).state == "superseded"
    assert post(path).status_code == 404  # the link issued before the restore no longer works
    assert WithdrawalConfirmation.objects.get(application=app).state == "superseded"
    running.refresh_from_db()
    assert running.lease_expires_at <= timezone.now()  # the ledger now recovers it through its own path
    assert hold().exists()


def test_6b7b_unused_confirmation_links_are_closed_and_sessions_end(p2):
    from django.contrib.sessions.models import Session

    from applications.models import ContactChallenge
    from tests.test_outbound import staff, verified_application

    verified_application(email="first@example.test")
    from urllib.parse import urlencode

    from tests.test_outbound import FORM, VALID

    response = Client().post(FORM, urlencode({**VALID, "email": "second@example.test"}),
                             content_type="application/x-www-form-urlencoded")  # its link is never used
    assert response.status_code == 302
    run_worker()  # the verification email for the second request is sent: its link is live
    open_before = ContactChallenge.objects.filter(used_at__isnull=True, superseded_at__isnull=True).count()
    assert open_before >= 1, "the test needs a live confirmation link to close"
    client = Client()
    client.force_login(staff(p2, "restore-staff"))
    assert Session.objects.count() >= 1
    place_hold()
    report = json.loads(post_restore().stdout.strip().splitlines()[-1])
    assert report["confirmation_links_closed"] == open_before
    assert ContactChallenge.objects.filter(used_at__isnull=True, superseded_at__isnull=True).count() == 0
    assert Session.objects.count() == 0 and client.get("/staff/").status_code == 302  # staff sign in again


def test_6b7b_unfinished_access_removal_gets_a_new_round(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    assert AccessRevocation.objects.filter(request=request).exclude(state__in=closure.FINAL).exists()
    PendingAction.objects.filter(kind=closure.REVOKE).update(status="done")  # as if the backup predates the rounds
    place_hold()
    report = json.loads(post_restore().stdout.strip().splitlines()[-1])
    assert report["revocation_rounds_queued"] == 1
    assert PendingAction.objects.filter(kind=closure.REVOKE, status="queued").exists()


def test_6b7b_the_report_names_outward_actions_and_only_lift_resumes_work(cl, monkeypatch):
    from workflow import ledger

    PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=uuid.uuid4(),
                                 idempotency_key="post-restore-queued-send")
    place_hold()
    report = json.loads(post_restore().stdout.strip().splitlines()[-1])
    assert report["queued_outward_actions"].get("send_message") == 1 and hold().exists()
    assert ledger.claim_next() is None  # still held
    lifted = json.loads(post_restore("--lift").stdout.strip().splitlines()[-1])
    assert lifted["hold"] == "lifted" and not hold().exists()


def test_6b7b_refuses_without_a_hold_or_a_named_database(p2):
    assert hold().count() == 0
    no_hold = post_restore()
    assert no_hold.returncode == 1 and "there is no restore hold" in no_hold.stderr
    place_hold()
    wrong = post_restore(confirm="the-wrong-database")
    assert wrong.returncode == 1 and "--confirm-database must name this database" in wrong.stderr
    assert hold().exists()

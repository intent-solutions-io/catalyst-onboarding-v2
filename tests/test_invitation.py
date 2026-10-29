"""9kg.43 (029 sections 4.1 and 7; REQ-003, REQ-027, POL-01): invitation-only intake, enforced server-side.

The suite opens the mode per test (tests/conftest.py SUITE_PUBLIC_ENTRY); each test here closes it where it proves the
closed behaviour, and the shipped default is read from a fresh process. Invitations are issued only on the owner path
(the application role may not insert), so tests create them through an owner connection or the owner-run command and
use `privileged_reset`.
"""

import json
import logging
import os
import sys
import time
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

import psycopg
import pytest
from django.conf import settings as conf
from django.core.management import call_command
from django.db import ProgrammingError, connection
from django.test import Client
from django.utils import timezone

from applications import invitations
from applications.models import Application, Invitation
from config import guards
from tests.support import manage_as_owner, run
from tests.test_confirmation import hold_application, in_thread, intake, link_for, post_confirm, snapshot, version
from tests.test_intake import FORM, RECEIVED, counts, post, wait_for_waiters
from tests.test_staff import change_url, logged_in, make_user
from tests.test_startup import STAGING
from tests.test_system_health import health
from workflow.models import PendingAction

ADA, BOB, CAROL, DAVE, ERIN, FRANK = (f"{n}@example.test" for n in ("ada", "bob", "carol", "dave", "erin", "frank"))
PROBE = [sys.executable, "-c",
         "import django; django.setup(); from django.conf import settings as s; print(s.CATALYST_INTAKE_MODE, s.CATALYST_CLIENT_IDENTITY)"]
CHECK = [sys.executable, "manage.py", "check"]


def invite(owner, email_key, *, lifetime="1 day", issued_ago="0 seconds", used=False, superseded=False, issued_by="test owner"):
    """Test setup on the owner path (the application role cannot insert an invitation)."""
    return owner.execute(
        "INSERT INTO applications_invitation (public_id, email_key, issued_by, note, issued_at, expires_at, used_at,"
        " superseded_at, application_id) VALUES (gen_random_uuid(), %s, %s, '', now() - %s::interval, now() - %s::interval"
        " + %s::interval, CASE WHEN %s THEN now() END, CASE WHEN %s THEN now() END, NULL) RETURNING id",
        [email_key, issued_by, issued_ago, issued_ago, lifetime, used, superseded]).fetchone()[0]


def ensure_notice_templates():
    """9kg.52: invitation mode needs the data notice and invitation templates (correspondence migration 0018), and the
    reset truncates every correspondence table, so a test recreates the seeded drafts when they are absent."""
    from importlib import import_module

    from correspondence.models import MessageTemplate, MessageTemplateVersion

    if not MessageTemplate.objects.filter(key="data_notice").exists():
        import_module("correspondence.migrations.0018_intake_notice_templates").create_templates(MessageTemplate, MessageTemplateVersion)


def closed(settings):
    settings.CATALYST_INTAKE_MODE = "invitation"
    ensure_notice_templates()


# --- the mode: fixed in code, invitation-only by default -------------------------------------------------------

def test_9kg_43_the_shipped_default_is_invitation_only_and_the_mode_is_fixed_in_code():
    local = run(PROBE)
    assert local.returncode == 0, local.stderr
    assert local.stdout.split() == ["invitation", "direct"]
    staging = run(PROBE, **STAGING)
    assert staging.returncode == 0, staging.stderr
    assert staging.stdout.split() == ["invitation", "proxy"]
    for name, value in (("CATALYST_INTAKE_MODE", "open"), ("CATALYST_CLIENT_IDENTITY", "direct")):
        refused = run(CHECK, **{name: value})
        assert refused.returncode != 0 and f"{name} may not be set from the environment" in refused.stderr
    # An unset or invalid mode value is a start-up problem, never an open form.
    for bad in ("", None, "closed", "Invitation", "invite"):
        problems = guards.intake_problems(SimpleNamespace(CATALYST_INTAKE_MODE=bad, CATALYST_CLIENT_IDENTITY="direct", CATALYST_ENV="test"), {})
        assert problems == ["CATALYST_INTAKE_MODE must be 'invitation' (the default) or 'open'"], bad
    for mode in ("invitation", "open"):
        assert guards.intake_problems(SimpleNamespace(CATALYST_INTAKE_MODE=mode, CATALYST_CLIENT_IDENTITY="direct", CATALYST_ENV="test"), {}) == []


# --- an uninvited address: one response, nothing recorded ------------------------------------------------------

def test_9kg_43_an_uninvited_address_gets_exactly_the_invited_response_and_nothing_is_recorded(privileged_reset, settings, caplog):
    caplog.set_level(logging.INFO, logger="applications.views")
    closed(settings)
    owner = privileged_reset.connect("owner", autocommit=True)
    invite(owner, ADA)  # live
    invite(owner, CAROL, lifetime="1 hour", issued_ago="2 hours")  # expired
    invite(owner, DAVE, used=True)  # used
    invite(owner, ERIN, superseded=True)  # superseded
    invite(owner, FRANK)  # live, but the submission below comes from another address
    client = Client()
    invited = post(client, email=ADA)
    refusals = [post(client, email=e) for e in (BOB, CAROL, DAVE, ERIN, "frank+x@example.test")]
    for refusal in refusals:
        assert (refusal.status_code, refusal["Location"], refusal.content) == (invited.status_code, invited["Location"], invited.content)
    assert (invited.status_code, invited["Location"]) == (302, RECEIVED)
    assert list(Application.objects.values_list("email_key", flat=True)) == [ADA]  # the invited one, and only it
    assert counts() == {"applications": 1, "versions": 1, "events": 1, "challenges": 1, "actions": 1}
    assert PendingAction.objects.get().subject_id == Application.objects.get().public_ref  # one verification send
    assert caplog.text.count("intake refused: not_invited; nothing recorded") == 5
    for address in (ADA, BOB, CAROL, DAVE, ERIN, FRANK, "frank+x"):
        assert address not in caplog.text
    assert Invitation.objects.get(email_key=ADA).used_at is None  # spent at confirmation, not at acceptance
    page = client.get(FORM).content.decode()
    assert "Access is currently by invitation" in page


# --- consumption: at confirmation, once ------------------------------------------------------------------------

def test_9kg_43_an_invitation_is_spent_at_confirmation_once_and_the_applicant_stays_admitted_afterwards(privileged_reset, settings):
    closed(settings)
    owner = privileged_reset.connect("owner", autocommit=True)
    invite(owner, ADA)
    client = Client()
    app = intake(client)
    assert Invitation.objects.get(email_key=ADA).used_at is None and Invitation.objects.get().application_id is None
    link, v1 = link_for(app), version(app, 1).public_id
    confirmed = post_confirm(client, link, v1)
    assert confirmed.status_code == 200 and b"confirmed" in confirmed.content
    invitation = Invitation.objects.get(email_key=ADA)
    assert invitation.used_at is not None and invitation.application_id == app.id
    again = post_confirm(client, link, v1)
    assert again.status_code == 200 and b"already confirmed" in again.content
    assert Invitation.objects.get(pk=invitation.pk).used_at == invitation.used_at  # nothing changed
    # A later submission by the verified applicant is admitted by the invitation that names the application.
    repeat = post(client, reason="A later synthetic reason.")
    assert (repeat.status_code, repeat["Location"]) == (302, RECEIVED)
    assert list(app.versions.order_by("version_number").values_list("origin", flat=True)) == ["form", "repeat_after_verification"]
    # An invitation can be spent by one application only: the key's open application is unique, and consumption is
    # the one conditional update, so a second confirmation path finds nothing live.
    assert invitations.consume(app) is False


def test_9kg_43_concurrent_confirmations_spend_the_invitation_once(privileged_reset, settings):
    closed(settings)
    owner = privileged_reset.connect("owner", autocommit=True)
    invite(owner, ADA)
    app = intake()
    link, v1 = link_for(app), version(app, 1).public_id
    holder, monitor = hold_application(privileged_reset, app)
    results = []
    threads = [privileged_reset.thread(in_thread(results, lambda: post_confirm(Client(), link, v1))) for _ in range(2)]
    wait_for_waiters(monitor, expected=2)
    assert results == []
    holder.commit()
    for t in threads:
        t.join(timeout=30)
    assert [status for status, _, _ in results] == [200, 200]
    assert sorted("already confirmed" in body for _, body, _ in results) == [False, True]
    spent = Invitation.objects.filter(email_key=ADA, used_at__isnull=False)
    assert spent.count() == 1 and spent.get().application_id == app.id
    app.refresh_from_db()
    assert app.contact_verified_at is not None


def test_9kg_43_an_invitation_expires_by_the_database_clock_and_an_expired_one_refuses_confirmation(privileged_reset, settings, monkeypatch):
    closed(settings)
    owner = privileged_reset.connect("owner", autocommit=True)
    invite(owner, ADA, lifetime="1 second")
    client = Client()
    app = intake(client)  # live at acceptance
    link, v1 = link_for(app), version(app, 1).public_id
    real_now = timezone.now
    monkeypatch.setattr(timezone, "now", lambda: real_now() - timedelta(days=1))  # an application clock far behind
    time.sleep(1.5)  # the database clock passes the expiry; the application clock says otherwise
    before = snapshot()
    refused = post_confirm(client, link, v1)
    assert refused.status_code == 410 and b"This link is not valid" in refused.content  # the same page as an expired challenge
    assert snapshot() == before and Invitation.objects.get(email_key=ADA).used_at is None
    expired = post(client, email=ADA)  # and a new submission from the address is now refused like any uninvited one
    assert (expired.status_code, expired["Location"]) == (302, RECEIVED)
    assert app.versions.count() == 1


# --- issuance: the owner-run command, and what no role may change ----------------------------------------------

def test_9kg_43_issuance_is_an_owner_run_command_that_records_who_issued_it_and_nobody_else_can_change(privileged_reset, settings):
    ensure_notice_templates()  # the command renders the invitation mail before it issues (9kg.52)
    first = manage_as_owner("catalyst_invite", "Ada@Example.TEST", "--issued-by", "owner probe", "--note", "cohort member")
    issued = json.loads(first.stdout)
    assert issued["issued"] is True and issued["superseded"] == 0 and issued["mode"] == "invitation"
    assert "invitation issued by owner probe" in first.stderr  # the audit line names the issuer, never the address
    assert ADA not in (first.stdout + first.stderr).lower() and "Ada@Example.TEST" not in first.stdout + first.stderr
    row = Invitation.objects.get()
    assert (row.email_key, row.issued_by, row.note, row.used_at, row.superseded_at, row.application_id) == (ADA, "owner probe", "cohort member", None, None, None)
    assert abs((row.expires_at - row.issued_at) - timedelta(seconds=settings.CATALYST_INVITATION_LIFETIME_SECONDS)) < timedelta(seconds=5)
    second = json.loads(manage_as_owner("catalyst_invite", ADA, "--issued-by", "owner probe", "--days", "3").stdout)
    assert second["superseded"] == 1
    old, new = Invitation.objects.order_by("id")
    assert old.superseded_at is not None and new.superseded_at is None
    assert abs((new.expires_at - new.issued_at) - timedelta(days=3)) < timedelta(seconds=5)
    # Refused inputs (the owner env, so the refusal is the command's, not a privilege).
    owner_env = dict(CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=conf.CATALYST_DB_ROLES["owner"],
                     CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
    for args in (["not-an-address", "--issued-by", "x"], [ADA], [ADA, "--issued-by", " "], [ADA, "--issued-by", "x", "--days", "0"]):
        assert run([sys.executable, "manage.py", "catalyst_invite", *args], **owner_env).returncode != 0, args
    assert Invitation.objects.count() == 2
    # The application role may not issue one (the command run as that role is refused the same way).
    with pytest.raises(ProgrammingError, match="permission denied for table applications_invitation"):
        Invitation.objects.create(email_key=BOB, issued_by="web", expires_at=timezone.now() + timedelta(days=1))
    app_role = run([sys.executable, "manage.py", "catalyst_invite", BOB, "--issued-by", "web"],
                   CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=conf.CATALYST_DB_ROLES["app"],
                   CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"])
    assert app_role.returncode != 0 and "could not be written (ProgrammingError)" in app_role.stderr
    app_conn = privileged_reset.connect("app", autocommit=True)
    with pytest.raises(psycopg.Error, match="permission denied"):
        app_conn.execute("UPDATE applications_invitation SET superseded_at = now() WHERE id = %s", [new.id])
    with pytest.raises(psycopg.Error, match="permission denied"):
        app_conn.execute("DELETE FROM applications_invitation WHERE id = %s", [new.id])
    # Not even the owner changes identity, issuer or expiry, re-spends, deletes or truncates.
    owner = privileged_reset.connect("owner", autocommit=True)
    for sql in ("UPDATE applications_invitation SET issued_by = 'someone else' WHERE id = %s",
                "UPDATE applications_invitation SET expires_at = now() + interval '1 year' WHERE id = %s",
                "UPDATE applications_invitation SET email_key = 'bob@example.test' WHERE id = %s",
                "UPDATE applications_invitation SET superseded_at = now() + interval '1 hour' WHERE id = %s",
                "DELETE FROM applications_invitation WHERE id = %s"):
        with pytest.raises(psycopg.Error, match="invitation: (UPDATE|DELETE) refused"):
            owner.execute(sql, [old.id])
    with pytest.raises(psycopg.Error, match="append-only"):
        owner.execute("TRUNCATE applications_invitation")
    assert Invitation.objects.count() == 2


# --- the mode off: today's intake, byte for byte ---------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_43_with_the_mode_off_the_public_intake_is_unchanged(settings):
    settings.CATALYST_INTAKE_MODE = "open"
    client = Client()
    page = client.get(FORM).content.decode()
    assert "invitation" not in page.lower()
    assert Invitation.objects.count() == 0
    response = post(client, email=BOB)  # nobody invited anyone
    assert (response.status_code, response["Location"], response.content) == (302, RECEIVED, b"")
    assert counts() == {"applications": 1, "versions": 1, "events": 1, "challenges": 1, "actions": 1}
    app = Application.objects.get()
    confirmed = post_confirm(client, link_for(app), version(app, 1).public_id)
    assert confirmed.status_code == 200 and b"confirmed" in confirmed.content
    assert invitations.describe(app) == "open intake: no invitation required"
    settings.CATALYST_INTAKE_MODE = "invitation"
    assert "Access is currently by invitation" in client.get(FORM).content.decode()
    assert invitations.describe(app).startswith("invitation-only: no live invitation")


# --- visible: the dossier, the health report and the release receipt --------------------------------------------

def test_9kg_43_the_dossier_the_health_report_and_the_release_receipt_show_the_mode(privileged_reset, settings):
    closed(settings)
    owner = privileged_reset.connect("owner", autocommit=True)
    invite(owner, ADA, issued_by="the owner")
    client = Client()
    app = intake(client)
    code, report = health()
    assert code == 0 and report["intake"] == {"mode": "invitation", "client_identity": "direct", "live_invitations": 1, "anomalies": [], "registry_provisional": False,
                                              "data_notice": {"status": "draft", "version": 1, "synthetic": True,
                                                                              "sha256": report["intake"]["data_notice"]["sha256"]},
                                              "verification": report["intake"]["verification"]}  # 9kg.80, its own test
    assert len(report["intake"]["data_notice"]["sha256"]) == 64  # the version's digest, never the wording
    out = StringIO()
    call_command("catalyst_release", "receipt", stdout=out)
    assert json.loads(out.getvalue())["intake_mode"] == "invitation"
    staff = logged_in(make_user(privileged_reset, "dossier-staff"))
    before = staff.get(change_url(app))
    assert before.status_code == 200
    body = before.content.decode()
    assert "invitation-only: live invitation until" in body and "issued by the owner" in body
    assert str(Invitation.objects.get().public_id) not in body
    post_confirm(client, link_for(app), version(app, 1).public_id)
    after = staff.get(change_url(app)).content.decode()
    assert "invitation-only: invitation used at" in after
    assert health()[1]["intake"]["live_invitations"] == 0
    settings.CATALYST_INTAKE_MODE = "open"
    assert health()[1]["intake"]["mode"] == "open"
    assert "open intake: no invitation required" in staff.get(change_url(app)).content.decode()

"""P5 task 5B.2: the set-your-own-password flow and activation (023 sections 5 steps 6 and 7, 11.2, 11.5, 11.8 and
11.11; P5-D-6). TEST-P5-03, 04, 13 to 16. Synthetic only: the fake mail host, the locmem invitation sink and the
scripted SMTP server for the welcome.
"""

import logging
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.db import connection
from django.db.models.functions import Now
from django.test import Client
from psycopg import errors

from applications.models import Application
from correspondence import outbound
from correspondence.models import MessageTemplate, MessageTemplateVersion, StaffItem
from correspondence.rendering import canonical_digest
from correspondence.roles import TEMPLATE_OWNER
from provisioning import credentials
from provisioning.models import CredentialSetup, ProvisioningRequest
from tests.mxroute_fake import FakeMailHost
from tests.test_outbound import staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, approved, c, d, ev, g, grant, h, issued, k, nda, of, p2, pv, run_worker,
    sign_and_settle, tls,
)
from workflow.models import PendingAction

PASSWORD = "Synthetic-choice-0042"  # gitleaks:allow (synthetic; never a real credential)
LINK = re.compile(r"http://catalyst\.example\.test(/setup/[^/\s]+/)")


def welcome_template(env):
    template, _ = MessageTemplate.objects.get_or_create(key="provisioning_welcome", defaults={
        "purpose": "Welcome an activated applicant", "secret_bearing": False})
    subject, body = "Your mailbox is ready", "Hello $display_name,\n\nYour mailbox $mailbox_address is ready.\n"
    version = MessageTemplateVersion.objects.filter(template=template, version=1).first() or \
        MessageTemplateVersion.objects.create(template=template, version=1, subject=subject, body_text=body,
                                              variables=["display_name", "mailbox_address"],
                                              content_sha256=canonical_digest(subject, body))
    outbound.approve_template_version(version.pk, staff(env, "welcome-owner", TEMPLATE_OWNER))


def invited(env, monkeypatch, with_welcome=True):
    """A verified mailbox and its invitation, sent; returns (application, request, setup path)."""
    if with_welcome:
        welcome_template(env)
    app, request = approved(env, monkeypatch)
    run_worker()
    request.refresh_from_db()
    assert request.status == "setup_pending", request.status
    return app, request, LINK.search(mail.outbox[-1].body).group(1)


def setup_of(request):
    return CredentialSetup.objects.filter(request=request).order_by("-series").first()


def post(path, password=PASSWORD, confirm=None):
    return Client().post(path, {"password": password, "confirm": password if confirm is None else confirm})


# --- TEST-P5-13, 14, 03, 04: the whole flow ------------------------------------------------------------------

def test_p5_13_14_03_04_invite_set_activate_and_welcome(pv, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    app, request, path = invited(pv, monkeypatch)
    invitation = mail.outbox[-1]
    assert invitation.to == ["ada@example.test"]  # the verified external address, never the new mailbox
    token = path.split("/")[2]
    setup = setup_of(request)
    assert setup.state == "invited" and setup.token_sha256 == credentials.token_hash(token)
    with connection.cursor() as cursor:  # only the hash is stored, nowhere the token
        for table in ("provisioning_credentialsetup", "workflow_pendingaction", "applications_applicationevent"):
            cursor.execute(f"SELECT count(*) FROM {table} WHERE row_to_json({table})::text LIKE %s", [f"%{token}%"])
            assert cursor.fetchone()[0] == 0, table
    for _ in range(2):  # a GET (or a link preview) never consumes the link
        page = Client().get(path)
        assert page.status_code == 200 and b'type="password"' in page.content
        assert page["Referrer-Policy"] == "same-origin" and "no-store" in page["Cache-Control"]
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    done = post(path)
    assert done.status_code == 200 and PASSWORD.encode() not in done.content
    assert FakeMailHost.current_passwords[("team.example.test", "ada.example")] == PASSWORD
    assert setup_of(request).state == "completed"
    run_worker()  # activation, then the P2 sender
    app.refresh_from_db()
    request.refresh_from_db()
    assert app.stage == "active" and request.status == "active"
    welcome = pv.server.messages[-1]
    assert welcome["rcpts"] == ["ada@example.test"]
    assert b"ada.example@team.example.test" in welcome["data"]
    with connection.cursor() as cursor:  # TEST-P5-15: the chosen password is in no record, event or payload
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        for (table,) in cursor.fetchall():
            cursor.execute(f"SELECT count(*) FROM {table} WHERE row_to_json({table})::text LIKE %s", [f"%{PASSWORD}%"])
            assert cursor.fetchone()[0] == 0, table
    assert PASSWORD not in caplog.text and token not in caplog.text
    assert all(PASSWORD not in m.body for m in mail.outbox)
    assert all(PASSWORD.encode() not in m["data"] for m in pv.server.messages)
    assert post(path).status_code == 404  # used once only


def test_p5_13_used_expired_and_superseded_links_get_the_same_answer(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch)
    CredentialSetup.objects.filter(request=request).update(expires_at=Now() - timedelta(seconds=1))
    expired = Client().get(path)
    unknown = Client().get("/setup/not-a-real-token-at-all/")
    assert expired.status_code == unknown.status_code == 404 and expired.content == unknown.content
    assert expired["Referrer-Policy"] == "same-origin"
    assert post(path).status_code == 404 and not FakeMailHost.current_passwords


def test_p5_13_mismatched_entries_change_nothing(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch)
    response = post(path, confirm="something-else-9")
    assert response.status_code == 400 and setup_of(request).state in ("invited", "presented")
    assert b"something-else-9" not in response.content and not FakeMailHost.current_passwords


def test_p5_13_a_definite_rejection_lets_the_applicant_choose_again_within_the_bound(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch)
    FakeMailHost.faults.append("set_rejected")
    retry = post(path, password="weak-but-long-1")
    assert retry.status_code == 400 and setup_of(request).state == "presented"
    assert post(path).status_code == 200 and setup_of(request).state == "completed"


def test_p5_16_an_unknown_password_outcome_blocks_activation_and_a_new_link_is_sent(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch)
    sent = len(mail.outbox)
    FakeMailHost.faults.append("set_unknown")
    assert post(path).status_code == 404  # the same closed page
    states = list(CredentialSetup.objects.filter(request=request).order_by("series").values_list("state", flat=True))
    assert states == ["superseded", "invitation_pending"]
    run_worker()
    assert len(mail.outbox) == sent + 1 and Application.objects.get(pk=app.pk).stage == "provisioning"
    assert post(path).status_code == 404  # the old link is dead
    assert sum(c[0] == "set_password" for c in FakeMailHost.calls) == 1  # the unknown set was never replayed
    new_path = LINK.search(mail.outbox[-1].body).group(1)
    assert new_path != path and post(new_path).status_code == 200  # never replayed: the applicant chooses again
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "active"


def test_p5_16_a_set_that_never_returns_is_swept_to_uncertain(pv, monkeypatch, settings):
    settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS = 0
    app, request, path = invited(pv, monkeypatch)
    setup = setup_of(request)
    CredentialSetup.objects.filter(pk=setup.pk).update(state="set_pending", set_started_at=Now(), set_attempts=1)
    from provisioning import core

    request = ProvisioningRequest.objects.get(pk=request.pk)
    core.enqueue(credentials.SWEEP, request, f"setup_sweep:{setup.public_id}:7")  # another attempt's sweep
    run_worker()
    assert setup_of(request).state == "set_pending"  # ignored
    settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS = 3600
    core.enqueue(credentials.SWEEP, request, f"setup_sweep:{setup.public_id}:1:young")
    run_worker()
    assert setup_of(request).state == "set_pending"  # this attempt, but not yet past its timeout: ignored
    settings.CATALYST_SETUP_SET_TIMEOUT_SECONDS = 0
    core.enqueue(credentials.SWEEP, request, f"setup_sweep:{setup.public_id}:1")
    run_worker()
    states = list(CredentialSetup.objects.filter(request=request).order_by("series").values_list("state", flat=True))
    assert states[0] == "superseded" and states[-1] == "invited"


def test_p5_14_an_uncertain_invitation_supersedes_and_is_bounded(pv, monkeypatch, settings):
    settings.CATALYST_SETUP_INVITE_MAX_SERIES = 2
    welcome_template(pv)

    class Unanswered(credentials.EmailMessage):  # only the invitation's sink fails
        def send(self, fail_silently=False):
            raise ConnectionError("synthetic: the sink did not answer")
    monkeypatch.setattr(credentials, "EmailMessage", Unanswered)
    app, request = approved(pv, monkeypatch)
    run_worker()
    states = list(CredentialSetup.objects.filter(request=request).order_by("series").values_list("state", flat=True))
    assert states == ["superseded", "superseded"]  # never reconciled by evidence; a new token each time
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").count() == 1
    assert not CredentialSetup.objects.exclude(token_sha256="").exists()


def test_p5_14_a_recipient_changed_before_sending_cancels_the_invitation(pv, monkeypatch):
    welcome_template(pv)
    app, request = approved(pv, monkeypatch)
    real = credentials.verified_address
    sent = len(mail.outbox)
    monkeypatch.setattr(credentials, "verified_address",  # the contact changes after the series was opened
                        lambda application: "someone-else@example.test" if CredentialSetup.objects.exists()
                        else real(application))
    run_worker()
    assert setup_of(request).state == "cancelled" and len(mail.outbox) == sent  # nothing was sent
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").exists()


def test_p5_03_activation_waits_for_an_approved_welcome_and_never_on_a_sent_link_alone(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch, with_welcome=False)
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "provisioning"  # a sent invitation is not access ready
    assert post(path).status_code == 200
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_ACTIVATION, status="open").exists()


def test_p5_15_an_error_during_the_set_leaks_no_password_to_logs_or_the_page(pv, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    app, request, path = invited(pv, monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic defect")
    monkeypatch.setattr(credentials, "set_password", boom)
    response = Client(raise_request_exception=False).post(path, {"password": PASSWORD, "confirm": PASSWORD})
    assert response.status_code == 500 and PASSWORD.encode() not in response.content
    assert PASSWORD not in caplog.text and path.split("/")[2] not in caplog.text


def test_p5_setups_are_fixed_for_every_role(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch)
    setup = setup_of(request)
    for role in ("app", "owner"):
        conn = pv.committed.connect(role, autocommit=True)
        for sql in ("UPDATE provisioning_credentialsetup SET token_sha256 = 'x' WHERE id = %s",
                    "UPDATE provisioning_credentialsetup SET recipient = 'mallory@example.test' WHERE id = %s",
                    "DELETE FROM provisioning_credentialsetup WHERE id = %s"):
            with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
                conn.execute(sql, [setup.pk])
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            conn.execute("TRUNCATE provisioning_credentialsetup")


# --- PR #54 review regressions --------------------------------------------------------------------------------------

def test_review_a_changed_contact_closes_a_link_already_sent(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch)
    monkeypatch.setattr(credentials, "verified_address", lambda application: "replacement@example.test")
    assert Client().get(path).status_code == 404 and post(path).status_code == 404  # re-checked at redemption
    assert not FakeMailHost.current_passwords


def test_review_an_unused_link_expires_visibly_and_a_new_one_follows_then_staff_reissue(pv, monkeypatch, settings):
    settings.CATALYST_SETUP_LINK_SECONDS = 0
    settings.CATALYST_SETUP_INVITE_MAX_SERIES = 2
    welcome_template(pv)
    app, request = approved(pv, monkeypatch)
    run_worker()  # verify, invite, expire, a second series, expire again, then the bound
    states = list(CredentialSetup.objects.filter(request=request).order_by("series").values_list("state", flat=True))
    assert states == ["expired", "expired"]
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").count() == 1
    settings.CATALYST_SETUP_LINK_SECONDS = 3600
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        credentials.reissue(request.pk, pv.approver, "Applicant asked for a new link")
    credentials.reissue(request.pk, pv.op1, "Applicant asked for a new link")
    run_worker()
    path = LINK.search(mail.outbox[-1].body).group(1)
    assert post(path).status_code == 200
    assert not StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").exists()


def test_review_a_refused_activation_can_be_retried_once_its_cause_is_fixed(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch, with_welcome=False)
    assert post(path).status_code == 200
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    assert not MessageTemplateVersion.objects.filter(template__key="provisioning_welcome", status="approved").exists()
    welcome_template(pv)
    credentials.retry_activation(request.pk, pv.op1, "Owner approved the welcome template")
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "active"
    assert not StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_ACTIVATION, status="open").exists()


@pytest.mark.parametrize("missing", ["setup", "verification"])
def test_review_activation_needs_verified_provisioning_and_a_completed_setup(pv, monkeypatch, missing):
    from provisioning import core

    app, request, path = invited(pv, monkeypatch)
    owner = pv.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE provisioning_provisioningrequest SET status = 'setup_complete' WHERE id = %s", [request.pk])
    if missing == "verification":  # the setup completed, but no verification of this request was ever recorded
        owner.execute("UPDATE provisioning_credentialsetup SET state = 'completed', completed_at = now() WHERE request_id = %s",
                      [request.pk])
        with owner.transaction():
            owner.execute("ALTER TABLE applications_applicationevent DISABLE TRIGGER catalyst_append_only")
            owner.execute("DELETE FROM applications_applicationevent WHERE kind = 'provisioning_verified'")
            owner.execute("ALTER TABLE applications_applicationevent ENABLE TRIGGER catalyst_append_only")
    core.enqueue(credentials.ACTIVATE, ProvisioningRequest.objects.get(pk=request.pk), f"activate:{request.public_id}:x")
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "provisioning"
    assert app.events.filter(kind="provisioning_activation_refused", data__reason="not_ready").exists()


def test_review_an_error_inside_the_recording_transaction_leaks_no_password(pv, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    app, request, path = invited(pv, monkeypatch)
    real = credentials.core.record

    def explode(application, kind, data, actor_ref, **extra):
        if kind == "provisioning_setup_completed":
            raise RuntimeError("synthetic defect after the credential operation")
        return real(application, kind, data, actor_ref, **extra)
    monkeypatch.setattr(credentials.core, "record", explode)
    response = Client(raise_request_exception=False).post(path, {"password": PASSWORD, "confirm": PASSWORD})
    assert response.status_code == 500 and PASSWORD.encode() not in response.content
    assert PASSWORD not in caplog.text and path.split("/")[2] not in caplog.text


def test_review_definite_rejections_are_bounded(pv, monkeypatch, settings):
    settings.CATALYST_SETUP_SET_ATTEMPTS = 2
    app, request, path = invited(pv, monkeypatch)
    FakeMailHost.faults.extend(["set_rejected", "set_rejected"])
    assert post(path, password="first-choice-1").status_code == 400
    assert post(path, password="second-choice-2").status_code == 404  # the bound: this series ends
    assert setup_of(request).state == "invitation_pending" and setup_of(request).series == 1


def test_review_an_invitation_is_never_sent_into_the_company_domain(pv, monkeypatch):
    welcome_template(pv)
    monkeypatch.setattr(credentials, "verified_address", lambda application: "someone@team.example.test")
    app, request = approved(pv, monkeypatch)
    run_worker()
    assert not CredentialSetup.objects.filter(request=request).exists()
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").exists()


def test_review_a_completed_series_is_final_for_every_role(pv, monkeypatch):
    app, request, path = invited(pv, monkeypatch)
    assert post(path).status_code == 200
    setup = CredentialSetup.objects.get(request=request, state="completed")
    for role in ("app", "owner"):
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            pv.committed.connect(role, autocommit=True).execute(
                "UPDATE provisioning_credentialsetup SET state = 'presented' WHERE id = %s", [setup.pk])


def test_review_the_setup_token_is_redacted_from_django_request_logs(pv, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    response = Client().get("/setup/SYNTHETICTOKENVALUE1234567890/")
    assert response.status_code == 404 and "no-store" in response["Cache-Control"]
    assert "SYNTHETICTOKENVALUE" not in caplog.text and "/setup/[redacted]" in caplog.text


def test_review_the_checklist_path_never_calls_the_api_for_the_credential(pv, monkeypatch, settings):
    from provisioning import services

    settings.CATALYST_PROVISIONING_METHOD = "checklist"
    app, request = approved(pv, monkeypatch)
    services.record_checklist_creation(request.pk, pv.op1, "Created in the panel with the approved limits")
    services.attest_checklist_verification(request.pk, pv.op2, "Listed in the panel with the limits")
    assert not CredentialSetup.objects.exists() and not FakeMailHost.calls
    assert StaffItem.objects.filter(application=app, reason_code=credentials.ITEM_SETUP, status="open").exists()


def test_review_a_change_can_be_superseded_while_a_link_is_outstanding(pv, monkeypatch):
    from provisioning import services

    app, request, path = invited(pv, monkeypatch)
    assert PendingAction.objects.filter(idempotency_key__startswith="setup_expire:", status="queued").exists()
    services.supersede(request.pk, pv.op1, "A prerequisite changed while the link was out")
    request.refresh_from_db()
    assert request.status == "superseded"
    assert post(path).status_code == 404  # the outstanding link no longer works


def test_review_staff_reissue_recovers_a_request_whose_contact_was_not_usable_at_first(pv, monkeypatch):
    welcome_template(pv)
    real = credentials.verified_address
    monkeypatch.setattr(credentials, "verified_address", lambda application: "someone@team.example.test")
    app, request = approved(pv, monkeypatch)
    run_worker()
    request.refresh_from_db()
    assert request.status == "verified" and not CredentialSetup.objects.exists()
    monkeypatch.setattr(credentials, "verified_address", real)  # the contact is fixed
    credentials.reissue(request.pk, pv.op1, "Contact corrected to the applicant's own address")
    run_worker()
    assert post(LINK.search(mail.outbox[-1].body).group(1)).status_code == 200


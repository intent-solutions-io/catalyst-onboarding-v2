"""P5 task 5B.3a: withdrawal, closure and access revocation (023 sections 6, 11.5, 11.6 and 11.11; P5-D-8 to P5-D-11).
TEST-P5-05, 17, 18, 21, 22. Synthetic only: the fake mail host and the locmem sink.
"""

import re

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import Client
from psycopg import errors

from applications.models import Application
from correspondence.models import StaffItem
from provisioning import closure, credentials, services
from provisioning.models import AccessRevocation, CredentialSetup, ProvisioningRequest, WithdrawalConfirmation
from tests.mxroute_fake import FakeMailHost
from tests.test_credentials import LINK, invited, post, welcome_template
from tests.test_outbound import staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, approved, c, complete, d, ev, g, grant, h, issued, k, nda, of, p2, pv, run_worker,
    sign_and_settle, tls,
)
from workflow.models import PendingAction

WITHDRAW_LINK = re.compile(r"http://catalyst\.example\.test(/withdraw/[^/\s]+/)")
ADDRESS = "ada.example@team.example.test"


@pytest.fixture
def cl(pv):
    pv.closer = grant(pv, staff(pv, "application-closer"), "close_application")
    return pv


def active_member(env, monkeypatch):
    app, request, path = invited(env, monkeypatch)
    assert post(path).status_code == 200
    run_worker()
    assert Application.objects.get(pk=app.pk).stage == "active"
    return app, ProvisioningRequest.objects.get(pk=request.pk)


def states(request):
    return dict(AccessRevocation.objects.filter(request=request).values_list("kind", "state"))


# --- TEST-P5-05, 18: closing an active member revokes access without deleting anything --------------------------

def test_p5_05_18_closing_an_active_member_revokes_access_and_deletes_nothing(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    FakeMailHost.forwarders[("team.example.test", "ada.example")] = ("ada@example.test",)  # owned by the mailbox
    FakeMailHost.forwarders[("team.example.test", "team")] = ("lead@example.test", ADDRESS)  # names it among others
    chosen = FakeMailHost.current_passwords[("team.example.test", "ada.example")]
    with pytest.raises(PermissionDenied):
        closure.close_application(app.pk, cl.op1, "closed", "Programme ended for this applicant")
    with pytest.raises(services.Refused, match="reason_needed"):
        closure.close_application(app.pk, cl.closer, "closed", "x")
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    assert Application.objects.get(pk=app.pk).stage == "closed"
    run_worker()  # the revocation round, then its repeat after the settle delay
    request.refresh_from_db()
    assert request.status == "stopped" and request.stop_requested_at is not None
    assert FakeMailHost.current_passwords[("team.example.test", "ada.example")] != chosen  # rotated, unknown to anyone
    assert ("team.example.test", "ada.example") in FakeMailHost.mailboxes  # never deleted (POL-10)
    assert ("team.example.test", "ada.example") not in FakeMailHost.forwarders  # the owned forwarder is removed
    assert ("team.example.test", "team") in FakeMailHost.forwarders  # a shared one is left for staff
    got = states(request)
    assert got["password_rotation"] == "applied_unverified" and got["owned_forwarders"] == "verified"
    assert got["inbound_forwarders"] == "pending" and got["catch_all"] == "verified"
    assert got["sessions"] == got["app_credentials"] == "unsupported" and got["setup_links"] == "verified"
    assert not closure.revocation_complete(request)
    assert StaffItem.objects.filter(application=app, reason_code=closure.ITEM_REVOCATION, status="open").exists()
    calls = [c[0] for c in FakeMailHost.calls]
    assert "delete_forwarder" in calls and not any(c in calls for c in ("delete_mailbox", "suspend"))
    assert sum(1 for c in FakeMailHost.calls if c[0] == "set_password") >= 2  # the chosen one, then rotations


def test_p5_18_unsupported_obligations_end_only_by_an_owner_accepted_exception(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    run_worker()
    for kind in ("sessions", "app_credentials"):
        row = AccessRevocation.objects.get(request=request, kind=kind)
        with pytest.raises(PermissionDenied):
            closure.accept_revocation_exception(row.pk, cl.op1, "No documented session revocation")
        closure.accept_revocation_exception(row.pk, cl.approver, "No documented session revocation exists")
    request.refresh_from_db()
    assert closure.revocation_complete(request)
    row = AccessRevocation.objects.get(request=request, kind="sessions")
    assert row.state == "exception" and row.decided_by == f"user:{cl.approver.pk}"


# --- TEST-P5-17: stop intent survives work in flight --------------------------------------------------------------

def test_p5_17_a_withdrawal_during_an_uncertain_create_recovers_the_late_mailbox_without_a_welcome(cl, monkeypatch):
    welcome_template(cl)
    app, request = approved(cl, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    from provisioning import handlers

    real = handlers.ReconcileMailbox.run

    def withdraw_first(self, claim):  # the applicant withdraws before reconciliation reads the mailbox
        if Application.objects.get(pk=app.pk).stage != "withdrawn":
            closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
        return real(self, claim)
    monkeypatch.setattr(handlers.ReconcileMailbox, "run", withdraw_first)
    run_worker()
    request.refresh_from_db()
    assert request.status == "recovered_after_stop" and Application.objects.get(pk=app.pk).stage == "withdrawn"
    assert not CredentialSetup.objects.filter(request=request).exists()  # no invitation, no welcome
    assert states(request)["password_rotation"] == "applied_unverified"


def test_p5_17_rotation_waits_for_a_password_set_in_flight(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    setup = CredentialSetup.objects.get(request=request)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    cl.committed.connect("owner", autocommit=True).execute(  # simulate a set still in flight on another series
        "INSERT INTO provisioning_credentialsetup (public_id, request_id, series, recipient, token_sha256, state,"
        " expires_at, set_attempts, created_at, updated_at) VALUES (gen_random_uuid(), %s, 9, %s, repeat('a', 64),"
        " 'set_pending', now() + interval '1 hour', 1, now(), now())",
        [request.pk, setup.recipient])
    before = sum(1 for c in FakeMailHost.calls if c[0] == "set_password")
    from tests.test_outbound import run_worker as one_pass
    one_pass()
    assert sum(1 for c in FakeMailHost.calls if c[0] == "set_password") == before  # nothing rotated yet
    revoke = PendingAction.objects.filter(kind=closure.REVOKE).order_by("-id").first()
    assert revoke.status == "queued" and revoke.last_error == "set_pending"


# --- TEST-P5-21: the applicant's explicit withdrawal ---------------------------------------------------------------

def test_p5_21_get_shows_post_commits_and_the_link_works_once(cl, monkeypatch):
    app = complete(cl, monkeypatch)
    with pytest.raises(PermissionDenied):
        closure.request_withdrawal_link(app.pk, cl.op1, "Applicant asked to withdraw by email")
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked to withdraw by email")
    run_worker()
    path = WITHDRAW_LINK.search(mail.outbox[-1].body).group(1)
    assert mail.outbox[-1].to == ["ada@example.test"]
    token = path.split("/")[2]
    assert not WithdrawalConfirmation.objects.filter(token_sha256=token).exists()  # only the hash is stored
    for _ in range(2):
        page = Client().get(path)
        assert page.status_code == 200 and page["Referrer-Policy"] == "no-referrer"
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"  # a GET changes nothing
    done = Client().post(path)
    assert done.status_code == 200 and Application.objects.get(pk=app.pk).stage == "withdrawn"
    assert PendingAction.objects.filter(kind="provision", status="cancelled").exists()  # the held hand-off is gone
    assert Client().post(path).status_code == 404 and Client().get(path).status_code == 404


def test_p5_21_a_new_link_supersedes_the_old_one_and_a_changed_contact_closes_it(cl, monkeypatch):
    app = complete(cl, monkeypatch)
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked to withdraw by email")
    run_worker()
    first = WITHDRAW_LINK.search(mail.outbox[-1].body).group(1)
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked again for a new link")
    run_worker()
    second = WITHDRAW_LINK.search(mail.outbox[-1].body).group(1)
    assert Client().post(first).status_code == 404
    monkeypatch.setattr(closure, "verified_address", lambda application: "replacement@example.test")
    assert Client().post(second).status_code == 404 and Application.objects.get(pk=app.pk).stage == "agreements_complete"


# --- TEST-P5-22: nothing is reopened or closed twice; no automatic closure -----------------------------------------

def test_p5_22_a_closed_application_is_never_closed_again_or_reopened(cl, monkeypatch):
    app = complete(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    with pytest.raises(services.Refused, match="already_closed"):
        closure.close_application(app.pk, cl.closer, "withdrawn", "A second attempt after closure")
    with pytest.raises(services.Refused, match="already_closed"):
        closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked after closure")
    from django.core.management import call_command
    from io import StringIO
    out = StringIO()
    call_command("activate_provisioning", "--activation-version", "1", "--approval-ref", "D-47", stdout=out)
    assert '"released": 0' in out.getvalue() and Application.objects.get(pk=app.pk).stage == "closed"


def test_p5_22_closing_during_agreements_stops_unfinished_agreements(cl, monkeypatch):
    app = issued(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
    assert Application.objects.get(pk=app.pk).stage == "withdrawn"
    assert app.events.filter(kind="agreements_stopped", data__reason="withdrawn").exists()


# --- protections ----------------------------------------------------------------------------------------------------

def test_p5_revocations_and_withdrawals_are_fixed_for_every_role(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    run_worker()
    row = AccessRevocation.objects.get(request=request, kind="owned_forwarders")
    for role in ("app", "owner"):
        conn = cl.committed.connect(role, autocommit=True)
        for sql in ("UPDATE provisioning_accessrevocation SET state = 'requested' WHERE id = %s",
                    "UPDATE provisioning_accessrevocation SET kind = 'sessions' WHERE id = %s",
                    "DELETE FROM provisioning_accessrevocation WHERE id = %s"):
            with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
                conn.execute(sql, [row.pk])
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            conn.execute("TRUNCATE provisioning_withdrawalconfirmation")

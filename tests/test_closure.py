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
from provisioning import closure, services
from provisioning.models import AccessRevocation, CredentialSetup, ProvisioningRequest, WithdrawalConfirmation
from tests.mxroute_fake import FakeMailHost
from tests.test_credentials import invited, post, welcome_template
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
    assert not closure.revocation_complete(request)  # the repeat rotation is still due
    from django.db.models.functions import Now
    PendingAction.objects.filter(kind=closure.REVOKE, status="queued").update(due_at=Now())
    run_worker()
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
    # A mailbox found after an unknown create is never acted on until staff confirm it is ours (023 11.3).
    assert states(request)["password_rotation"] == "requested"
    assert not closure.revocation_complete(request)
    services.confirm_found_mailbox(request.pk, cl.op1, "ours", "Limits and timing match our request")
    run_worker()
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
        assert page.status_code == 200 and page["Referrer-Policy"] == "same-origin"
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


# --- PR #55 review regressions --------------------------------------------------------------------------------------

def test_review_a_create_that_never_landed_settles_as_nothing_of_ours_only_after_its_watch(cl, monkeypatch):
    welcome_template(cl)
    app, request = approved(cl, monkeypatch)
    FakeMailHost.faults.append("create_lost")
    from provisioning import handlers

    real = handlers.ReconcileMailbox.run

    def withdraw_first(self, claim):
        if Application.objects.get(pk=app.pk).stage != "withdrawn":
            closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
        return real(self, claim)
    monkeypatch.setattr(handlers.ReconcileMailbox, "run", withdraw_first)
    run_worker()
    request.refresh_from_db()
    assert request.status == "stopped"
    assert app.events.filter(kind="provisioning_watch_ended").exists()  # the watch ran before anything settled
    got = states(request)
    assert got["password_rotation"] == got["sessions"] == got["catch_all"] == "not_applicable"
    assert closure.revocation_complete(request)
    assert not any(c[0] == "set_password" for c in FakeMailHost.calls)  # nothing rotated: nothing of ours exists


def test_review_a_mailbox_present_before_our_create_is_never_touched_by_revocation(cl, monkeypatch):
    from provisioning.adapter import Mailbox

    welcome_template(cl)
    app, request = approved(cl, monkeypatch)
    FakeMailHost.mailboxes[("team.example.test", "ada.example")] = Mailbox("ada.example", "team.example.test", 50, 5, False)
    FakeMailHost.current_passwords[("team.example.test", "ada.example")] = "someone-elses"
    run_worker()  # conflict: someone else's mailbox
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    run_worker()
    assert FakeMailHost.current_passwords[("team.example.test", "ada.example")] == "someone-elses"
    assert not AccessRevocation.objects.filter(request=request).exists()  # nothing of ours: nothing to revoke


def test_review_exceptions_cannot_waive_a_rotation_and_complete_the_rollup_only_when_settled(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    rotation = AccessRevocation.objects.get(request=request, kind="password_rotation")
    with pytest.raises(services.Refused, match="not_exceptionable"):
        closure.accept_revocation_exception(rotation.pk, cl.approver, "Trying to waive the rotation")
    run_worker()
    for kind in ("sessions", "app_credentials"):
        closure.accept_revocation_exception(AccessRevocation.objects.get(request=request, kind=kind).pk, cl.approver,
                                            "No documented session revocation exists")
    request.refresh_from_db()
    assert not closure.revocation_complete(request)  # the repeat rotation is still due
    from django.db.models.functions import Now
    PendingAction.objects.filter(kind=closure.REVOKE, status="queued").update(due_at=Now())  # the settle delay passes
    run_worker()
    assert closure.revocation_complete(request)
    assert not StaffItem.objects.filter(application=app, reason_code=closure.ITEM_REVOCATION, status="open").exists()
    rounds = PendingAction.objects.filter(kind=closure.REVOKE, input_ref=str(request.public_id)).count()
    assert rounds >= 2 and PendingAction.objects.filter(kind=closure.REVOKE, idempotency_key__contains=":repeat:",
                                                        status="done").exists()  # the repeat ran


def test_review_closing_mid_flow_cancels_queued_work_and_settles_cleanly(cl, monkeypatch):
    app, request, path = invited(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
    request.refresh_from_db()
    assert request.status == "stopped" and CredentialSetup.objects.get(request=request).state == "cancelled"
    assert post(path).status_code == 404
    assert not StaffItem.objects.filter(application=app, reason_code="provisioning_setup_needs_staff", status="open").exists()


def test_9kg_87_closing_cancels_the_held_evidence_collection_so_the_person_can_be_erased(cl, monkeypatch):
    """S1's confirmation holds a start_evidence_collection action for the owner's release; a closed or withdrawn
    application never starts it, and the erasure refuses while it is held (subject_has_open_work, CE004)."""
    from applications.confirmation import START_EVIDENCE_COLLECTION, start_evidence_collection_key

    app, request, path = invited(cl, monkeypatch)
    held = PendingAction.objects.get(kind=START_EVIDENCE_COLLECTION, subject_id=app.public_ref)  # S1 created it
    assert held.idempotency_key == start_evidence_collection_key(app.public_ref)
    # The P5 chain released it; a wave-one case keeps it held (evidence collection is not activated), so hold it again.
    PendingAction.objects.filter(pk=held.pk).update(status=PendingAction.Status.HELD, completed_at=None)
    other = PendingAction.objects.create(kind=START_EVIDENCE_COLLECTION, subject_type="application",
                                         subject_id="00000000-0000-0000-0000-00000000bbbb", input_ref="version",
                                         status=PendingAction.Status.HELD, idempotency_key="start_evidence_collection:other")
    closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
    held.refresh_from_db()
    other.refresh_from_db()
    assert (held.status, held.last_error) == ("cancelled", "application_closed") and held.completed_at is not None
    assert other.status == "held"  # another person's held collection is untouched
    assert not PendingAction.objects.filter(kind=START_EVIDENCE_COLLECTION, subject_id=app.public_ref,
                                            status__in=("queued", "running", "held", "uncertain")).exists()


def test_review_a_shared_forwarder_fixed_in_the_panel_is_verified_only_by_a_new_read(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    FakeMailHost.forwarders[("team.example.test", "team")] = ("lead@example.test", ADDRESS)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    run_worker()
    assert states(request)["inbound_forwarders"] == "pending"
    FakeMailHost.forwarders[("team.example.test", "team")] = ("lead@example.test",)  # staff edited it in the panel
    closure.recheck_revocation(request.pk, cl.op1, "Removed the address from the team forwarder")
    run_worker()
    assert states(request)["inbound_forwarders"] == "verified"
    assert app.events.filter(kind="provisioning_forwarder_removed").exists() is False  # none owned by the mailbox


def test_review_a_new_withdrawal_link_supersedes_one_still_sending(cl, monkeypatch):
    app = complete(cl, monkeypatch)
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked to withdraw by email")
    WithdrawalConfirmation.objects.filter(application=app).update(state="uncertain")  # a send whose result is unknown
    closure.request_withdrawal_link(app.pk, cl.closer, "Applicant asked again for a new link")
    assert list(WithdrawalConfirmation.objects.filter(application=app).order_by("id").values_list("state", flat=True)) \
        == ["superseded", "pending"]
    assert app.events.filter(kind="provisioning_withdrawal_link_requested").count() == 2


def test_review_closing_during_agreements_cancels_the_unfinished_envelope(cl, monkeypatch):
    from agreements.models import AgreementInstance

    app = issued(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
    run_worker()
    assert AgreementInstance.objects.get(application=app).issue_status == "cancelled"


def test_review_a_late_mailbox_found_by_the_watch_is_recorded_honestly_never_as_not_applicable(cl, monkeypatch):
    from provisioning import handlers
    from provisioning.adapter import Mailbox

    welcome_template(cl)
    app, request = approved(cl, monkeypatch)
    FakeMailHost.faults.append("create_lost")
    real_reconcile, real_watch = handlers.ReconcileMailbox.run, handlers.ReconcileMailbox._watch

    def withdraw_first(self, claim):
        if Application.objects.get(pk=app.pk).stage != "withdrawn":
            closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
        return real_reconcile(self, claim)

    def late_landing(self, claim, req, key):  # our lost create lands late, just before the watch looks
        FakeMailHost.mailboxes[("team.example.test", "ada.example")] = Mailbox("ada.example", "team.example.test",
                                                                               1024, 100, False)
        return real_watch(self, claim, req, key)
    monkeypatch.setattr(handlers.ReconcileMailbox, "run", withdraw_first)
    monkeypatch.setattr(handlers.ReconcileMailbox, "_watch", late_landing)
    run_worker()
    request.refresh_from_db()
    got = states(request)
    assert "not_applicable" not in (got["password_rotation"], got["owned_forwarders"])  # never frozen early
    assert not closure.revocation_complete(request)
    services.confirm_found_mailbox(request.pk, cl.op1, "ours", "The late mailbox matches our request")
    run_worker()
    assert states(request)["password_rotation"] == "applied_unverified"


@pytest.mark.parametrize("fault", ["create_rejected", "read_500"])
def test_review_a_stop_settles_when_the_create_fails_or_was_never_sent(cl, monkeypatch, fault):
    from provisioning import handlers

    welcome_template(cl)
    app, request = approved(cl, monkeypatch)
    FakeMailHost.faults.append(fault)
    real = handlers.CreateMailbox.run

    def close_mid_create(self, claim):  # the withdrawal lands while the create runs
        if Application.objects.get(pk=app.pk).stage != "withdrawn":
            closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
        return real(self, claim)
    monkeypatch.setattr(handlers.CreateMailbox, "run", close_mid_create)
    run_worker()
    request.refresh_from_db()
    assert request.status == "stopped" and not FakeMailHost.mailboxes
    assert all(s in ("verified", "not_applicable") for s in states(request).values())


def test_review_a_stop_at_the_create_result_recovers_the_new_mailbox_and_revokes_it(cl, monkeypatch):
    from provisioning import handlers

    welcome_template(cl)
    app, request = approved(cl, monkeypatch)

    def close_after_call(self, claim):  # the create succeeded at the host; the withdrawal commits before it is recorded
        if Application.objects.get(pk=app.pk).stage != "withdrawn":
            closure.close_application(app.pk, cl.closer, "withdrawn", "Applicant asked by phone to withdraw")
    monkeypatch.setattr(handlers.CreateMailbox, "after_call", close_after_call)
    run_worker()
    request.refresh_from_db()
    assert request.status == "recovered_after_stop" and not CredentialSetup.objects.filter(request=request).exists()
    assert states(request)["password_rotation"] == "applied_unverified"  # proven ours: our create succeeded


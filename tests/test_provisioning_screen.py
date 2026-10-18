"""P5 task 5B.3b: the applicant-centred provisioning staff screen (023 sections 7 and 9). TEST-P5-19, 20.
Synthetic only: the fake mail host and the locmem sink."""

import pytest
from django.test import Client
from django.urls import reverse

from applications.models import Application
from provisioning import staff_views
from provisioning.models import AccessRevocation, ProvisioningRequest
from tests.mxroute_fake import FakeMailHost
from tests.test_closure import active_member, cl  # noqa: F401  (fixture chain)
from tests.test_outbound import staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, admitted, approved, c, complete, d, ev, g, grant, h, issued, k, nda, p2, pv, release, request_of, run_worker,
    sign_and_settle, tls,
)


def page(app):
    return reverse("provisioning_staff:provisioning", args=[app.public_ref])


def act(app):
    return reverse("provisioning_staff:act", args=[app.public_ref])


def client_for(user, strict=False):
    client = Client(enforce_csrf_checks=strict)
    client.force_login(user)
    return client


@pytest.fixture
def released(cl, monkeypatch):
    app = complete(cl, monkeypatch)
    assert release()["released"] == 1
    return app, request_of(app)


# --- who may open it ---------------------------------------------------------------------------------------------

def test_p5_19_only_holders_of_a_provisioning_permission_open_the_screen_and_a_superuser_is_refused(cl, released):
    app, _ = released
    assert Client().get(page(app)).status_code == 302  # to the staff login
    for user in (staff(cl, "no-provisioning-permission"), staff(cl, "root-provisioning", superuser=True)):
        assert client_for(user).get(page(app)).status_code == 403
    viewer = grant(cl, staff(cl, "provisioning-viewer"), "view_provisioningrequest")
    for user in (viewer, cl.op1, cl.approver, cl.closer):
        response = client_for(user).get(page(app))
        cache = response["Cache-Control"]
        assert response.status_code == 200 and "no-cache" in cache and "no-store" in cache


def test_the_dossier_link_and_the_provisioning_screen_use_the_same_permissions(cl, released):
    from applications.admin import PROVISIONING_SCREEN_PERMISSIONS

    assert set(PROVISIONING_SCREEN_PERMISSIONS) == set(staff_views.SCREEN)  # the link never drifts from the gate
    app, _ = released
    dossier = reverse("admin:applications_application_change", args=[app.pk])
    reader = grant(cl, grant(cl, staff(cl, "dossier-reader"), "view_application"), "view_provisioningrequest")
    assert page(app) in client_for(reader).get(dossier).content.decode()
    plain = grant(cl, staff(cl, "dossier-only"), "view_application")
    assert page(app) not in client_for(plain).get(dossier).content.decode()


# --- TEST-P5-19: each phase shown separately, with the next action and its owner -----------------------------------

def test_p5_19_the_screen_shows_each_phase_the_next_action_and_its_owner(cl, released):
    app, _ = released
    body = client_for(cl.approver).get(page(app)).content.decode()
    assert "Approval" in body and "awaiting the approver" in body and "(owner: approver)" in body
    assert "ada.example@team.example.test" in body and "Approve exactly this" in body
    assert " checked" not in body  # nothing consequential is preselected
    operator_view = client_for(cl.op1).get(page(app)).content.decode()
    assert "Approve exactly this" not in operator_view  # each control only for its permission holder
    assert '<th scope="row">Approval</th><td>not approved</td>' in body
    for heading in ("Creation", "Verification", "Credential setup", "Activation", "Revocation"):
        assert f"<h3>{heading}</h3>" in body  # one section per phase
    assert "Not verified." in body and "No create yet." in body  # each phase states its own fact


def test_p5_19_approving_through_the_screen_needs_csrf_and_the_digest_shown(cl, released):
    app, request = released
    form = {"action": "approve", "request": str(request.public_id), "digest": request.approval_digest}
    assert client_for(cl.approver, strict=True).post(act(app), form).status_code == 403  # no CSRF token
    stale = client_for(cl.approver).post(act(app), {**form, "digest": "0" * 64})
    assert stale.status_code == 409 and "changed_since_shown" in stale.content.decode()
    assert ProvisioningRequest.objects.get(pk=request.pk).status == "awaiting_approval"
    refused = client_for(cl.op1).post(act(app), form)  # an operator is not the approver
    assert refused.status_code == 409 and "not_permitted" in refused.content.decode()
    done = client_for(cl.approver).post(act(app), form)
    assert done.status_code == 302 and ProvisioningRequest.objects.get(pk=request.pk).status != "awaiting_approval"


def test_p5_19_a_refusal_keeps_what_was_typed_and_an_unknown_action_is_not_found(cl, released):
    app, request = released
    note = "Applicant <b>asked</b> to stop"
    response = client_for(cl.closer).post(act(app), {"action": "close", "outcome": "withdrawn", "note": "short"})
    assert response.status_code == 409 and "reason_needed" in response.content.decode()
    response = client_for(cl.closer).post(act(app), {"action": "close", "outcome": "abandoned", "note": note})
    text = response.content.decode()
    assert response.status_code == 409 and "unknown_outcome" in text
    assert "Applicant &lt;b&gt;asked&lt;/b&gt; to stop" in text and "<b>asked</b>" not in text  # kept, escaped
    assert client_for(cl.closer).post(act(app), {"action": "delete_everything"}).status_code == 404
    assert Application.objects.get(pk=app.pk).stage == "provisioning"


def test_p5_19_closing_through_the_screen_shows_revocation_and_the_owner_accepts_an_exception(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    closer = client_for(cl.closer)
    assert closer.post(act(app), {"action": "close", "outcome": "closed",
                                  "note": "Programme ended for this applicant"}).status_code == 302
    run_worker()
    body = client_for(cl.approver).get(page(app)).content.decode()
    assert "Not complete." in body and "no documented mechanism: owner decision" in body
    assert "Close the application" not in body  # final: never closed twice
    sessions = AccessRevocation.objects.get(request=request, kind="sessions")
    rotation = AccessRevocation.objects.get(request=request, kind="password_rotation")
    owner = client_for(cl.approver)
    waive_rotation = owner.post(act(app), {"action": "accept_exception", "revocation": str(rotation.public_id),
                                           "note": "Trying to waive the rotation"})
    assert waive_rotation.status_code == 409 and "not_exceptionable" in waive_rotation.content.decode()
    assert owner.post(act(app), {"action": "accept_exception", "revocation": str(sessions.public_id),
                                 "note": "No documented session revocation exists"}).status_code == 302
    assert AccessRevocation.objects.get(pk=sessions.pk).state == "exception"


# --- TEST-P5-20: managing access is not reading mail or documents --------------------------------------------------

def test_p5_20_provisioning_permissions_grant_no_mail_or_document_access(cl, monkeypatch):
    from agreements.models import StoredDocument

    app, request = active_member(cl, monkeypatch)
    body = client_for(cl.op1).get(page(app)).content.decode()
    assert "shows no applicant mail and no signed documents" in body
    assert "/staff/p4/documents/" not in body and "/agreements/" not in body  # no document link
    assert f"/staff/p2/applications/{app.public_ref}" not in body  # no link into the applicant's mail
    for user in (cl.op1, cl.approver, cl.closer):
        assert not user.has_perm("agreements.retrieve_agreement_document")
        assert not any(user.has_perm(f"correspondence.{p}") for p in ("view_inboundmessage", "view_outboundmessage"))
        assert client_for(user).get(reverse("correspondence_staff:application", args=[app.public_ref])).status_code == 403
        document = StoredDocument.objects.filter(instance__application=app).first()
        assert document is not None  # the agreements were stored: the refusal below is real
        assert client_for(user).post(reverse("agreements_staff:retrieve", args=[document.public_id]),
                                     {"note": "Curious about the agreement"}).status_code == 404
    assert FakeMailHost.passwords_seen  # the applicant set one; it never reaches this screen
    assert not any(p in body for p in FakeMailHost.passwords_seen)
    setup = request.setups.get()
    assert setup.token_sha256 not in body and setup.recipient not in body  # no token hash, no external contact
    assert "Staff queue" not in body and "/staff/p2/" not in body  # no navigation into mail screens


# --- review regressions: the offers mirror the services ---------------------------------------------------------

class _Attempts:
    def __init__(self, conflict):
        self.conflict = conflict

    def filter(self, **kwargs):
        return self

    def exists(self):
        return self.conflict


def _stub(status, method="api", stop=False, released=False, conflict=False):
    from types import SimpleNamespace

    return SimpleNamespace(status=status, method=method, stop_requested_at="now" if stop else None,
                           reservation=SimpleNamespace(released_at="then" if released else None),
                           attempts=_Attempts(conflict))


@pytest.mark.parametrize(("status", "method", "closed", "expected"), [
    ("awaiting_approval", "api", False, {"supersede"}),
    ("approved", "api", False, {"supersede"}),
    ("approved", "checklist", False, {"record_checklist", "supersede"}),
    ("created", "checklist", False, {"attest", "supersede"}),
    ("create_pending", "api", False, set()),
    ("create_uncertain", "api", False, set()),
    ("stopping", "api", False, set()),
    ("found_by_evidence", "api", False, {"confirm_found", "supersede"}),
    ("verified", "api", False, {"reissue", "supersede"}),
    ("verified", "checklist", False, {"supersede"}),  # the credential is a separate contingency (P5-D-6)
    ("setup_pending", "api", False, {"reissue", "supersede"}),
    ("setup_complete", "api", False, {"retry_activation", "supersede"}),
    ("failed_needs_staff", "api", False, {"release_address", "supersede"}),
    ("conflict", "api", False, {"release_address", "supersede"}),
    ("active", "api", False, set()),
    ("superseded", "api", False, {"release_address"}),
    ("stopped", "api", True, {"release_address"}),
    ("recovered_after_stop", "api", True, {"release_address"}),
])
def test_review_the_offer_table_per_status_and_method_matches_the_service_guards_as_written(status, method, closed, expected):
    assert staff_views._offered(_stub(status, method), set(), closed) == expected


def test_review_confirm_found_is_offered_exactly_when_the_service_accepts_it():
    from provisioning import core

    assert "confirm_found" in staff_views._offered(_stub("superseded"), {core.ITEM_LATE_MAILBOX}, False)
    assert "confirm_found" in staff_views._offered(_stub("stopped", stop=True, conflict=True), set(), True)
    assert "confirm_found" not in staff_views._offered(_stub("stopped", stop=True), set(), True)
    assert "confirm_found" not in staff_views._offered(_stub("conflict"), set(), False)
    assert "release_address" not in staff_views._offered(_stub("superseded", released=True), set(), False)


@pytest.mark.parametrize(("status", "method", "owner"), [
    ("approved", "checklist", "operator"), ("created", "checklist", "operator"), ("approved", "api", "system"),
    ("created", "api", "system"), ("verified", "checklist", "operator"), ("failed_needs_staff", "api", "operator"),
    ("setup_pending", "api", "applicant"), ("awaiting_approval", "api", "approver"),
])
def test_review_the_next_action_names_the_right_owner_for_each_status_and_method(cl, released, status, method,
                                                                                  owner):
    from types import SimpleNamespace

    app, _ = released
    live = SimpleNamespace(status=status, method=method)
    assert staff_views._next_action(app, [live], [])[1] == owner


def test_review_after_a_close_the_address_is_released_from_the_screen(cl, monkeypatch):
    app, request = approved(cl, monkeypatch)  # approved; the create has not run
    assert client_for(cl.closer).post(act(app), {"action": "close", "outcome": "withdrawn",
                                                 "note": "Applicant asked by phone to withdraw"}).status_code == 302
    run_worker()
    request = ProvisioningRequest.objects.select_related("reservation").get(pk=request.pk)
    assert request.status == "stopped" and request.reservation.released_at is None  # the address is still held
    body = client_for(cl.op1).get(page(app)).content.decode()
    assert "Release the address" in body and "Supersede this request" not in body
    assert "(owner: staff)" in body  # an unreleased address is still something to settle
    assert client_for(cl.op1).post(act(app), {"action": "release_address", "request": str(request.public_id),
                                               "note": "Applicant withdrew; address no longer needed"}
                                   ).status_code == 302
    assert ProvisioningRequest.objects.get(pk=request.pk).reservation.released_at is not None


def test_review_a_late_mailbox_on_a_superseded_request_is_decided_from_the_screen(cl, monkeypatch):
    from provisioning import services

    app, request = approved(cl, monkeypatch)
    FakeMailHost.faults.append("create_unknown")
    run_worker()
    services.confirm_found_mailbox(request_of(app).pk, cl.op1, "conflict", "Not provably the one we requested")
    services.supersede(request.pk, cl.op1, "A new address will be chosen")
    run_worker()  # the watch finds the mailbox
    body = client_for(cl.op1).get(page(app)).content.decode()
    assert "a mailbox appeared late: confirm whether it is ours" in body and "Record the decision" in body
    assert client_for(cl.op1).post(act(app), {"action": "confirm_found", "request": str(request.public_id),
                                               "decision": "conflict", "note": "Still not provably ours"}
                                   ).status_code == 302


def test_review_a_checklist_request_shows_its_operator_steps(cl, monkeypatch, settings):
    settings.CATALYST_PROVISIONING_METHOD = "checklist"
    app, request = approved(cl, monkeypatch)
    body = client_for(cl.op1).get(page(app)).content.decode()
    assert "Create it in the panel and record it (owner: operator)" in body and "I created it in the panel" in body
    assert "create the mailbox in the panel, then a different operator attests it" in body  # the item, in words


def test_review_another_applications_records_are_never_acted_on(cl, monkeypatch, released):
    app, request = released
    from tests.test_outbound import verified_application

    other = verified_application(email="bea.second@example.test")  # a second applicant
    for form in ({"action": "approve", "request": str(request.public_id), "digest": request.approval_digest},
                 {"action": "supersede", "request": str(request.public_id), "note": "Foreign request attempt"},
                 {"action": "accept_exception", "revocation": str(request.public_id), "note": "Foreign attempt here"},
                 {"action": "approve", "request": "not-a-uuid", "digest": "x"}):
        response = client_for(cl.approver).post(act(other), form)
        assert response.status_code == 409 and "invalid_request" in response.content.decode(), form
    assert ProvisioningRequest.objects.get(pk=request.pk).status == "awaiting_approval"


def test_review_every_refusal_is_logged_without_typed_values_and_the_gate_covers_posts(cl, released, caplog):
    import logging

    app, request = released
    with caplog.at_level(logging.WARNING, logger="provisioning.staff_views"):
        client_for(cl.op1).post(act(app), {"action": "approve", "request": str(request.public_id),
                                           "digest": request.approval_digest, "note": "secret-ish typed text"})
    [record] = [r for r in caplog.records if r.name == "provisioning.staff_views"]
    assert f"user={cl.op1.pk}" in record.getMessage() and "code=not_permitted" in record.getMessage()
    assert "secret-ish" not in caplog.text
    for user in (staff(cl, "poster-without-permission"), staff(cl, "root-poster", superuser=True)):
        assert client_for(user).post(act(app), {"action": "approve", "request": str(request.public_id),
                                                "digest": request.approval_digest}).status_code == 403
    assert client_for(cl.approver).get(act(app)).status_code == 405
    assert ProvisioningRequest.objects.get(pk=request.pk).status == "awaiting_approval"


def test_review_a_refused_exception_keeps_its_note(cl, monkeypatch):
    app, request = active_member(cl, monkeypatch)
    client_for(cl.closer).post(act(app), {"action": "close", "outcome": "closed", "note": "Programme ended here"})
    run_worker()
    sessions = AccessRevocation.objects.get(request=request, kind="sessions")
    refused = client_for(cl.approver).post(act(app), {"action": "accept_exception",
                                                      "revocation": str(sessions.public_id), "note": "short"})
    assert refused.status_code == 409 and "reason_needed" in refused.content.decode()
    assert 'value="short"' in refused.content.decode()


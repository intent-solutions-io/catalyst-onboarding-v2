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
        assert response.status_code == 200 and response["Cache-Control"].startswith(("max-age=0", "no-cache", "private"))


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

def test_p5_19_the_screen_shows_each_phase_the_next_action_and_its_owner(cl, monkeypatch, released):
    app, request = released
    body = client_for(cl.approver).get(page(app)).content.decode()
    assert "Approval" in body and "awaiting the approver" in body and "(owner: approver)" in body
    assert "ada.example@team.example.test" in body and "Approve exactly this" in body
    assert " checked" not in body  # nothing consequential is preselected
    operator_view = client_for(cl.op1).get(page(app)).content.decode()
    assert "Approve exactly this" not in operator_view  # each control only for its permission holder
    for heading in ("Creation and verification", "Credential setup", "Activation", "Revocation"):
        assert heading in body


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
        if document is not None:
            assert client_for(user).post(reverse("agreements_staff:retrieve", args=[document.public_id]),
                                         {"note": "Curious about the agreement"}).status_code == 404
    assert FakeMailHost.passwords_seen  # the applicant set one; it never reaches this screen
    assert not any(p in body for p in FakeMailHost.passwords_seen)

"""P4 task 4C: the GATE-P4 journey over real Django HTTP, and negative controls that remove a critical gate (021
section 12; D-40 item E).

The journey runs the default gate (signing AND custody, P4-D-6) for both agreements, with no signing-only override.
Staff log in through the admin login form, and every staff POST carries a CSRF token from the page, through a client
that enforces CSRF. The provider is the synthetic Documenso fake; its webhook arrives over HTTP with the shared secret.
"""

import re

import pytest
from django.db import transaction
from django.test import Client
from django.urls import reverse
from psycopg import errors

from agreements import completion
from agreements.models import AgreementInstance, AgreementType, DocumentAccess, StoredDocument
from applications.models import Application
from tests.test_agreement_completion import SECRET, post, reads_now
from tests.test_agreement_custody import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, k, nda, of, p2, run_worker, tls,
)
from workflow.models import PendingAction

PASSWORD = "synthetic-password-only"  # tests.test_outbound.staff gives every synthetic staff user this password


def csrf(page: str) -> str:
    return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)


def logged_in(username: str) -> Client:
    """A browser-like session: the admin login form, with its CSRF token, and CSRF enforced afterwards."""
    client = Client(enforce_csrf_checks=True)
    login = reverse("admin:login")
    page = client.get(login).content.decode()
    response = client.post(login, {"username": username, "password": PASSWORD, "csrfmiddlewaretoken": csrf(page),
                                   "next": "/staff/"})
    assert response.status_code == 302, "the synthetic staff login failed"
    return client


def sign_over_http(k, app, key):
    """The applicant signs at the provider; the provider's webhook arrives over HTTP; the fresh read decides."""
    instance = of(app, key).get()
    k.fake.sign(instance.envelope_id)
    response = post(k.fake.webhook(instance.envelope_id))
    assert response.status_code in (200, 202, 204)
    reads_now()
    return AgreementInstance.objects.get(pk=instance.pk)


# --- the journey ------------------------------------------------------------------------------------------------

def test_p4_journey_the_default_gate_journey_over_http(k, monkeypatch):
    assert set(AgreementType.objects.values_list("gate", flat=True)) == {"signing_and_custody"}  # no override
    app = admitted(k, monkeypatch)  # intake and confirmation over HTTP, P3 assessment and the admit decision
    approve(k)
    activate()  # the owner's versioned activation command
    run_worker()
    staff = logged_in(k.agreement_decider.username)
    screen = reverse("agreements_staff:agreements", args=[app.public_ref])
    page = staff.get(screen).content.decode()
    for label in ("Issue", "Signing", "Custody"):  # three statuses, shown separately
        assert f'<th scope="row">{label}</th>' in page
    assert not of(app, "user_agreement").exists()  # the User Agreement waits for the NDA's gate

    nda_instance = sign_over_http(k, app, "nda")
    assert (nda_instance.signing_status, nda_instance.custody_status) == ("signing_complete_verified", "stored_verified")
    ua = sign_over_http(k, app, "user_agreement")
    assert (ua.signing_status, ua.custody_status) == ("signing_complete_verified", "stored_verified")
    app = Application.objects.get(pk=app.pk)
    assert app.stage == "agreements_complete"
    [handoff] = PendingAction.objects.filter(kind="provision")
    assert handoff.status == "held"

    # Audited retrieval over HTTP: a POST without the page's CSRF token is refused; with it, the PDF is served
    # privately as an attachment and the access is recorded.
    document = StoredDocument.objects.filter(instance=nda_instance).first()
    retrieve = reverse("agreements_staff:retrieve", args=[document.public_id])
    assert staff.post(retrieve, {"note": "Counsel review copy"}).status_code == 403
    assert not DocumentAccess.objects.exists()
    page = staff.get(screen).content.decode()
    assert retrieve in page
    response = staff.post(retrieve, {"note": "Counsel review copy", "csrfmiddlewaretoken": csrf(page)})
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("attachment;")
    cache = {part.strip() for part in response["Cache-Control"].split(",")}
    assert {"private", "no-store"} <= cache and response["X-Content-Type-Options"] == "nosniff"
    body = b"".join(response.streaming_content) if response.streaming else response.content
    assert body.startswith(b"%PDF")
    assert list(DocumentAccess.objects.values_list("outcome", flat=True)) == ["granted"]

    # A forged webhook changes nothing, and a duplicate callback after completion adds no second hand-off.
    assert post(k.fake.webhook(nda_instance.envelope_id), secret="wrong-secret").status_code == 401
    post(k.fake.webhook(ua.envelope_id))
    reads_now()
    assert PendingAction.objects.filter(kind="provision").count() == 1
    assert Application.objects.get(pk=app.pk).stage == "agreements_complete"


# --- negative controls: remove a critical gate and show the outcome is caught -----------------------------------

def test_p4_removed_gate_a_status_write_without_a_fresh_read_is_refused(k, monkeypatch):
    """With the service-level fresh read removed, the database still refuses `signing_complete_verified` unless a
    read observation is recorded in the same transaction (021 section 16)."""
    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    run_worker()
    instance = nda(app)
    with pytest.raises(Exception) as caught, transaction.atomic():
        AgreementInstance.objects.filter(pk=instance.pk).update(signing_status="signing_complete_verified")
    assert isinstance(caught.value.__cause__, errors.InsufficientPrivilege)
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status != "signing_complete_verified"


def test_p4_removed_gate_the_user_agreement_backstop_refuses_an_early_instance(k, monkeypatch):
    """With the sequence gate removed (the advance believes the NDA passed), the D-15 database backstop still refuses
    a User Agreement instance before the NDA is `signing_complete_verified`."""
    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    run_worker()
    monkeypatch.setattr(completion, "gate_passed", lambda instance: True)
    completion.enqueue_advance(Application.objects.get(pk=app.pk))
    run_worker()
    assert not of(app, "user_agreement").exists()


def test_p4_removed_gate_the_hand_off_refuses_without_custody(k, monkeypatch, settings):
    """The custody gate is load-bearing: with custody unavailable, signing is verified but nothing advances. With the
    gate removed, the same run would advance, which is what the journey and TEST-P4-07 would catch."""
    settings.CATALYST_AGREEMENT_STORAGE_DIR = ""  # custody cannot store
    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    run_worker()
    instance = sign_over_http(k, app, "nda")
    assert instance.signing_status == "signing_complete_verified" and instance.custody_status != "stored_verified"
    assert not of(app, "user_agreement").exists()
    # Remove the custody half of the gate (a signing-only gate) and the same state advances: the gate is load-bearing,
    # and TEST-P4-07's "nothing advances" assertion is what catches its removal.
    monkeypatch.setattr(completion, "gate_passed", lambda i: i.signing_status == "signing_complete_verified")
    completion.enqueue_advance(Application.objects.get(pk=app.pk))
    run_worker()
    assert of(app, "user_agreement").exists()

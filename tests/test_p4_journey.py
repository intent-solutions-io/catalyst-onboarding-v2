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
from agreements.models import AgreementInstance, AgreementType, DocumentAccess, ProviderObservation, StoredDocument
from applications.models import Application
from tests.test_agreement_completion import post, reads_now
from tests.test_agreement_custody import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, k, nda, of, p2, run_worker, tls,
)
from workflow.models import PendingAction

PASSWORD = "synthetic-password-only"  # gitleaks:allow (synthetic; tests.test_outbound.staff gives every staff user this)


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
    """The applicant signs at the provider; the provider's webhook arrives over HTTP and is recorded as a hint (never
    a verification); then the fresh read it brought forward decides."""
    instance = of(app, key).get()
    k.fake.sign(instance.envelope_id)
    hints = ProviderObservation.objects.filter(instance=instance, source="webhook").count()
    response = post(k.fake.webhook(instance.envelope_id))
    assert response.status_code == 200
    assert ProviderObservation.objects.filter(instance=instance, source="webhook").count() == hints + 1
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status != "signing_complete_verified"  # a hint only
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
    # The User Agreement waits for the NDA's gate: not created, not shown, not linked.
    assert not of(app, "user_agreement").exists() and "user_agreement &middot;" not in page
    assert "secret-signing-token" not in page and "/sign/" not in page  # the fake's token and link are never rendered

    nda_instance = sign_over_http(k, app, "nda")
    assert (nda_instance.signing_status, nda_instance.custody_status) == ("signing_complete_verified", "stored_verified")
    events = list(app.events.order_by("id").values_list("kind", flat=True))
    created = [i for i, e in enumerate(events) if e == "agreement_instance_created"]
    assert len(created) == 2 and events.index("agreement_custody_verified") < created[1]  # signing AND custody first
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

    assert b"secret-signing-token" not in body
    # A forged webhook changes nothing, and a duplicate callback after completion adds no second hand-off.
    observations = ProviderObservation.objects.count()
    assert post(k.fake.webhook(nda_instance.envelope_id), secret="wrong-secret").status_code == 401
    assert ProviderObservation.objects.count() == observations
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
    assert "verified only by a fresh read" in str(caught.value)  # the trigger, not a column grant
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status != "signing_complete_verified"


def test_p4_removed_gate_the_user_agreement_backstop_refuses_an_early_instance(k, monkeypatch):
    """Remove every service-level gate: call the instance-creating step directly for the User Agreement while the NDA
    is complete at the provider but not yet verified in Catalyst. The D-15 database backstop still refuses it."""
    from agreements import handlers

    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    run_worker()
    k.fake.sign(nda(app).envelope_id)  # complete at the provider; no read has run, so not verified in Catalyst
    with pytest.raises(Exception) as caught, transaction.atomic():
        handlers.start_agreement(Application.objects.get(pk=app.pk), k.ua, "test:removed-gate")
    assert isinstance(caught.value.__cause__, errors.InsufficientPrivilege) and "D-15" in str(caught.value)
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
    assert (instance.signing_status, instance.custody_status) == ("signing_complete_verified", "failed_needs_staff")
    assert not of(app, "user_agreement").exists()
    # Remove the custody half of the gate (a signing-only gate) and the same state advances: the gate is load-bearing,
    # and TEST-P4-07's "nothing advances" assertion is what catches its removal.
    monkeypatch.setattr(completion, "gate_passed", lambda i: i.signing_status == "signing_complete_verified")
    completion.enqueue_advance(Application.objects.get(pk=app.pk))
    run_worker()
    assert of(app, "user_agreement").exists()


def test_p4_details_are_visible_only_to_those_who_confirm_them(k, monkeypatch, settings):
    """TEST-P4-05's visibility clause: recorded details appear only for a holder of `confirm_required_details`; a
    reader or an operator of the same screen never sees the values."""
    from agreements import services

    settings.CATALYST_AGREEMENT_REQUIRED_DETAILS = {"user_agreement": ["mailing_country"]}
    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    run_worker()
    sign_over_http(k, app, "nda")
    services.record_required_details(app.pk, "user_agreement", {"mailing_country": "Exampleland-7731"},
                                     k.agreement_decider)
    grant(k, k.operator, "view_agreementinstance")
    screen = reverse("agreements_staff:agreements", args=[app.public_ref])
    for user, sees in ((k.reader, False), (k.operator, False), (k.agreement_decider, True)):
        client = Client()
        client.force_login(user)
        page = client.get(screen)
        assert page.status_code == 200
        assert ("Exampleland-7731" in page.content.decode()) is sees, user.username


# --- P4 closeout after D-45: activation eligibility and hostile staff-visible text ------------------------------

def test_p4_09_activation_refuses_a_non_admitted_application_and_never_releases_other_held_kinds(k, monkeypatch):
    from io import StringIO

    from django.core.management import call_command

    app = admitted(k, monkeypatch)
    approve(k)
    other_kinds = [PendingAction.objects.create(
        kind=kind, subject_type="application", subject_id=app.public_ref, input_ref=f"synthetic:{kind}",
        idempotency_key=f"synthetic-held-{kind}", status="held", max_attempts=3) for kind in ("provision", "interpret_reply")]
    activate()
    assert PendingAction.objects.get(kind="issue_nda").status == "queued"  # the eligible NDA is released
    for action in other_kinds:  # nothing else held for the same applicant moves
        assert PendingAction.objects.get(pk=action.pk).status == "held"
    # The same held NDA for an application that is no longer admitted is refused and stays held.
    owner = k.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE workflow_pendingaction SET status = 'held' WHERE kind = 'issue_nda'")
    owner.execute("UPDATE applications_application SET stage = 'withdrawn' WHERE id = %s", [app.pk])
    out = StringIO()
    call_command("activate_agreements", "--activation-version", "1", "--approval-ref", "D-38", stdout=out)
    assert '"stage_not_admitted": 1' in out.getvalue() and '"released": 0' in out.getvalue()
    assert PendingAction.objects.get(kind="issue_nda").status == "held"


HOSTILE = '<img src=x onerror=alert(1)><script>alert(2)</script>"\''


def test_p4_21_hostile_details_and_typed_reasons_are_escaped_on_the_screen_and_its_refusals(k, monkeypatch, settings):
    from agreements import services

    settings.CATALYST_AGREEMENT_REQUIRED_DETAILS = {"user_agreement": ["mailing_country"]}
    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    run_worker()
    sign_over_http(k, app, "nda")
    services.record_required_details(app.pk, "user_agreement", {"mailing_country": HOSTILE}, k.agreement_decider)
    client = Client()
    client.force_login(k.agreement_decider)
    screen = reverse("agreements_staff:agreements", args=[app.public_ref])
    html = client.get(screen).content.decode()
    assert "<script>alert(2)</script>" not in html and "<img src=x" not in html and "&lt;script&gt;" in html
    # A refused action re-renders what was typed, escaped, in the failure screen: an integrity resolution whose screen
    # went stale keeps the typed reason.
    instance = of(app, "nda").get()
    k.fake.envelopes[instance.envelope_id]["recipients"].append(
        {"email": "stranger@example.test", "role": "SIGNER", "signingOrder": 2, "signingStatus": "SIGNED"})
    completion.enqueue_read(AgreementInstance.objects.get(pk=instance.pk))
    reads_now()
    refused = client.post(reverse("agreements_staff:act", args=[app.public_ref]), {
        "action": "resolve", "instance": str(instance.public_id), "disposition": "continue", "note": HOSTILE,
        "digest": "stale"})
    body = refused.content.decode()
    assert refused.status_code == 409 and "changed_since_shown" in body
    assert "<script>alert(2)</script>" not in body and "<img src=x" not in body
    assert "&lt;img src=x onerror=alert(1)&gt;&lt;script&gt;alert(2)&lt;/script&gt;" in body  # shown, escaped

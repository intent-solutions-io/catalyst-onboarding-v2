"""9kg.47 (029 section 5.2): a supported staff screen for every agreement state that needed a shell. The decisions
on an unknown Documenso create, distribute and cancel, and agreement template approval, each through one POST to
the existing service under the existing permission, each with a refusal for a user without it and a recorded
event (the template's record is its own approval columns). Synthetic only, against the fake Documenso.
"""

from django.test import Client
from django.urls import reverse

from agreements import handlers, services
from agreements.models import AgreementInstance, AgreementTemplateVersion, EnvelopeAttempt
from applications.models import Application
from tests.test_agreement_completion import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, issued, nda, p2, run_worker, tls,
)
from tests.test_outbound import staff


def client_for(user):
    client = Client()
    client.force_login(type(user).objects.get(pk=user.pk))
    return client


def screen(app):
    return reverse("agreements_staff:agreements", args=[app.public_ref])


def act(app):
    return reverse("agreements_staff:act", args=[app.public_ref])


def test_an_unknown_create_is_decided_on_the_screen_and_refused_without_the_permission(h, monkeypatch):
    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    h.fake.fault("POST /envelope/use", ("drop_before",))  # sent, never processed: the outcome stays unknown
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "create_uncertain"
    reader = grant(h, staff(h, "agreement-reader-screen"), "view_agreementinstance")
    page = client_for(reader).get(screen(app)).content.decode()
    assert "Decide the unknown create" not in page  # offered only to holders of the decision permission
    refused = client_for(reader).post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "not_sent"})
    assert refused.status_code == 409 and "decide_create: refused (not_permitted)" in refused.content.decode()
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "create_uncertain"
    assert not app.events.filter(kind="agreement_create_decided").exists()
    decider = client_for(h.agreement_decider)
    page = decider.get(screen(app)).content.decode()
    assert "Decide the unknown create" in page and 'name="choice"' in page and " checked" not in page.split("Decide the unknown create")[1]
    assert decider.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "junk"}).status_code == 409
    response = decider.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "not_sent"})
    assert response.status_code == 302
    decided = AgreementInstance.objects.get(pk=instance.pk)
    assert decided.issue_status == "create_pending" and decided.external_key != instance.external_key
    assert EnvelopeAttempt.objects.get(external_key=instance.external_key).outcome == "decided_not_sent"
    event = app.events.get(kind="agreement_create_decided")
    assert event.actor_ref == f"user:{h.agreement_decider.pk}" and event.data["choice"] == "not_sent"
    assert "Decide the unknown create" not in decider.get(screen(app)).content.decode()


def test_an_unknown_distribute_is_decided_on_the_screen_and_cancelling_needs_the_manage_permission(h, monkeypatch):
    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    h.fake.fault("POST /envelope/distribute", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "distribute_uncertain"
    decide_only = grant(h, staff(h, "decide-only-screen"), "decide_uncertain_agreement")
    page = client_for(decide_only).get(screen(app)).content.decode()
    assert "Decide the unknown distribute" in page
    refused = client_for(decide_only).post(act(app), {"action": "decide_distribute", "instance": str(instance.public_id),
                                                      "choice": "cancel"})
    assert refused.status_code == 409 and "not_permitted" in refused.content.decode()  # cancelling is the manage act
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "distribute_uncertain"
    response = client_for(h.agreement_decider).post(act(app), {"action": "decide_distribute", "instance": str(instance.public_id),
                                                               "choice": "redistribute"})
    assert response.status_code == 302
    run_worker()
    instance.refresh_from_db()
    assert instance.issue_status == "issued" and h.fake.envelopes[instance.envelope_id]["status"] == "PENDING"
    event = app.events.get(kind="agreement_distribute_decided")
    assert event.actor_ref == f"user:{h.agreement_decider.pk}" and event.data["choice"] == "redistribute"
    assert not app.staff_items.filter(reason_code=handlers.DISTRIBUTE_UNKNOWN, status="open").exists()


def test_an_unknown_cancel_is_decided_on_the_screen_and_refused_without_the_permission(h, monkeypatch):
    app = issued(h, monkeypatch)
    instance = nda(app)
    h.fake.fault("POST /envelope/cancel", ("drop_before",))
    services.cancel_agreement(instance.pk, h.agreement_decider)
    run_worker()
    instance.refresh_from_db()
    assert instance.issue_status == "cancel_uncertain" and app.staff_items.filter(reason_code=handlers.CANCEL_UNKNOWN, status="open").count() == 1
    decide_only = grant(h, staff(h, "decide-only-cancel"), "decide_uncertain_agreement")
    assert "Decide the unknown cancel" not in client_for(decide_only).get(screen(app)).content.decode()
    refused = client_for(decide_only).post(act(app), {"action": "cancel", "instance": str(instance.public_id)})
    assert refused.status_code == 409 and "cancel: refused (not_permitted)" in refused.content.decode()
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "cancel_uncertain"
    manager = client_for(h.agreement_decider)
    page = manager.get(screen(app)).content.decode()
    assert "Decide the unknown cancel" in page and "Cancel again (reconciled)" in page
    assert manager.post(act(app), {"action": "cancel", "instance": str(instance.public_id)}).status_code == 302
    run_worker()
    instance.refresh_from_db()
    assert (instance.issue_status, instance.signing_status) == ("cancelled", "cancelled")
    assert h.fake.envelopes[instance.envelope_id]["status"] == "CANCELLED"
    assert not app.staff_items.filter(reason_code=handlers.CANCEL_UNKNOWN, status="open").exists()
    assert [e.data["result"] for e in app.events.filter(kind="agreement_cancel_requested").order_by("id")] == ["cancel_pending", "cancel_pending"]
    assert set(instance.attempts.filter(step="cancel").values_list("outcome", flat=True)) == {"decided_not_sent", "succeeded"}


def test_a_template_version_is_approved_on_its_own_screen_by_the_digest_shown(h):
    version = h.template
    assert version.status == "draft"
    url = reverse("agreements_staff:templates")
    approve_url = reverse("agreements_staff:approve_template", args=[version.pk])
    assert client_for(h.agreement_decider).get(url).status_code == 403  # a decision-maker is not the owner (POL-07)
    assert client_for(h.agreement_decider).post(approve_url, {"digest": version.pdf_sha256}).status_code == 403
    assert client_for(staff(h, "root-templates", superuser=True)).get(url).status_code == 403
    owner = client_for(h.template_owner)
    page = owner.get(url).content.decode()
    assert "nda" in page and "Approve exactly this version" in page and version.pdf_sha256[:14] in page
    assert owner.post(approve_url, {"digest": "0" * 64}).status_code == 302
    assert AgreementTemplateVersion.objects.get(pk=version.pk).status == "draft"
    page = owner.get(url).content.decode()
    assert "approve_template: refused (template_changed_since_shown)" in page
    assert owner.post(approve_url, {"digest": version.pdf_sha256}).status_code == 302
    approved = AgreementTemplateVersion.objects.get(pk=version.pk)
    assert approved.status == "approved" and approved.approved_by == f"user:{h.template_owner.pk}" and approved.approved_at
    page = owner.get(url).content.decode()
    assert "Template version approved." in page and "Approve exactly this version" not in page
    assert handlers.approved_version("nda").pk == version.pk  # what activate_agreements requires
    # The dossier offers the template screen only to a holder of the approval permission (who can read the dossier).
    app = Application.objects.create(email="dossier@example.test", email_key="dossier@example.test", display_name="Synthetic")
    change = reverse("admin:applications_application_change", args=[app.pk])
    reader = staff(h, "reader-dossier", "Read-only staff")
    assert "Agreement templates" not in client_for(reader).get(change).content.decode()
    grant(h, reader, "approve_agreement_template")
    assert "Agreement templates" in client_for(reader).get(change).content.decode()

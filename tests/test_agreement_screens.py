"""9kg.47 (029 section 5.2): a supported staff screen for every agreement state that needed a shell. The decisions
on an unknown Documenso create, distribute and cancel, and agreement template approval, each through one POST to
the existing service under the existing permission, each with a refusal for a user without it and a recorded
event (the template's record is its own approval columns). Synthetic only, against the fake Documenso.
"""

import pytest

from django.test import Client
from django.urls import reverse

from agreements import handlers, services
from agreements.models import AgreementInstance, AgreementTemplateVersion, EnvelopeAttempt
from applications.models import Application
from tests.test_agreement_completion import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, d, ev, g, grant, h, issued, nda, p2, run_worker, tls,
)
from tests.test_agreement_custody import k, sign_and_settle  # noqa: F401
from tests.test_outbound import staff
from workflow.models import PendingAction


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
    assert version.pdf_sha256 in page and len(version.pdf_sha256) == 64  # the full registered digest, never truncated
    assert "Nothing here reads or compares the live provider template" in page
    for stale in ("0" * 64, version.pdf_sha256):  # the posted digest covers the whole frozen tuple, not the PDF alone
        assert owner.post(approve_url, {"digest": stale}).status_code == 302
        assert AgreementTemplateVersion.objects.get(pk=version.pk).status == "draft"
    page = owner.get(url).content.decode()
    assert "approve_template: refused (template_changed_since_shown)" in page
    assert owner.post(approve_url, {"digest": services.template_digest(version)}).status_code == 302
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


def test_agreement_items_point_at_the_agreements_screen(h, monkeypatch):
    from correspondence.processing import AGREEMENT_SCREEN_ITEMS

    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    h.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    item = app.staff_items.get(reason_code=handlers.CREATE_UNKNOWN, status="open")
    assert handlers.CREATE_UNKNOWN in AGREEMENT_SCREEN_ITEMS
    operator = grant(h, staff(h, "item-reader", "Correspondence operator"), "view_agreementinstance")
    page = client_for(operator).get(reverse("correspondence_staff:item", args=[item.public_id])).content.decode()
    assert screen(app) in page and "Open the agreements screen" in page and "decided there" in page
    assert "You hold no permission that resolves this item here" not in page and 'name="code"' not in page
    # Every code decided on the screen says so; any other agreement item links the screen without that claim.
    from django.db import transaction

    from correspondence.staff_items import open_item

    assert AGREEMENT_SCREEN_ITEMS == {"agreement_create_unknown", "agreement_distribute_unknown", "agreement_cancel_unknown",
                                      "agreement_orphan_watch_ended"}
    for code in sorted(AGREEMENT_SCREEN_ITEMS | {"agreement_duplicate_envelopes", "agreement_declined"}):
        with transaction.atomic():
            probe = open_item(code, f"probe:{code}", application=app)
        page = client_for(operator).get(reverse("correspondence_staff:item", args=[probe.public_id])).content.decode()
        assert "Open the agreements screen" in page, code
        assert ("decided there" in page) is (code in AGREEMENT_SCREEN_ITEMS), code


def test_a_withdrawal_stops_an_agreement_the_provider_reports_complete_but_unverified(k, monkeypatch):
    """The observed-complete refusal is the decision-maker's cancel only: a withdrawal (or closure, or hold) through
    stop_locked never rolls back on it; the cancel re-reads first and cancels only a pending envelope."""
    app = issued(k, monkeypatch)
    instance = nda(app)
    owner = k.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE agreements_agreementinstance SET signing_status = 'signing_complete_observed' WHERE id = %s", [instance.pk])
    assert services.stop_agreements(app.pk, k.agreement_decider, "withdrawn") == ["cancel_pending"]
    assert AgreementInstance.objects.get(pk=instance.pk).issue_status == "cancel_pending"
    assert app.events.filter(kind="agreements_stopped", data__reason="withdrawn").exists()


def test_the_screen_refuses_a_reconciliation_in_progress_a_signed_and_an_observed_complete_agreement(k, monkeypatch):
    app = admitted(k, monkeypatch)
    approve(k)
    activate()
    k.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    attempt = EnvelopeAttempt.objects.get(instance=instance, step="create", outcome="unknown")
    handlers.enqueue_reconcile(attempt, 9)  # a check still queued: deciding is refused until it ends
    decider = client_for(k.agreement_decider)
    page = decider.get(screen(app)).content.decode()
    assert "checks below distinguish a successful listing from a failed check" in page
    assert "reconcile action(s) were queued for it, one is still queued or running" in page and "Duplicate risk" in page
    assert "The unknown attempt was sent at 20" in page  # the attempt's time
    refused = decider.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "not_sent"})
    assert refused.status_code == 409 and "decide_create: refused (reconciliation_in_progress)" in refused.content.decode()
    PendingAction.objects.filter(input_ref=str(attempt.public_id), status="queued").update(status="cancelled")
    assert decider.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "not_sent"}).status_code == 302
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "issued"
    # Reported complete by the provider but not yet verified: a cancel is refused until a fresh read decides.
    owner = k.committed.connect("owner", autocommit=True)
    owner.execute("UPDATE agreements_agreementinstance SET signing_status = 'signing_complete_observed' WHERE id = %s", [instance.pk])
    refused = decider.post(act(app), {"action": "cancel", "instance": str(instance.public_id)})
    assert refused.status_code == 409 and "cancel: refused (completion_observed_verify_first)" in refused.content.decode()
    owner.execute("UPDATE agreements_agreementinstance SET signing_status = 'not_started' WHERE id = %s", [instance.pk])
    sign_and_settle(k, app, "nda")
    instance.refresh_from_db()
    assert instance.signing_status == "signing_complete_verified"
    refused = decider.post(act(app), {"action": "cancel", "instance": str(instance.public_id)})
    assert refused.status_code == 409 and "cancel: refused (agreement_already_signed)" in refused.content.decode()


def test_the_cancel_button_is_absent_for_verified_cancelled_and_superseded_rows(k, monkeypatch):
    app = issued(k, monkeypatch)
    instance = nda(app)
    decider = client_for(k.agreement_decider)
    section = lambda page, ref: page.split(f"instance {ref}")[1].split("</section>")[0]  # noqa: E731
    assert 'value="cancel"' in section(decider.get(screen(app)).content.decode(), instance.public_id)
    owner = k.committed.connect("owner", autocommit=True)
    for state in ("cancelled", "superseded"):  # test-only: the owner places the unverified row in the state under test
        owner.execute("UPDATE agreements_agreementinstance SET issue_status = %s WHERE id = %s", [state, instance.pk])
        page = decider.get(screen(app)).content.decode()
        assert 'value="cancel"' not in section(page, instance.public_id), state
    owner.execute("UPDATE agreements_agreementinstance SET issue_status = 'issued' WHERE id = %s", [instance.pk])
    sign_and_settle(k, app, "nda")
    assert AgreementInstance.objects.get(pk=instance.pk).signing_status == "signing_complete_verified"
    page = decider.get(screen(app)).content.decode()
    assert 'value="cancel"' not in section(page, instance.public_id)  # verified: the database never lets it change


def test_a_second_template_version_becomes_current_and_a_repeat_approval_is_a_no_op(h):
    import hashlib

    from agreements.models import AgreementType

    first = h.template
    owner = client_for(h.template_owner)
    url = reverse("agreements_staff:templates")
    assert owner.post(reverse("agreements_staff:approve_template", args=[first.pk]), {"digest": services.template_digest(first)}).status_code == 302
    page = owner.get(url).content.decode()
    assert page.count("yes: new agreements of this type use it") == 2  # one current version per type (nda, user agreement)
    second = AgreementTemplateVersion.objects.create(
        agreement_type=AgreementType.objects.get(key="nda"), version=2, provider_template_ref="envelope_template_nda2",
        provider_template_number=103, recipient_slots={"SIGNER:1": 7003}, pdf_sha256=hashlib.sha256(b"v2").hexdigest())
    assert owner.post(reverse("agreements_staff:approve_template", args=[second.pk]), {"digest": services.template_digest(second)}).status_code == 302
    assert handlers.approved_version("nda").pk == second.pk
    page = owner.get(url).content.decode()
    nda_rows = [r for r in page.split("<tr>") if r.startswith("<td>nda</td>")]
    assert [("yes: new agreements" in r) for r in nda_rows] == [True, False]  # version 2 is current, version 1 no longer
    assert page.count("yes: new agreements of this type use it") == 2
    # Approving an approved version again changes nothing and says so.
    version, changed = services.approve_template_version(second.pk, h.template_owner, services.template_digest(second))
    assert changed is False and version.approved_at == AgreementTemplateVersion.objects.get(pk=second.pk).approved_at
    assert owner.post(reverse("agreements_staff:approve_template", args=[second.pk]), {"digest": services.template_digest(second)}).status_code == 302
    assert "nothing changed (the version was already approved)" in owner.get(url).content.decode()


@pytest.mark.parametrize("http_status", [None, 503])
def test_9kg53_failed_checks_never_authorize_mark_not_sent_and_a_successful_empty_check_does(h, monkeypatch, http_status):
    from agreements import provider

    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    h.fake.fault("POST /envelope/use", ("drop_before",))
    real_find = provider.find

    def unavailable(*args):
        raise provider.ProviderError("unavailable", sent=False, status=http_status)

    monkeypatch.setattr(provider, "find", unavailable)
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    attempt = instance.attempts.get(step="create")
    checks = app.events.filter(kind=handlers.RECONCILIATION_CHECKED)
    assert checks.count() == 2
    assert all(e.occurred_at and e.data["reached"] is (http_status is not None) and e.data["matches"] is None for e in checks)
    client = client_for(h.agreement_decider)
    page = client.get(screen(app)).content.decode()
    assert "2 completed provider checks recorded" in page and "Duplicate risk" in page
    assert checks.first().occurred_at.isoformat() in page
    assert 'value="not_sent" required disabled' in page
    response = client.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "not_sent"})
    assert response.status_code == 409 and "successful_empty_listing_required" in response.content.decode()
    assert len(h.fake.calls("POST", "/envelope/use")) == 1
    attempt.refresh_from_db()
    assert attempt.outcome == "unknown"
    monkeypatch.setattr(provider, "find", real_find)
    handlers.enqueue_reconcile(attempt, 3, grace=0)
    run_worker()
    checked = checks.order_by("-id").first()
    assert checked.data["reached"] is True and checked.data["complete"] is True and checked.data["matches"] == 0
    page = client.get(screen(app)).content.decode()
    assert 'value="not_sent" required disabled' not in page
    assert client.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "not_sent"}).status_code == 302
    attempt.refresh_from_db()
    assert attempt.outcome == "decided_not_sent"


def test_9kg53_a_truncated_listing_cannot_prove_absence_and_abandon_stays_available(h, monkeypatch, settings):
    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    settings.CATALYST_AGREEMENT_LIST_PAGES = 1
    for i in range(3):
        h.fake.add_envelope(template_ref=h.template.provider_template_ref, external_id=f"ag_foreign_{i}",
                            recipients=[{"id": 7001, "email": "synthetic@example.test"}])
    h.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    checks = app.events.filter(kind=handlers.RECONCILIATION_CHECKED)
    assert checks.count() == 2
    assert all(e.data["reached"] is True and e.data["complete"] is False and e.data["matches"] == 0 for e in checks)
    client = client_for(h.agreement_decider)
    response = client.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "not_sent"})
    assert response.status_code == 409 and "successful_empty_listing_required" in response.content.decode()
    assert client.post(act(app), {"action": "decide_create", "instance": str(instance.public_id), "choice": "abandon"}).status_code == 302
    instance.refresh_from_db()
    assert instance.issue_status == "cancelled"


def test_9kg53_missing_pagination_metadata_is_unknown_not_empty(h, monkeypatch):
    app = admitted(h, monkeypatch)
    approve(h)
    activate()
    h.fake.list_omit_total_pages = True
    h.fake.fault("POST /envelope/use", ("drop_before",))
    run_worker()
    instance = nda(Application.objects.get(pk=app.pk))
    assert instance.issue_status == "create_uncertain"
    assert not services.create_absence_checked(instance.attempts.get(step="create"))
    assert all(e.data["reached"] is True and e.data["complete"] is False and e.data["matches"] is None
               for e in app.events.filter(kind=handlers.RECONCILIATION_CHECKED))

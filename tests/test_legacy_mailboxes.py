"""Imported mailbox ownership must be reviewed before native access operations."""

import pytest
from types import SimpleNamespace
from dataclasses import replace

from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse
from psycopg import sql

from correspondence.common import Refused
from firstgen import mailboxes, review
from provisioning import closure, services
from provisioning.adapter import AdapterError, Mailbox
from provisioning.models import AccessRevocation, ProvisioningEvidence
from tests.mxroute_fake import FakeMailHost
from tests.test_agreements import grant
from tests.test_legacy_review import app
from tests.test_first_generation_import import import_v1, populate, v1  # noqa: F401
from tests.test_outbound import staff
from tests.test_staff import logged_in
from workflow import ledger
from workflow.models import AutomationPause, PendingAction


@pytest.fixture
def mailbox(v1, privileged_reset, settings, request):
    ids = populate(v1)
    state = getattr(request, "param", "active")
    v1.owner.execute(
        sql.SQL("UPDATE {}.onboarding_case SET state = %s WHERE id = %s").format(
            sql.Identifier(v1.schema)
        ),
        [state, ids["CAT-AC00-0011"]],
    )
    import_v1(v1)
    legacy = SimpleNamespace(committed=privileged_reset)
    legacy.user = staff(legacy, "mailbox-handover")
    grant(legacy, legacy.user, "view_application")
    settings.CATALYST_PROVISIONING_ADAPTER = "tests.mxroute_fake.FakeMailHost"
    FakeMailHost.reset()
    application = app("CAT-AC00-0011")
    request = application.provisioning_requests.get()
    reservation = request.reservation
    legacy.application, legacy.request = application, request
    grant(legacy, legacy.user, "close_application")
    grant(legacy, legacy.user, "operate_provisioning")
    FakeMailHost.mailboxes[(reservation.domain, reservation.local_part)] = Mailbox(
        reservation.local_part,
        reservation.domain,
        request.quota_mb,
        request.send_limit,
        False,
    )
    try:
        yield legacy
    finally:
        FakeMailHost.reset()


def revoke_once():
    handler = closure.RevokeAccess()
    claim = ledger.claim_next({closure.REVOKE: handler})
    assert claim is not None
    handler.run(claim)


def test_imported_mailbox_closure_cannot_claim_access_removal_before_ownership_review(
    mailbox,
):
    closure.close_application(
        mailbox.application.pk, mailbox.user, "closed", "Owner requested access closure"
    )
    revoke_once()
    rows = AccessRevocation.objects.filter(request=mailbox.request)
    assert not rows.filter(state="not_applicable").exists()
    assert rows.get(kind="password_rotation").state == "requested"
    assert not closure.revocation_complete(mailbox.request)
    assert FakeMailHost.calls == []
    for action in (services.supersede, services.release_address):
        with pytest.raises(services.Refused, match="legacy_mailbox_review_required"):
            action(
                mailbox.request.pk,
                mailbox.user,
                "Do not release an unreviewed old address",
            )


def confirm(env, **overrides):
    env.application.refresh_from_db()
    args = dict(
        expected_digest=review.review_state(env.application)["digest"],
        source_stopped=True,
        ownership_reviewed=True,
        note="Frozen source and provider account ownership reviewed",
    )
    args.update(overrides)
    return mailboxes.confirm(env.application.pk, env.request.pk, env.user, **args)


def test_reviewed_existing_mailbox_closes_through_native_revocation_without_recreation(
    mailbox,
):
    application, request = mailbox.application, mailbox.request
    reservation = request.reservation
    key = (reservation.domain, reservation.local_part)
    FakeMailHost.current_passwords[key] = "synthetic-existing-password"
    FakeMailHost.forwarders[key] = ("ada@example.test",)
    receipt = confirm(mailbox)
    assert confirm(mailbox).pk == receipt.pk
    assert FakeMailHost.calls == [("read", *key)]
    assert closure.proven_ours(request)
    assert not PendingAction.objects.filter(subject_id=application.public_ref).exists()
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    assert FakeMailHost.current_passwords[key] == "synthetic-existing-password"
    closure.close_application(
        application.pk, mailbox.user, "closed", "Owner requested access closure"
    )
    revoke_once()
    assert FakeMailHost.current_passwords[key] != "synthetic-existing-password"
    assert key in FakeMailHost.mailboxes and key not in FakeMailHost.forwarders
    states = dict(request.revocations.values_list("kind", "state"))
    assert states["password_rotation"] == "applied_unverified"
    assert states["sessions"] == states["app_credentials"] == "unsupported"
    assert not closure.revocation_complete(request)
    assert all(
        call[0] not in ("create", "delete_mailbox", "suspend")
        for call in FakeMailHost.calls
    )


@pytest.mark.parametrize("mailbox", ["offboarding"], indirect=True)
def test_imported_offboarding_records_ownership_and_starts_native_protection(mailbox):
    assert mailbox.application.stage == "closed"
    receipt = confirm(mailbox)
    assert receipt.data["revocation_requested"] is True
    assert confirm(mailbox).pk == receipt.pk
    assert not FakeMailHost.passwords_seen
    mailbox.request.refresh_from_db()
    assert mailbox.request.status == "stopped" and mailbox.request.stop_requested_at
    revoke_once()
    assert (
        mailbox.request.revocations.get(kind="password_rotation").state
        == "applied_unverified"
    )
    assert FakeMailHost.passwords_seen


@pytest.mark.parametrize("mailbox", ["suspended"], indirect=True)
def test_suspended_legacy_access_is_preserved_and_never_reactivated(mailbox):
    with pytest.raises(Refused, match="legacy_suspension_requires_reconciliation"):
        confirm(mailbox)
    key = (mailbox.request.reservation.domain, mailbox.request.reservation.local_part)
    FakeMailHost.mailboxes[key] = replace(FakeMailHost.mailboxes[key], suspended=True)
    confirm(mailbox)
    assert FakeMailHost.mailboxes[key].suspended
    assert all(c[0] == "read" for c in FakeMailHost.calls)
    assert AutomationPause.objects.filter(
        subject_id=mailbox.application.public_ref
    ).exists()
    assert not PendingAction.objects.filter(
        subject_id=mailbox.application.public_ref
    ).exists()


def test_mailbox_handover_requires_authority_current_history_and_source_attestation(
    mailbox,
):
    user = mailbox.user
    mailbox.user = None
    with pytest.raises(PermissionDenied):
        confirm(mailbox)
    mailbox.user = user
    for changed, reason in [
        ({"source_stopped": False}, "reviewed_mailbox"),
        ({"ownership_reviewed": False}, "reviewed_mailbox"),
        ({"note": "x"}, "reviewed_mailbox"),
        ({"expected_digest": "stale"}, "changed_since_shown"),
    ]:
        with pytest.raises(Refused, match=reason):
            confirm(mailbox, **changed)
    other = app("CAT-PV00-0010").provisioning_requests.get()
    own = mailbox.request
    mailbox.request = other
    with pytest.raises(Refused, match="imported_mailbox_required"):
        confirm(mailbox)
    mailbox.request = own
    assert FakeMailHost.calls == []


def test_mailbox_handover_refuses_unknown_absent_and_wrong_provider_identity(mailbox):
    FakeMailHost.faults.append("read_500")
    with pytest.raises(AdapterError):
        confirm(mailbox)
    key = (mailbox.request.reservation.domain, mailbox.request.reservation.local_part)
    saved = FakeMailHost.mailboxes.pop(key)
    with pytest.raises(Refused, match="legacy_mailbox_not_found"):
        confirm(mailbox)
    FakeMailHost.mailboxes[key] = replace(saved, local_part="someone.else")
    with pytest.raises(Refused, match="mailbox_identity_mismatch"):
        confirm(mailbox)
    assert not ProvisioningEvidence.objects.filter(request=mailbox.request).exists()


def test_mailbox_handover_rechecks_closure_during_provider_read(mailbox, monkeypatch):
    original = FakeMailHost.read

    def read(host, domain, local):
        value = original(host, domain, local)
        closure.close_application(
            mailbox.application.pk, mailbox.user, "closed", "Owner closed while reading"
        )
        return value

    monkeypatch.setattr(FakeMailHost, "read", read)
    with pytest.raises(Refused, match="changed_since_shown"):
        confirm(mailbox)
    assert not ProvisioningEvidence.objects.filter(request=mailbox.request).exists()
    revoke_once()
    assert (
        mailbox.request.revocations.get(kind="password_rotation").state == "requested"
    )


def test_approved_but_uncertain_legacy_mailbox_cannot_be_assumed_absent_or_owned(
    mailbox,
):
    mailbox.application = app("CAT-PV00-0010")
    mailbox.request = mailbox.application.provisioning_requests.get()
    with pytest.raises(
        Refused, match="legacy_mailbox_creation_requires_reconciliation"
    ):
        confirm(mailbox)
    with pytest.raises(services.Refused, match="legacy_mailbox_review_required"):
        services.supersede(
            mailbox.request.pk, mailbox.user, "A create may have happened in v1"
        )
    closure.close_application(
        mailbox.application.pk, mailbox.user, "closed", "Owner requested closure"
    )
    revoke_once()
    assert (
        mailbox.request.revocations.get(kind="password_rotation").state == "requested"
    )
    assert not mailbox.request.revocations.filter(state="not_applicable").exists()


def test_mailbox_handover_form_requires_post_csrf_and_scoped_request(mailbox):
    application = mailbox.application
    url = reverse("firstgen_staff:confirm_mailbox", args=[application.public_ref])
    client = logged_in(mailbox.user)
    assert client.get(url).status_code == 405
    fields = dict(
        request=str(mailbox.request.pk),
        digest=review.review_state(application)["digest"],
        source_stopped="yes",
        ownership_reviewed="yes",
        note="Frozen source mailbox ownership reviewed",
    )
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(mailbox.user)
    assert strict.post(url, fields).status_code == 403
    response = client.post(
        url, {**fields, "request": "999999", "note": "<script>bad</script>"}
    )
    assert (
        response.status_code == 409 and b"<script>bad</script>" not in response.content
    )
    assert client.post(url, fields).status_code == 302
    page = client.get(reverse("firstgen_staff:history", args=[application.public_ref]))
    assert (
        page.status_code == 200 and b"Mailbox ownership review recorded" in page.content
    )

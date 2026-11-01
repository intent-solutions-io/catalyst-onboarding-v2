"""Frozen source effects get a recorded disposition and one native continuation."""

from dataclasses import replace

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse

from config import runtime
from correspondence import staff_actions
from correspondence.common import Refused
from firstgen import mailbox_recovery, mailboxes
from provisioning import closure, password_welcome, services
from provisioning.adapter import AdapterError, Mailbox
from provisioning.models import ProvisioningRequest
from tests.firstgen_v1 import new_id
from tests.mxroute_fake import FakeMailHost
from tests.test_agreements import grant
from tests.test_first_generation_import import import_v1
from tests.test_legacy_mailbox_history import account, changed, job
from tests.test_legacy_mailboxes import revoke_once
from tests.test_legacy_review import app, legacy, v1  # noqa: F401
from tests.test_outbound import run_worker
from tests.test_parity_mxroute import password_template, nowhere_in_the_database
from tests.test_staff import logged_in
from workflow.models import AutomationPause, PendingAction


@pytest.fixture
def recovery(legacy, settings, request, monkeypatch):
    reference = getattr(request, "param", "CAT-PV00-0010")
    legacy.application = app(reference)
    legacy.request = legacy.application.provisioning_requests.select_related(
        "reservation"
    ).get()
    legacy.mailbox_id = account(legacy.source, legacy.ids[reference])
    legacy.case_id = legacy.ids[reference]
    if reference == "CAT-PV00-0010":
        legacy.source.insert(
            "case_release",
            id=new_id(),
            case_id=legacy.case_id,
            released_by="policy",
            policy_version="synthetic-release.v1",
            nda_agreement_id=legacy.ids[reference + ":nda"],
            ua_agreement_id=legacy.ids[reference + ":ua"],
            ua_envelope_id="synthetic-existing-envelope",
            archive_basis="archive_source",
            verified_at=legacy.source.at(96),
            created_at=legacy.source.at(96),
        )
    changed(
        legacy.source,
        "mailbox_account",
        legacy.mailbox_id,
        create_requested_at=legacy.source.at(97),
    )
    legacy.job_id = job(
        legacy.source,
        legacy.case_id,
        legacy.mailbox_id,
        kind="mailbox_create",
        status="needs_reconcile",
    )
    changed(legacy.source, "job", legacy.job_id, outcome_unknown=True)
    import_v1(legacy.source)
    for permission in (
        "approve_provisioning",
        "operate_provisioning",
        "close_application",
    ):
        grant(legacy, legacy.user, permission)
    settings.CATALYST_PROVISIONING_ADAPTER = "tests.mxroute_fake.FakeMailHost"
    settings.CATALYST_PROVISIONING_DOMAIN = legacy.request.reservation.domain
    settings.CATALYST_PROVISIONING_CREDENTIAL_MODE = "set_your_own"
    settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS = 0
    settings.CATALYST_WORKER_POLL_SECONDS = 0.01
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    FakeMailHost.reset()
    try:
        yield legacy
    finally:
        FakeMailHost.reset()


def present(env):
    request = env.request
    key = (request.reservation.domain, request.reservation.local_part)
    FakeMailHost.mailboxes[key] = Mailbox(
        key[1], key[0], request.quota_mb, request.send_limit, False
    )
    FakeMailHost.current_passwords[key] = "synthetic-existing-password"
    return key


def reconcile(env, decision="absent", **overrides):
    env.application.refresh_from_db()
    env.request.refresh_from_db()
    kwargs = dict(
        expected_digest=mailbox_recovery.state(env.application, env.request)["digest"],
        decision=decision,
        quota_mb=env.request.quota_mb,
        send_limit=env.request.send_limit,
        source_stopped=True,
        inflight_settled=True,
        ownership_reviewed=True,
        delivery_reviewed=True,
        note="Source frozen, operations settled, provider ownership and current delivery round reviewed",
    )
    kwargs.update(overrides)
    return mailbox_recovery.reconcile(
        env.application.pk, env.request.pk, env.user, **kwargs
    )


def successor(env):
    env.request.refresh_from_db()
    return ProvisioningRequest.objects.select_related("reservation", "application").get(
        pk=env.request.superseded_by_id
    )


def resume(env):
    staff_actions.resume(
        env.application.pk,
        env.user,
        "Source stopped; current mailbox and delivery disposition recorded",
    )


def test_absent_legacy_create_requires_new_approval_then_creates_once(recovery):
    old = recovery.request
    identity = (
        old.approval_digest,
        old.prerequisite_digest,
        old.approved_by,
        old.approved_at,
        old.method,
    )
    receipt = reconcile(recovery)
    new = successor(recovery)
    assert reconcile(recovery).pk == receipt.pk
    assert (
        new.status == "awaiting_approval" and new.reservation_id == old.reservation_id
    )
    old.refresh_from_db()
    assert (
        old.approval_digest,
        old.prerequisite_digest,
        old.approved_by,
        old.approved_at,
        old.method,
    ) == identity
    assert not old.attempts.exists() and not new.attempts.exists()
    assert not mailboxes.ownership_unreviewed(new)
    with pytest.raises(services.Refused, match="paused"):
        services.approve(new.pk, recovery.user, new.approval_digest)
    assert all(call[0] == "read" for call in FakeMailHost.calls)
    resume(recovery)
    services.approve(new.pk, recovery.user, new.approval_digest)
    run_worker()
    new.refresh_from_db()
    assert new.status == "setup_pending" and new.setups.count() == 1
    assert len([c for c in FakeMailHost.calls if c[0] == "create"]) == 1
    with pytest.raises(services.Refused, match="address_transferred_to_successor"):
        services.release_address(
            old.pk, recovery.user, "The successor still holds this address"
        )
    closure.close_application(
        recovery.application.pk,
        recovery.user,
        "closed",
        "Owner requested closure after handover",
    )
    assert not PendingAction.objects.filter(
        kind=closure.REVOKE, input_ref=str(old.public_id)
    ).exists()
    revoke_once()
    assert len([c for c in FakeMailHost.calls if c[0] == "set_password"]) == 1
    assert not old.revocations.exists()


def test_found_legacy_create_recovers_through_native_password_welcome_without_recreating(
    recovery, settings, monkeypatch
):
    key = present(recovery)
    settings.CATALYST_PROVISIONING_CREDENTIAL_MODE = "one_time_password"
    settings.CATALYST_PROVISIONING_IMAP_HOST = "imap.example.test"
    password_template(recovery)
    monkeypatch.setattr(
        password_welcome.mxroute, "login_check", lambda address, password: True
    )
    receipt = reconcile(recovery, "recover_credentials")
    new = successor(recovery)
    assert new.status == "created" and not new.attempts.exists()
    assert closure.proven_ours(new)
    run_worker()
    assert FakeMailHost.current_passwords[key] == "synthetic-existing-password"
    assert len(mail.outbox) == 0
    assert AutomationPause.objects.filter(
        subject_id=recovery.application.public_ref
    ).exists()
    resume(recovery)
    run_worker()
    new.refresh_from_db()
    recovery.application.refresh_from_db()
    assert new.status == recovery.application.stage == "active"
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [recovery.application.email]
    assert all(c[0] != "create" for c in FakeMailHost.calls)
    assert len([c for c in FakeMailHost.calls if c[0] == "set_password"]) == 1
    password = FakeMailHost.current_passwords[key]
    assert password != "synthetic-existing-password" and password in mail.outbox[0].body
    nowhere_in_the_database(password)
    assert reconcile(recovery, "recover_credentials").pk == receipt.pk
    run_worker()
    assert len(mail.outbox) == 1
    closure.close_application(
        recovery.application.pk,
        recovery.user,
        "closed",
        "Owner requested closure after recovery",
    )
    assert not PendingAction.objects.filter(
        kind=closure.REVOKE, input_ref=str(recovery.request.public_id)
    ).exists()
    revoke_once()
    assert len([c for c in FakeMailHost.calls if c[0] == "set_password"]) == 2


@pytest.mark.parametrize("recovery", ["CAT-AC00-0011"], indirect=True)
def test_verified_legacy_welcome_preserves_access_without_a_new_password_or_mail(
    recovery,
):
    key = present(recovery)
    changed(
        recovery.source,
        "mailbox_account",
        recovery.mailbox_id,
        welcome_sent_at=None,
        welcome_send_started_at=recovery.source.at(100),
    )
    import_v1(recovery.source)
    receipt = reconcile(recovery, "received")
    assert reconcile(recovery, "received").pk == receipt.pk
    assert recovery.application.stage == "active" and closure.proven_ours(
        recovery.request
    )
    assert (
        not recovery.request.setups.exists() and not recovery.request.superseded_by_id
    )
    assert not PendingAction.objects.filter(
        subject_id=recovery.application.public_ref
    ).exists()
    assert FakeMailHost.current_passwords[key] == "synthetic-existing-password"
    assert all(c[0] == "read" for c in FakeMailHost.calls)
    assert len(mail.outbox) == 0


def test_foreign_legacy_address_returns_a_held_handoff_and_never_touches_that_account(
    recovery,
):
    key = present(recovery)
    receipt = reconcile(recovery, "foreign")
    recovery.application.refresh_from_db()
    recovery.request.refresh_from_db()
    assert recovery.application.stage == "agreements_complete"
    assert recovery.request.status == "conflict" and closure.refused_as_foreign(
        recovery.request
    )
    assert (
        PendingAction.objects.get(subject_id=recovery.application.public_ref).status
        == "held"
    )
    assert reconcile(recovery, "foreign").pk == receipt.pk
    assert FakeMailHost.current_passwords[key] == "synthetic-existing-password"
    assert all(c[0] == "read" for c in FakeMailHost.calls)


@pytest.mark.parametrize("decision", ["absent", "protect_owned", "foreign"])
def test_closed_uncertain_legacy_create_is_resolved_only_for_protection(
    recovery, decision
):
    if decision != "absent":
        present(recovery)
    closure.close_application(
        recovery.application.pk,
        recovery.user,
        "closed",
        "Owner requested closure before handover",
    )
    with pytest.raises(Refused, match="stopped_case_requires_protection"):
        reconcile(recovery, "recover_credentials")
    reconcile(recovery, decision)
    assert recovery.application.stage == "closed"
    revoke_once()
    states = set(
        recovery.request.revocations.exclude(kind="setup_links").values_list(
            "state", flat=True
        )
    )
    if decision == "protect_owned":
        assert (
            "unsupported" in states
            and len([c for c in FakeMailHost.calls if c[0] == "set_password"]) == 1
        )
    else:
        assert states == {"not_applicable"}
        assert all(c[0] == "read" for c in FakeMailHost.calls)
    assert (
        not recovery.request.setups.exists() and not recovery.request.superseded_by_id
    )


def test_reconciliation_requires_authority_current_source_and_all_attestations(
    recovery,
):
    user = recovery.user
    recovery.user = None
    with pytest.raises(PermissionDenied):
        reconcile(recovery)
    recovery.user = user
    for key in (
        "source_stopped",
        "inflight_settled",
        "ownership_reviewed",
        "delivery_reviewed",
    ):
        with pytest.raises(Refused, match="reviewed_mailbox_reconciliation_required"):
            reconcile(recovery, **{key: False})
    with pytest.raises(Refused, match="changed_since_shown"):
        reconcile(recovery, expected_digest="stale")
    with pytest.raises(Refused, match="invalid_mailbox_limits"):
        reconcile(recovery, quota_mb=0)
    changed(recovery.source, "job", recovery.job_id, status="running")
    import_v1(recovery.source)
    with pytest.raises(Refused, match="source_job_still_in_flight"):
        reconcile(recovery)
    assert FakeMailHost.calls == [] and not recovery.request.evidence.exists()


def test_reconciliation_refuses_provider_errors_wrong_identity_limits_and_missing_create_marker(
    recovery,
):
    FakeMailHost.faults = ["read_500"]
    with pytest.raises(AdapterError):
        reconcile(recovery)
    key = present(recovery)
    with pytest.raises(Refused, match="presence_does_not_match"):
        reconcile(recovery)
    saved = FakeMailHost.mailboxes[key]
    FakeMailHost.mailboxes[key] = replace(saved, local_part="someone.else")
    with pytest.raises(Refused, match="identity_mismatch"):
        reconcile(recovery, "recover_credentials")
    FakeMailHost.mailboxes[key] = replace(saved, quota_mb=saved.quota_mb + 1)
    with pytest.raises(Refused, match="limits_or_suspension"):
        reconcile(recovery, "recover_credentials")
    FakeMailHost.mailboxes[key] = saved
    changed(
        recovery.source,
        "mailbox_account",
        recovery.mailbox_id,
        create_requested_at=None,
    )
    import_v1(recovery.source)
    with pytest.raises(Refused, match="source_never_requested"):
        reconcile(recovery, "recover_credentials")
    assert not recovery.request.evidence.exists()


def test_reconciliation_revalidates_closure_during_provider_read(recovery, monkeypatch):
    original = FakeMailHost.read

    def read(host, domain, local):
        found = original(host, domain, local)
        closure.close_application(
            recovery.application.pk,
            recovery.user,
            "closed",
            "Closed while provider read was pending",
        )
        return found

    monkeypatch.setattr(FakeMailHost, "read", read)
    with pytest.raises(Refused, match="changed_since_shown"):
        reconcile(recovery)
    assert (
        not recovery.request.evidence.exists() and not recovery.request.superseded_by_id
    )


def test_reconciliation_refuses_changed_source_completion(recovery):
    changed(
        recovery.source, "agreement", recovery.ids["CAT-PV00-0010:ua"], status="sent"
    )
    import_v1(recovery.source)
    with pytest.raises(Refused, match="current_source_agreement_completion_required"):
        reconcile(recovery)
    assert FakeMailHost.calls == []


def test_reconciliation_form_is_scoped_post_only_and_shows_current_delivery_evidence(
    recovery,
):
    client = logged_in(recovery.user)
    url = reverse(
        "firstgen_staff:reconcile_mailbox", args=[recovery.application.public_ref]
    )
    history = reverse("firstgen_staff:history", args=[recovery.application.public_ref])
    assert client.get(url).status_code == 405
    page = client.get(history + "?table=mailbox_history")
    assert page.status_code == 200 and b"needs_reconcile" in page.content
    assert b"synthetic-not-for-import" not in page.content
    fields = dict(
        request=recovery.request.pk,
        digest=mailbox_recovery.state(recovery.application, recovery.request)["digest"],
        decision="absent",
        quota_mb=recovery.request.quota_mb,
        send_limit=recovery.request.send_limit,
        source_stopped="yes",
        inflight_settled="yes",
        ownership_reviewed="yes",
        delivery_reviewed="yes",
        note="Frozen source and current provider evidence reviewed",
    )
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(recovery.user)
    assert csrf_client.post(url, fields).status_code == 403
    other = app("CAT-AC00-0011").provisioning_requests.get()
    assert client.post(url, {**fields, "request": other.pk}).status_code == 409
    assert client.post(url, fields).status_code == 302
    assert client.get(history).status_code == 200
    assert (
        recovery.application.events.filter(kind=mailbox_recovery.RECONCILED).count()
        == 1
    )

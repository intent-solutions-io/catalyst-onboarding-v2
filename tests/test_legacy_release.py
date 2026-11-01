"""A frozen release-pending case resumes through the existing provisioning gates."""

import pytest
from types import SimpleNamespace
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from psycopg import sql

from applications.models import ApplicationEvent
from config import runtime
from correspondence import staff_actions
from correspondence.common import Refused
from correspondence.roles import DECISION_MAKER
from firstgen import release
from provisioning import auto_release, services
from provisioning.models import ProvisioningRequest
from tests.firstgen_v1 import new_id
from tests.mxroute_fake import FakeMailHost
from tests.support import manage_as_owner
from tests.test_agreements import grant
from tests.test_first_generation_import import import_v1, populate
from tests.test_legacy_review import app, legacy, v1  # noqa: F401
from tests.test_outbound import run_worker, staff
from tests.test_staff import logged_in
from workflow.models import AutomationPause, PendingAction


@pytest.fixture
def pending(legacy, settings, monkeypatch):
    grant(legacy, legacy.user, "approve_provisioning")
    legacy.application = app("CAT-RP00-0009")
    settings.CATALYST_PROVISIONING_ADAPTER = "tests.mxroute_fake.FakeMailHost"
    settings.CATALYST_PROVISIONING_DOMAIN = "team.example.test"
    settings.CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS = 0
    settings.CATALYST_WORKER_POLL_SECONDS = 0.01
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    FakeMailHost.reset()
    try:
        yield legacy
    finally:
        FakeMailHost.reset()


def prepare(env, **overrides):
    env.application.refresh_from_db()
    args = dict(
        expected_digest=release.state(env.application)["digest"],
        source_stopped=True,
        completion_reviewed=True,
        effects_reviewed=True,
        note="Frozen source and completed agreement references reviewed; no provisioning effect",
    )
    args.update(overrides)
    return release.prepare(env.application.pk, env.user, **args)


def resume(env):
    staff_actions.resume(
        env.application.pk,
        env.user,
        "Source stopped and all imported release effects reviewed",
    )


def change_source(env, table, column, value):
    env.source.owner.execute(
        sql.SQL("UPDATE {}.{} SET {} = %s WHERE case_id = %s").format(
            sql.Identifier(env.source.schema),
            sql.Identifier(table),
            sql.Identifier(column),
        ),
        [value, env.ids["CAT-RP00-0009"]],
    )
    import_v1(env.source)


def test_legacy_release_handoff_is_held_once_and_keeps_native_owner_approval(pending):
    application = pending.application
    assert not PendingAction.objects.filter(subject_id=application.public_ref).exists()
    receipt = prepare(pending)
    assert prepare(pending).pk == receipt.pk
    handoff = PendingAction.objects.get(
        subject_id=application.public_ref, kind="provision"
    )
    assert handoff.status == "held" and not application.agreements.exists()
    assert receipt.data["prerequisites"]["nda"]["referenced"]
    assert receipt.data["prerequisites"]["user_agreement"]["referenced"]
    assert FakeMailHost.calls == []
    assert services.release(handoff.pk, 1, "synthetic-release-review") == "paused"
    assert not ProvisioningRequest.objects.filter(application=application).exists()
    resume(pending)
    assert services.release(handoff.pk, 1, "synthetic-release-review") == "released"
    request = ProvisioningRequest.objects.get(application=application)
    assert request.status == "awaiting_approval" and request.approved_by == ""
    assert not any(c[0] == "create" for c in FakeMailHost.calls)
    assert services.release(handoff.pk, 1, "synthetic-release-review") == "not_held"
    assert application.events.filter(kind="provisioning_released").count() == 1


def test_legacy_release_automatic_mode_waits_for_resume_then_creates_once(
    pending, settings
):
    settings.CATALYST_RELEASE_MODE = "automatic"
    prepare(pending)
    run_worker()
    automatic = PendingAction.objects.get(
        subject_id=pending.application.public_ref, kind=auto_release.AUTO_RELEASE
    )
    assert automatic.status == "queued" and automatic.last_error == "paused"
    assert not FakeMailHost.calls
    resume(pending)
    PendingAction.objects.filter(pk=automatic.pk).update(due_at=timezone.now())
    run_worker()
    request = ProvisioningRequest.objects.get(application=pending.application)
    assert request.approved_by == "auto-release" and request.status == "setup_pending"
    assert len([c for c in FakeMailHost.calls if c[0] == "create"]) == 1
    assert not pending.application.agreements.exists()
    assert request.setups.count() == 1
    PendingAction.objects.filter(pk=automatic.pk).update(
        status="queued", due_at=timezone.now()
    )
    run_worker()
    assert len([c for c in FakeMailHost.calls if c[0] == "create"]) == 1
    assert (
        ProvisioningRequest.objects.filter(application=pending.application).count() == 1
    )


def test_legacy_release_requires_authority_attestations_and_current_member_reference(
    pending,
):
    user = pending.user
    pending.user = None
    with pytest.raises(PermissionDenied):
        prepare(pending)
    pending.user = user
    for override in (
        {"source_stopped": False},
        {"completion_reviewed": False},
        {"effects_reviewed": False},
        {"note": "x"},
    ):
        with pytest.raises(Refused, match="reviewed_release_handover_required"):
            prepare(pending, **override)
    digest = release.state(pending.application)["digest"]
    manage_as_owner(
        "catalyst_member_on_file",
        pending.application.email,
        "--nda",
        "Reviewed NDA v2",
        "--completion-verified",
        "--recorded-by",
        "owner probe",
        "--correct",
    )
    with pytest.raises(Refused, match="changed_since_shown"):
        prepare(pending, expected_digest=digest)
    with pytest.raises(Refused):
        prepare(pending)
    assert not PendingAction.objects.filter(
        subject_id=pending.application.public_ref
    ).exists()


def test_legacy_release_refuses_a_later_source_agreement_state(pending):
    change_source(pending, "agreement", "status", "sent")
    with pytest.raises(Refused, match="later_legacy_state_requires_reconciliation"):
        prepare(pending)
    assert not ApplicationEvent.objects.filter(
        application=pending.application, kind=release.PREPARED
    ).exists()


def test_legacy_release_refuses_source_release_or_mailbox_effects(pending):
    source = pending.source
    source.insert(
        "case_release",
        id=new_id(),
        case_id=pending.ids["CAT-RP00-0009"],
        released_by="policy",
        policy_version="synthetic-release.v1",
        nda_agreement_id=pending.ids["CAT-RP00-0009:nda"],
        ua_agreement_id=pending.ids["CAT-RP00-0009:ua"],
        ua_envelope_id="envelope_ua",
        archive_basis="archive_source",
        verified_at=source.at(96),
        created_at=source.at(96),
    )
    import_v1(source)
    with pytest.raises(Refused, match="legacy_provisioning_requires_reconciliation"):
        prepare(pending)
    assert not PendingAction.objects.filter(
        subject_id=pending.application.public_ref
    ).exists()


def test_legacy_release_rechecks_source_after_the_fresh_read(pending, monkeypatch):
    def changed(application):
        change_source(pending, "agreement", "status", "sent")
        return ""

    monkeypatch.setattr(release.completion, "fresh_read_problem", changed)
    with pytest.raises(Refused, match="changed_since_shown"):
        prepare(pending)
    assert not PendingAction.objects.filter(
        subject_id=pending.application.public_ref
    ).exists()


def test_legacy_release_refuses_native_work_and_a_reused_handoff_key(pending):
    application = pending.application
    action = PendingAction.objects.create(
        kind="provision",
        subject_type="application",
        subject_id=application.public_ref,
        idempotency_key=f"provision:{application.public_ref}",
        status="held",
    )
    with pytest.raises(Refused, match="native_work_requires_reconciliation"):
        prepare(pending)
    PendingAction.objects.filter(pk=action.pk).update(
        status="cancelled", completed_at=timezone.now()
    )
    with pytest.raises(Refused, match="native_handoff_already_exists"):
        prepare(pending)
    assert not application.events.filter(kind=release.PREPARED).exists()


def test_legacy_release_form_requires_post_csrf_and_case_scope(pending):
    application = pending.application
    url = reverse("firstgen_staff:prepare_release", args=[application.public_ref])
    client = logged_in(pending.user)
    assert client.get(url).status_code == 405
    fields = dict(
        digest=release.state(application)["digest"],
        source_stopped="yes",
        completion_reviewed="yes",
        effects_reviewed="yes",
        note="Source and historical completion reviewed",
    )
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(pending.user)
    assert strict.post(url, fields).status_code == 403
    other = app("CAT-PV00-0010")
    assert (
        client.post(
            reverse("firstgen_staff:prepare_release", args=[other.public_ref]), fields
        ).status_code
        == 409
    )
    assert client.post(url, fields).status_code == 302
    response = client.get(
        reverse("firstgen_staff:history", args=[application.public_ref])
    )
    assert (
        response.status_code == 200 and b"Release handoff recorded" in response.content
    )
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()


def test_missing_source_agreements_cannot_be_replaced_by_a_member_reference(
    v1, privileged_reset, settings
):
    settings.CATALYST_QUALIFICATION_AUTHORITY = "explicit_permission"
    ids = populate(v1)
    for table in ("agreement_details", "agreement"):
        v1.owner.execute(
            sql.SQL("DELETE FROM {}.{} WHERE case_id = %s").format(
                sql.Identifier(v1.schema), sql.Identifier(table)
            ),
            [ids["CAT-RP00-0009"]],
        )
    import_v1(v1)
    env = SimpleNamespace(committed=privileged_reset, application=app("CAT-RP00-0009"))
    env.user = staff(env, "legacy-release-reviewer", DECISION_MAKER)
    for permission in (
        "record_qualification_decision",
        "view_application",
        "approve_provisioning",
    ):
        grant(env, env.user, permission)
    manage_as_owner(
        "catalyst_member_on_file",
        env.application.email,
        "--nda",
        "Historical NDA v1",
        "--user-agreement",
        "Historical UA v1",
        "--completion-verified",
        "--recorded-by",
        "owner probe",
    )
    with pytest.raises(Refused, match="frozen_agreement_history_required"):
        prepare(env)
    assert not PendingAction.objects.filter(
        subject_id=env.application.public_ref
    ).exists()


def test_legacy_release_refuses_uncertain_source_delivery(pending):
    source = pending.source
    source.insert(
        "job",
        id=new_id(),
        action_key="signing.reminder:synthetic",
        kind="signing_reminder",
        case_id=pending.ids["CAT-RP00-0009"],
        agreement_id=pending.ids["CAT-RP00-0009:nda"],
        status="running",
        attempts=1,
        outcome_unknown=True,
        next_run_at=source.at(99),
        created_at=source.at(98),
        updated_at=source.at(99),
    )
    import_v1(source)
    with pytest.raises(
        Refused, match="legacy_signing_delivery_requires_reconciliation"
    ):
        prepare(pending)
    assert not PendingAction.objects.filter(
        subject_id=pending.application.public_ref
    ).exists()
